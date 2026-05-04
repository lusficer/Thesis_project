"""
Backtest cache service — precompute and query per-product backtest metrics.
"""
import logging
import time
from typing import Optional

import pandas as pd
from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from app.core.backtest import run_product_backtest
from app.core.hybrid_model import MODEL_VERSION
from app.database import SessionLocal
from app.models import BacktestResult, Product, SalesHistory

logger = logging.getLogger(__name__)

# Suppress Prophet/cmdstanpy stdout logs during batch precompute
logging.getLogger("cmdstanpy").setLevel(logging.WARNING)
logging.getLogger("prophet").setLevel(logging.WARNING)


def _row_to_dict(row: BacktestResult) -> dict:
    return {
        "product_id": row.product_id,
        "model_version": row.model_version,
        "test_start_date": row.test_start_date,
        "test_end_date": row.test_end_date,
        "n_test_days": row.n_test_days,
        "mae": row.mae,
        "rmse": row.rmse,
        "mape": row.mape,
        "under_forecast_pct": row.under_forecast_pct,
        "over_forecast_pct": row.over_forecast_pct,
        "dss_service_level": row.dss_service_level,
        "dss_stockout_days": row.dss_stockout_days,
        "dss_avg_inventory": row.dss_avg_inventory,
        "naive_service_level": row.naive_service_level,
        "naive_stockout_days": row.naive_stockout_days,
        "naive_avg_inventory": row.naive_avg_inventory,
        "oracle_service_level": row.oracle_service_level,
        "oracle_stockout_days": row.oracle_stockout_days,
        "oracle_avg_inventory": row.oracle_avg_inventory,
        "computed_at": row.computed_at,
    }


def precompute_all_backtests(
    test_days: int = 30,
    product_ids: Optional[list[int]] = None,
    model_version: str = MODEL_VERSION,  # from hybrid_model
    progress_callback: Optional[callable] = None,
) -> dict:
    start = time.time()
    db = SessionLocal()
    products_processed = 0
    products_skipped = []
    failed = []

    try:
        products_query = db.query(Product.id).filter(Product.is_active.is_(True))
        if product_ids is not None:
            products_query = products_query.filter(Product.id.in_(product_ids))

        product_id_rows = products_query.all()
        target_product_ids = [pid for (pid,) in product_id_rows]
        total_count = len(target_product_ids)

        for i, pid in enumerate(target_product_ids, start=1):
            history_rows = (
                db.query(SalesHistory.date, SalesHistory.quantity_sold)
                .filter(SalesHistory.product_id == pid)
                .order_by(SalesHistory.date)
                .all()
            )
            df = pd.DataFrame(history_rows, columns=["ds", "y"])
            if not df.empty:
                df["ds"] = pd.to_datetime(df["ds"])

            if len(df) < 60:
                products_skipped.append(
                    {
                        "product_id": pid,
                        "reason": "insufficient_data",
                        "days_available": len(df),
                    }
                )
                if progress_callback:
                    progress_callback(i, total_count, pid)
                continue

            try:
                result = run_product_backtest(
                    df,
                    test_days=test_days,
                    penalty_under=5.0,
                    penalty_over=1.0,
                )
            except Exception as exc:
                failed.append({"product_id": pid, "error": str(exc)})
                if progress_callback:
                    progress_callback(i, total_count, pid)
                continue

            (
                db.query(BacktestResult)
                .filter(
                    BacktestResult.product_id == pid,
                    BacktestResult.model_version == model_version,
                )
                .delete(synchronize_session=False)
            )

            db.add(
                BacktestResult(
                    product_id=pid,
                    model_version=model_version,
                    test_start_date=result["test_start_date"],
                    test_end_date=result["test_end_date"],
                    n_test_days=result["n_test_days"],
                    mae=float(result["mae"]),
                    rmse=float(result["rmse"]),
                    mape=float(result["mape"]) if result["mape"] is not None else None,
                    under_forecast_pct=float(result["under_forecast_pct"]),
                    over_forecast_pct=float(result["over_forecast_pct"]),
                    dss_service_level=float(result["dss_service_level"]),
                    dss_stockout_days=int(result["dss_stockout_days"]),
                    dss_avg_inventory=float(result["dss_avg_inventory"]),
                    naive_service_level=float(result["naive_service_level"]),
                    naive_stockout_days=int(result["naive_stockout_days"]),
                    naive_avg_inventory=float(result["naive_avg_inventory"]),
                    oracle_service_level=float(result["oracle_service_level"]),
                    oracle_stockout_days=int(result["oracle_stockout_days"]),
                    oracle_avg_inventory=float(result["oracle_avg_inventory"]),
                )
            )
            db.commit()
            products_processed += 1

            logger.info(
                f"[{i}/{total_count}] product {pid}: backtest OK, {test_days} test days cached"
            )
            if progress_callback:
                progress_callback(i, total_count, pid)

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    return {
        "products_processed": products_processed,
        "products_skipped": products_skipped,
        "failed": failed,
        "duration_seconds": time.time() - start,
    }


def get_cached_backtest(
    product_id: int,
    model_version: str = MODEL_VERSION,
    db: Optional[Session] = None,
) -> Optional[dict]:
    own_session = db is None
    if own_session:
        db = SessionLocal()

    try:
        row = (
            db.query(BacktestResult)
            .filter(
                BacktestResult.product_id == product_id,
                BacktestResult.model_version == model_version,
            )
            .order_by(BacktestResult.computed_at.desc())
            .first()
        )
        if row is None:
            return None
        return _row_to_dict(row)
    finally:
        if own_session:
            db.close()


def get_all_backtests(
    model_version: str = MODEL_VERSION,
    db: Optional[Session] = None,
) -> list[dict]:
    own_session = db is None
    if own_session:
        db = SessionLocal()

    try:
        latest_subq = (
            db.query(
                BacktestResult.product_id.label("product_id"),
                func.max(BacktestResult.computed_at).label("max_computed_at"),
            )
            .filter(BacktestResult.model_version == model_version)
            .group_by(BacktestResult.product_id)
            .subquery()
        )

        rows = (
            db.query(BacktestResult)
            .join(
                latest_subq,
                and_(
                    BacktestResult.product_id == latest_subq.c.product_id,
                    BacktestResult.computed_at == latest_subq.c.max_computed_at,
                ),
            )
            .filter(BacktestResult.model_version == model_version)
            .order_by(BacktestResult.product_id.asc())
            .all()
        )
        return [_row_to_dict(r) for r in rows]
    finally:
        if own_session:
            db.close()


def get_backtest_meta(
    model_version: str = MODEL_VERSION,
    db: Optional[Session] = None,
) -> dict:
    own_session = db is None
    if own_session:
        db = SessionLocal()

    try:
        last_computed_at = (
            db.query(func.max(BacktestResult.computed_at))
            .filter(BacktestResult.model_version == model_version)
            .scalar()
        )
        products_cached = (
            db.query(func.count(func.distinct(BacktestResult.product_id)))
            .filter(BacktestResult.model_version == model_version)
            .scalar()
            or 0
        )
        total_rows = (
            db.query(func.count(BacktestResult.id))
            .filter(BacktestResult.model_version == model_version)
            .scalar()
            or 0
        )
        return {
            "last_computed_at": last_computed_at,
            "products_cached": products_cached,
            "total_rows": total_rows,
            "model_version": model_version,
        }
    finally:
        if own_session:
            db.close()
