"""
═══════════════════════════════════════════════════════════════════════
  BENCHMARK SCRIPT — Model Comparison for Thesis Chapter 4 & 5
  Prophet-only vs XGBoost-only vs Hybrid (Prophet+XGBoost)
═══════════════════════════════════════════════════════════════════════

Usage:
    python benchmark.py

Requirements:
    pip install prophet xgboost pandas numpy scikit-learn matplotlib tabulate

Output:
    - benchmark_results.csv       → Raw metrics per product per model
    - benchmark_summary.csv       → Aggregated summary per dataset per model
    - benchmark_report.txt        → Formatted tables for thesis
    - charts/                     → Comparison charts (bar + line)

Place this file in: THESIS_PROJECT/
Run from project root: python benchmark.py
"""

import pandas as pd
import numpy as np
import os
import sys
import warnings
import logging
from datetime import datetime

# Suppress noisy logs
warnings.filterwarnings('ignore')
logging.getLogger('cmdstanpy').setLevel(logging.WARNING)
logging.getLogger('prophet').setLevel(logging.WARNING)

# ── Import project modules ──
sys.path.append(os.path.abspath(os.path.dirname(__file__)))
from app.core.preprocessing import clean_ecommerce_data

# ── Import ML libraries ──
from prophet import Prophet
import xgboost as xgb
from sklearn.metrics import mean_absolute_error, mean_squared_error


# ═══════════════════════════════════════════════════════════════
#  1. DATASET REGISTRY — Add your datasets here
# ═══════════════════════════════════════════════════════════════

def load_datasets():
    """
    Returns a dict of {dataset_name: (df_clean, price_map)}.
    Each df_clean has columns: order_purchase_timestamp, product_id, quantity, product_name
    
    ── HOW TO ADD A NEW DATASET ──
    1. Put CSV files in a folder (e.g., data/new_dataset/)
    2. Add a new block below following the pattern
    3. Run benchmark.py — it will auto-include the new dataset
    """
    datasets = {}
    
    # ── Dataset 1: India Sales ──
    try:
        df_list = pd.read_csv('data/india/List_of_Orders.csv', encoding='ISO-8859-1')
        df_details = pd.read_csv('data/india/Order_Details.csv', encoding='ISO-8859-1')
        if {'Order ID', 'Order Date'}.issubset(df_list.columns) and \
        {'Order ID', 'Sub-Category', 'Amount', 'Quantity'}.issubset(df_details.columns):
            merged = pd.merge(df_list, df_details, on='Order ID', how='inner')
            merged['Order Date'] = pd.to_datetime(merged['Order Date'], dayfirst=True)
            # Bypass clean_ecommerce_data — build unified schema directly
            df_clean = pd.DataFrame({
                'order_purchase_timestamp': merged['Order Date'],
                'product_id': merged['Sub-Category'],
                'quantity': merged['Quantity'],
                'product_name': merged['Sub-Category']
            }).dropna(subset=['order_purchase_timestamp', 'product_id', 'quantity'])
            df_clean['quantity'] = df_clean['quantity'].clip(lower=0)
            datasets['India Sales'] = df_clean
            print(f"  ✅ India Sales: {len(df_clean)} rows ({df_clean['product_id'].nunique()} categories)")
    except FileNotFoundError:
        print("  ⚠️ India Sales not found")
    # ── Dataset 2: UK Retail ──
    try:
        for path in ['data/uk/online_retail_II.csv', 'data/uk/OnlineRetail.csv', 'data/uk/data.csv', 'data/uk_retail.csv']:
            if os.path.exists(path):
                df = pd.read_csv(path, encoding='ISO-8859-1')
                # Format A: InvoiceNo, StockCode, Description, UnitPrice
                if {'InvoiceNo', 'StockCode', 'Description', 'UnitPrice'}.issubset(df.columns):
                    df_clean, *_ = clean_ecommerce_data(df, {
                        'date_col': 'InvoiceDate', 'pid_col': 'StockCode',
                        'qty_col': 'Quantity', 'name_col': 'Description'
                    })
                    datasets['UK Retail'] = df_clean
                    print(f"  ✅ UK Retail: {len(df_clean)} rows")
                # Format B: Invoice, StockCode, Description, Price (online_retail_II)
                elif {'Invoice', 'StockCode', 'Description', 'Price'}.issubset(df.columns):
                    df_clean, *_ = clean_ecommerce_data(df, {
                        'date_col': 'InvoiceDate', 'pid_col': 'StockCode',
                        'qty_col': 'Quantity', 'name_col': 'Description'
                    })
                    datasets['UK Retail'] = df_clean
                    print(f"  ✅ UK Retail: {len(df_clean)} rows")
                break
    except Exception as e:
        print(f"  ⚠️ UK Retail error: {e}")

    # ── Dataset 3: Electronics ──
    try:
        for path in ['data/electronics/Sales_Data.csv', 'data/electronics/data.csv']:
            if os.path.exists(path):
                df = pd.read_csv(path, encoding='ISO-8859-1')
                if {'Order Date', 'Product', 'Price Each'}.issubset(df.columns):
                    df_clean, *_ = clean_ecommerce_data(df, {
                        'date_col': 'Order Date', 'pid_col': 'Product',
                        'qty_col': 'Quantity Ordered', 'name_col': 'Product'
                    })
                    datasets['Electronics'] = df_clean
                    print(f"  ✅ Electronics: {len(df_clean)} rows")
                break
    except Exception as e:
        print(f"  ⚠️ Electronics error: {e}")

    # ── Dataset 4: Olist ──
    try:
        olist_dir = 'data/olist/'
        if os.path.exists(olist_dir):
            df_ord = pd.read_csv(f'{olist_dir}olist_orders_dataset.csv')
            df_itm = pd.read_csv(f'{olist_dir}olist_order_items_dataset.csv')
            merged = pd.merge(df_ord, df_itm, on='order_id', how='inner')
            if os.path.exists(f'{olist_dir}olist_products_dataset.csv'):
                df_prd = pd.read_csv(f'{olist_dir}olist_products_dataset.csv')
                merged = pd.merge(merged, df_prd, on='product_id', how='left')
            if 'quantity' not in merged.columns:
                merged['quantity'] = 1
            df_clean, *_ = clean_ecommerce_data(merged, {
                'date_col': 'order_purchase_timestamp', 'pid_col': 'product_id',
                'qty_col': 'quantity', 'name_col': 'product_category_name'
            })
            datasets['Olist Brazil'] = df_clean
            print(f"  ✅ Olist Brazil: {len(df_clean)} rows")
    except Exception as e:
        print(f"  ⚠️ Olist error: {e}")

    # ──────────────────────────────────────────────────────────
    #  ADD NEW DATASETS BELOW — follow the pattern above
    # ──────────────────────────────────────────────────────────
    
    # ── Dataset 5: Retail Transactions (Kaggle - prasad22) ──
    # Product column is a stringified list: "['Ketchup', 'Shaving Cream']"
    # Need to explode into individual product rows
    try:
        for path in ['data/Retail/Retail_Transactions_Dataset.csv',
                      'data/retail_transactions/Retail_Transactions_Dataset.csv',
                      'data/retail/retail_transactions.csv']:
            if os.path.exists(path):
                df = pd.read_csv(path)
                if 'Product' in df.columns and 'Date' in df.columns:
                    import ast
                    # Parse product list string → actual list → explode
                    df['Product'] = df['Product'].apply(lambda x: ast.literal_eval(x) if isinstance(x, str) and x.startswith('[') else [x])
                    df = df.explode('Product').reset_index(drop=True)
                    df['Product'] = df['Product'].str.strip()
                    # Each exploded row = 1 unit of that product
                    df['Quantity'] = 1
                    df_clean, *_ = clean_ecommerce_data(df, {
                        'date_col': 'Date', 'pid_col': 'Product',
                        'qty_col': 'Quantity', 'name_col': 'Product'
                    })
                    datasets['Retail Transactions'] = df_clean
                    print(f"  ✅ Retail Transactions: {len(df_clean)} rows ({df_clean['product_id'].nunique()} products)")
                break
    except Exception as e:
        print(f"  ⚠️ Retail Transactions error: {e}")

    # ── Dataset 6: FMCG Product Sales 2023-2024 (Kaggle - yashyennewar) ──
    # Date format: MM-DD-YY (e.g., 08-23-23)
    # Column names have trailing spaces: " Unit_Price ", " Revenue ", " Profit "
    # ── Dataset 6: FMCG Product Sales 2023-2024 ──
    try:
        for path in ['data/FMCG/product_sales_dataset_final.csv',
                    'data/fmcg/product_sales.csv',
                    'data/product_sales_2023/product_sales.csv']:
            if os.path.exists(path):
                df = pd.read_csv(path)
                df.columns = df.columns.str.strip()
                if 'Order_Date' in df.columns and 'Product_Name' in df.columns:
                    df['Order_Date'] = pd.to_datetime(df['Order_Date'], format='%m-%d-%y', errors='coerce')
                    # Aggregate by Sub_Category (thesis evaluates 5 sub-categories, not 49 products)
                    df_agg = df.groupby(['Order_Date', 'Sub_Category']).agg(
                        Quantity=('Quantity', 'sum')
                    ).reset_index()
                    df_clean = pd.DataFrame({
                        'order_purchase_timestamp': df_agg['Order_Date'],
                        'product_id': df_agg['Sub_Category'],
                        'quantity': df_agg['Quantity'],
                        'product_name': df_agg['Sub_Category']
                    }).dropna(subset=['order_purchase_timestamp', 'product_id', 'quantity'])
                    df_clean['quantity'] = df_clean['quantity'].clip(lower=0)
                    datasets['FMCG Sales 2023-24'] = df_clean
                    print(f"  ✅ FMCG Sales 2023-24: {len(df_clean)} rows ({df_clean['product_id'].nunique()} sub-categories)")
                break
    except Exception as e:
        print(f"  ⚠️ FMCG Sales 2023-24 error: {e}")

    # ── Dataset 7: Store Sales - Favorita Ecuador (Kaggle competition) ──
    # Download from: kaggle.com/c/store-sales-time-series-forecasting/data
    # Columns: id, date, store_nbr, family, sales, onpromotion
    # 4+ years daily data, 33 product families, strong seasonality
    try:
        for path in ['data/favorita/train.csv', 'data/store_sales/train.csv']:
            if os.path.exists(path):
                df = pd.read_csv(path, parse_dates=['date'])
                if {'date', 'family', 'sales'}.issubset(df.columns):
                    # Aggregate across all stores: total daily sales per product family
                    df_agg = df.groupby(['date', 'family']).agg(
                        sales=('sales', 'sum')
                    ).reset_index()
                    df_agg['Quantity'] = df_agg['sales'].clip(lower=0).astype(int)
                    df_agg = df_agg[df_agg['Quantity'] > 0]
                    df_clean, *_ = clean_ecommerce_data(df_agg, {
                        'date_col': 'date', 'pid_col': 'family',
                        'qty_col': 'Quantity', 'name_col': 'family'
                    })
                    datasets['Favorita Ecuador'] = df_clean
                    print(f"  ✅ Favorita Ecuador: {len(df_clean)} rows ({df_clean['product_id'].nunique()} families)")
                break
    except Exception as e:
        print(f"  ⚠️ Favorita error: {e}")

    return datasets


# ═══════════════════════════════════════════════════════════════
#  2. MODEL IMPLEMENTATIONS — Same logic as hybrid_model.py
# ═══════════════════════════════════════════════════════════════

FEATURES = ['day_of_week', 'is_weekend', 'month', 'rolling_mean_7', 'lag_7']

def feature_engineering(df):
    """Same as ThesisHybridModel._feature_engineering"""
    df = df.copy()
    df['day_of_week'] = df['ds'].dt.dayofweek
    df['is_weekend'] = df['day_of_week'].apply(lambda x: 1 if x >= 5 else 0)
    df['month'] = df['ds'].dt.month
    df['rolling_mean_7'] = df['y'].shift(1).rolling(window=7).mean()
    df['lag_7'] = df['y'].shift(7)
    df = df.bfill().fillna(0)
    return df


def feature_engineering_no_leak(df_train, df_test, y_proxy_test=None):
    """
    Feature engineering WITHOUT data leakage.
    Uses train's actual y for context. For test rows, uses y_proxy_test
    (e.g., Prophet yhat or 0) instead of actual y.
    """
    df_tr = df_train.copy()
    df_te = df_test.copy()
    
    # Replace test y with proxy to prevent leakage
    if y_proxy_test is not None:
        df_te['y'] = y_proxy_test
    else:
        # Default proxy: use last known train value (no future info)
        last_train_mean = df_tr['y'].tail(7).mean()
        df_te['y'] = last_train_mean
    
    df_full = pd.concat([df_tr, df_te], ignore_index=True)
    df_full = feature_engineering(df_full)
    
    df_te_feat = df_full.iloc[len(df_tr):].reset_index(drop=True)
    df_tr_feat = df_full.iloc[:len(df_tr)]
    return df_tr_feat, df_te_feat


def custom_objective_asym(y_true, y_pred, penalty_under=5.0, penalty_over=1.0):
    """Asymmetric loss matching ThesisHybridModel._custom_objective.
    XGBRegressor sklearn API passes (y_true, y_pred) — not DMatrix."""
    residual = y_pred - y_true
    grad = np.where(residual < 0, penalty_under * 2 * residual, penalty_over * 2 * residual)
    hess = np.where(residual < 0, penalty_under * 2, penalty_over * 2)
    return grad, hess


def train_predict_prophet_only(df_train, df_test):
    """Model A: Prophet alone"""
    model = Prophet(daily_seasonality=True, yearly_seasonality=False)
    model.fit(df_train[['ds', 'y']])
    
    forecast = model.predict(df_test[['ds']])
    preds = forecast['yhat'].values
    preds = np.maximum(preds, 0)  # clamp
    return preds


def train_predict_xgboost_only(df_train, df_test):
    """Model B: XGBoost alone (standard MSE, same features, NO data leakage)"""
    # Train features: use actual y
    df_tr_feat = feature_engineering(df_train)
    
    # Test features: use train's trailing mean as y proxy (no future info)
    df_tr_feat2, df_te_feat = feature_engineering_no_leak(df_train, df_test, y_proxy_test=None)
    
    X_train = df_tr_feat[FEATURES]
    y_train = df_tr_feat['y']
    X_test = df_te_feat[FEATURES]
    
    model = xgb.XGBRegressor(n_estimators=100, objective='reg:squarederror')
    model.fit(X_train, y_train)
    
    preds = model.predict(X_test)
    preds = np.maximum(preds, 0)
    return preds


def train_predict_hybrid(df_train, df_test, penalty_under=5.0, penalty_over=1.0):
    """Model C: Hybrid Prophet+XGBoost (exact same logic as ThesisHybridModel, NO leakage)"""
    # Step 1: Prophet on training data
    prophet_model = Prophet(daily_seasonality=True, yearly_seasonality=False)
    prophet_model.fit(df_train[['ds', 'y']])
    
    # Step 2: Get train residuals
    train_forecast = prophet_model.predict(df_train[['ds']])
    df_tr_feat = feature_engineering(df_train)
    df_merged = pd.merge(df_tr_feat, train_forecast[['ds', 'yhat']], on='ds')
    df_merged['residual'] = df_merged['y'] - df_merged['yhat']
    df_clean = df_merged.dropna(subset=['residual'] + FEATURES)
    
    if df_clean.empty or len(df_clean) < 7:
        test_forecast = prophet_model.predict(df_test[['ds']])
        preds = test_forecast['yhat'].values
        return np.maximum(preds, 0)
    
    # Step 3: Train XGBoost on residuals
    X_train = df_clean[FEATURES]
    y_residual = df_clean['residual']
    
    def asym_obj(y_true, y_pred):
        return custom_objective_asym(y_true, y_pred, penalty_under, penalty_over)
    
    xgb_model = xgb.XGBRegressor(objective=asym_obj, n_estimators=100)
    xgb_model.fit(X_train, y_residual)
    
    # Step 4: Predict on test — use Prophet yhat as y proxy (no leakage)
    test_forecast = prophet_model.predict(df_test[['ds']])
    prophet_yhat = test_forecast['yhat'].values
    
    # Feature engineering with Prophet predictions as proxy for unknown future y
    _, df_te_feat = feature_engineering_no_leak(df_train, df_test, y_proxy_test=prophet_yhat)
    
    residual_pred = xgb_model.predict(df_te_feat[FEATURES])
    final_pred = prophet_yhat + residual_pred
    final_pred = np.maximum(final_pred, 0)
    
    return final_pred


def train_predict_hybrid_no_asym(df_train, df_test):
    """Model D: Hybrid WITHOUT asymmetric loss (ablation study)"""
    return train_predict_hybrid(df_train, df_test, penalty_under=1.0, penalty_over=1.0)


# ═══════════════════════════════════════════════════════════════
#  3. EVALUATION METRICS
# ═══════════════════════════════════════════════════════════════

def compute_metrics(y_true, y_pred):
    """Compute standard forecasting metrics"""
    y_true = np.array(y_true, dtype=float)
    y_pred = np.array(y_pred, dtype=float)
    
    mae = mean_absolute_error(y_true, y_pred)
    rmse = np.sqrt(mean_squared_error(y_true, y_pred))
    
    # MAPE (avoid division by zero)
    mask = y_true != 0
    if mask.sum() > 0:
        mape = np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])) * 100
    else:
        mape = np.nan
    
    # Directional Accuracy (does the model predict up/down correctly?)
    if len(y_true) > 1:
        true_dir = np.diff(y_true) > 0
        pred_dir = np.diff(y_pred) > 0
        dir_acc = np.mean(true_dir == pred_dir) * 100
    else:
        dir_acc = np.nan
    
    # Under-forecast ratio (important for inventory DSS)
    under_forecast_pct = np.mean(y_pred < y_true) * 100
    
    return {
        'MAE': round(mae, 4),
        'RMSE': round(rmse, 4),
        'MAPE': round(mape, 2) if not np.isnan(mape) else None,
        'Dir_Accuracy': round(dir_acc, 2) if not np.isnan(dir_acc) else None,
        'Under_Forecast_Pct': round(under_forecast_pct, 1),
    }


# ═══════════════════════════════════════════════════════════════
#  4. SELECT REPRESENTATIVE PRODUCTS
# ═══════════════════════════════════════════════════════════════

def select_products(df_clean, top_n=5, min_days=14):
    """
    Select top N products that are suitable for time series forecasting.
    Prioritizes products with HIGH DAILY SALES FREQUENCY — not just total count.
    Products with sparse daily sales (mostly zeros) are poor forecasting candidates.
    """
    stats = df_clean.groupby('product_id').agg(
        days_active=('order_purchase_timestamp', lambda x: x.dt.date.nunique()),
        total_qty=('quantity', 'sum'),
        total_orders=('quantity', 'count'),
        date_min=('order_purchase_timestamp', 'min'),
        date_max=('order_purchase_timestamp', 'max'),
    )
    
    # Calculate date span and sales density
    stats['date_span'] = (stats['date_max'] - stats['date_min']).dt.days + 1
    stats['sales_density'] = stats['days_active'] / stats['date_span']  # % of days with sales
    stats['avg_daily_qty'] = stats['total_qty'] / stats['date_span']
    
    # Filter: at least min_days active AND reasonable density
    # Density > 0.15 means product sells on at least 15% of days
    # avg_daily_qty > 1 means at least 1 unit per day on average
    valid = stats[
        (stats['days_active'] >= min_days) & 
        (stats['avg_daily_qty'] >= 1.0) &
        (stats['sales_density'] >= 0.15)
    ]
    
    if valid.empty:
        # Relax: just require min_days and some volume
        valid = stats[
            (stats['days_active'] >= min_days) & 
            (stats['avg_daily_qty'] >= 0.3)
        ]
    
    if valid.empty:
        valid = stats[stats['days_active'] >= 7]
    
    # Sort by avg_daily_qty (prefer products with consistent daily sales)
    top = valid.sort_values('avg_daily_qty', ascending=False).head(top_n)
    
    # Print selection info
    for pid, row in top.iterrows():
        print(f"    → {str(pid)[:25]:25s}  avg={row['avg_daily_qty']:.1f}/day  density={row['sales_density']:.0%}  span={int(row['date_span'])}d")
    
    return top.index.tolist()


# ═══════════════════════════════════════════════════════════════
#  5. MAIN BENCHMARK LOOP
# ═══════════════════════════════════════════════════════════════

def run_benchmark():
    print("=" * 70)
    print("  THESIS BENCHMARK — Model Comparison")
    print("  Prophet vs XGBoost vs Hybrid vs Hybrid (no asymmetric loss)")
    print("=" * 70)
    print()
    
    # ── Load datasets ──
    print("📂 Loading datasets...")
    datasets = load_datasets()
    
    if not datasets:
        print("\n❌ No datasets found! Please organize your data files.")
        print("   Expected structure:")
        print("   data/india/List_of_Orders.csv + Order_Details.csv")
        print("   data/uk/OnlineRetail.csv")
        print("   data/electronics/Sales_Data.csv")
        print("   data/olist/olist_orders_dataset.csv + olist_order_items_dataset.csv")
        return
    
    print(f"\n📊 Found {len(datasets)} dataset(s)\n")
    
    # ── Models to compare ──
    models = {
        'Prophet-Only': train_predict_prophet_only,
        'XGBoost-Only': train_predict_xgboost_only,
        'Hybrid':       train_predict_hybrid,
        'Hybrid (no asym.)': train_predict_hybrid_no_asym,
    }
    
    all_results = []
    
    # ── Iterate datasets ──
    for ds_name, df_clean in datasets.items():
        print(f"\n{'─' * 60}")
        print(f"  Dataset: {ds_name}")
        print(f"{'─' * 60}")
        if df_clean is None or len(df_clean) == 0:
            print(f"  ⚠️ Skipping {ds_name}: empty after preprocessing")
            continue
        products = select_products(df_clean, top_n=5)
        print(f"  Selected {len(products)} products: {products[:3]}{'...' if len(products) > 3 else ''}")
        
        for pid in products:
            df_product = df_clean[df_clean['product_id'] == pid].copy()
            
            # Prepare time series
            df_product['ds'] = df_product['order_purchase_timestamp']
            df_product['y'] = df_product['quantity']
            df_daily = df_product.groupby('ds')['y'].sum().reset_index().sort_values('ds')
            
            # ── CRITICAL: Fill missing dates with 0 ──
            # Without this, rolling features have gaps and Prophet/XGBoost misalign
            full_date_range = pd.date_range(start=df_daily['ds'].min(), end=df_daily['ds'].max(), freq='D')
            df_daily = df_daily.set_index('ds').reindex(full_date_range, fill_value=0).reset_index()
            df_daily.columns = ['ds', 'y']
            
            if len(df_daily) < 21:
                print(f"    ⚠️ {pid}: Only {len(df_daily)} days, skipping")
                continue
            
            # ── Time-based train/test split (80/20) ──
            split_idx = int(len(df_daily) * 0.8)
            df_train = df_daily.iloc[:split_idx].copy().reset_index(drop=True)
            df_test = df_daily.iloc[split_idx:].copy().reset_index(drop=True)
            
            if len(df_test) < 5:
                print(f"    ⚠️ {pid}: Test set too small ({len(df_test)} rows), skipping")
                continue
            
            y_true = df_test['y'].values
            product_label = str(pid)[:30]
            
            print(f"\n    🏷️  {product_label}")
            print(f"       Train: {len(df_train)} days | Test: {len(df_test)} days | Total: {len(df_daily)} days")
            
            # ── Run each model ──
            for model_name, model_fn in models.items():
                try:
                    preds = model_fn(df_train, df_test)
                    
                    # Align lengths (some models may return different lengths)
                    min_len = min(len(y_true), len(preds))
                    metrics = compute_metrics(y_true[:min_len], preds[:min_len])
                    
                    all_results.append({
                        'Dataset': ds_name,
                        'Product': product_label,
                        'Model': model_name,
                        'Train_Days': len(df_train),
                        'Test_Days': len(df_test),
                        **metrics
                    })
                    
                    status = f"MAE={metrics['MAE']:.2f}  RMSE={metrics['RMSE']:.2f}  MAPE={metrics['MAPE']}%"
                    print(f"       {model_name:22s} → {status}")
                    
                except Exception as e:
                    import traceback
                    print(f"       {model_name:22s} → ❌ Error: {str(e)[:80]}")
                    traceback.print_exc()
                    all_results.append({
                        'Dataset': ds_name,
                        'Product': product_label,
                        'Model': model_name,
                        'Train_Days': len(df_train),
                        'Test_Days': len(df_test),
                        'MAE': None, 'RMSE': None, 'MAPE': None,
                        'Dir_Accuracy': None, 'Under_Forecast_Pct': None
                    })
    
    # ═══════════════════════════════════════════════════════════
    #  6. SAVE RESULTS & GENERATE REPORT
    # ═══════════════════════════════════════════════════════════
    
    if not all_results:
        print("\n❌ No results generated. Check your data paths.")
        return
    
    df_results = pd.DataFrame(all_results)
    
    # ── Save raw results ──
    os.makedirs('benchmark_output', exist_ok=True)
    df_results.to_csv('benchmark_output/benchmark_results.csv', index=False)
    print(f"\n\n💾 Raw results saved: benchmark_output/benchmark_results.csv")
    
    # ── Aggregated summary per dataset × model ──
    numeric_cols = ['MAE', 'RMSE', 'MAPE', 'Dir_Accuracy', 'Under_Forecast_Pct']
    summary = df_results.groupby(['Dataset', 'Model'])[numeric_cols].mean().round(2)
    summary.to_csv('benchmark_output/benchmark_summary.csv')
    print(f"💾 Summary saved: benchmark_output/benchmark_summary.csv")
    
    # ── Text report ──
    report_lines = []
    report_lines.append("=" * 75)
    report_lines.append("  BENCHMARK RESULTS — Model Comparison for Thesis")
    report_lines.append(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    report_lines.append("=" * 75)
    
    for ds_name in df_results['Dataset'].unique():
        ds_data = df_results[df_results['Dataset'] == ds_name]
        report_lines.append(f"\n\n{'━' * 75}")
        report_lines.append(f"  DATASET: {ds_name}")
        report_lines.append(f"  Products tested: {ds_data['Product'].nunique()}")
        report_lines.append(f"{'━' * 75}")
        
        # Per-model summary
        model_summary = ds_data.groupby('Model')[numeric_cols].agg(['mean', 'std']).round(2)
        
        report_lines.append(f"\n  {'Model':<24s} {'MAE':>10s} {'RMSE':>10s} {'MAPE(%)':>10s} {'DirAcc(%)':>10s} {'UnderF(%)':>10s}")
        report_lines.append(f"  {'─' * 74}")
        
        for model_name in ['Prophet-Only', 'XGBoost-Only', 'Hybrid', 'Hybrid (no asym.)']:
            if model_name in ds_data['Model'].values:
                row = ds_data[ds_data['Model'] == model_name][numeric_cols].mean()
                mae = f"{row['MAE']:.2f}" if pd.notna(row['MAE']) else "N/A"
                rmse = f"{row['RMSE']:.2f}" if pd.notna(row['RMSE']) else "N/A"
                mape = f"{row['MAPE']:.1f}" if pd.notna(row['MAPE']) else "N/A"
                da = f"{row['Dir_Accuracy']:.1f}" if pd.notna(row['Dir_Accuracy']) else "N/A"
                uf = f"{row['Under_Forecast_Pct']:.1f}" if pd.notna(row['Under_Forecast_Pct']) else "N/A"
                
                # Mark best model
                best_mae = ds_data.groupby('Model')['MAE'].mean().idxmin()
                marker = " ★" if model_name == best_mae else ""
                
                report_lines.append(f"  {model_name:<24s} {mae:>10s} {rmse:>10s} {mape:>10s} {da:>10s} {uf:>10s}{marker}")
        
        # Per-product detail
        report_lines.append(f"\n  Detail per product:")
        for pid in ds_data['Product'].unique():
            report_lines.append(f"\n    Product: {pid}")
            pid_data = ds_data[ds_data['Product'] == pid]
            for _, row in pid_data.iterrows():
                mae = f"{row['MAE']:.2f}" if pd.notna(row['MAE']) else "ERR"
                rmse = f"{row['RMSE']:.2f}" if pd.notna(row['RMSE']) else "ERR"
                mape = f"{row['MAPE']:.1f}%" if pd.notna(row['MAPE']) else "ERR"
                report_lines.append(f"      {row['Model']:<24s} MAE={mae:>8s}  RMSE={rmse:>8s}  MAPE={mape:>8s}")
    
    # ── Overall winner ──
    report_lines.append(f"\n\n{'=' * 75}")
    report_lines.append("  OVERALL COMPARISON (averaged across all datasets & products)")
    report_lines.append(f"{'=' * 75}")
    
    overall = df_results.groupby('Model')[numeric_cols].mean().round(2)
    report_lines.append(f"\n  {'Model':<24s} {'MAE':>10s} {'RMSE':>10s} {'MAPE(%)':>10s} {'UnderF(%)':>10s}")
    report_lines.append(f"  {'─' * 64}")
    
    for model_name in ['Prophet-Only', 'XGBoost-Only', 'Hybrid', 'Hybrid (no asym.)']:
        if model_name in overall.index:
            row = overall.loc[model_name]
            best_overall = overall['MAE'].idxmin()
            marker = " ★ BEST" if model_name == best_overall else ""
            report_lines.append(
                f"  {model_name:<24s} {row['MAE']:>10.2f} {row['RMSE']:>10.2f} "
                f"{row['MAPE']:>10.1f} {row['Under_Forecast_Pct']:>10.1f}{marker}"
            )
    
    # Improvement calculation
    if 'Prophet-Only' in overall.index and 'Hybrid' in overall.index:
        prophet_mae = overall.loc['Prophet-Only', 'MAE']
        hybrid_mae = overall.loc['Hybrid', 'MAE']
        if prophet_mae > 0:
            improvement = ((prophet_mae - hybrid_mae) / prophet_mae) * 100
            report_lines.append(f"\n  📈 Hybrid improvement over Prophet-Only: {improvement:.1f}% (MAE)")
    
    if 'XGBoost-Only' in overall.index and 'Hybrid' in overall.index:
        xgb_mae = overall.loc['XGBoost-Only', 'MAE']
        hybrid_mae = overall.loc['Hybrid', 'MAE']
        if xgb_mae > 0:
            improvement = ((xgb_mae - hybrid_mae) / xgb_mae) * 100
            report_lines.append(f"  📈 Hybrid improvement over XGBoost-Only: {improvement:.1f}% (MAE)")
    
    if 'Hybrid (no asym.)' in overall.index and 'Hybrid' in overall.index:
        no_asym_uf = overall.loc['Hybrid (no asym.)', 'Under_Forecast_Pct']
        asym_uf = overall.loc['Hybrid', 'Under_Forecast_Pct']
        report_lines.append(f"  📈 Asymmetric loss reduces under-forecasting: {no_asym_uf:.1f}% → {asym_uf:.1f}%")
    
    report_text = '\n'.join(report_lines)
    
    with open('benchmark_output/benchmark_report.txt', 'w') as f:
        f.write(report_text)
    print(f"💾 Report saved: benchmark_output/benchmark_report.txt")
    
    # Print report to console
    print(f"\n{report_text}")
    
    # ── Generate charts ──
    try:
        generate_charts(df_results)
    except Exception as e:
        print(f"\n⚠️ Chart generation failed: {e}")
        print("   Install matplotlib: pip install matplotlib")
    
    print("\n✅ Benchmark complete!")


# ═══════════════════════════════════════════════════════════════
#  7. CHART GENERATION
# ═══════════════════════════════════════════════════════════════

def generate_charts(df_results):
    """Generate comparison bar charts for thesis"""
    import matplotlib.pyplot as plt
    import matplotlib
    matplotlib.use('Agg')
    
    os.makedirs('benchmark_output/charts', exist_ok=True)
    
    colors = {
        'Prophet-Only': '#94A3B8',
        'XGBoost-Only': '#F59E0B', 
        'Hybrid': '#3B82F6',
        'Hybrid (no asym.)': '#A78BFA',
    }
    
    # ── Chart 1: Overall MAE comparison ──
    fig, axes = plt.subplots(1, 3, figsize=(16, 5))
    fig.suptitle('Model Comparison Across Datasets', fontsize=14, fontweight='bold', y=1.02)
    
    for idx, metric in enumerate(['MAE', 'RMSE', 'MAPE']):
        ax = axes[idx]
        pivot = df_results.groupby(['Dataset', 'Model'])[metric].mean().unstack('Model')
        
        if pivot.empty:
            continue
        
        model_order = [m for m in ['Prophet-Only', 'XGBoost-Only', 'Hybrid', 'Hybrid (no asym.)'] if m in pivot.columns]
        pivot = pivot[model_order]
        
        pivot.plot(kind='bar', ax=ax, color=[colors[m] for m in model_order], edgecolor='white', linewidth=0.5)
        ax.set_title(metric, fontsize=12, fontweight='bold')
        ax.set_xlabel('')
        ax.set_ylabel(metric)
        ax.legend(fontsize=8, loc='upper right')
        ax.tick_params(axis='x', rotation=30)
        ax.grid(axis='y', alpha=0.3)
    
    plt.tight_layout()
    plt.savefig('benchmark_output/charts/overall_comparison.png', dpi=200, bbox_inches='tight')
    plt.close()
    print(f"📊 Chart saved: benchmark_output/charts/overall_comparison.png")
    
    # ── Chart 2: Per-dataset detailed ──
    for ds_name in df_results['Dataset'].unique():
        ds_data = df_results[df_results['Dataset'] == ds_name]
        
        fig, ax = plt.subplots(figsize=(10, 5))
        
        products = ds_data['Product'].unique()
        x = np.arange(len(products))
        width = 0.2
        
        model_order = [m for m in ['Prophet-Only', 'XGBoost-Only', 'Hybrid', 'Hybrid (no asym.)'] 
                       if m in ds_data['Model'].values]
        
        for i, model_name in enumerate(model_order):
            model_data = ds_data[ds_data['Model'] == model_name]
            maes = [model_data[model_data['Product'] == p]['MAE'].values[0] 
                    if p in model_data['Product'].values else 0 
                    for p in products]
            ax.bar(x + i * width, maes, width, label=model_name, 
                   color=colors.get(model_name, '#999'), edgecolor='white', linewidth=0.5)
        
        ax.set_title(f'{ds_name} — MAE per Product', fontsize=12, fontweight='bold')
        ax.set_xticks(x + width * 1.5)
        ax.set_xticklabels([str(p)[:20] for p in products], rotation=30, ha='right', fontsize=9)
        ax.set_ylabel('MAE (lower is better)')
        ax.legend(fontsize=9)
        ax.grid(axis='y', alpha=0.3)
        
        plt.tight_layout()
        safe_name = ds_name.replace(' ', '_').lower()
        plt.savefig(f'benchmark_output/charts/{safe_name}_detail.png', dpi=200, bbox_inches='tight')
        plt.close()
        print(f"📊 Chart saved: benchmark_output/charts/{safe_name}_detail.png")
    
    # ── Chart 3: Ablation — Under-forecast comparison ──
    fig, ax = plt.subplots(figsize=(8, 5))
    
    ablation_data = df_results[df_results['Model'].isin(['Hybrid', 'Hybrid (no asym.)'])]
    if not ablation_data.empty:
        pivot = ablation_data.groupby(['Dataset', 'Model'])['Under_Forecast_Pct'].mean().unstack('Model')
        pivot.plot(kind='bar', ax=ax, color=['#3B82F6', '#A78BFA'], edgecolor='white')
        ax.set_title('Ablation: Asymmetric Loss Effect on Under-Forecasting', fontsize=12, fontweight='bold')
        ax.set_ylabel('Under-Forecast Rate (%)\n(lower = model over-predicts more = safer for inventory)')
        ax.set_xlabel('')
        ax.tick_params(axis='x', rotation=30)
        ax.legend(fontsize=10)
        ax.grid(axis='y', alpha=0.3)
    
    plt.tight_layout()
    plt.savefig('benchmark_output/charts/ablation_asymmetric_loss.png', dpi=200, bbox_inches='tight')
    plt.close()
    print(f"📊 Chart saved: benchmark_output/charts/ablation_asymmetric_loss.png")


# ═══════════════════════════════════════════════════════════════
#  RUN
# ═══════════════════════════════════════════════════════════════

if __name__ == '__main__':
    run_benchmark()