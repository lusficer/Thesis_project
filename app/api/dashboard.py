"""
Dashboard API — summary statistics for the main overview page.

FIX: anchor_date always uses max(SalesHistory.date) in the DB.
    Never fall back to datetime.utcnow() because old data (FMCG 2024)
    would make the entire reporting window empty.
"""

from datetime import timedelta
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app.models import Product, Inventory, SalesHistory, Notification
from app.schemas import DashboardSummary

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


def _get_anchor_date(db: Session):
    """
    Always use the newest date in the DB as "today".
    If the DB is empty, return None - caller handles it.
    """
    return db.query(func.max(SalesHistory.date)).scalar()


@router.get("/summary", response_model=DashboardSummary)
def get_summary(db: Session = Depends(get_db)):
    # ── Anchor date: newest date in sales_history ───────────────────
    today = _get_anchor_date(db)
    has_sales = today is not None

    week_ago      = (today - timedelta(days=7))  if has_sales else None
    prev_week_ago = (today - timedelta(days=14)) if has_sales else None
    month_ago     = (today - timedelta(days=30)) if has_sales else None

    # ── Total active products ───────────────────────────────────────
    total_products = (
        db.query(func.count(Product.id))
        .filter(Product.is_active == True)
        .scalar() or 0
    )

    # ── Inventory value ─────────────────────────────────────────────
    inv_value = (
        db.query(func.sum(Inventory.current_stock * Product.current_price))
        .join(Product, Product.id == Inventory.product_id)
        .filter(Product.is_active == True)
        .scalar()
    ) or 0

    # ── Low stock / out of stock ──────────────────────────────────────
    low_stock = (
        db.query(func.count(Inventory.id))
        .join(Product, Product.id == Inventory.product_id)
        .filter(
            Product.is_active == True,
            Inventory.current_stock > 0,
            Inventory.current_stock <= Inventory.reorder_point,
        )
        .scalar()
    ) or 0

    oos = (
        db.query(func.count(Inventory.id))
        .join(Product, Product.id == Inventory.product_id)
        .filter(Product.is_active == True, Inventory.current_stock <= 0)
        .scalar()
    ) or 0

    # ── Revenue stats (only when data exists) ───────────────────────
    if has_sales:
        rev_today = (
            db.query(func.sum(SalesHistory.revenue))
            .filter(SalesHistory.date == today)
            .scalar()
        ) or 0

        rev_week = (
            db.query(func.sum(SalesHistory.revenue))
            .filter(SalesHistory.date >= week_ago)
            .scalar()
        ) or 0

        rev_month = (
            db.query(func.sum(SalesHistory.revenue))
            .filter(SalesHistory.date >= month_ago)
            .scalar()
        ) or 0

        sales_today = (
            db.query(func.sum(SalesHistory.quantity_sold))
            .filter(SalesHistory.date == today)
            .scalar()
        ) or 0

        revenue_prev_week = (
            db.query(func.sum(SalesHistory.revenue))
            .filter(
                SalesHistory.date >= prev_week_ago,
                SalesHistory.date < week_ago,
            )
            .scalar()
        ) or 0
    else:
        rev_today = rev_week = rev_month = sales_today = revenue_prev_week = 0

    # ── Sales trend ───────────────────────────────────────────────────
    if rev_week > revenue_prev_week:
        recent_sales_trend = "UP"
    elif rev_week < revenue_prev_week:
        recent_sales_trend = "DOWN"
    else:
        recent_sales_trend = "STABLE"

    # ── Notifications ─────────────────────────────────────────────────
    total_notifications = db.query(func.count(Notification.id)).scalar() or 0

    # ── Top products (30 days from anchor date) ─────────────────────
    top_products = []
    if has_sales:
        top_rows = (
            db.query(
                Product.id,
                Product.name,
                func.sum(SalesHistory.revenue),
                func.sum(SalesHistory.quantity_sold),
            )
            .join(SalesHistory, Product.id == SalesHistory.product_id)
            .filter(Product.is_active == True, SalesHistory.date >= month_ago)
            .group_by(Product.id, Product.name)
            .order_by(func.sum(SalesHistory.revenue).desc())
            .limit(5)
            .all()
        )
        top_products = [
            {
                "product_id": pid,
                "name": name,
                "revenue": float(revenue or 0),
                "units_sold": int(units_sold or 0),
            }
            for pid, name, revenue, units_sold in top_rows
        ]

    # ── Low stock alerts ──────────────────────────────────────────────
    low_stock_rows = (
        db.query(Product.id, Product.name, Inventory.current_stock)
        .join(Inventory, Product.id == Inventory.product_id)
        .filter(
            Product.is_active == True,
            Inventory.current_stock <= Inventory.reorder_point,
        )
        .order_by(Inventory.current_stock.asc())
        .limit(10)
        .all()
    )

    # Compute last-7-days velocity (from anchor_date) for each alert product
    alert_pids = [row[0] for row in low_stock_rows]
    velocity_map = {}
    if alert_pids and has_sales:
        seven_days_ago = today - timedelta(days=7)
        vel_rows = (
            db.query(SalesHistory.product_id, func.sum(SalesHistory.quantity_sold))
            .filter(
                SalesHistory.product_id.in_(alert_pids),
                SalesHistory.date >= seven_days_ago,
            )
            .group_by(SalesHistory.product_id)
            .all()
        )
        velocity_map = {pid: float(qty or 0) / 7.0 for pid, qty in vel_rows}

    low_stock_alerts = []
    for pid, name, current_stock in low_stock_rows:
        stock = int(current_stock or 0)
        daily_vel = velocity_map.get(pid, 0.0)
        days_left = int(stock / daily_vel) if daily_vel > 0 else None
        low_stock_alerts.append({
            "product_id": pid,
            "name": name,
            "current_stock": stock,
            "days_until_stockout": days_left,
            "daily_velocity": round(daily_vel, 2),
        })

    return DashboardSummary(
        total_products=total_products,
        total_inventory_value=float(inv_value),
        low_stock_count=low_stock,
        out_of_stock_count=oos,
        revenue_today=float(rev_today),
        revenue_week=float(rev_week),
        revenue_month=float(rev_month),
        total_sales_today=int(sales_today),
        products_needing_attention=int(low_stock + oos),
        total_notifications=int(total_notifications),
        recent_sales_trend=recent_sales_trend,
        top_products=top_products,
        low_stock_alerts=low_stock_alerts,
    )


@router.get("/revenue-trend")
def get_revenue_trend(
    days: int = 30,
    from_date: str = None,
    to_date: str = None,
    db: Session = Depends(get_db),
):
    """
    Return daily revenue.
    - ?days=N        -> N days from anchor_date (latest date in DB)
    - ?from=X&to=Y   -> custom range (YYYY-MM-DD)
    """
    from datetime import date as date_type

    anchor = _get_anchor_date(db)
    if anchor is None:
        return {"anchor_date": None, "data": []}

    # Custom range
    if from_date and to_date:
        try:
            start = date_type.fromisoformat(from_date)
            today = date_type.fromisoformat(to_date)
        except ValueError:
            start = anchor - timedelta(days=days - 1)
            today = anchor
    else:
        today = anchor
        start = today - timedelta(days=days - 1)

    rows = (
        db.query(
            SalesHistory.date,
            func.sum(SalesHistory.revenue),
            func.sum(SalesHistory.quantity_sold),
        )
        .filter(SalesHistory.date >= start, SalesHistory.date <= today)
        .group_by(SalesHistory.date)
        .order_by(SalesHistory.date.asc())
        .all()
    )

    # Fill all days (including days with no sales -> 0)
    date_map = {row[0]: (float(row[1] or 0), int(row[2] or 0)) for row in rows}
    from datetime import timedelta as td
    result = []
    cur = start
    while cur <= today:
        revenue, quantity = date_map.get(cur, (0.0, 0))
        result.append({
            # Include year to avoid confusing 2024 data with the current year
            "date":      cur.strftime("%m/%d/%y"),
            "full_date": cur.isoformat(),
            "revenue":   revenue,
            "quantity":  quantity,
        })
        cur += td(days=1)

    return {"anchor_date": today.isoformat(), "data": result}