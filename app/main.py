"""
eCommerce Smart DSS — Main FastAPI Application
Combines existing DSS engine with new product management APIs.
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from app.api import products, inventory, sales, dashboard, dss, auth, notifications

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Schema is managed by Alembic — run `alembic upgrade head`
    # before starting uvicorn. This lifespan intentionally does
    # NOT call Base.metadata.create_all() to avoid conflicts
    # between auto-created tables and Alembic migrations.
    yield


app = FastAPI(
    title="eCommerce Smart DSS",
    description="Decision Support System for Inventory & Pricing Optimization",
    version="2.0.0",
    lifespan=lifespan,
)

# CORS — allow Next.js frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(auth.router, prefix="/api")
app.include_router(products.router, prefix="/api")
app.include_router(inventory.router, prefix="/api")
app.include_router(sales.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")
app.include_router(dss.router, prefix="/api")
app.include_router(notifications.router, prefix="/api")


@app.get("/api/health")
def health_check():
    return {"status": "ok", "version": "2.0.0"}
