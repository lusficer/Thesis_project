"""
One-time category seeding for thesis Plan 2 rollup.

Usage:
  python -m scripts.seed_categories          # dry-run (default)
  python -m scripts.seed_categories --apply  # write changes
"""

from __future__ import annotations

import argparse
import sys
from typing import Dict, List

from sqlalchemy import text

from app.database import SessionLocal


CATEGORY_DEFS: dict[str, dict[str, List[str] | str]] = {
    "accessories": {
        "name": "Accessories",
        "products": [
            "Charging Cable",
            "Closet Organizer",
            "Cookware Set",
            "Dell XPS 13",
            "Dining Table Set",
            "Dyson Vacuum",
            "Instant Pot",
            "KitchenAid Mixer",
            "LG OLED TV",
            "Lenovo ThinkPad",
            "MacBook Air",
            "Office Chair",
            "Phone Case",
            "Power Bank",
            "Sony Bravia TV",
            "Storage Rack",
            "Vase",
            "Wall Art",
        ],
    },
    "clothing-apparel": {
        "name": "Clothing & Apparel",
        "products": [
            "Adidas Tracksuit",
            "Ashley Recliner",
            "Backpack",
            "Brooklinen Sheets",
            "Carter's Onesie",
            "Children's Hoodie",
            "GAP Hoodie",
            "IKEA Sofa",
            "Levi's Jeans",
            "Old Navy Dress",
            "Tempur-Pedic Mattress",
            "Throw Pillows",
            "Tote Bag",
            "Under Armour T-Shirt",
            "Zara Blouse",
        ],
    },
    "footwear": {
        "name": "Footwear",
        "products": [
            "Belt",
            "Crocs",
            "Nike Air Force 1",
            "Nike Running Shoes",
            "Sunglasses",
            "Timberland Boots",
            "Wallet",
            "Watch Strap",
        ],
    },
    "electronics": {
        "name": "Electronics",
        "products": [
            "Apple Watch",
            "Apple iPhone 14",
            "Bose Soundbar",
            "Fitbit Charge",
            "Google Pixel 7",
            "Samsung Galaxy S23",
            "Samsung Galaxy Tab",
            "iPad Pro",
        ],
    },
}


def build_product_to_slug() -> dict[str, str]:
    product_to_slug: dict[str, str] = {}
    for slug, info in CATEGORY_DEFS.items():
        for name in info["products"]:  # type: ignore[index]
            if name in product_to_slug:
                raise RuntimeError(f"Duplicate product mapping detected: {name}")
            product_to_slug[name] = slug
    return product_to_slug


def verify_counts(conn) -> None:
    print("\nVerification snapshot:")
    rows = conn.execute(
        text(
            """
            SELECT COALESCE(c.name, '(NULL category_id)') AS category_name,
                   COUNT(p.id) AS product_count
            FROM products p
            LEFT JOIN categories c ON c.id = p.category_id
            GROUP BY c.name
            ORDER BY product_count DESC
            """
        )
    ).mappings().all()
    for r in rows:
        print(f"  {r['category_name']}: {r['product_count']}")

    null_count = conn.execute(
        text("SELECT COUNT(*) FROM products WHERE category_id IS NULL")
    ).scalar_one()
    print(f"  NULL category_id count: {null_count}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed product categories")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply changes (default is dry-run)",
    )
    args = parser.parse_args()

    product_to_slug = build_product_to_slug()
    expected_products = len(product_to_slug)

    print(f"Mode: {'APPLY' if args.apply else 'DRY-RUN'}")
    print(f"Expected mapped products: {expected_products}")

    db = SessionLocal()
    try:
        all_products = db.execute(
            text("SELECT id, name FROM products ORDER BY id")
        ).mappings().all()
        db_name_to_id: Dict[str, int] = {r["name"]: int(r["id"]) for r in all_products}

        missing_in_db = [name for name in product_to_slug if name not in db_name_to_id]
        unmapped_in_db = [r["name"] for r in all_products if r["name"] not in product_to_slug]

        if missing_in_db:
            print("\nERROR: Mapped product names not found in DB (exact match required):")
            for name in missing_in_db:
                print(f"  - {name}")
        if unmapped_in_db:
            print("\nERROR: DB products missing from mapping:")
            for name in unmapped_in_db:
                print(f"  - {name}")

        if missing_in_db or unmapped_in_db:
            print("\nAborting due to mapping mismatch.")
            verify_counts(db)
            return 1

        # Load existing categories by relevant slugs and legacy electronics marker.
        existing_rows = db.execute(
            text(
                """
                SELECT id, name, slug
                FROM categories
                WHERE slug IN ('accessories', 'clothing-apparel', 'footwear', 'electronics', 'electronic')
                   OR lower(name) = 'electronic'
                """
            )
        ).mappings().all()

        existing_by_slug = {r["slug"]: r for r in existing_rows if r["slug"]}
        slug_to_id: Dict[str, int] = {}

        for slug, info in CATEGORY_DEFS.items():
            canonical_name = str(info["name"])
            row = existing_by_slug.get(slug)

            # Handle legacy singular electronics row by renaming/updating it.
            if slug == "electronics" and row is None:
                legacy = existing_by_slug.get("electronic")
                if legacy is None:
                    legacy = next(
                        (r for r in existing_rows if str(r["name"]).lower() == "electronic"),
                        None,
                    )
                if legacy is not None:
                    slug_to_id[slug] = int(legacy["id"])
                    if args.apply:
                        db.execute(
                            text(
                                """
                                UPDATE categories
                                SET name = :name, slug = :slug
                                WHERE id = :id
                                """
                            ),
                            {"name": canonical_name, "slug": slug, "id": int(legacy["id"])},
                        )
                    print(
                        f"{'[APPLY]' if args.apply else '[DRY]'} repurpose category id={legacy['id']} "
                        f"to name='{canonical_name}', slug='{slug}'"
                    )
                    continue

            if row is not None:
                slug_to_id[slug] = int(row["id"])
                if args.apply and (row["name"] != canonical_name):
                    db.execute(
                        text("UPDATE categories SET name = :name WHERE id = :id"),
                        {"name": canonical_name, "id": int(row["id"])},
                    )
                print(
                    f"{'[APPLY]' if args.apply else '[DRY]'} keep category id={row['id']} "
                    f"slug='{slug}' name='{canonical_name}'"
                )
            else:
                if args.apply:
                    new_id = db.execute(
                        text(
                            """
                            INSERT INTO categories (name, slug, parent_id, description, created_at)
                            VALUES (:name, :slug, NULL, NULL, CURRENT_TIMESTAMP)
                            RETURNING id
                            """
                        ),
                        {"name": canonical_name, "slug": slug},
                    ).scalar_one()
                    slug_to_id[slug] = int(new_id)
                print(
                    f"{'[APPLY]' if args.apply else '[DRY]'} create category "
                    f"slug='{slug}' name='{canonical_name}'"
                )

        if not args.apply:
            # Build projected ids from current DB for reporting consistency.
            current = db.execute(
                text("SELECT id, slug FROM categories WHERE slug IN ('accessories','clothing-apparel','footwear','electronics')")
            ).mappings().all()
            for r in current:
                slug_to_id[str(r["slug"])] = int(r["id"])

        if args.apply and len(slug_to_id) != 4:
            raise RuntimeError(f"Category upsert incomplete, got ids: {slug_to_id}")

        print("\nApplying product category assignments:")
        updated = 0
        for product_name, slug in sorted(product_to_slug.items()):
            category_id = slug_to_id.get(slug)
            if category_id is None:
                print(f"[DRY] would set '{product_name}' -> {slug}")
                continue

            if args.apply:
                db.execute(
                    text(
                        """
                        UPDATE products
                        SET category_id = :category_id
                        WHERE name = :name
                        """
                    ),
                    {"category_id": category_id, "name": product_name},
                )
                updated += 1

        if args.apply:
            db.commit()
            print(f"\nApplied category_id updates for {updated} products.")
        else:
            print("\nDry-run only; no DB writes performed.")

        verify_counts(db)
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
