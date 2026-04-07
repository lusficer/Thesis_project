"""
eCommerce Smart DSS Application
================================

A comprehensive Decision Support System for eCommerce inventory management 
and pricing optimization.

Tech Stack:
- Backend: FastAPI + SQLAlchemy
- ML: Prophet + XGBoost (Hybrid Forecasting)
- Database: SQLite
- Frontend: Next.js 16.2 + React 19

Version: 2.0
"""

__version__ = "2.0.0"
__author__ = "Thesis Project Team"

# Core exports
from app.core import (
    ThesisHybridModel,
    DSSEngine,
    clean_ecommerce_data,
    smart_merge_files,
)

from app.models import (
    User, UserRole,
    Category,
    Product,
    Inventory, StockStatus,
    SalesHistory,
    DSSReport,
)

__all__ = [
    # Version info
    "__version__",
    "__author__",
    
    # Core ML/DSS
    "ThesisHybridModel",
    "DSSEngine",
    "clean_ecommerce_data",
    "smart_merge_files",
    
    # Database models
    "User", "UserRole",
    "Category",
    "Product",
    "Inventory", "StockStatus",
    "SalesHistory",
    "DSSReport",
]

