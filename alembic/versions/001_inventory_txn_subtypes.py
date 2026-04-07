"""inventory_txn_subtypes

Add unit_price, supplier, customer_name columns to inventory_transactions.
Extend TransactionType enum with SALE, WHOLESALE, DAMAGE, LOSS values.

SQLite does not support ALTER COLUMN for enums, so we use batch mode
to recreate the table with the updated enum definition.

Revision ID: 001_inventory_txn_subtypes
Revises:
Create Date: 2025-01-01 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import sqlite

# revision identifiers
revision = "001_inventory_txn_subtypes"
down_revision = None
branch_labels = None
depends_on = None

# Full enum with old + new values (order matters for SQLite recreation)
NEW_TRANSACTION_TYPE = sa.Enum(
    "IN", "OUT", "ADJUSTMENT", "SALE", "WHOLESALE", "DAMAGE", "LOSS",
    name="transactiontype",
)


def upgrade() -> None:
    # SQLite requires batch mode to modify column types / add enum values
    with op.batch_alter_table("inventory_transactions", schema=None) as batch_op:
        # Recreate `type` column with expanded enum
        batch_op.alter_column(
            "type",
            existing_type=sa.Enum("IN", "OUT", "ADJUSTMENT", name="transactiontype"),
            type_=NEW_TRANSACTION_TYPE,
            existing_nullable=False,
        )
        # New columns — all nullable so existing rows are unaffected
        batch_op.add_column(sa.Column("unit_price", sa.Numeric(12, 2), nullable=True))
        batch_op.add_column(sa.Column("supplier", sa.String(255), nullable=True))
        batch_op.add_column(sa.Column("customer_name", sa.String(255), nullable=True))


def downgrade() -> None:
    OLD_TRANSACTION_TYPE = sa.Enum(
        "IN", "OUT", "ADJUSTMENT",
        name="transactiontype",
    )
    with op.batch_alter_table("inventory_transactions", schema=None) as batch_op:
        batch_op.drop_column("customer_name")
        batch_op.drop_column("supplier")
        batch_op.drop_column("unit_price")
        batch_op.alter_column(
            "type",
            existing_type=NEW_TRANSACTION_TYPE,
            type_=OLD_TRANSACTION_TYPE,
            existing_nullable=False,
        )
