"""
SQLAlchemy ORM Models
Tables: users, categories, products, inventory, inventory_transactions,
        sales_history, suppliers, product_suppliers, dss_reports,
        forecast_cache, backtest_results
"""

from datetime import datetime, date
from sqlalchemy import (
    Column, Integer, String, Float, Text, Boolean, DateTime, Date,
    ForeignKey, JSON, Enum, Index, Numeric
)
from sqlalchemy.orm import relationship
import enum

from app.database import Base



class UserRole(str, enum.Enum):
    ADMIN = "admin"
    MANAGER = "manager"
    VIEWER = "viewer"


class TransactionType(str, enum.Enum):
    IN         = "IN"
    OUT        = "OUT"          # kept for backward compat
    ADJUSTMENT = "ADJUSTMENT"   # kept for backward compat
    SALE       = "SALE"         # retail sale → creates SalesHistory
    WHOLESALE  = "WHOLESALE"    # bulk sale → creates SalesHistory
    DAMAGE     = "DAMAGE"       # damaged goods
    LOSS       = "LOSS"         # lost/missing stock


class StockStatus(str, enum.Enum):
    IN_STOCK = "in_stock"
    LOW_STOCK = "low_stock"
    OUT_OF_STOCK = "out_of_stock"



class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=True)
    role = Column(Enum(UserRole), default=UserRole.MANAGER, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)



class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    slug = Column(String(255), unique=True, nullable=False, index=True)
    parent_id = Column(Integer, ForeignKey("categories.id"), nullable=True)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    parent = relationship("Category", remote_side=[id], backref="children")
    products = relationship("Product", back_populates="category")



class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sku = Column(String(100), unique=True, nullable=False, index=True)
    name = Column(String(500), nullable=False)
    description = Column(Text, nullable=True)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=True)
    image_url = Column(String(1000), nullable=True)
    base_price = Column(Numeric(12, 2), nullable=False, default=0)
    current_price = Column(Numeric(12, 2), nullable=False, default=0)
    cost_price = Column(Numeric(12, 2), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    category = relationship("Category", back_populates="products")
    inventory = relationship("Inventory", back_populates="product", uselist=False)
    sales = relationship("SalesHistory", back_populates="product")
    transactions = relationship("InventoryTransaction", back_populates="product")
    dss_reports = relationship("DSSReport", back_populates="product")
    suppliers = relationship("ProductSupplier", back_populates="product")

    __table_args__ = (
        Index("idx_product_name", "name"),
        Index("idx_product_active", "is_active"),
    )



class Inventory(Base):
    __tablename__ = "inventory"

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(Integer, ForeignKey("products.id"), unique=True, nullable=False)
    current_stock = Column(Integer, default=0, nullable=False)
    reorder_point = Column(Integer, default=0)
    safety_stock = Column(Integer, default=0)
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    product = relationship("Product", back_populates="inventory")

    @property
    def stock_status(self) -> StockStatus:
        if self.current_stock <= 0:
            return StockStatus.OUT_OF_STOCK
        elif self.current_stock <= self.reorder_point:
            return StockStatus.LOW_STOCK
        return StockStatus.IN_STOCK



class InventoryTransaction(Base):
    __tablename__ = "inventory_transactions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    type = Column(Enum(TransactionType), nullable=False)
    quantity = Column(Integer, nullable=False)   # positive = IN, negative = OUT
    reference = Column(String(255), nullable=True)
    notes = Column(Text, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)

    # Extended fields added for richer stock-out/in tracking
    unit_price = Column(Numeric(12, 2), nullable=True)   # sale price (SALE/WHOLESALE) or purchase cost (IN)
    supplier = Column(String(255), nullable=True)         # supplier name (stock-in)
    customer_name = Column(String(255), nullable=True)    # customer (SALE/WHOLESALE)

    product = relationship("Product", back_populates="transactions")

    __table_args__ = (
        Index("idx_txn_product_time", "product_id", "timestamp"),
    )



class SalesHistory(Base):
    __tablename__ = "sales_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    date = Column(Date, nullable=False)
    quantity_sold = Column(Integer, default=0, nullable=False)
    revenue = Column(Numeric(14, 2), default=0)
    import_batch = Column(String(100), nullable=True)  # track which CSV import created this

    product = relationship("Product", back_populates="sales")

    __table_args__ = (
        Index("idx_sales_product_date", "product_id", "date"),
        Index("idx_sales_date", "date"),
    )



class Supplier(Base):
    __tablename__ = "suppliers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    contact_email = Column(String(255), nullable=True)
    contact_phone = Column(String(50), nullable=True)
    address = Column(Text, nullable=True)
    lead_time_days = Column(Integer, default=7)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    products = relationship("ProductSupplier", back_populates="supplier")


class ProductSupplier(Base):
    """Many-to-many: which suppliers provide which products."""
    __tablename__ = "product_suppliers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=False)
    supplier_sku = Column(String(100), nullable=True)
    unit_cost = Column(Numeric(12, 2), nullable=True)
    is_primary = Column(Boolean, default=False)

    product = relationship("Product", back_populates="suppliers")
    supplier = relationship("Supplier", back_populates="products")

    __table_args__ = (
        Index("idx_ps_product_supplier", "product_id", "supplier_id", unique=True),
    )



class NotificationType(str, enum.Enum):
    LOW_STOCK = "low_stock"
    OUT_OF_STOCK = "out_of_stock"
    ORDER_CONFIRMED = "order_confirmed"
    PRICE_UPDATED = "price_updated"
    DSS_COMPLETED = "dss_completed"
    STOCKOUT_WARNING = "stockout_warning"


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    type = Column(Enum(NotificationType), nullable=False)
    title = Column(String(255), nullable=False)
    message = Column(Text, nullable=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=True)
    dss_report_id = Column(Integer, ForeignKey("dss_reports.id"), nullable=True)
    is_read = Column(Boolean, default=False)
    is_actioned = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    product = relationship("Product")

    __table_args__ = (
        Index("idx_notif_unread", "is_read", "created_at"),
    )


class DSSReport(Base):
    __tablename__ = "dss_reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    generated_at = Column(DateTime, default=datetime.utcnow, index=True)
    forecast_data = Column(JSON, nullable=True)
    inventory_advice = Column(JSON, nullable=True)
    pricing_advice = Column(JSON, nullable=True)
    ai_reasoning = Column(Text, nullable=True)
    parameters = Column(JSON, nullable=True)

    product = relationship("Product", back_populates="dss_reports")

    __table_args__ = (
        Index("idx_dss_product_time", "product_id", "generated_at"),
    )


class ForecastCache(Base):
    __tablename__ = "forecast_cache"

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    forecast_date = Column(Date, nullable=False, index=True)
    yhat = Column(Float, nullable=False)
    yhat_lower = Column(Float, nullable=False)
    yhat_upper = Column(Float, nullable=False)
    model_version = Column(String(50), nullable=False, default="hybrid_asym_v1")
    computed_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    product = relationship("Product")

    __table_args__ = (
        Index("idx_fc_product_date", "product_id", "forecast_date"),
        Index("idx_fc_product_version", "product_id", "model_version"),
    )


class BacktestResult(Base):
    __tablename__ = "backtest_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    model_version = Column(String(50), nullable=False, default="hybrid_asym_v1")

    test_start_date = Column(Date, nullable=False)
    test_end_date = Column(Date, nullable=False)
    n_test_days = Column(Integer, nullable=False)

    mae = Column(Float, nullable=False)
    rmse = Column(Float, nullable=False)
    mape = Column(Float, nullable=True)
    under_forecast_pct = Column(Float, nullable=False)
    over_forecast_pct = Column(Float, nullable=False)

    dss_service_level = Column(Float, nullable=False)
    dss_stockout_days = Column(Integer, nullable=False)
    dss_avg_inventory = Column(Float, nullable=False)

    naive_service_level = Column(Float, nullable=False)
    naive_stockout_days = Column(Integer, nullable=False)
    naive_avg_inventory = Column(Float, nullable=False)

    oracle_service_level = Column(Float, nullable=False)
    oracle_stockout_days = Column(Integer, nullable=False)
    oracle_avg_inventory = Column(Float, nullable=False)

    computed_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    product = relationship("Product")

    __table_args__ = (
        Index("idx_br_product_version", "product_id", "model_version"),
        Index("idx_br_version", "model_version"),
    )
