# eCommerce Smart DSS
**Decision Support System for Product Management**  
Bachelor's Thesis Project — Inventory & Pricing Optimization

---

## Project Structure

```
dss-project/
├── app/
│   ├── core/
│   │   ├── preprocessing.py       # Universal Data Adapter (7 CSV formats)
│   │   ├── hybrid_model.py        # Prophet + XGBoost with asymmetric loss
│   │   ├── dss_engine.py          # Inventory calculations + dynamic pricing
│   │   └── explainability.py      # n8n webhook → LLM integration
│   ├── api/
│   │   └── routes.py              # FastAPI /train and /predict endpoints
│   └── frontend/
│       ├── app.py                 # Streamlit entry point (sidebar nav)
│       ├── components/
│       │   ├── upload.py          # File upload + Universal Data Adapter UI
│       │   ├── product_selector.py# Product dropdown + config inputs
│       │   └── charts.py          # Reusable Plotly chart builders
│       ├── pages/
│       │   ├── strategic_report.py# 🎯 DSS output page (forecast + advice)
│       │   └── analytics.py       # 📊 Analytics Dashboard (3 tabs)
│       └── styles/
│           └── theme.py           # Colors, CHART_LAYOUT, MASTER_CSS, inject_css()
├── .streamlit/
│   └── config.toml                # Light theme config
├── requirements.txt
├── run.py                         # Convenience launcher
└── README.md
```

---

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Start backend (FastAPI) — in one terminal
python run.py --backend

# 3. Start frontend (Streamlit) — in another terminal
python run.py

# Or start both together:
python run.py --all
```

---

## Pages

### 📊 Analytics Dashboard
Explore your data **before** running the AI forecast.
- **Tab 1 — Product Overview**: Individual product deep-dive (trend, monthly, day-of-week, price history, raw table)
- **Tab 2 — Insights**: Cross-product analytics (Top 10, heatmap, YoY trend, sales density)
- **Tab 3 — Simulation**: What-if stock projection without ML (historical averages)

### 🎯 Strategic Report
AI-powered DSS output after clicking **GENERATE INSIGHTS**.
- Product banner + Historical Data Explorer
- ORDER_NOW / HOLD / LOW_STOCK action card
- Inventory metrics (ROP, Safety Stock) + Dynamic Pricing
- AI Analyst card (n8n → LLM explanation)
- 30-Day Inventory Projection chart
- Backtest Validation (DSS vs Naive comparison)

---

## Supported CSV Formats (Auto-Detection)

| Format | Key Columns |
|--------|-------------|
| India Sales | Order ID, Order Date, Sub-Category, Amount, Quantity |
| UK Retail I | InvoiceNo, StockCode, UnitPrice |
| UK Retail II | Invoice, StockCode, Price |
| Electronics | Order Date, Product, Price Each |
| Olist | order_purchase_timestamp, product_id, price |
| Retail Transactions | Transaction_ID, Product (list), Total_Cost |
| FMCG 2023-24 | Order_ID, Order_Date, Product_Name |
| Favorita Ecuador | date, family, sales |
| Unknown | → Manual Mapping UI |

---

## Session State Keys

| Key | Set by | Used by |
|-----|--------|---------|
| `df_clean` | `upload.py` | Strategic Report |
| `price_map` | `upload.py` | Strategic Report, Simulation tab |
| `analytics_df` | `upload.py` | Analytics Dashboard |
| `dss_result` | Strategic Report | Strategic Report (result persistence) |
| `dss_product` | Strategic Report | Strategic Report |
| `dss_stock` / `dss_price` / `dss_target_days` | Strategic Report | Strategic Report |
