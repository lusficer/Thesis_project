"""
Pydantic Schemas
================

Request/Response validation schemas for FastAPI endpoints.

Schema Categories:
------------------
- Authentication : Login, Register, Token, User profiles
- Products : Product CRUD, Category management
- Inventory : Stock management, Transactions
- Sales : Sales data import/export
- DSS : Forecasting requests/responses, Analysis reports
- Dashboard : Summary statistics, Metrics
- Notifications : Alert schemas

Features:
- Type validation with Pydantic v2
- Automatic JSON serialization
- OpenAPI documentation generation
- Config for ORM mode compatibility

Usage:
    from app.schemas import ProductCreate, DSSResponse
"""

from app.schemas.schemas import *

# Note: Using wildcard import from schemas.schemas
# All Pydantic models are exported automatically
# See app/schemas/schemas.py for complete list

__all__ = [
    # Wildcard import - all schemas from schemas.py are exported
    # Includes: Product*, Category*, Inventory*, Sales*, DSS*, User*, etc.
]

