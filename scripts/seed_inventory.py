"""
Seed realistic inventory levels for demo.

For each active product, reads avg daily forecast from forecast_cache
and sets current_stock = avg_daily_forecast * days_of_stock, where
days_of_stock is drawn from a 4-bucket distribution designed to
produce a visible mix of ORDER_NOW / LOW_STOCK / HOLD recommendations
in the Plan 1 portfolio view.

Deterministic (seed=42) for reproducibility across defense runs.

Usage:
    python scripts/seed_inventory.py
"""
import random
import sys
from pathlib import Path

from sqlalchemy import func

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal
from app.models import ForecastCache, Inventory, Product


BUCKETS = [
    # (probability, days_range_min, days_range_max, label)
    (0.15, 0, 5, "critical"),
    (0.25, 6, 12, "low"),
    (0.45, 15, 45, "normal"),
    (0.15, 50, 90, "overstocked"),
]


def pick_days_of_stock(rng: random.Random) -> tuple[int, str]:
    """Sample days_of_stock from the 4-bucket distribution."""
    r = rng.random()
    cumulative = 0.0
    for prob, lo, hi, label in BUCKETS:
        cumulative += prob
        if r < cumulative:
            return rng.randint(lo, hi), label
    # fallback (float drift)
    _, lo, hi, label = BUCKETS[-1]
    return rng.randint(lo, hi), label


def main():
    rng = random.Random(42)
    db = SessionLocal()
    try:
        products = db.query(Product).filter(Product.is_active == True).all()
        print(f"Found {len(products)} active products")

        updated = 0
        skipped = 0
        bucket_counts: dict[str, int] = {}

        for p in products:
            # Average daily forecast from cache
            avg_yhat = (
                db.query(func.avg(ForecastCache.yhat))
                .filter(ForecastCache.product_id == p.id)
                .scalar()
            )
            if avg_yhat is None or avg_yhat <= 0:
                print(f"  product {p.id} ({p.name}): no forecast, skipping")
                skipped += 1
                continue

            days, label = pick_days_of_stock(rng)
            new_stock = max(0, round(float(avg_yhat) * days))

            inv = db.query(Inventory).filter(Inventory.product_id == p.id).first()
            if inv is None:
                inv = Inventory(product_id=p.id, current_stock=new_stock)
                db.add(inv)
            else:
                inv.current_stock = new_stock

            bucket_counts[label] = bucket_counts.get(label, 0) + 1
            print(
                f"  product {p.id:>3} ({p.name[:30]:<30}): "
                f"avg_daily={float(avg_yhat):>6.1f}, days={days:>3} ({label:<12}), "
                f"stock={new_stock}"
            )
            updated += 1

        db.commit()

        print("\n=== Summary ===")
        print(f"Updated:  {updated}")
        print(f"Skipped:  {skipped}")
        print(f"Buckets:  {bucket_counts}")

    finally:
        db.close()


if __name__ == "__main__":
    main()
