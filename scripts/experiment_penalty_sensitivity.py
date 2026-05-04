"""
Sensitivity experiment: penalty_under=1.0 vs penalty_under=5.0.

Measures action distribution shift to test whether observed
16/33/0 distribution is asymmetric-loss-driven or bucket-seeding-driven.

Does NOT modify persistent state — uses its own model_version strings
so both runs can coexist in forecast_cache.

After the experiment, default portfolio (/dss/portfolio) still reads
the original hybrid_asym_v1 (penalty=5.0) rows.

Usage:
    python scripts/experiment_penalty_sensitivity.py
"""
import time
import logging
import sys
from pathlib import Path
from collections import Counter
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal
from app.models import Product, Inventory, ForecastCache
from app.core.hybrid_model import ThesisHybridModel
from app.core.dss_engine import DSSEngine

import pandas as pd
from app.models import SalesHistory

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)
logging.getLogger("cmdstanpy").setLevel(logging.WARNING)
logging.getLogger("prophet").setLevel(logging.WARNING)


def run_with_penalty(penalty_under: float, model_version: str) -> dict:
    """
    Refit all eligible products with given penalty and return
    action distribution after running DSSEngine on the new forecasts.
    """
    db: Session = SessionLocal()
    engine = DSSEngine(lead_time=7)
    action_counts: Counter = Counter()
    processed = 0
    skipped = 0

    try:
        products = db.query(Product).filter(Product.is_active == True).all()
        logger.info(f"\n=== penalty_under={penalty_under} (version={model_version}) ===")

        # Delete any existing cache for this model_version (idempotent)
        db.query(ForecastCache).filter(
            ForecastCache.model_version == model_version
        ).delete(synchronize_session=False)
        db.commit()

        for i, p in enumerate(products, start=1):
            rows = (
                db.query(SalesHistory.date, SalesHistory.quantity_sold)
                  .filter(SalesHistory.product_id == p.id)
                  .order_by(SalesHistory.date).all()
            )
            if len(rows) < 30:
                skipped += 1
                continue
            df = pd.DataFrame(rows, columns=["ds", "y"])
            df["ds"] = pd.to_datetime(df["ds"])

            try:
                model = ThesisHybridModel(
                    penalty_under=penalty_under,
                    penalty_over=1.0,
                )
                model.fit(df)
                fc = model.predict(30)

                # Cache under experimental model_version
                cache_rows = [
                    ForecastCache(
                        product_id=p.id,
                        forecast_date=r.ds.date(),
                        yhat=float(r.yhat),
                        yhat_lower=float(r.yhat_lower),
                        yhat_upper=float(r.yhat_upper),
                        model_version=model_version,
                    )
                    for r in fc.itertuples()
                ]
                db.bulk_save_objects(cache_rows)
                db.commit()

                # Run DSSEngine on same inventory
                inv = db.query(Inventory).filter(
                    Inventory.product_id == p.id
                ).first()
                current_stock = inv.current_stock if inv else 0
                current_price = float(p.current_price) if p.current_price else 0.0

                fc_df = fc[["ds", "yhat", "yhat_lower", "yhat_upper"]].copy()
                analysis = engine.analyze(
                    forecast_df=fc_df,
                    current_stock=float(current_stock),
                    current_price=current_price,
                    target_days_to_sell=30,
                )
                action = analysis["inventory_advice"]["action"]
                action_counts[action] += 1
                processed += 1

                if i % 10 == 0:
                    logger.info(f"  [{i}/{len(products)}] processed")

            except Exception as e:
                logger.warning(f"  product {p.id} failed: {e}")
                continue

    finally:
        db.close()

    return {
        "penalty_under": penalty_under,
        "model_version": model_version,
        "processed": processed,
        "skipped": skipped,
        "actions": dict(action_counts),
    }


def main():
    t0 = time.time()

    # Run 1: symmetric (penalty 1.0)
    result_p1 = run_with_penalty(1.0, "hybrid_sym_v1_experiment")

    # Run 2: asymmetric (penalty 5.0) — re-run to have a fresh
    # comparison baseline; saves into experimental version,
    # does NOT overwrite hybrid_asym_v1 production cache
    result_p5 = run_with_penalty(5.0, "hybrid_asym_v1_experiment")

    elapsed = time.time() - t0
    logger.info(f"\n=== Results (total {elapsed:.1f}s) ===\n")
    logger.info(f"penalty_under=1.0 (symmetric):")
    logger.info(f"  processed: {result_p1['processed']}, skipped: {result_p1['skipped']}")
    logger.info(f"  actions:   {result_p1['actions']}")
    logger.info(f"")
    logger.info(f"penalty_under=5.0 (asymmetric):")
    logger.info(f"  processed: {result_p5['processed']}, skipped: {result_p5['skipped']}")
    logger.info(f"  actions:   {result_p5['actions']}")
    logger.info(f"")

    # Delta analysis
    all_actions = set(result_p1['actions']) | set(result_p5['actions'])
    logger.info(f"=== Distribution delta (p1 → p5) ===")
    for a in sorted(all_actions):
        n1 = result_p1['actions'].get(a, 0)
        n5 = result_p5['actions'].get(a, 0)
        delta = n5 - n1
        logger.info(f"  {a:12}: {n1:>3} → {n5:>3}  (Δ {delta:+d})")
    logger.info(f"")

    # Interpretation guide
    logger.info(f"=== Interpretation ===")
    if abs(result_p1['actions'].get('ORDER_NOW', 0) -
           result_p5['actions'].get('ORDER_NOW', 0)) < 3:
        logger.info("ORDER_NOW count is similar across penalties — "
                    "distribution may be bucket-seed-driven, NOT loss-driven.")
        logger.info("D14 framing needs revision.")
    else:
        logger.info("ORDER_NOW count differs meaningfully across penalties — "
                    "asymmetric loss IS shifting behavior.")
        logger.info("D14 framing is supported.")

    low_p1 = result_p1['actions'].get('LOW_STOCK', 0)
    low_p5 = result_p5['actions'].get('LOW_STOCK', 0)
    if low_p1 > low_p5:
        logger.info(f"LOW_STOCK: symmetric={low_p1}, asymmetric={low_p5} — "
                    "asymmetric DOES preempt LOW_STOCK (supports D14).")
    elif low_p1 == 0 and low_p5 == 0:
        logger.info("LOW_STOCK is zero in both — the DSSEngine ORDER_NOW "
                    "trigger (stock<ROP as hard condition) may dominate "
                    "over loss function. This is a separate finding.")


if __name__ == "__main__":
    main()
