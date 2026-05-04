
import logging
import time
from datetime import date
from typing import Optional

import pandas as pd
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import ForecastCache, SalesHistory, Product
from app.core.hybrid_model import ThesisHybridModel, MODEL_VERSION

logger = logging.getLogger(__name__)

# Suppress Prophet/cmdstanpy stdout logs during batch precompute
logging.getLogger("cmdstanpy").setLevel(logging.WARNING)
logging.getLogger("prophet").setLevel(logging.WARNING)


def precompute_all_forecasts(
    horizon_days: int = 30,
    product_ids: Optional[list[int]] = None,
    progress_callback: Optional[callable] = None,
) -> dict:
    """
    Fit Hybrid model per product and cache 30-day forecasts.

    Parameters
    ----------
    horizon_days : int
        Number of future days to forecast per product.
    product_ids : list[int] | None
        If None, precompute for ALL active products.
        If given, only recompute these products (used by ingest hook).
    progress_callback : callable | None
        Called as progress_callback(done_count, total_count, product_id)
        after each product. Used by SSE endpoint (Prompt 2).

    Returns
    -------
    dict with keys:
        products_processed : int       — successfully cached
        products_skipped   : list      — [{product_id, reason, days_available}]
        failed             : list      — [{product_id, error}]
        duration_seconds   : float
    """
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

            if len(df) < 30:
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
                model = ThesisHybridModel(penalty_under=5.0)
                model.fit(df)
                fc = model.predict(horizon_days)
            except Exception as exc:
                failed.append({"product_id": pid, "error": str(exc)})
                if progress_callback:
                    progress_callback(i, total_count, pid)
                continue

            (
                db.query(ForecastCache)
                .filter(
                    ForecastCache.product_id == pid,
                    ForecastCache.model_version == MODEL_VERSION,
                )
                .delete(synchronize_session=False)
            )

            rows = [
                ForecastCache(
                    product_id=pid,
                    forecast_date=row.ds.date(),
                    yhat=float(row.yhat),
                    yhat_lower=float(row.yhat_lower),
                    yhat_upper=float(row.yhat_upper),
                    model_version=MODEL_VERSION,
                )
                for row in fc.itertuples()
            ]
            db.bulk_save_objects(rows)
            db.commit()

            products_processed += 1
            logger.info(
                f"[{i}/{total_count}] product {pid}: fit OK, {horizon_days} rows cached"
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


def get_cached_forecast(
    product_id: int,
    days: int = 30,
    db: Optional[Session] = None,
) -> dict:
    """
    Read cached forecast for a product.

    Parameters
    ----------
    product_id : int
    days : int
        Max number of future days to return.
    db : Session | None
        If given, use this session (for reuse in FastAPI endpoints).
        If None, open a new SessionLocal().

    Returns
    -------
    dict with keys:
        rows : list[dict]         — [{forecast_date, yhat, yhat_lower, yhat_upper}, ...]
                                    sorted by forecast_date ASC,
                                    only dates >= today
        computed_at : datetime | None
        staleness_days : int      — days since computed_at; 0 if computed today
        rows_returned : int       — may be < `days` if cache is stale
    """
    own_session = db is None
    if own_session:
        db = SessionLocal()

    try:
        today = date.today()
        q = (
            db.query(ForecastCache)
            .filter(
                ForecastCache.product_id == product_id,
                ForecastCache.model_version == MODEL_VERSION,
                ForecastCache.forecast_date >= today,
            )
            .order_by(ForecastCache.forecast_date.asc())
            .limit(days)
            .all()
        )

        if not q:
            return {
                "rows": [],
                "computed_at": None,
            }

        computed_at = q[0].computed_at
        rows = [
            {
                "forecast_date": r.forecast_date.isoformat(),
                "yhat": r.yhat,
                "yhat_lower": r.yhat_lower,
                "yhat_upper": r.yhat_upper,
            }
            for r in q
        ]
        return {
            "rows": rows,
            "computed_at": computed_at,
        }
    finally:
        if own_session:
            db.close()


def get_forecast_cache_meta(db: Optional[Session] = None) -> dict:
    """
    Summary of cache state, for frontend "last updated" display.

    Returns
    -------
    dict with keys:
        last_computed_at : datetime | None     — most recent computed_at across all rows
        products_cached  : int                  — distinct product_ids in cache
        total_rows       : int
        model_version    : str
    """
    own_session = db is None
    if own_session:
        db = SessionLocal()

    try:
        last_computed_at = (
            db.query(func.max(ForecastCache.computed_at))
            .filter(ForecastCache.model_version == MODEL_VERSION)
            .scalar()
        )
        products_cached = (
            db.query(func.count(func.distinct(ForecastCache.product_id)))
            .filter(ForecastCache.model_version == MODEL_VERSION)
            .scalar()
            or 0
        )
        total_rows = (
            db.query(func.count(ForecastCache.id))
            .filter(ForecastCache.model_version == MODEL_VERSION)
            .scalar()
            or 0
        )
        return {
            "last_computed_at": last_computed_at,
            "products_cached": products_cached,
            "total_rows": total_rows,
            "model_version": MODEL_VERSION,
        }
    finally:
        if own_session:
            db.close()
