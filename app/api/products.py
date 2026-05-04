import io
import os
import tempfile
import uuid
import time
import json
import asyncio
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import func, or_
import re
import pandas as pd
from app.database import get_db, SessionLocal
from app.database import get_db
from app.models import (
    Product,
    Category,
    Inventory,
    SalesHistory,
    InventoryTransaction,
    ProductSupplier,
    DSSReport,
    Notification,
)
from app.schemas import (
    ProductCreate, ProductUpdate, ProductListItem, ProductDetail,
    ProductListResponse, CategoryCreate, CategoryResponse, StockStatusEnum,
    BulkDeleteRequest, BulkDeleteResponse,
)
from fastapi.responses import StreamingResponse
from sqlalchemy import text

router = APIRouter(prefix="/products", tags=["Products"])

_jobs: dict[str, dict] = {}   # job_id → {status, progress, total, created, updated, skipped, error}
 
CHUNK_SIZE = 50_000            # rows per pandas chunk
 
 
def _new_job() -> str:
    jid = str(uuid.uuid4())
    _jobs[jid] = {
        "status": "pending",   # pending | running | done | error
        "progress": 0,
        "total": 0,
        "created": 0,
        "updated": 0,
        "skipped": 0,
        "error": None,
    }
    return jid



def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _stock_status(stock: int, rop: int) -> StockStatusEnum:
    if stock <= 0:
        return StockStatusEnum.OUT_OF_STOCK
    if stock <= rop:
        return StockStatusEnum.LOW_STOCK
    return StockStatusEnum.IN_STOCK


def _product_import_item(product: Product, db: Session) -> dict:
    inv = db.query(Inventory).filter(Inventory.product_id == product.id).first()
    cat_name = None
    if product.category_id:
        cat_name = db.query(Category.name).filter(Category.id == product.category_id).scalar()

    stock = inv.current_stock if inv else 0
    rop = inv.reorder_point if inv else 0

    return {
        "id": product.id,
        "sku": product.sku,
        "name": product.name,
        "description": product.description,
        "category_id": product.category_id,
        "category_name": cat_name,
        "base_price": float(product.base_price),
        "current_price": float(product.current_price),
        "cost_price": float(product.cost_price) if product.cost_price is not None else None,
        "current_stock": stock,
        "reorder_point": rop,
        "stock_status": _stock_status(stock, rop).value,
        "image_url": product.image_url,
        "is_active": product.is_active,
    }


# ─── Categories ──────────────────────────────────────────────────────

@router.get("/categories", response_model=list[CategoryResponse])
def list_categories(db: Session = Depends(get_db)):
    return db.query(Category).order_by(Category.name).all()


@router.post("/categories", response_model=CategoryResponse, status_code=201)
def create_category(data: CategoryCreate, db: Session = Depends(get_db)):
    cat = Category(
        name=data.name,
        slug=_slugify(data.name),
        parent_id=data.parent_id,
        description=data.description,
    )
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return cat


@router.delete("/categories/{category_id}", status_code=204)
def delete_category(category_id: int, db: Session = Depends(get_db)):
    cat = db.query(Category).filter(Category.id == category_id).first()
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")

    # Keep products and child categories, just detach them from the deleted category.
    db.query(Product).filter(Product.category_id == category_id).update(
        {Product.category_id: None},
        synchronize_session=False,
    )
    db.query(Category).filter(Category.parent_id == category_id).update(
        {Category.parent_id: None},
        synchronize_session=False,
    )

    db.delete(cat)
    db.commit()
    return None


# ─── Bulk Import ────────────────────────────────────────────────────

def _run_import(job_id: str, file_bytes_list: list[bytes], filenames: list[str]):
    """Run in BackgroundTasks thread pool (does not block the event loop)."""
    job = _jobs[job_id]
    job["status"] = "running"
 
    db: Session = SessionLocal()
    try:
        from app.core.preprocessing import smart_merge_files
 
        # ── 1. Detect encoding, read CSVs in chunks ─────────────────────────
        raw_dfs: list[pd.DataFrame] = []
        for b, fname in zip(file_bytes_list, filenames):
            encoding = _detect_encoding(b)
            # If file is small (<50MB) read once; otherwise use chunks
            if len(b) < 50 * 1024 * 1024:
                raw_dfs.append(pd.read_csv(io.BytesIO(b), encoding=encoding, low_memory=False))
            else:
                chunks = []
                for chunk in pd.read_csv(
                    io.BytesIO(b),
                    encoding=encoding,
                    low_memory=False,
                    chunksize=CHUNK_SIZE,
                ):
                    chunks.append(chunk)
                    # Yield CPU each chunk (avoid long blocking)
                    time.sleep(0)
                raw_dfs.append(pd.concat(chunks, ignore_index=True))
 
        # ── 2. smart_merge -> normalize ─────────────────────────────────────
        # cost_map is non-empty only for FMCG datasets (Revenue/Profit/Quantity cols)
        merged_df, price_map, cost_map = smart_merge_files(raw_dfs)
        if merged_df.empty:
            raise ValueError("No product data found in the CSV file.")
 
        # ── 3. Dedup with dict (faster than groupby on 3M rows) ─────────────
        seen: dict[str, str] = {}   # sku -> product_name
        for pid, pname in zip(merged_df["product_id"], merged_df["product_name"]):
            sku = str(pid).strip() if pid else ""
            name = str(pname).strip() if pname else sku
            if sku and sku.lower() not in ("nan", "none", "unknown"):
                seen.setdefault(sku, name)  # keep first occurrence
 
        job["total"] = len(seen)
 
        # ── 4. Batch-query existing SKUs ───────────────────────────────────
        all_skus = list(seen.keys())
        BATCH = 2000   # MySQL IN() safe with ~2000 values
        existing: dict[str, int] = {}  # sku -> product_id
 
        for i in range(0, len(all_skus), BATCH):
            batch = all_skus[i:i + BATCH]
            rows = db.query(Product.id, Product.sku).filter(Product.sku.in_(batch)).all()
            for pid, psku in rows:
                existing[psku] = pid
 
        # ── 5. Classify create vs update ───────────────────────────────────
        to_create: list[dict] = []
        to_update: list[dict] = []
        skipped = 0
 
        for sku, name in seen.items():
            price = float(price_map.get(sku, 0.0))
            # cost_price: validated median from FMCG; None for all other formats
            cost  = cost_map.get(sku)
            cost_val = float(cost) if cost is not None else None
            if sku in existing:
                row: dict = {"id": existing[sku], "name": name,
                             "base_price": price, "current_price": price}
                # Only overwrite cost_price when the dataset actually provides it
                if cost_val is not None:
                    row["cost_price"] = cost_val
                to_update.append(row)
            else:
                to_create.append({"sku": sku, "name": name,
                                   "base_price": price, "current_price": price,
                                   "cost_price": cost_val})
 
        # ── 6. Bulk INSERT new products ───────────────────────────────────
        if to_create:
            db.bulk_insert_mappings(Product, [
                {
                    "sku":           r["sku"],
                    "name":          r["name"],
                    "base_price":    r["base_price"],
                    "current_price": r["current_price"],
                    "cost_price":    r["cost_price"],   # None for non-FMCG
                    "is_active":     True,
                    "description":   None,
                }
                for r in to_create
            ])
            db.flush()
 
        # ── 7. Bulk UPDATE existing products ───────────────────────────────
        if to_update:
            db.bulk_update_mappings(Product, to_update)
 
        # ── 8. Create inventory for new products - no full re-query ─────────
        #    Only query small batches of inserted SKUs to get IDs
        if to_create:
            new_skus = [r["sku"] for r in to_create]
            existing_inv_pids = {
                row[0]
                for row in db.query(Inventory.product_id).filter(
                    Inventory.product_id.in_(
                        db.query(Product.id).filter(Product.sku.in_(new_skus[:BATCH]))
                    )
                ).all()
            }
            new_inv_maps = []
            for i in range(0, len(new_skus), BATCH):
                batch = new_skus[i:i + BATCH]
                new_prods = db.query(Product.id).filter(Product.sku.in_(batch)).all()
                for (pid,) in new_prods:
                    if pid not in existing_inv_pids:
                        new_inv_maps.append({
                            "product_id":    pid,
                            "current_stock": 0,
                            "reorder_point": 0,
                            "safety_stock":  0,
                        })
                # Update progress after each inventory batch
                job["progress"] = min(
                    90,
                    int(50 + 40 * (i + BATCH) / max(len(new_skus), 1))
                )
 
            if new_inv_maps:
                db.bulk_insert_mappings(Inventory, new_inv_maps)
 
        # ── 9. Single commit ───────────────────────────────────────────────
        db.commit()
 
        job.update({
            "status":  "done",
            "progress": 100,
            "created": len(to_create),
            "updated": len(to_update),
            "skipped": skipped,
        })
 
    except Exception as exc:
        db.rollback()
        job["status"] = "error"
        job["error"]  = str(exc)
    finally:
        db.close()
 
 
def _detect_encoding(b: bytes) -> str:
    for enc in ("utf-8", "utf-8-sig", "latin-1", "cp1252"):
        try:
            b[:4096].decode(enc)
            return enc
        except Exception:
            continue
    return "latin-1"
 
 
# ─── Endpoints ───────────────────────────────────────────────────────────────
 
 
@router.post("/import")
async def import_products_csv(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
):
    """
    Receive CSV file(s), return job_id immediately (<200ms).
    Import runs in the background - monitor via GET /import/{job_id}/progress.

    Changes vs previous version:
    - Does not block the request while parsing a 160MB CSV
    - Frontend gets job_id -> opens EventSource for real progress updates
    """
    if not files:
        raise HTTPException(400, "At least one CSV file is required")
    for f in files:
        if not f.filename.lower().endswith(".csv"):
            raise HTTPException(400, f"Only CSV files are supported: {f.filename}")
 
    # Read bytes immediately (must read before request scope closes)
    file_bytes_list = [await f.read() for f in files]
    filenames       = [f.filename for f in files]
 
    job_id = _new_job()
    background_tasks.add_task(_run_import, job_id, file_bytes_list, filenames)
 
    return {"job_id": job_id, "status": "pending"}
 
 
@router.get("/import/{job_id}/progress")
async def import_progress(job_id: str):
    """
        Server-Sent Events stream - frontend uses EventSource to receive progress.

        Data sent every 500ms:
            data: {"status": "running", "progress": 45, "created": 0, "updated": 0}

        When status == "done" or "error" -> stream ends.
    """
    if job_id not in _jobs:
        raise HTTPException(404, f"Job '{job_id}' not found")
 
    async def event_generator():
        while True:
            job = _jobs.get(job_id, {})
            payload = json.dumps({
                "status":   job.get("status", "unknown"),
                "progress": job.get("progress", 0),
                "total":    job.get("total", 0),
                "created":  job.get("created", 0),
                "updated":  job.get("updated", 0),
                "skipped":  job.get("skipped", 0),
                "error":    job.get("error"),
            })
            yield f"data: {payload}\n\n"
 
            if job.get("status") in ("done", "error"):
                # Cleanup after 5 minutes to avoid memory leak
                await asyncio.sleep(300)
                _jobs.pop(job_id, None)
                break
 
            await asyncio.sleep(0.5)
 
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # disable nginx buffering if present
        },
    )
 


@router.post("/cleanup-junk")
def cleanup_junk_products(db: Session = Depends(get_db)):
    """
    Soft-delete products whose name/SKU looks like a raw StockCode or junk entry.
    Targets UK Retail artifacts: pure numeric names, short alpha-numeric codes,
    cancelled codes (C prefix + digits), known service codes (POST, DOT, etc.).
    Safe: only sets is_active=False, does not delete data.
    """
    import re as _re

    JUNK_SKUS = {
        "POST", "D", "DOT", "M", "AMAZONFEE", "BANK CHARGES", "PADS",
        "CRUK", "ADJUST", "TEST001", "TEST002", "SP1002",
    }
    JUNK_NAME_PATTERNS = [
        r"^[A-Z0-9]{1,6}$",          # Pure code: "15060A", "16131", "84465"
        r"^C\d+$",                    # Cancelled: "C536379"
        r"^\?+$",                     # "???" entries
        r"^(nan|none|unknown)$",       # Literal null strings
    ]

    all_products = db.query(Product).filter(Product.is_active == True).all()

    cleaned = 0
    reasons = {}

    for p in all_products:
        name_upper = (p.name or "").strip().upper()
        sku_upper  = (p.sku  or "").strip().upper()

        reason = None

        # Check SKU against known junk codes
        if sku_upper in JUNK_SKUS:
            reason = f"junk_sku:{p.sku}"

        # Check if name matches a junk pattern (looks like a StockCode, not a real name)
        if not reason:
            for pat in JUNK_NAME_PATTERNS:
                if _re.fullmatch(pat, name_upper):
                    reason = f"code_as_name:{p.name}"
                    break

        # Name same as SKU and SKU looks like a code (no spaces, short)
        if not reason and name_upper == sku_upper and _re.fullmatch(r"[A-Z0-9]{1,8}", sku_upper):
            reason = f"name_equals_sku_code:{p.sku}"

        # Name has no spaces and ≤8 chars and is all caps → likely a code
        if not reason and " " not in name_upper and len(name_upper) <= 8 and name_upper.isupper() and name_upper.isalnum():
            reason = f"short_code_name:{p.name}"

        if reason:
            p.is_active = False
            cleaned += 1
            reasons[p.id] = reason

    db.commit()

    return {
        "cleaned": cleaned,
        "message": f"Soft-deleted {cleaned} junk products",
        "sample_reasons": dict(list(reasons.items())[:10]),
    }


# ─── Product List ────────────────────────────────────────────────────

@router.get("", response_model=ProductListResponse)
def list_products(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    skip: Optional[int] = Query(None, ge=0),
    limit: Optional[int] = Query(None, ge=1, le=200),
    search: Optional[str] = None,
    category_id: Optional[int] = None,
    stock_status: Optional[StockStatusEnum] = None,
    sort_by: str = Query("name", regex="^(name|sku|current_stock|current_price|sales_7d|created_at)$"),
    sort_order: str = Query("asc", regex="^(asc|desc)$"),
    is_active: bool = True,
    db: Session = Depends(get_db),
):
    effective_page = page
    effective_page_size = page_size
    if limit is not None:
        effective_page_size = limit
    if skip is not None:
        effective_page = (skip // effective_page_size) + 1

    query = (
        db.query(Product, Inventory)
        .outerjoin(Inventory, Product.id == Inventory.product_id)
        .filter(Product.is_active == is_active)
    )

    # Search by name or SKU
    if search:
        pattern = f"%{search}%"
        query = query.filter(
            or_(Product.name.ilike(pattern), Product.sku.ilike(pattern))
        )

    # Filter by category
    if category_id is not None:
        query = query.filter(Product.category_id == category_id)

    # Filter by stock status
    if stock_status:
        if stock_status == StockStatusEnum.OUT_OF_STOCK:
            query = query.filter(
                or_(Inventory.current_stock <= 0, Inventory.product_id.is_(None))
            )
        elif stock_status == StockStatusEnum.LOW_STOCK:
            query = query.filter(
                Inventory.current_stock > 0,
                Inventory.current_stock <= Inventory.reorder_point,
            )
        elif stock_status == StockStatusEnum.IN_STOCK:
            query = query.filter(Inventory.current_stock > Inventory.reorder_point)

    total = query.count()

    # Sorting
    sort_col = {
        "name": Product.name,
        "sku": Product.sku,
        "current_stock": Inventory.current_stock,
        "current_price": Product.current_price,
        "created_at": Product.created_at,
    }.get(sort_by, Product.name)

    if sort_order == "desc":
        query = query.order_by(sort_col.desc())
    else:
        query = query.order_by(sort_col.asc())

    rows = query.offset((effective_page - 1) * effective_page_size).limit(effective_page_size).all()

    # Get 7-day sales for these products
    latest_sales_date = None
    product_ids = [p.id for p, _ in rows]
    sales_7d = {}
    if product_ids:
        # Skip filters to get the latest transaction date across the whole database
        latest_sales_date = db.query(func.max(SalesHistory.date)).scalar()
        anchor_date = latest_sales_date or datetime.utcnow().date()
        seven_days_ago = anchor_date - timedelta(days=7)
        sales_rows = (
            db.query(SalesHistory.product_id, func.sum(SalesHistory.quantity_sold))
            .filter(
                SalesHistory.product_id.in_(product_ids),
                SalesHistory.date >= seven_days_ago,
            )
            .group_by(SalesHistory.product_id)
            .all()
        )
        sales_7d = {pid: int(qty) for pid, qty in sales_rows}

    items = []
    for product, inv in rows:
        stock = inv.current_stock if inv else 0
        rop = inv.reorder_point if inv else 0
        cat = db.query(Category.name).filter(Category.id == product.category_id).scalar() if product.category_id else None

        items.append(ProductListItem(
            id=product.id,
            sku=product.sku,
            name=product.name,
            description=product.description,
            category_id=product.category_id,
            category_name=cat,
            image_url=product.image_url,
            current_stock=stock,
            reorder_point=rop,
            stock_status=_stock_status(stock, rop),
            base_price=float(product.base_price),
            current_price=float(product.current_price),
            cost_price=float(product.cost_price) if product.cost_price is not None else None,
            sales_7d=sales_7d.get(product.id, 0),
            is_active=product.is_active,
        ))

    # Handle sales_7d sorting in-memory (can't easily join aggregate)
    if sort_by == "sales_7d":
        items.sort(key=lambda x: x.sales_7d, reverse=(sort_order == "desc"))

    total_pages = (total + effective_page_size - 1) // effective_page_size

    return ProductListResponse(
        items=items,
        total=total,
        page=effective_page,
        page_size=effective_page_size,
        total_pages=total_pages,
    )




# ─── Product Detail ─────────────────────────────────────────────────

@router.get("/{product_id}", response_model=ProductDetail)
def get_product(product_id: int, db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    inv = db.query(Inventory).filter(Inventory.product_id == product_id).first()
    cat = None
    if product.category_id:
        cat = db.query(Category).filter(Category.id == product.category_id).first()

    stock = inv.current_stock if inv else 0
    rop = inv.reorder_point if inv else 0
    ss = inv.safety_stock if inv else 0

    return ProductDetail(
        id=product.id,
        sku=product.sku,
        name=product.name,
        description=product.description,
        category=CategoryResponse.model_validate(cat) if cat else None,
        image_url=product.image_url,
        base_price=float(product.base_price),
        current_price=float(product.current_price),
        cost_price=float(product.cost_price) if product.cost_price else None,
        current_stock=stock,
        reorder_point=rop,
        safety_stock=ss,
        stock_status=_stock_status(stock, rop),
        is_active=product.is_active,
        created_at=product.created_at,
        updated_at=product.updated_at,
    )


# ─── Create Product ─────────────────────────────────────────────────

@router.post("", response_model=ProductDetail, status_code=201)
def create_product(data: ProductCreate, db: Session = Depends(get_db)):
    # Check duplicate SKU
    existing = db.query(Product).filter(Product.sku == data.sku).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"SKU '{data.sku}' already exists")

    product = Product(
        sku=data.sku,
        name=data.name,
        description=data.description,
        category_id=data.category_id,
        image_url=data.image_url,
        base_price=data.base_price,
        current_price=data.current_price or data.base_price,
        cost_price=data.cost_price,
    )
    db.add(product)
    db.flush()

    # Create inventory record
    inv = Inventory(
        product_id=product.id,
        current_stock=data.initial_stock,
    )
    db.add(inv)
    db.commit()
    db.refresh(product)

    return get_product(product.id, db)


# ─── Update Product ─────────────────────────────────────────────────

@router.put("/{product_id}", response_model=ProductDetail)
def update_product(product_id: int, data: ProductUpdate, db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(product, field, value)

    db.commit()
    db.refresh(product)
    return get_product(product.id, db)


# ─── Delete (soft) ──────────────────────────────────────────────────

@router.delete("/{product_id}", status_code=204)
def delete_product(product_id: int, db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    product.is_active = False
    db.commit()
    return None


# ─── Bulk Delete (soft) ─────────────────────────────────────────────

@router.post("/bulk-delete", response_model=BulkDeleteResponse)
def bulk_delete_products(data: BulkDeleteRequest, db: Session = Depends(get_db)):
    if data.ids:
        target_ids = data.ids
    else:
        query = (
            db.query(Product.id)
            .outerjoin(Inventory, Product.id == Inventory.product_id)
            .filter(Product.is_active == (True if data.is_active is None else data.is_active))
        )

        if data.search:
            pattern = f"%{data.search}%"
            query = query.filter(
                or_(Product.name.ilike(pattern), Product.sku.ilike(pattern))
            )

        if data.category_id is not None:
            query = query.filter(Product.category_id == data.category_id)

        if data.stock_status:
            if data.stock_status == StockStatusEnum.OUT_OF_STOCK:
                query = query.filter(
                    or_(Inventory.current_stock <= 0, Inventory.product_id.is_(None))
                )
            elif data.stock_status == StockStatusEnum.LOW_STOCK:
                query = query.filter(
                    Inventory.current_stock > 0,
                    Inventory.current_stock <= Inventory.reorder_point,
                )
            elif data.stock_status == StockStatusEnum.IN_STOCK:
                query = query.filter(Inventory.current_stock > Inventory.reorder_point)

        target_ids = [row[0] for row in query.all()]

    if not target_ids:
        return BulkDeleteResponse(deleted=0)

    if data.hard_delete:
        db.query(InventoryTransaction).filter(
            InventoryTransaction.product_id.in_(target_ids)
        ).delete(synchronize_session=False)
        db.query(SalesHistory).filter(
            SalesHistory.product_id.in_(target_ids)
        ).delete(synchronize_session=False)
        db.query(Inventory).filter(
            Inventory.product_id.in_(target_ids)
        ).delete(synchronize_session=False)
        db.query(ProductSupplier).filter(
            ProductSupplier.product_id.in_(target_ids)
        ).delete(synchronize_session=False)
        db.query(DSSReport).filter(
            DSSReport.product_id.in_(target_ids)
        ).delete(synchronize_session=False)
        db.query(Notification).filter(
            Notification.product_id.in_(target_ids)
        ).delete(synchronize_session=False)

        deleted = (
            db.query(Product)
            .filter(Product.id.in_(target_ids))
            .delete(synchronize_session=False)
        )
        db.commit()
        return BulkDeleteResponse(deleted=deleted)

    deleted = (
        db.query(Product)
        .filter(Product.id.in_(target_ids))
        .update({Product.is_active: False}, synchronize_session=False)
    )
    db.commit()
    return BulkDeleteResponse(deleted=deleted)
