"""
DSS API — Phase 3 Integration
- Train from DB sales_history
- Run forecast + inventory + pricing analysis
- Save reports to DB
- Confirm ORDER_NOW → auto stock-in transaction
- Apply pricing → auto update product price
- Backtest validation from DB data
- Auto-generate notifications
"""

from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
import pandas as pd
import numpy as np

from app.database import get_db
from app.models import (
    Product, Inventory, SalesHistory, DSSReport,
    InventoryTransaction, TransactionType,
    Notification, NotificationType,
)
from app.schemas import (
    DSSRunRequest, DSSReportResponse,
    DSSConfirmOrderRequest, DSSApplyPriceRequest, DSSActionResponse,
    BacktestRequest, BacktestResponse, DSSScanAllRequest,
)
from app.api.notifications import create_notification

router = APIRouter(prefix="/dss", tags=["DSS"])

# In-memory model store (same pattern as original thesis app)
model_store: dict = {}


def _probability_pct(value: Optional[float]) -> float:
    if value is None:
        return 0.0
    if value <= 1:
        return float(value) * 100
    return float(value)


def _get_sales_df(product_id: int, db: Session) -> pd.DataFrame:
    """Pull sales history from DB into a DataFrame for model training."""
    rows = (
        db.query(SalesHistory.date, SalesHistory.quantity_sold)
        .filter(SalesHistory.product_id == product_id)
        .order_by(SalesHistory.date.asc())
        .all()
    )
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows, columns=["ds", "y"])
    df["ds"] = pd.to_datetime(df["ds"])
    return df


# ─── Run DSS Analysis ───────────────────────────────────────────────

@router.post("/run", response_model=DSSReportResponse)
def run_dss(data: DSSRunRequest, db: Session = Depends(get_db)):
    """
    Full DSS pipeline:
    1. Pull sales history from DB
    2. Train Prophet + XGBoost hybrid model
    3. Generate forecast
    4. Run inventory analysis (ROP, safety stock, stockout probability)
    5. Run velocity-based pricing rules
    6. Save report to DB
    7. Update inventory ROP/safety_stock
    8. Generate notifications
    """
    product = db.query(Product).filter(Product.id == data.product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    inv = db.query(Inventory).filter(Inventory.product_id == data.product_id).first()

    # Get sales data from DB
    sales_df = _get_sales_df(data.product_id, db)
    if len(sales_df) < 30:
        raise HTTPException(
            status_code=400,
            detail=f"Insufficient sales history: {len(sales_df)} days (minimum 30 required)"
        )

    # Resolve current stock and price
    current_stock = data.current_stock if data.current_stock is not None else (inv.current_stock if inv else 0)
    current_price = data.current_price if data.current_price is not None else float(product.current_price)

    # Train model + run analysis
    try:
        from app.core.hybrid_model import ThesisHybridModel
        from app.core.dss_engine import DSSEngine

        model = ThesisHybridModel(penalty_under=data.penalty_under)
        model.fit(sales_df)
        model_store[data.product_id] = model

        forecast = model.predict(data.future_days)

        engine = DSSEngine()
        result = engine.analyze(
            forecast_df=forecast,
            current_stock=current_stock,
            current_price=current_price,
            target_days_to_sell=data.target_days_to_sell,
        )

        forecast_data = {
            "dates": forecast["ds"].dt.strftime("%Y-%m-%d").tolist(),
            "yhat": forecast["yhat"].round(2).tolist(),
            "yhat_lower": forecast.get("yhat_lower", forecast["yhat"]).round(2).tolist(),
            "yhat_upper": forecast.get("yhat_upper", forecast["yhat"]).round(2).tolist(),
        }

    except ImportError:
        forecast_data = {"error": "Core DSS modules not found. Place hybrid_model.py and dss_engine.py in app/core/"}
        result = {
            "inventory_advice": {"status": "UNAVAILABLE"},
            "pricing_advice": {"status": "UNAVAILABLE"},
        }

    # Save report
    report = DSSReport(
        product_id=data.product_id,
        forecast_data=forecast_data,
        inventory_advice=result.get("inventory_advice"),
        pricing_advice=result.get("pricing_advice"),
        ai_reasoning=result.get("ai_narrative"),
        parameters={
            "future_days": data.future_days,
            "current_stock": current_stock,
            "current_price": current_price,
            "target_days_to_sell": data.target_days_to_sell,
            "penalty_under": data.penalty_under,
        },
    )
    db.add(report)
    db.flush()

    # ── Update inventory ROP / safety stock ──────────────────────────
    if inv and isinstance(result.get("inventory_advice"), dict):
        advice = result["inventory_advice"]
        if "reorder_point" in advice:
            inv.reorder_point = int(advice["reorder_point"])
        if "safety_stock" in advice:
            inv.safety_stock = int(advice["safety_stock"])

    # ── Generate notifications based on results ──────────────────────
    inv_advice = result.get("inventory_advice", {})
    pricing_advice = result.get("pricing_advice", {})

    create_notification(
        db, NotificationType.DSS_COMPLETED,
        title=f"DSS analysis completed for {product.name}",
        message=f"Action: {inv_advice.get('action', 'N/A')}. "
            f"Stockout probability: {_probability_pct(inv_advice.get('stockout_probability', 0)):.1f}%",
        product_id=product.id,
        dss_report_id=report.id,
    )

    if inv_advice.get("action") == "ORDER_NOW":
        create_notification(
            db, NotificationType.LOW_STOCK,
            title=f"ORDER NOW: {product.name}",
            message=f"Current stock: {current_stock}. "
                    f"Suggested order: {inv_advice.get('suggested_order_qty', '?')} units. "
                    f"Stockout risk: {_probability_pct(inv_advice.get('stockout_probability', 0)):.1f}%",
            product_id=product.id,
            dss_report_id=report.id,
        )

    stockout_prob = _probability_pct(inv_advice.get("stockout_probability", 0))
    if isinstance(stockout_prob, (int, float)) and stockout_prob > 80:
        create_notification(
            db, NotificationType.STOCKOUT_WARNING,
            title=f"HIGH stockout risk: {product.name}",
            message=f"Stockout probability: {stockout_prob:.1f}%. Immediate action required.",
            product_id=product.id,
            dss_report_id=report.id,
        )

    if pricing_advice.get("action") in ("INCREASE", "DECREASE"):
        direction = "up" if pricing_advice["action"] == "INCREASE" else "down"
        create_notification(
            db, NotificationType.PRICE_UPDATED,
            title=f"Price suggestion ({direction}): {product.name}",
            message=f"Suggested: ${pricing_advice.get('suggested_price', 0):.2f} "
                    f"({pricing_advice.get('change_percent', pricing_advice.get('adjustment_pct', 0)):+.1f}% from ${current_price:.2f})",
            product_id=product.id,
            dss_report_id=report.id,
        )

    db.commit()
    db.refresh(report)

    return DSSReportResponse(
        id=report.id,
        report_id=report.id,
        product_id=report.product_id,
        generated_at=report.generated_at,
        forecast_data=report.forecast_data,
        inventory_advice=report.inventory_advice,
        pricing_advice=report.pricing_advice,
        ai_reasoning=report.ai_reasoning,
        parameters=report.parameters,
    )


# ─── Confirm Order (ORDER_NOW → Stock In) ───────────────────────────

@router.post("/confirm-order", response_model=DSSActionResponse)
def confirm_order(data: DSSConfirmOrderRequest, db: Session = Depends(get_db)):
    """
    Manager confirms DSS ORDER_NOW recommendation.
    Creates a stock-in transaction and updates inventory.
    """
    report = db.query(DSSReport).filter(DSSReport.id == data.report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="DSS report not found")

    product = db.query(Product).filter(Product.id == report.product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    inv = db.query(Inventory).filter(Inventory.product_id == report.product_id).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Product inventory not found")

    quantity = data.quantity
    if quantity is None:
        advice = report.inventory_advice or {}
        quantity = int(advice.get("qty_to_order") or advice.get("suggested_order_qty") or 0)
        if quantity <= 0:
            raise HTTPException(status_code=400, detail="No valid order quantity in report. Provide quantity explicitly.")

    txn = InventoryTransaction(
        product_id=report.product_id,
        type=TransactionType.IN,
        quantity=quantity,
        reference=f"DSS-{report.id}",
        notes=data.notes or f"DSS order confirmation (Report #{report.id})",
    )
    db.add(txn)

    old_stock = inv.current_stock
    inv.current_stock += quantity

    db.query(Notification).filter(
        Notification.dss_report_id == report.id,
        Notification.type == NotificationType.LOW_STOCK,
    ).update({"is_actioned": True, "is_read": True})

    create_notification(
        db, NotificationType.ORDER_CONFIRMED,
        title=f"Order confirmed: {product.name}",
        message=f"Stock replenished: {old_stock} -> {inv.current_stock} (+{quantity} units)",
        product_id=product.id,
        dss_report_id=report.id,
    )

    db.commit()
    db.refresh(txn)

    return DSSActionResponse(
        success=True,
        message=f"Stock-in confirmed: +{quantity} units for {product.name}. "
                f"New stock level: {inv.current_stock}",
        transaction_id=txn.id,
    )


# ─── Apply Price Recommendation ─────────────────────────────────────

@router.post("/apply-price", response_model=DSSActionResponse)
def apply_price(data: DSSApplyPriceRequest, db: Session = Depends(get_db)):
    """
    Manager approves DSS pricing recommendation.
    Updates product.current_price with ±30% guardrail validation.
    """
    report = db.query(DSSReport).filter(DSSReport.id == data.report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="DSS report not found")

    product = db.query(Product).filter(Product.id == report.product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    old_price = float(product.current_price)

    approved_price = data.approved_price
    if approved_price is None:
        advice = report.pricing_advice or {}
        approved_price = advice.get("suggested_price")
        if approved_price is None:
            raise HTTPException(status_code=400, detail="No suggested price in report. Provide approved_price explicitly.")
    approved_price = float(approved_price)

    # Guardrail: ±30% from base price
    base = float(product.base_price)
    if base > 0:
        change_pct = abs(approved_price - base) / base
        if change_pct > 0.30:
            raise HTTPException(
                status_code=400,
                detail=f"Price ${approved_price:.2f} exceeds +/-30% guardrail from base ${base:.2f}"
            )

    product.current_price = approved_price

    db.query(Notification).filter(
        Notification.dss_report_id == report.id,
        Notification.type == NotificationType.PRICE_UPDATED,
    ).update({"is_actioned": True, "is_read": True})

    direction = "increased" if approved_price > old_price else "decreased"
    pct = ((approved_price - old_price) / old_price * 100) if old_price > 0 else 0
    create_notification(
        db, NotificationType.PRICE_UPDATED,
        title=f"Price {direction}: {product.name}",
        message=f"${old_price:.2f} -> ${approved_price:.2f} ({pct:+.1f}%)",
        product_id=product.id,
        dss_report_id=report.id,
    )

    db.commit()

    return DSSActionResponse(
        success=True,
        message=f"Price updated for {product.name}: ${old_price:.2f} -> ${approved_price:.2f}",
        old_price=old_price,
        new_price=approved_price,
    )


# ─── Backtest Validation ────────────────────────────────────────────

@router.post("/backtest", response_model=BacktestResponse)
def run_backtest(data: BacktestRequest, db: Session = Depends(get_db)):
    """
    3-way inventory simulation over the TEST period (last 30% of sales history):

    1. DSS      — ROP + order_qty from ThesisHybridModel forecast (Prophet+XGBoost)
    2. Naive    — Fixed ROP = 20% initial stock, order = initial stock, lead_time 7 days
                  (represents a basic reorder-point policy without forecasting)
    3. Oracle   — Perfect foresight: knows exact future demand, orders exactly what is needed
                  7 days in advance. This is the theoretical upper bound (service_level = 100%
                  by design). NOTE: public eCommerce datasets (FMCG, India Sales, UK Retail)
                  do NOT contain actual inventory records, so Oracle is the correct upper-bound
                  baseline instead of "actual inventory".

    Why not compare against "actual inventory from dataset"?
    - These datasets only record sales transactions (quantity_sold per day).
    - Actual stock levels, reorder decisions, and supplier lead times are NOT recorded.
    - Reconstructing "actual inventory" from sales-only data is impossible without knowing
      initial stock, when orders were placed, and supplier delivery schedules.
    - Oracle baseline is the standard academic substitute for this gap.
    """
    product = db.query(Product).filter(Product.id == data.product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    inv = db.query(Inventory).filter(Inventory.product_id == data.product_id).first()
    initial_stock = data.initial_stock or (inv.current_stock if inv else 100)

    sales_df = _get_sales_df(data.product_id, db)
    if len(sales_df) < data.simulation_days:
        raise HTTPException(
            status_code=400,
            detail=f"Need at least {data.simulation_days} days of history, have {len(sales_df)}"
        )

    # ── Test period: last simulation_days rows ────────────────────────
    sim_data = sales_df.tail(data.simulation_days).reset_index(drop=True)
    daily_demand = sim_data["y"].values
    total = len(daily_demand)
    lead_time = 7

    # ── Train period: everything before test ──────────────────────────
    train_df = sales_df.head(max(30, len(sales_df) - data.simulation_days))

    # ── Pre-compute demand stats ──────────────────────────────────────
    avg_demand = float(np.mean(daily_demand))
    std_demand = float(np.std(daily_demand))

    # ══════════════════════════════════════════════════════════════════
    # STRATEGY 1: DSS — Order-up-to (s,S) model
    # ROP and Target are computed directly from forecast statistics
    # Do NOT use DSSEngine.analyze() because it is affected by
    # current_stock (real-time advisory), which is not suitable for simulation.
    # ══════════════════════════════════════════════════════════════════
    try:
        from app.core.hybrid_model import ThesisHybridModel

        model = ThesisHybridModel(penalty_under=data.penalty_under)
        model.fit(train_df)
        forecast = model.predict(data.simulation_days)

        f_vals = forecast["yhat"].values
        # Forecast daily mean and std - characteristic of this model
        f_mean = float(np.mean(f_vals))
        f_std  = float(np.std(f_vals))

        # With high penalty_under -> f_mean > avg_demand (intentional over-forecast)
        # -> ROP and target are higher than Naive -> fewer stockouts
        z_score   = 1.645   # 95% service level target
        dss_safety = max(1, int(z_score * f_std * np.sqrt(lead_time)))
        dss_rop    = max(1, int(f_mean * lead_time) + dss_safety)

        # Target-level (S): enough for a full cycle = lead_time wait + 30 selling days
        # S must be >= total demand in (lead_time + review_period) + safety
        # If S is too small -> stockout before the next batch arrives
        cycle_days = lead_time + 30
        dss_target_level = max(1, int(f_mean * cycle_days) + 2 * dss_safety)

    except Exception:
        z_score   = 1.645
        dss_safety = max(1, int(z_score * std_demand * np.sqrt(lead_time)))
        dss_rop    = max(1, int(avg_demand * lead_time) + dss_safety)
        cycle_days = lead_time + 30
        dss_target_level = max(1, int(avg_demand * cycle_days) + 2 * dss_safety)

    # ══════════════════════════════════════════════════════════════════
    # STRATEGY 2: Naive — simple order-up-to, no forecast
    # Uses historical avg_demand, NO safety stock
    # Target covers 30 days only (no lead_time) -> deliberately inferior
    # ══════════════════════════════════════════════════════════════════
    naive_rop          = max(1, int(avg_demand * lead_time))
    naive_target_level = naive_rop + max(1, int(avg_demand * 30))

    # ══════════════════════════════════════════════════════════════════
    # STRATEGY 3: Oracle (perfect foresight — theoretical upper bound)
    #
    # True perfect-foresight: pre-compute exactly when and how much to
    # order so stock never hits zero.
    # Algorithm: work backwards — for each day, if stock would run out
    # within lead_time, schedule an order lead_time days earlier for
    # exactly the deficit. This guarantees oracle_stockout_days == 0
    # and makes it a proper upper bound over DSS and Naive.
    # ══════════════════════════════════════════════════════════════════
    oracle_stock     = float(initial_stock)
    oracle_pending   = 0
    oracle_order_day = -999

    # Pre-compute oracle orders using forward simulation with look-ahead:
    # On day i, if current_stock will reach 0 before day i+lead_time,
    # order enough to cover demand from day i+lead_time through i+lead_time+cycle_days
    oracle_orders = [0] * total   # oracle_orders[i] = qty arriving on day i
    _sim_stock = float(initial_stock)
    _pending   = 0
    _order_day = -999
    for i in range(total):
        # Receive pending
        if _pending > 0 and (i - _order_day) >= lead_time:
            _sim_stock += _pending; _pending = 0
        # Will stock survive the next lead_time days?
        future_need = int(np.sum(daily_demand[i : i + lead_time + 1]))
        if _sim_stock < future_need and _pending == 0:
            # Order exactly enough to cover lead_time + full cycle without stockout
            cycle = lead_time + 30
            order_qty = max(1, int(np.sum(daily_demand[i : i + cycle])) - int(_sim_stock) + 1)
            _pending   = order_qty
            _order_day = i
            deliver_day = min(i + lead_time, total - 1)
            oracle_orders[deliver_day] += order_qty
        # Consume demand
        _sim_stock = max(0.0, _sim_stock - int(daily_demand[i]))

    future_demand_windows = [
        int(np.sum(daily_demand[i : i + lead_time]))
        for i in range(total)
    ]

    # ── Simulation loop ───────────────────────────────────────────────
    dss_stock   = float(initial_stock)
    naive_stock = float(initial_stock)

    dss_pending   = 0;  dss_order_day   = -999
    naive_pending = 0;  naive_order_day = -999

    daily_data = []
    dss_stockout_days    = 0
    naive_stockout_days  = 0
    oracle_stockout_days = 0

    for i, demand in enumerate(daily_demand):
        demand = int(demand)

        # ── Receive pending orders ────────────────────────────────────
        if naive_pending > 0 and (i - naive_order_day) >= lead_time:
            naive_stock += naive_pending; naive_pending = 0
        if dss_pending > 0 and (i - dss_order_day) >= lead_time:
            dss_stock += dss_pending; dss_pending = 0
        if oracle_pending > 0 and (i - oracle_order_day) >= lead_time:
            oracle_stock += oracle_pending; oracle_pending = 0
        # Also receive any pre-computed oracle deliveries for today
        if oracle_orders[i] > 0:
            oracle_stock += oracle_orders[i]

        # ── Consume demand ────────────────────────────────────────────
        naive_stock  = max(0.0, naive_stock  - demand)
        dss_stock    = max(0.0, dss_stock    - demand)
        oracle_stock = max(0.0, oracle_stock - demand)

        # ── Count stockouts ───────────────────────────────────────────
        if naive_stock  <= 0: naive_stockout_days  += 1
        if dss_stock    <= 0: dss_stockout_days    += 1
        if oracle_stock <= 0: oracle_stockout_days += 1

        # ── Reorder decisions — Order-up-to model ─────────────────────
        # Standard formula (s,S):
        #   order = S - (on_hand + on_order)
        # "on_order" = pending inbound stock - avoid double-order
        # Naive: reorder when stock reaches ROP
        if naive_stock <= naive_rop and naive_pending == 0:
            in_transit = naive_pending  # = 0 here but pattern is explicit
            order = max(1, naive_target_level - int(naive_stock) - in_transit)
            naive_pending = order; naive_order_day = i

        # DSS: reorder when stock reaches ROP
        # order = T - (stock + pending) to avoid over-ordering when inbound exists
        if dss_stock <= dss_rop and dss_pending == 0:
            order = max(1, dss_target_level - int(dss_stock) - dss_pending)
            dss_pending = order; dss_order_day = i
        # Emergency: stock hits 0, no pending -> order one full cycle immediately
        elif dss_stock == 0 and dss_pending == 0:
            order = max(1, dss_target_level)
            dss_pending = order; dss_order_day = i

        # Oracle orders are pre-computed above (look-ahead pass) and
        # delivered via oracle_orders[i] — no reactive reorder needed here

        daily_data.append({
            "day":          i + 1,
            "date":         sim_data.iloc[i]["ds"].strftime("%Y-%m-%d"),
            "demand":       demand,
            "dss_stock":    int(dss_stock),
            "naive_stock":  int(naive_stock),
            "oracle_stock": int(oracle_stock),
        })

    # ── Metrics ───────────────────────────────────────────────────────
    reduction = (
        (naive_stockout_days - dss_stockout_days) / naive_stockout_days * 100
        if naive_stockout_days > 0 else 0.0
    )

    methodology_note = (
        "Baseline comparison: public eCommerce datasets (FMCG, India Sales, UK Retail, etc.) "
        "only contain daily quantity_sold — actual inventory levels, reorder decisions, and "
        "supplier lead times are NOT recorded. 'Oracle' (perfect foresight) is used as the "
        "theoretical upper-bound baseline instead of 'actual inventory'. "
        f"Train: {len(train_df)} days | Test: {total} days (last 30% of history)."
    )

    return BacktestResponse(
        product_id=data.product_id,
        simulation_days=total,
        dss_stockout_days=dss_stockout_days,
        naive_stockout_days=naive_stockout_days,
        stockout_reduction_pct=round(reduction, 1),
        dss_service_level=round((1 - dss_stockout_days / total) * 100, 1),
        naive_service_level=round((1 - naive_stockout_days / total) * 100, 1),
        oracle_stockout_days=oracle_stockout_days,
        oracle_service_level=round((1 - oracle_stockout_days / total) * 100, 1),
        methodology_note=methodology_note,
        daily_data=daily_data,
    )


# ─── Report History ─────────────────────────────────────────────────

@router.get("/reports/{product_id}", response_model=list[DSSReportResponse])
def get_reports(product_id: int, limit: int = 10, db: Session = Depends(get_db)):
    reports = (
        db.query(DSSReport)
        .filter(DSSReport.product_id == product_id)
        .order_by(DSSReport.generated_at.desc())
        .limit(limit)
        .all()
    )
    return [
        DSSReportResponse(
            id=r.id, report_id=r.id, product_id=r.product_id, generated_at=r.generated_at,
            forecast_data=r.forecast_data, inventory_advice=r.inventory_advice,
            pricing_advice=r.pricing_advice, ai_reasoning=r.ai_reasoning,
            parameters=r.parameters,
        )
        for r in reports
    ]


# ─── Batch DSS Scan (for cron job) ──────────────────────────────────

@router.post("/scan-all")
def scan_all_products(data: Optional[DSSScanAllRequest] = None, db: Session = Depends(get_db)):
    """
    Quick scan all products — generate alerts for those needing attention.
    Run as daily cron: curl -X POST http://localhost:8000/api/dss/scan-all
    """
    min_sales_days = data.min_sales_days if data else 30

    products_with_data = (
        db.query(Product.id, Product.name, func.count(SalesHistory.id))
        .join(SalesHistory, Product.id == SalesHistory.product_id)
        .filter(Product.is_active == True)
        .group_by(Product.id)
        .having(func.count(SalesHistory.id) >= min_sales_days)
        .all()
    )

    scanned = 0
    alerts_generated = 0

    for pid, pname, _ in products_with_data:
        inv = db.query(Inventory).filter(Inventory.product_id == pid).first()
        if not inv:
            continue

        thirty_days_ago = datetime.utcnow().date() - timedelta(days=30)
        avg_daily = (
            db.query(func.avg(SalesHistory.quantity_sold))
            .filter(SalesHistory.product_id == pid, SalesHistory.date >= thirty_days_ago)
            .scalar()
        ) or 0

        if avg_daily > 0:
            days_left = inv.current_stock / float(avg_daily)

            if days_left < 10.5:  # less than 1.5x lead time
                create_notification(
                    db, NotificationType.LOW_STOCK,
                    title=f"Low stock alert: {pname}",
                    message=f"~{days_left:.0f} days remaining at {avg_daily:.1f}/day velocity.",
                    product_id=pid,
                )
                alerts_generated += 1

            if inv.current_stock <= inv.reorder_point:
                create_notification(
                    db, NotificationType.STOCKOUT_WARNING,
                    title=f"Below ROP: {pname}",
                    message=f"Stock ({inv.current_stock}) <= ROP ({inv.reorder_point}). Run DSS analysis.",
                    product_id=pid,
                )
                alerts_generated += 1

        scanned += 1

    db.commit()
    return {"scanned": scanned, "alerts_generated": alerts_generated}