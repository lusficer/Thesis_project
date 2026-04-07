"""
Sales API — import sales history from CSV (reuses Universal Data Adapter),
query daily sales for charts.

Import runs as a BackgroundTask (same pattern as products.py) to avoid
blocking the uvicorn event loop on large files like FMCG (200k rows).
"""

import io
import json
import uuid
import asyncio
from datetime import date, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query, BackgroundTasks
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
import pandas as pd

from app.database import get_db, SessionLocal
from app.models import Product, SalesHistory, Inventory
from app.schemas import SalesImportResponse, DailySalesResponse

router = APIRouter(prefix="/sales", tags=["Sales"])

# job_id → {status, progress, products_imported, records_imported, date_range, error}
_jobs: dict[str, dict] = {}


def _new_job() -> str:
    jid = str(uuid.uuid4())
    _jobs[jid] = {
        "status":            "pending",
        "progress":          0,
        "products_imported": 0,
        "records_imported":  0,
        "date_range":        None,
        "error":             None,
    }
    return jid


def _is_placeholder_name(name: str, sku: str) -> bool:
    normalized     = (name or "").strip().lower()
    sku_normalized = (sku  or "").strip().lower()
    if not normalized:
        return True
    if normalized == sku_normalized:
        return True
    if normalized.startswith("product ") and sku_normalized in normalized:
        return True
    return False


# ─── Background worker ────────────────────────────────────────────────

def _run_import(job_id: str, file_bytes_list: list[bytes], filenames: list[str]):
    """Runs in BackgroundTasks thread pool — does not block the event loop."""
    job = _jobs[job_id]
    job["status"] = "running"
    job["progress"] = 5

    db: Session = SessionLocal()
    try:
        from app.core.preprocessing import smart_merge_files

        # ── 1. Decode bytes → DataFrames ──────────────────────────────
        raw_dfs: list[pd.DataFrame] = []
        for b in file_bytes_list:
            for enc in ("utf-8", "utf-8-sig", "latin-1", "cp1252"):
                try:
                    raw_dfs.append(pd.read_csv(io.BytesIO(b), encoding=enc, low_memory=False))
                    break
                except Exception:
                    continue

        if not raw_dfs:
            raise ValueError("Failed to parse any CSV file")

        job["progress"] = 15

        # ── 2. Normalize via preprocessing adapter ────────────────────
        df_clean, price_map, cost_map = smart_merge_files(raw_dfs)

        if df_clean is None or df_clean.empty:
            raise ValueError("Could not parse sales data from CSV — check file format")

        job["progress"] = 30

        # ── 3. Aggregate to product x date ───────────────────────────
        df_clean["date"] = pd.to_datetime(df_clean["order_purchase_timestamp"]).dt.date
        groups       = list(df_clean.groupby(["product_id", "date"]))
        total_groups = len(groups)

        batch_id         = str(uuid.uuid4())[:8]
        records_imported = 0
        products_seen    = set()

        # ── 4. Upsert products + sales history ────────────────────────
        for idx, ((pid, d), group) in enumerate(groups):
            pid_str = str(pid)

            product_name = None
            if "product_name" in group.columns:
                s = group["product_name"].dropna()
                if not s.empty:
                    product_name = str(s.iloc[0]).strip()

            price_value = float(price_map[pid]) if pid in price_map else None
            cost_value  = float(cost_map[pid_str]) if pid_str in cost_map else None
            qty         = int(group["quantity"].sum())

            product = (
                db.query(Product)
                .filter((Product.sku == pid_str) | (Product.name == pid_str))
                .first()
            )

            if not product:
                product = Product(
                    sku=pid_str[:100],
                    name=(product_name or pid_str)[:500],
                    base_price=price_value or 0,
                    current_price=price_value or 0,
                    cost_price=cost_value,
                )
                db.add(product)
                db.flush()
                db.add(Inventory(product_id=product.id, current_stock=0))
            else:
                if product_name and _is_placeholder_name(product.name, product.sku):
                    product.name = product_name[:500]
                if product.is_active is False:
                    product.is_active = True
                if price_value is not None:
                    if product.base_price is None or float(product.base_price) == 0:
                        product.base_price = price_value
                    if product.current_price is None or float(product.current_price) == 0:
                        product.current_price = price_value
                if cost_value is not None and (product.cost_price is None or float(product.cost_price) == 0):
                    product.cost_price = cost_value

            existing = (
                db.query(SalesHistory)
                .filter(SalesHistory.product_id == product.id, SalesHistory.date == d)
                .first()
            )
            if existing:
                existing.quantity_sold += qty
                if price_value is not None:
                    existing.revenue = float(existing.quantity_sold) * price_value
            else:
                db.add(SalesHistory(
                    product_id=product.id,
                    date=d,
                    quantity_sold=qty,
                    revenue=float(qty) * (price_value or 0),
                    import_batch=batch_id,
                ))

            products_seen.add(product.id)
            records_imported += 1

            # Commit every 500 groups to avoid huge transactions
            if idx % 500 == 0:
                db.commit()
                job["progress"] = min(90, 30 + int(60 * idx / max(total_groups, 1)))

        db.commit()
        job["progress"] = 95

        dates      = df_clean["date"].dropna()
        date_range = f"{dates.min()} to {dates.max()}" if not dates.empty else None

        job.update({
            "status":            "done",
            "progress":          100,
            "products_imported": len(products_seen),
            "records_imported":  records_imported,
            "date_range":        date_range,
        })

    except Exception as exc:
        db.rollback()
        job["status"] = "error"
        job["error"]  = str(exc)
    finally:
        db.close()


# ─── Endpoints ────────────────────────────────────────────────────────

@router.post("/import")
async def import_sales_csv(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
):
    """
    Accept CSV file(s), return job_id immediately (<200ms).
    Import runs in background — poll GET /sales/import/{job_id}/progress.
    """
    for f in files:
        if not f.filename.lower().endswith(".csv"):
            raise HTTPException(400, f"Only CSV files are supported: {f.filename}")

    file_bytes_list = [await f.read() for f in files]
    filenames       = [f.filename for f in files]

    job_id = _new_job()
    background_tasks.add_task(_run_import, job_id, file_bytes_list, filenames)

    return {"job_id": job_id, "status": "pending"}


@router.get("/import/{job_id}/progress")
async def import_progress(job_id: str):
    """SSE stream — poll until status == done | error."""
    if job_id not in _jobs:
        raise HTTPException(404, f"Job '{job_id}' not found")

    async def event_generator():
        while True:
            job = _jobs.get(job_id, {})
            yield f"data: {json.dumps(job)}\n\n"

            if job.get("status") in ("done", "error"):
                await asyncio.sleep(300)
                _jobs.pop(job_id, None)
                break

            await asyncio.sleep(0.8)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/{product_id}/daily", response_model=list[DailySalesResponse])
def get_daily_sales(
    product_id: int,
    days: Optional[int] = Query(None, ge=1, le=3650),
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    db: Session = Depends(get_db),
):
    if days is not None and not start_date and not end_date:
        end_date   = date.today()
        start_date = end_date - timedelta(days=days - 1)

    query = db.query(SalesHistory).filter(SalesHistory.product_id == product_id)
    if start_date:
        query = query.filter(SalesHistory.date >= start_date)
    if end_date:
        query = query.filter(SalesHistory.date <= end_date)

    rows = query.order_by(SalesHistory.date.asc()).all()
    return [
        DailySalesResponse(
            date=r.date,
            quantity=r.quantity_sold,
            quantity_sold=r.quantity_sold,
            revenue=float(r.revenue or 0),
        )
        for r in rows
    ]