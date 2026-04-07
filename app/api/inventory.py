"""
Inventory API — stock-in, stock-out, transaction history, low-stock alerts.
"""

from datetime import datetime, timedelta, date as date_type
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app.models import (
    Product, Inventory, InventoryTransaction, TransactionType, SalesHistory,
)
from app.schemas import (
    StockInRequest, StockOutRequest,
    InventoryTransactionResponse, InventoryAlertItem, StockStatusEnum,
    TransactionTypeEnum,
)

router = APIRouter(prefix="/inventory", tags=["Inventory"])

# Reason values that are valid for stock-out operations
VALID_OUT_REASONS = {
    TransactionType.SALE,
    TransactionType.WHOLESALE,
    TransactionType.DAMAGE,
    TransactionType.LOSS,
    TransactionType.OUT,   # backward compat
}

# Reasons that should auto-create a SalesHistory record
SALE_REASONS = {TransactionType.SALE, TransactionType.WHOLESALE}


def _stock_status(stock: int, rop: int) -> StockStatusEnum:
    if stock <= 0:
        return StockStatusEnum.OUT_OF_STOCK
    if stock <= rop:
        return StockStatusEnum.LOW_STOCK
    return StockStatusEnum.IN_STOCK


def _build_txn_response(txn: InventoryTransaction, product_name: str, sku: str) -> InventoryTransactionResponse:
    return InventoryTransactionResponse(
        id=txn.id,
        product_id=txn.product_id,
        product_name=product_name,
        sku=sku,
        type=txn.type.value,
        quantity=txn.quantity,
        reference=txn.reference,
        notes=txn.notes,
        unit_price=float(txn.unit_price) if txn.unit_price is not None else None,
        supplier=txn.supplier,
        customer_name=txn.customer_name,
        timestamp=txn.timestamp,
    )


# ─── Stock In ────────────────────────────────────────────────────────

@router.post("/stock-in", response_model=InventoryTransactionResponse, status_code=201)
def stock_in(data: StockInRequest, db: Session = Depends(get_db)):
    inv = db.query(Inventory).filter(Inventory.product_id == data.product_id).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Product inventory not found")

    inv.current_stock += data.quantity

    txn = InventoryTransaction(
        product_id=data.product_id,
        type=TransactionType.IN,
        quantity=data.quantity,
        reference=data.reference,
        notes=data.notes,
        unit_price=data.unit_cost,   # store purchase cost in unit_price column
        supplier=data.supplier,
    )
    db.add(txn)
    db.commit()
    db.refresh(txn)

    product = db.query(Product).filter(Product.id == data.product_id).first()
    return _build_txn_response(txn, product.name if product else None, product.sku if product else None)


# ─── Stock Out ───────────────────────────────────────────────────────

@router.post("/stock-out", response_model=InventoryTransactionResponse, status_code=201)
def stock_out(data: StockOutRequest, db: Session = Depends(get_db)):
    inv = db.query(Inventory).filter(Inventory.product_id == data.product_id).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Product inventory not found")

    if inv.current_stock < data.quantity:
        raise HTTPException(
            status_code=400,
            detail=f"Insufficient stock. Available: {inv.current_stock}, requested: {data.quantity}"
        )

    # Parse reason from request string and validate it's a supported stock-out type
    try:
        reason_raw = (data.reason or "SALE").strip().upper()
        reason = TransactionType(reason_raw)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown transaction type: {data.reason}")

    if reason not in VALID_OUT_REASONS:
        raise HTTPException(status_code=400, detail=f"Invalid stock-out reason: {reason}")

    inv.current_stock -= data.quantity

    # Resolve effective unit price: use provided value, fall back to product's current_price for sales
    effective_price = data.unit_price
    if reason in SALE_REASONS and effective_price is None:
        product = db.query(Product).filter(Product.id == data.product_id).first()
        effective_price = float(product.current_price) if product and product.current_price else None

    txn = InventoryTransaction(
        product_id=data.product_id,
        type=reason,
        quantity=-data.quantity,
        reference=data.reference,
        notes=data.notes,
        unit_price=effective_price,
        customer_name=data.customer_name,
    )
    db.add(txn)

    # Auto-create / upsert SalesHistory for SALE and WHOLESALE
    if reason in SALE_REASONS:
        today = date_type.today()
        revenue = (effective_price or 0) * data.quantity

        # Upsert: merge into existing manual record for the same product+date.
        # Records with import_batch set are from CSV imports — never merge those.
        existing = db.query(SalesHistory).filter(
            SalesHistory.product_id == data.product_id,
            SalesHistory.date == today,
            SalesHistory.import_batch == None,
        ).first()

        if existing:
            existing.quantity_sold += data.quantity
            existing.revenue += revenue
        else:
            db.add(SalesHistory(
                product_id=data.product_id,
                date=today,
                quantity_sold=data.quantity,
                revenue=revenue,
                import_batch=None,
            ))

    db.commit()
    db.refresh(txn)

    product = db.query(Product).filter(Product.id == data.product_id).first()
    return _build_txn_response(txn, product.name if product else None, product.sku if product else None)


# ─── Transaction History (per product) ──────────────────────────────

@router.get("/{product_id}/transactions", response_model=list[InventoryTransactionResponse])
def get_transactions(
    product_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    type_filter: Optional[TransactionType] = None,
    db: Session = Depends(get_db),
):
    query = db.query(InventoryTransaction).filter(InventoryTransaction.product_id == product_id)
    if type_filter:
        query = query.filter(InventoryTransaction.type == type_filter)

    txns = (
        query.order_by(InventoryTransaction.timestamp.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    product = db.query(Product).filter(Product.id == product_id).first()
    p_name = product.name if product else None
    p_sku = product.sku if product else None

    return [_build_txn_response(t, p_name, p_sku) for t in txns]


# ─── All Transactions (inventory dashboard view) ─────────────────────

@router.get("/transactions", response_model=list[InventoryTransactionResponse])
def get_all_transactions(
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(InventoryTransaction, Product.name, Product.sku)
        .join(Product, Product.id == InventoryTransaction.product_id)
        .order_by(InventoryTransaction.timestamp.desc())
        .limit(limit)
        .all()
    )

    return [_build_txn_response(txn, name, sku) for txn, name, sku in rows]


# ─── Low Stock Alerts ───────────────────────────────────────────────

@router.get("/alerts", response_model=list[InventoryAlertItem])
def get_alerts(db: Session = Depends(get_db)):
    """Products at or below reorder point, sorted by urgency (lowest stock first)."""
    rows = (
        db.query(Product, Inventory)
        .join(Inventory, Product.id == Inventory.product_id)
        .filter(
            Product.is_active == True,
            Inventory.current_stock <= Inventory.reorder_point,
        )
        .order_by(Inventory.current_stock.asc())
        .all()
    )

    alerts = []
    for product, inv in rows:
        latest_sales_date = db.query(func.max(SalesHistory.date)).scalar()
        today = latest_sales_date or datetime.utcnow().date()
        thirty_days_ago = today - timedelta(days=30)

        avg_daily = (
            db.query(func.avg(SalesHistory.quantity_sold))
            .filter(
                SalesHistory.product_id == product.id,
                SalesHistory.date >= thirty_days_ago,
            )
            .scalar()
        )
        days_left = None
        if avg_daily and avg_daily > 0:
            days_left = int(inv.current_stock / float(avg_daily))

        alerts.append(InventoryAlertItem(
            product_id=product.id,
            product_name=product.name,
            sku=product.sku,
            current_stock=inv.current_stock,
            reorder_point=inv.reorder_point,
            safety_stock=inv.safety_stock,
            stock_status=_stock_status(inv.current_stock, inv.reorder_point),
            days_until_stockout=days_left,
        ))

    return alerts
