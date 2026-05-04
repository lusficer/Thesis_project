"""
Database Models
===============

SQLAlchemy ORM models for the eCommerce DSS database.

Models:
-------
- User : User accounts & authentication
- UserRole : Enum for user roles (ADMIN, MANAGER, ANALYST)
- Category : Product categories (hierarchical support)
- Product : Products with pricing & status
- Inventory : Current stock levels & reorder points
- StockStatus : Enum for stock status (in_stock, low_stock, out_of_stock)
- InventoryTransaction : Stock movements (in/out)
- TransactionType : Enum for transaction types (stock_in, stock_out, adjustment)
- SalesHistory : Historical sales data for forecasting
- Supplier : Supplier information
- ProductSupplier : Many-to-many relationship (products ↔ suppliers)
- Notification : System notifications
- NotificationType : Enum for notification types (stockout, low_stock, reorder, price_change, forecast_ready)
- DSSReport : Generated DSS analysis reports
- ForecastCache : Cached future forecast rows per product/version
- BacktestResult : Cached per-product backtest metrics per model version

Database: SQLite (ecommerce_dss.db)
ORM: SQLAlchemy 2.0+
"""

from app.models.models import (
    User, UserRole,
    Category,
    Product,
    Inventory, StockStatus,
    InventoryTransaction, TransactionType,
    SalesHistory,
    Supplier, ProductSupplier,
    Notification, NotificationType,
    DSSReport,
    ForecastCache,
    BacktestResult,
)

__all__ = [
    # User management
    "User", 
    "UserRole",
    
    # Product catalog
    "Category",
    "Product",
    
    # Inventory management
    "Inventory", 
    "StockStatus",
    "InventoryTransaction", 
    "TransactionType",
    
    # Sales & forecasting
    "SalesHistory",
    "ForecastCache",
    "BacktestResult",
    
    # Supply chain
    "Supplier", 
    "ProductSupplier",
    
    # System
    "Notification", 
    "NotificationType",
    "DSSReport",
]
