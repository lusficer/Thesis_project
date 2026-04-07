"""
API Routes
==========

FastAPI router modules for all API endpoints.

Route Modules:
--------------
- auth.py : Authentication & authorization (login, register, logout)
- products.py : Product & category management CRUD
- inventory.py : Inventory tracking & stock transactions
- sales.py : Sales data import/export & history
- dss.py : DSS analysis & forecasting endpoints
- dashboard.py : Dashboard metrics & summary statistics
- notifications.py : System notifications & alerts

Base Path: /api
Documentation: http://localhost:8000/docs (Swagger UI)

All routes are registered in app/main.py
"""

# API routes package
# Individual routers are imported and registered in main.py

__all__ = [
    # Route modules are not exported directly
    # Import from specific modules as needed:
    # from app.api.products import router as products_router
]

