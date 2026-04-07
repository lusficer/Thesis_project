"""
Core DSS Engine Modules
========================

Provides the core forecasting and decision support functionality.

Modules:
--------
- hybrid_model.py : ThesisHybridModel - Prophet + XGBoost hybrid forecasting
  * Two-stage model: Prophet (trend/seasonality) + XGBoost (residual correction)
  * Custom asymmetric loss function (penalty_under=5.0, penalty_over=1.0)
  * Minimum 30 days of historical data required

- dss_engine.py : DSSEngine - Inventory management & dynamic pricing
  * Inventory: Z-score stockout probability, ROP, safety stock
  * Pricing: Velocity-based rules (±30% guardrails)
  * Lead time: 7 days (hardcoded)

- preprocessing.py : Data cleaning & CSV adapters
  * clean_ecommerce_data() - Universal CSV cleaner
  * smart_merge_files() - Auto-detect 8+ dataset formats
  * Normalizes to: order_purchase_timestamp | product_id | quantity | product_name

- ingest.py : CSV utilities
  * aggregate_sales_by_day() - Daily aggregation
  * filter_product() - Product-specific filtering

Built from: TECHNICAL_DOCUMENTATION.md
"""

from .hybrid_model import ThesisHybridModel
from .dss_engine import DSSEngine
from .preprocessing import clean_ecommerce_data, smart_merge_files
from .ingest import aggregate_sales_by_day, filter_product

__all__ = [
    'ThesisHybridModel',
    'DSSEngine',
    'clean_ecommerce_data',
    'smart_merge_files',
    'aggregate_sales_by_day',
    'filter_product',
]

