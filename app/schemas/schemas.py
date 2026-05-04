"""
Pydantic schemas for request/response validation.
Organized by domain: products, inventory, sales, dashboard, dss.
"""

from datetime import datetime, date
from typing import Optional, List
from pydantic import BaseModel, Field, ConfigDict, model_validator
from enum import Enum


# ─── Enums ───────────────────────────────────────────────────────────

class StockStatusEnum(str, Enum):
    IN_STOCK = "in_stock"
    LOW_STOCK = "low_stock"
    OUT_OF_STOCK = "out_of_stock"


class TransactionTypeEnum(str, Enum):
    IN = "IN"
    OUT = "OUT"
    ADJUSTMENT = "ADJUSTMENT"
    SALE = "SALE"
    WHOLESALE = "WHOLESALE"
    DAMAGE = "DAMAGE"
    LOSS = "LOSS"


# ─── Category ────────────────────────────────────────────────────────

class CategoryCreate(BaseModel):
    name: str
    parent_id: Optional[int] = None
    description: Optional[str] = None

class CategoryResponse(BaseModel):
    id: int
    name: str
    slug: str
    parent_id: Optional[int]
    description: Optional[str]
    model_config = ConfigDict(from_attributes=True)


# ─── Product ─────────────────────────────────────────────────────────

class ProductCreate(BaseModel):
    sku: str = Field(..., max_length=100)
    name: str = Field(..., max_length=500)
    description: Optional[str] = None
    category_id: Optional[int] = None
    image_url: Optional[str] = None
    base_price: float = Field(..., ge=0)
    current_price: Optional[float] = None
    cost_price: Optional[float] = None
    initial_stock: int = Field(default=0, ge=0)
    supplier_id: Optional[int] = None


class ProductUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    category_id: Optional[int] = None
    image_url: Optional[str] = None
    base_price: Optional[float] = None
    current_price: Optional[float] = None
    cost_price: Optional[float] = None
    is_active: Optional[bool] = None


class ProductListItem(BaseModel):
    id: int
    sku: str
    name: str
    description: Optional[str] = None
    category_id: Optional[int] = None
    category_name: Optional[str] = None
    image_url: Optional[str] = None
    current_stock: int = 0
    reorder_point: int = 0
    stock_status: StockStatusEnum = StockStatusEnum.IN_STOCK
    base_price: float
    current_price: float
    cost_price: Optional[float] = None
    sales_7d: int = 0  # last 7 days sales
    is_active: bool
    model_config = ConfigDict(from_attributes=True)


class ProductDetail(BaseModel):
    id: int
    sku: str
    name: str
    description: Optional[str]
    category: Optional[CategoryResponse]
    image_url: Optional[str]
    base_price: float
    current_price: float
    cost_price: Optional[float]
    current_stock: int = 0
    reorder_point: int = 0
    safety_stock: int = 0
    stock_status: StockStatusEnum = StockStatusEnum.IN_STOCK
    is_active: bool
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ProductListResponse(BaseModel):
    items: List[ProductListItem]
    total: int
    page: int
    page_size: int
    total_pages: int


class BulkDeleteRequest(BaseModel):
    ids: Optional[List[int]] = None
    search: Optional[str] = None
    category_id: Optional[int] = None
    stock_status: Optional[StockStatusEnum] = None
    is_active: Optional[bool] = True
    hard_delete: Optional[bool] = False


class BulkDeleteResponse(BaseModel):
    deleted: int


# ─── Inventory ───────────────────────────────────────────────────────

class StockInRequest(BaseModel):
    product_id: int
    quantity: int = Field(..., gt=0)
    supplier: Optional[str] = None    # free-text supplier name
    unit_cost: Optional[float] = None # purchase cost per unit
    reference: Optional[str] = None
    notes: Optional[str] = None


class StockOutRequest(BaseModel):
    product_id: int
    quantity: int = Field(..., gt=0)
    reason: TransactionTypeEnum = TransactionTypeEnum.SALE  # default to SALE
    unit_price: Optional[float] = None     # if None → falls back to product.current_price for SALE/WHOLESALE
    customer_name: Optional[str] = None
    reference: Optional[str] = None
    notes: Optional[str] = None


class InventoryTransactionResponse(BaseModel):
    id: int
    product_id: int
    product_name: Optional[str] = None
    sku: Optional[str] = None
    type: TransactionTypeEnum
    quantity: int
    reference: Optional[str]
    notes: Optional[str]
    unit_price: Optional[float] = None
    supplier: Optional[str] = None
    customer_name: Optional[str] = None
    timestamp: datetime
    model_config = ConfigDict(from_attributes=True)


class InventoryAlertItem(BaseModel):
    product_id: int
    product_name: str
    sku: str
    current_stock: int
    reorder_point: int
    safety_stock: int
    stock_status: StockStatusEnum
    stockout_probability: Optional[float] = None  # from DSS
    days_until_stockout: Optional[int] = None


# ─── Sales ───────────────────────────────────────────────────────────

class SalesImportResponse(BaseModel):
    products_imported: int
    records_imported: int
    date_range: Optional[str] = None
    errors: List[str] = []


class DailySalesResponse(BaseModel):
    date: date
    quantity: int
    quantity_sold: int
    revenue: float


# ─── Dashboard ───────────────────────────────────────────────────────

class DashboardSummary(BaseModel):
    total_products: int
    total_inventory_value: float
    low_stock_count: int
    out_of_stock_count: int
    revenue_today: float
    revenue_week: float
    revenue_month: float
    total_sales_today: int
    products_needing_attention: Optional[int] = None
    total_notifications: Optional[int] = None
    recent_sales_trend: Optional[str] = None
    top_products: Optional[List[dict]] = None
    low_stock_alerts: Optional[List[dict]] = None


# ─── DSS ─────────────────────────────────────────────────────────────

class DSSRunRequest(BaseModel):
    product_id: int
    future_days: int = Field(default=30, ge=7, le=90)
    current_stock: Optional[int] = None  # if None, read from inventory table
    current_price: Optional[float] = None  # if None, read from product table
    target_days_to_sell: int = Field(default=30, ge=7, le=180)
    penalty_under: float = Field(default=5.0, ge=0.1)


class PMReportRequest(BaseModel):
    product_id: Optional[int] = None


class DSSReportResponse(BaseModel):
    id: int
    report_id: Optional[int] = None
    product_id: int
    generated_at: datetime
    forecast_data: Optional[dict]
    inventory_advice: Optional[dict]
    pricing_advice: Optional[dict]
    ai_reasoning: Optional[str]
    parameters: Optional[dict]
    model_config = ConfigDict(from_attributes=True)


class DSSReportUpdate(BaseModel):
    ai_reasoning: Optional[str] = None


# ─── Notifications ───────────────────────────────────────────────────

class NotificationResponse(BaseModel):
    id: int
    type: str
    title: str
    message: Optional[str]
    product_id: Optional[int]
    product_name: Optional[str] = None
    dss_report_id: Optional[int] = None
    is_read: bool
    is_actioned: bool
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class NotificationListResponse(BaseModel):
    items: List[NotificationResponse]
    total: int
    unread_count: int


# ─── DSS Actions (Phase 3 Integration) ──────────────────────────────

class DSSConfirmOrderRequest(BaseModel):
    """Manager confirms ORDER_NOW recommendation → auto stock-in."""
    report_id: int
    quantity: Optional[int] = Field(default=None, gt=0)
    supplier_id: Optional[int] = None   # FK to suppliers table (kept for compat)
    supplier: Optional[str] = None      # free-text supplier name from confirm modal
    unit_cost: Optional[float] = None   # purchase cost per unit
    notes: Optional[str] = None


class DSSApplyPriceRequest(BaseModel):
    """Manager approves DSS pricing recommendation → auto update price."""
    report_id: int
    approved_price: Optional[float] = Field(default=None, gt=0)


class DSSActionResponse(BaseModel):
    success: bool
    message: str
    transaction_id: Optional[int] = None  # for order confirmation
    old_price: Optional[float] = None     # for price update
    new_price: Optional[float] = None


class BacktestRequest(BaseModel):
    product_id: int
    simulation_days: int = Field(default=60, ge=7, le=9999)
    initial_stock: Optional[int] = None
    penalty_under: float = Field(default=5.0, ge=0.1)


class BacktestResponse(BaseModel):
    product_id: int
    simulation_days: int
    # DSS strategy
    dss_stockout_days: int
    dss_service_level: float
    # Naive strategy (fixed ROP = 20% initial stock, order = initial stock)
    naive_stockout_days: int
    naive_service_level: float
    stockout_reduction_pct: float          # DSS vs Naive improvement
    # Oracle baseline (perfect foresight — upper bound)
    oracle_stockout_days: int = 0
    oracle_service_level: float = 100.0
    # Methodology note shown in UI
    methodology_note: str = ""
    daily_data: List[dict]


class DSSScanAllRequest(BaseModel):
    min_sales_days: int = Field(default=30, ge=1, le=365)


# ─── Auth ────────────────────────────────────────────────────────────

class UserLogin(BaseModel):
    username: Optional[str] = None
    email: Optional[str] = None
    password: str

    @model_validator(mode="after")
    def validate_identity(self):
        if not self.username and not self.email:
            raise ValueError("Either username or email is required")
        return self


class UserRegister(BaseModel):
    username: Optional[str] = None
    email: Optional[str] = None
    password: str
    full_name: Optional[str] = None

    @model_validator(mode="after")
    def validate_identity(self):
        if not self.username and not self.email:
            raise ValueError("Either username or email is required")
        return self


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: int
    email: str
    full_name: Optional[str]
    role: str
    is_active: bool
    model_config = ConfigDict(from_attributes=True)
