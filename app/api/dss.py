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

from datetime import date, datetime, timedelta
from typing import Optional
import asyncio
import json
import os
import statistics
import uuid
import requests
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, text
import pandas as pd
import numpy as np

from app.database import get_db
from app.core.backtest import run_product_backtest
from app.models import (
    Category,
    Product, Inventory, SalesHistory, DSSReport,
    ForecastCache,
    InventoryTransaction, TransactionType,
    Notification, NotificationType,
)
from app.schemas import (
    DSSRunRequest, DSSReportResponse,
    DSSConfirmOrderRequest, DSSApplyPriceRequest, DSSActionResponse,
    BacktestRequest, BacktestResponse, DSSScanAllRequest,
)
from app.api.notifications import create_notification
from app.core.dss_engine import DSSEngine
from app.services.forecast_cache import (
    precompute_all_forecasts,
    get_forecast_cache_meta,
)
from app.services.backtest_cache import (
    precompute_all_backtests,
    get_backtest_meta,
)

router = APIRouter(prefix="/dss", tags=["DSS"])

# In-memory job registry for recompute-forecasts endpoint.
# Separate from sales.py's _jobs to avoid coupling.
# job_id -> {status, progress, products_processed, products_total,
#            skipped_count, failed_count, duration_seconds, error}
_recompute_jobs: dict[str, dict] = {}


def _new_recompute_job() -> str:
    jid = str(uuid.uuid4())
    _recompute_jobs[jid] = {
        "status":              "pending",
        "progress":            0,
        "products_processed":  0,
        "products_total":      0,
        "skipped_count":       0,
        "failed_count":        0,
        "duration_seconds":    None,
        "error":               None,
    }
    return jid


# In-memory job registry for recompute-backtests endpoint.
# Separate from forecast jobs to avoid clobbering progress fields.
_backtest_jobs: dict[str, dict] = {}


def _new_backtest_job() -> str:
    jid = str(uuid.uuid4())
    _backtest_jobs[jid] = {
        "status":              "pending",
        "progress":            0,
        "products_processed":  0,
        "products_total":      0,
        "skipped_count":       0,
        "failed_count":        0,
        "duration_seconds":    None,
        "error":               None,
    }
    return jid

# In-memory model store (same pattern as original thesis app)
model_store: dict = {}


def _probability_pct(value: Optional[float]) -> float:
    if value is None:
        return 0.0
    if value <= 1:
        return float(value) * 100
    return float(value)


def _fallback_pm_narrative(payload: dict) -> str:
    ps = payload["portfolio_summary"]
    lines = [
        f"# Portfolio Health Report — {payload['report_date']}",
        "",
        "## Executive Summary",
        "",
        f"Portfolio contains **{ps['total_products']} products** across "
        f"{len(payload['category_performance'])} categories.",
        f"Action distribution: {ps['action_distribution']['ORDER_NOW']} ORDER_NOW, "
        f"{ps['action_distribution']['HOLD']} HOLD, "
        f"{ps['action_distribution']['LOW_STOCK']} LOW_STOCK.",
        f"**{ps['products_at_risk']} products** flagged at risk (stockout probability >50%).",
        "",
        "## Top 5 At-Risk Products",
        "",
    ]
    for p in payload["top_5_at_risk"]:
        lines.append(
            f"- **{p['name']}**: {p['stockout_probability']:.1f}% stockout risk, "
            f"stock={p['current_stock']}, action={p['recommended_action']}"
        )
    lines += [
        "",
        "## Category Overview",
        "",
    ]
    for c in payload["category_performance"]:
        lines.append(
            f"- **{c['category']}** ({c['product_count']} products): "
            f"Avg MAE={c['avg_mae']:.1f}, DSS SL={c['avg_dss_service_level']:.1f}%, "
            f"{c['at_risk_count']} at risk"
        )
    lines += [
        "",
        "*Note: This report was generated using a template fallback. "
        "LLM-powered narrative was unavailable.*",
    ]
    return "\n".join(lines)


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
    result = run_product_backtest(
        sales_df=sales_df,
        test_days=data.simulation_days,
        lead_time=7,
        penalty_under=data.penalty_under,
        penalty_over=1.0,
        initial_stock=initial_stock,
    )

    return BacktestResponse(
        product_id=data.product_id,
        simulation_days=result["n_test_days"],
        dss_stockout_days=result["dss_stockout_days"],
        naive_stockout_days=result["naive_stockout_days"],
        stockout_reduction_pct=round(result["stockout_reduction_pct"], 1),
        dss_service_level=round(result["dss_service_level"], 1),
        naive_service_level=round(result["naive_service_level"], 1),
        oracle_stockout_days=result["oracle_stockout_days"],
        oracle_service_level=round(result["oracle_service_level"], 1),
        methodology_note=result["methodology_note"],
        daily_data=result["daily_data"],
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


def _run_recompute(job_id: str, product_ids: Optional[list[int]] = None):
    """
    Background worker — runs precompute_all_forecasts and updates
    _recompute_jobs[job_id] with progress.

    Runs in FastAPI BackgroundTasks thread pool. Does NOT block
    the event loop.
    """
    job = _recompute_jobs[job_id]
    job["status"] = "running"

    def on_progress(done: int, total: int, product_id: int):
        # Called by precompute after each product
        job["products_processed"] = done
        job["products_total"] = total
        job["progress"] = int(100 * done / max(total, 1))

    try:
        result = precompute_all_forecasts(
            horizon_days=30,
            product_ids=product_ids,
            progress_callback=on_progress,
        )
        job.update({
            "status":              "done",
            "progress":            100,
            "products_processed":  result["products_processed"],
            "skipped_count":       len(result["products_skipped"]),
            "failed_count":        len(result["failed"]),
            "duration_seconds":    result["duration_seconds"],
        })
    except Exception as exc:
        job["status"] = "error"
        job["error"] = str(exc)


@router.post("/recompute-forecasts")
async def recompute_forecasts(background_tasks: BackgroundTasks):
    """
    Trigger precompute of Hybrid forecasts for ALL active products.
    Returns job_id immediately. Poll GET /dss/recompute-forecasts/{job_id}/progress.

    TODO: add auth (admin-only) before production. Bachelor thesis scope.
    """
    job_id = _new_recompute_job()
    background_tasks.add_task(_run_recompute, job_id, None)
    return {"job_id": job_id, "status": "pending"}


@router.get("/recompute-forecasts/{job_id}/progress")
async def recompute_progress(job_id: str):
    """
    SSE stream of recompute job progress. Poll until status in
    {"done", "error"}. Mirrors pattern from /sales/import/{job_id}/progress.
    """
    if job_id not in _recompute_jobs:
        raise HTTPException(404, f"Recompute job '{job_id}' not found")

    async def event_generator():
        while True:
            job = _recompute_jobs.get(job_id, {})
            # datetime/None safe JSON dump
            yield f"data: {json.dumps(job, default=str)}\n\n"

            if job.get("status") in ("done", "error"):
                await asyncio.sleep(300)  # keep around 5min for late pollers
                _recompute_jobs.pop(job_id, None)
                break

            await asyncio.sleep(0.8)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/recompute-forecasts/meta")
def recompute_meta():
    """
    Cache metadata for frontend "last updated" display.
    Returns {last_computed_at, products_cached, total_rows, model_version}.
    """
    return get_forecast_cache_meta()


def _run_backtest(job_id: str, product_ids: Optional[list[int]] = None):
    """
    Background worker — runs precompute_all_backtests and updates
    _backtest_jobs[job_id] with progress.

    Runs in FastAPI BackgroundTasks thread pool. Does NOT block
    the event loop.
    """
    job = _backtest_jobs[job_id]
    job["status"] = "running"

    def on_progress(done: int, total: int, product_id: int):
        # Called by precompute after each product
        job["products_processed"] = done
        job["products_total"] = total
        job["progress"] = int(100 * done / max(total, 1))

    try:
        result = precompute_all_backtests(
            test_days=30,
            product_ids=product_ids,
            progress_callback=on_progress,
        )
        job.update({
            "status":              "done",
            "progress":            100,
            "products_processed":  result["products_processed"],
            "skipped_count":       len(result["products_skipped"]),
            "failed_count":        len(result["failed"]),
            "duration_seconds":    result["duration_seconds"],
        })
    except Exception as exc:
        job["status"] = "error"
        job["error"] = str(exc)


@router.post("/recompute-backtests")
async def recompute_backtests(background_tasks: BackgroundTasks):
    """
    Trigger full backtest recompute for all active products.
    Returns job_id. Poll GET /dss/recompute-backtests/{job_id}/progress.

    TODO: add auth (admin-only) before production. Bachelor thesis scope.
    """
    job_id = _new_backtest_job()
    background_tasks.add_task(_run_backtest, job_id, None)
    return {"job_id": job_id, "status": "pending"}


@router.get("/recompute-backtests/{job_id}/progress")
async def recompute_backtests_progress(job_id: str):
    """
    SSE stream of backtest recompute job progress. Poll until status in
    {"done", "error"}.
    """
    if job_id not in _backtest_jobs:
        raise HTTPException(404, f"Backtest recompute job '{job_id}' not found")

    async def event_generator():
        while True:
            job = _backtest_jobs.get(job_id, {})
            # datetime/None safe JSON dump
            yield f"data: {json.dumps(job, default=str)}\n\n"

            if job.get("status") in ("done", "error"):
                await asyncio.sleep(300)  # keep around 5min for late pollers
                _backtest_jobs.pop(job_id, None)
                break

            await asyncio.sleep(0.8)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/recompute-backtests/meta")
def recompute_backtests_meta():
    """
    Backtest cache metadata for frontend "last updated" display.
    Returns {last_computed_at, products_cached, total_rows, model_version}.
    """
    meta = get_backtest_meta()
    return {
        "last_computed_at": meta["last_computed_at"].isoformat()
        if meta["last_computed_at"] else None,
        "products_cached": meta["products_cached"],
        "total_rows": meta["total_rows"],
        "model_version": meta["model_version"],
    }


@router.get("/portfolio/meta")
def portfolio_meta(db: Session = Depends(get_db)):
    """
    Summary of cache + product state for frontend "last updated" display.
    Cheap — single aggregate queries only.
    """
    cache_meta = get_forecast_cache_meta(db)
    total_products = db.query(func.count(Product.id)).filter(
        Product.is_active == True
    ).scalar() or 0

    return {
        "last_computed_at": cache_meta["last_computed_at"].isoformat()
        if cache_meta["last_computed_at"] else None,
        "products_cached": cache_meta["products_cached"],
        "total_products": total_products,
        "model_version": cache_meta["model_version"],
    }


@router.get("/portfolio")
def portfolio(db: Session = Depends(get_db)):
    """
    Returns health metrics for every active product.

    Batch-loads forecasts in one query (no N+1), then loops products
    in Python calling DSSEngine.analyze() per product.

    Product states:
      - "ok"                  : has ≥1 cached forecast row from today onward
      - "insufficient_data"   : no cached forecast rows (likely <30 days history)
      - "error"               : DSSEngine.analyze() raised — null metrics,
                                logged server-side

    Performance: <500ms for ~49 products (cache reads only, pure DSS calc).
    """
    # 1. Load all active products with category + inventory joined
    #    (avoids N+1 for category name / stock)
    products = (
        db.query(Product)
        .options(
            joinedload(Product.category),
            joinedload(Product.inventory),
        )
        .filter(Product.is_active == True)
        .all()
    )

    if not products:
        return []

    product_ids = [p.id for p in products]

    # 2. Batch-load future forecasts — ONE query for all products
    today = date.today()
    forecast_rows = (
        db.query(ForecastCache)
        .filter(
            ForecastCache.product_id.in_(product_ids),
            ForecastCache.forecast_date >= today,
            ForecastCache.model_version == "hybrid_asym_v1",
        )
        .order_by(ForecastCache.product_id, ForecastCache.forecast_date)
        .all()
    )

    # Group by product_id -> list of rows
    forecasts_by_product: dict[int, list[ForecastCache]] = {}
    for row in forecast_rows:
        forecasts_by_product.setdefault(row.product_id, []).append(row)

    # 3. Loop products, build response
    engine = DSSEngine(lead_time=7)
    result = []

    for p in products:
        current_stock = p.inventory.current_stock if p.inventory else 0
        current_price = float(p.current_price) if p.current_price else None
        category_name = p.category.name if p.category else "Uncategorized"

        fc_rows = forecasts_by_product.get(p.id, [])

        # Base record with nulls for metrics
        record = {
            "product_id":             p.id,
            "product_name":           p.name,
            "category":               category_name,
            "current_stock":          current_stock,
            "current_price":          current_price,
            "avg_daily_forecast":     None,
            "reorder_point":          None,
            "safety_stock":           None,
            "stockout_probability":   None,   # 0-100 scale
            "velocity_ratio":         None,
            "recommended_action":     None,
            "price_change_pct":       None,
            "status":                 "ok",
        }

        # Case A: no forecast rows cached
        if not fc_rows:
            record["status"] = "insufficient_data"
            result.append(record)
            continue

        # Case B: no current_price → can't run pricing logic cleanly
        # DSSEngine still works but price_change_pct will be degenerate.
        # Keep status "ok", return null for price_change_pct only.
        # (See also: guard after analyze() call.)

        # Build forecast_df for DSSEngine
        fc_df = pd.DataFrame([
            {
                "ds": r.forecast_date,
                "yhat": r.yhat,
                "yhat_lower": r.yhat_lower,
                "yhat_upper": r.yhat_upper,
            }
            for r in fc_rows
        ])

        avg_daily = float(fc_df["yhat"].mean())

        try:
            analysis = engine.analyze(
                forecast_df=fc_df,
                current_stock=float(current_stock),
                current_price=float(current_price) if current_price else 0.0,
                target_days_to_sell=30,
            )
        except Exception as exc:
            # Per-product failure is NON-fatal
            import logging
            logging.getLogger(__name__).warning(
                f"DSSEngine.analyze failed for product {p.id}: {exc}"
            )
            record["status"] = "error"
            record["avg_daily_forecast"] = avg_daily
            result.append(record)
            continue

        inv = analysis["inventory_advice"]
        pr = analysis["pricing_advice"]

        record.update({
            "avg_daily_forecast":   round(avg_daily, 2),
            "reorder_point":        inv["reorder_point"],
            "safety_stock":         inv["safety_stock"],
            "stockout_probability": inv["stockout_probability"],
            "velocity_ratio":       pr["velocity_ratio"],
            "recommended_action":   inv["action"],
            "price_change_pct":     pr["adjustment_pct"] if current_price else None,
        })

        result.append(record)

    return result


@router.get("/category-rollup")
def category_rollup(db: Session = Depends(get_db)):
    """
    Category-level rollup for backtest + live portfolio risk.

    Uses backtest_results (raw SQL) joined with products/categories, then
    enriches with at-risk counts from the live /portfolio computation.
    """
    rows = db.execute(
        text(
            """
            SELECT
              COALESCE(c.name, 'Uncategorized') AS category_name,
              p.id                              AS product_id,
              p.name                            AS product_name,
              br.mae,
              br.rmse,
              br.mape,
              br.under_forecast_pct,
              br.over_forecast_pct,
              br.dss_service_level,
              br.naive_service_level,
              br.oracle_service_level,
              br.dss_stockout_days,
              br.naive_stockout_days
            FROM backtest_results br
            JOIN products p
              ON p.id = br.product_id
            LEFT JOIN categories c
              ON c.id = p.category_id
            WHERE br.model_version = 'hybrid_asym_v1'
              AND p.is_active = 1
            ORDER BY category_name, p.name
            """
        )
    ).mappings().all()

    if not rows:
        return []

    portfolio_rows = portfolio(db=db)
    at_risk_by_category: dict[str, int] = {}
    for r in portfolio_rows:
        category = r.get("category") or "Uncategorized"
        prob = r.get("stockout_probability")
        if isinstance(prob, (int, float)) and prob > 50:
            at_risk_by_category[category] = at_risk_by_category.get(category, 0) + 1

    grouped: dict[str, dict] = {}

    def _to_float(v):
        return float(v) if v is not None else None

    def _round_or_none(v, digits: int = 2):
        if v is None:
            return None
        return round(float(v), digits)

    for r in rows:
        category = r["category_name"] or "Uncategorized"
        if category not in grouped:
            grouped[category] = {
                "category": category,
                "product_count": 0,
                "avg_mae": 0.0,
                "avg_rmse": 0.0,
                "avg_under_forecast_pct": 0.0,
                "avg_dss_service_level": 0.0,
                "avg_naive_service_level": 0.0,
                "at_risk_count": at_risk_by_category.get(category, 0),
                "products": [],
            }

        g = grouped[category]
        g["product_count"] += 1

        mae = _to_float(r["mae"]) or 0.0
        rmse = _to_float(r["rmse"]) or 0.0
        under = _to_float(r["under_forecast_pct"]) or 0.0
        dss_sl = _to_float(r["dss_service_level"]) or 0.0
        naive_sl = _to_float(r["naive_service_level"]) or 0.0

        g["avg_mae"] += mae
        g["avg_rmse"] += rmse
        g["avg_under_forecast_pct"] += under
        g["avg_dss_service_level"] += dss_sl
        g["avg_naive_service_level"] += naive_sl

        g["products"].append(
            {
                "product_id": int(r["product_id"]),
                "product_name": r["product_name"],
                "mae": _round_or_none(r["mae"], 2),
                "rmse": _round_or_none(r["rmse"], 2),
                "under_forecast_pct": _round_or_none(r["under_forecast_pct"], 2),
                "dss_service_level": _round_or_none(r["dss_service_level"], 2),
                "naive_service_level": _round_or_none(r["naive_service_level"], 2),
                "dss_stockout_days": int(r["dss_stockout_days"]),
                "naive_stockout_days": int(r["naive_stockout_days"]),
            }
        )

    output = []
    for category in sorted(grouped.keys()):
        g = grouped[category]
        n = max(g["product_count"], 1)
        output.append(
            {
                "category": g["category"],
                "product_count": g["product_count"],
                "avg_mae": round(g["avg_mae"] / n, 2),
                "avg_rmse": round(g["avg_rmse"] / n, 2),
                "avg_under_forecast_pct": round(g["avg_under_forecast_pct"] / n, 2),
                "avg_dss_service_level": round(g["avg_dss_service_level"] / n, 2),
                "avg_naive_service_level": round(g["avg_naive_service_level"] / n, 2),
                "at_risk_count": g["at_risk_count"],
                "products": g["products"],
            }
        )

    return output


@router.get("/model-performance")
def model_performance(db: Session = Depends(get_db)):
    """
    Product-level backtest metrics + summary for model performance monitor.
    """
    SAFETY_THRESHOLD = 50.0
    rows = db.execute(
        text(
            """
            SELECT
              p.id AS product_id,
              p.name AS product_name,
              COALESCE(c.name, 'Uncategorized') AS category,
              br.mae,
              br.rmse,
              br.mape,
              br.under_forecast_pct,
              br.over_forecast_pct,
              br.dss_service_level,
              br.naive_service_level,
              br.dss_stockout_days,
              br.naive_stockout_days
            FROM backtest_results br
            JOIN products p ON p.id = br.product_id
            LEFT JOIN categories c ON c.id = p.category_id
            WHERE br.model_version = 'hybrid_asym_v1'
              AND p.is_active = 1
            ORDER BY br.under_forecast_pct DESC
            """
        )
    ).mappings().all()

    if not rows:
        return {
            "products": [],
            "summary": {
                "avg_mae": 0.0,
                "avg_under_forecast_pct": 0.0,
                "median_under_forecast_pct": 0.0,
                "products_above_safety_threshold": 0,
                "safety_threshold": SAFETY_THRESHOLD,
            },
        }

    products: list[dict] = []
    maes: list[float] = []
    under_values: list[float] = []

    for r in rows:
        mae = float(r["mae"]) if r["mae"] is not None else 0.0
        under = (
            float(r["under_forecast_pct"])
            if r["under_forecast_pct"] is not None
            else 0.0
        )
        maes.append(mae)
        under_values.append(under)

        products.append(
            {
                "product_id": int(r["product_id"]),
                "product_name": r["product_name"],
                "category": r["category"],
                "mae": round(mae, 2),
                "rmse": round(float(r["rmse"]) if r["rmse"] is not None else 0.0, 2),
                "mape": round(float(r["mape"]), 2) if r["mape"] is not None else None,
                "under_forecast_pct": round(under, 2),
                "over_forecast_pct": round(
                    float(r["over_forecast_pct"]) if r["over_forecast_pct"] is not None else 0.0,
                    2,
                ),
                "dss_service_level": round(
                    float(r["dss_service_level"]) if r["dss_service_level"] is not None else 0.0,
                    2,
                ),
                "naive_service_level": round(
                    float(r["naive_service_level"]) if r["naive_service_level"] is not None else 0.0,
                    2,
                ),
                "dss_stockout_days": int(r["dss_stockout_days"]),
                "naive_stockout_days": int(r["naive_stockout_days"]),
            }
        )

    summary = {
        "avg_mae": round(sum(maes) / len(maes), 2),
        "avg_under_forecast_pct": round(sum(under_values) / len(under_values), 2),
        "median_under_forecast_pct": round(float(statistics.median(under_values)), 2),
        "products_above_safety_threshold": sum(1 for v in under_values if v > SAFETY_THRESHOLD),
        "safety_threshold": SAFETY_THRESHOLD,
    }

    return {"products": products, "summary": summary}


@router.post("/pm-report")
def generate_pm_report(db: Session = Depends(get_db)):
    """
    Generate portfolio-level PM report markdown using n8n webhook + LLM.
    Falls back to a template narrative when webhook is unavailable.
    """
    report_date = date.today().isoformat()

    portfolio_rows = portfolio(db=db)
    rollup_rows = category_rollup(db=db)

    if not portfolio_rows:
        return {
            "report_date": report_date,
            "markdown": "# Portfolio Health Report\n\nNo portfolio data available.",
            "payload_summary": {
                "total_products": 0,
                "at_risk_count": 0,
                "categories_analyzed": 0,
            },
            "llm_generated": False,
        }

    action_distribution = {"ORDER_NOW": 0, "HOLD": 0, "LOW_STOCK": 0}
    stockout_probs: list[float] = []
    products_at_risk = 0
    for r in portfolio_rows:
        action = r.get("recommended_action")
        if action in action_distribution:
            action_distribution[action] += 1
        prob = r.get("stockout_probability")
        if isinstance(prob, (int, float)):
            stockout_probs.append(float(prob))
            if prob > 50:
                products_at_risk += 1

    avg_stockout_probability = (
        round(sum(stockout_probs) / len(stockout_probs), 2) if stockout_probs else 0.0
    )

    by_risk_desc = sorted(
        [r for r in portfolio_rows if isinstance(r.get("stockout_probability"), (int, float))],
        key=lambda x: float(x.get("stockout_probability") or 0.0),
        reverse=True,
    )
    top_5_at_risk = [
        {
            "name": p.get("product_name"),
            "stockout_probability": round(float(p.get("stockout_probability") or 0.0), 2),
            "current_stock": int(p.get("current_stock") or 0),
            "recommended_action": p.get("recommended_action"),
            "price_change_pct": float(p.get("price_change_pct") or 0.0),
        }
        for p in by_risk_desc[:5]
    ]

    by_risk_asc_ok = sorted(
        [
            r
            for r in portfolio_rows
            if r.get("status") == "ok"
            and isinstance(r.get("stockout_probability"), (int, float))
        ],
        key=lambda x: float(x.get("stockout_probability") or 0.0),
    )
    top_3_performers = [
        {
            "name": p.get("product_name"),
            "stockout_probability": round(float(p.get("stockout_probability") or 0.0), 2),
            "velocity_ratio": round(float(p.get("velocity_ratio") or 0.0), 2),
            "current_stock": int(p.get("current_stock") or 0),
        }
        for p in by_risk_asc_ok[:3]
    ]

    backtest_summary = db.execute(
        text(
            """
            SELECT
              AVG(mae)                AS avg_mae_overall,
              AVG(dss_service_level)  AS avg_dss_service_level,
              AVG(naive_service_level) AS avg_naive_service_level
            FROM backtest_results br
            JOIN products p ON p.id = br.product_id
            WHERE br.model_version = 'hybrid_asym_v1'
              AND p.is_active = 1
            """
        )
    ).mappings().first() or {}

    avg_mae_overall = float(backtest_summary.get("avg_mae_overall") or 0.0)
    avg_dss_service_level = float(backtest_summary.get("avg_dss_service_level") or 0.0)
    avg_naive_service_level = float(backtest_summary.get("avg_naive_service_level") or 0.0)
    dss_advantage_pct = round(avg_dss_service_level - avg_naive_service_level, 2)

    payload = {
        "report_date": report_date,
        "portfolio_summary": {
            "total_products": len(portfolio_rows),
            "action_distribution": action_distribution,
            "avg_stockout_probability": avg_stockout_probability,
            "products_at_risk": products_at_risk,
        },
        "top_5_at_risk": top_5_at_risk,
        "top_3_performers": top_3_performers,
        "category_performance": [
            {
                "category": c.get("category"),
                "product_count": c.get("product_count"),
                "avg_mae": c.get("avg_mae"),
                "at_risk_count": c.get("at_risk_count"),
                "avg_dss_service_level": c.get("avg_dss_service_level"),
                "avg_naive_service_level": c.get("avg_naive_service_level"),
            }
            for c in rollup_rows
        ],
        "model_summary": {
            "model_version": "hybrid_asym_v1",
            "avg_mae_overall": round(avg_mae_overall, 2),
            "avg_dss_service_level": round(avg_dss_service_level, 2),
            "avg_naive_service_level": round(avg_naive_service_level, 2),
            "dss_advantage_pct": dss_advantage_pct,
        },
    }

    webhook_url = os.getenv("N8N_WEBHOOK_URL", "http://localhost:5678/webhook/pm-report")
    fallback_markdown = _fallback_pm_narrative(payload)

    try:
        response = requests.post(webhook_url, json=payload, timeout=60)
        if response.status_code != 200:
            return {
                "report_date": report_date,
                "markdown": fallback_markdown,
                "payload_summary": {
                    "total_products": len(portfolio_rows),
                    "at_risk_count": products_at_risk,
                    "categories_analyzed": len(rollup_rows),
                },
                "llm_generated": False,
                "webhook_error": {
                    "status_code": response.status_code,
                    "detail": response.text[:400],
                },
            }

        try:
            resp_data = response.json()
            markdown = (
                resp_data.get("markdown")
                or resp_data.get("text")
                or resp_data.get("output")
                or str(resp_data)
            )
        except Exception:
            markdown = response.text

        return {
            "report_date": report_date,
            "markdown": markdown,
            "payload_summary": {
                "total_products": len(portfolio_rows),
                "at_risk_count": products_at_risk,
                "categories_analyzed": len(rollup_rows),
            },
            "llm_generated": True,
        }
    except Exception as exc:
        return {
            "report_date": report_date,
            "markdown": fallback_markdown,
            "payload_summary": {
                "total_products": len(portfolio_rows),
                "at_risk_count": products_at_risk,
                "categories_analyzed": len(rollup_rows),
            },
            "llm_generated": False,
            "webhook_error": str(exc),
        }
