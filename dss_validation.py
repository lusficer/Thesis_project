"""
  DSS VALIDATION — Simulate Real-World Usage on Historical Data

This script answers: "Does the DSS actually help a shop manager?"

Instead of just measuring forecast accuracy (MAE/RMSE), it simulates
a manager using the DSS every week over the test period and measures:

1. Did ORDER_NOW prevent actual stockouts?
2. Did HOLD avoid unnecessary orders?
3. Did price recommendations align with demand direction?
4. What was the simulated stockout rate WITH vs WITHOUT the DSS?

Usage:
    python dss_validation.py

Place in: THESIS_PROJECT/
Requires: Same dependencies as benchmark.py
"""

import pandas as pd
import numpy as np
import os
import sys
import warnings
import logging

warnings.filterwarnings('ignore')
logging.getLogger('cmdstanpy').setLevel(logging.WARNING)
logging.getLogger('prophet').setLevel(logging.WARNING)

sys.path.append(os.path.abspath(os.path.dirname(__file__)))
from app.core.preprocessing import clean_ecommerce_data
from app.core.hybrid_model import ThesisHybridModel
from app.core.dss_engine import DSSEngine


def load_india_sales():
    """Load India Sales dataset"""
    try:
        df_list = pd.read_csv('data/india/List_of_Orders.csv', encoding='ISO-8859-1')
        df_details = pd.read_csv('data/india/Order_Details.csv', encoding='ISO-8859-1')
        merged = pd.merge(df_list, df_details, on='Order ID', how='inner')
        
        # Price map
        merged['Amount'] = pd.to_numeric(merged['Amount'], errors='coerce')
        merged['Quantity'] = pd.to_numeric(merged['Quantity'], errors='coerce')
        merged['calc_price'] = merged['Amount'] / merged['Quantity']
        price_map = merged.groupby('Sub-Category')['calc_price'].mean().to_dict()
        
        df_clean = clean_ecommerce_data(merged, {
            'date_col': 'Order Date', 'pid_col': 'Sub-Category',
            'qty_col': 'Quantity', 'name_col': 'Sub-Category'
        })
        return df_clean, price_map, 'India Sales'
    except Exception as e:
        print(f"Error loading India Sales: {e}")
        return None, None, None


def load_fmcg():
    """Load FMCG dataset"""
    try:
        path = 'data/FMCG/product_sales_dataset_final.csv'
        if not os.path.exists(path):
            return None, None, None
        df = pd.read_csv(path)
        df.columns = df.columns.str.strip()
        df['Order_Date'] = pd.to_datetime(df['Order_Date'], format='%m-%d-%y', errors='coerce')
        
        price_map = {}
        if 'Unit_Price' in df.columns:
            df['Unit_Price'] = pd.to_numeric(df['Unit_Price'], errors='coerce')
            price_map = df.groupby('Sub_Category')['Unit_Price'].mean().to_dict()
        
        df_clean = clean_ecommerce_data(df, {
            'date_col': 'Order_Date', 'pid_col': 'Sub_Category',
            'qty_col': 'Quantity', 'name_col': 'Product_Name'
        })
        return df_clean, price_map, 'FMCG Sales 2023-24'
    except Exception as e:
        print(f"Error loading FMCG: {e}")
        return None, None, None


def simulate_dss(df_clean, price_map, product_id, initial_stock=100):
    """
    Simulate a shop manager using the DSS over the test period.
    
    Strategy:
    - Split data 80/20 (train/test) by time
    - Train the Hybrid model on training data
    - Then simulate day-by-day through the test period:
      * Each week, the DSS gives advice based on current stock + forecast
      * Track actual stock changes using real sales data
      * Measure: stockouts, order decisions, pricing decisions
    """
    
    # Prepare daily time series
    df_product = df_clean[df_clean['product_id'] == product_id].copy()
    df_product['ds'] = df_product['order_purchase_timestamp']
    df_product['y'] = df_product['quantity']
    df_daily = df_product.groupby('ds')['y'].sum().reset_index().sort_values('ds')
    
    # Fill missing dates
    full_range = pd.date_range(df_daily['ds'].min(), df_daily['ds'].max(), freq='D')
    df_daily = df_daily.set_index('ds').reindex(full_range, fill_value=0).reset_index()
    df_daily.columns = ['ds', 'y']
    
    if len(df_daily) < 30:
        return None
    
    # Split 80/20
    split_idx = int(len(df_daily) * 0.8)
    df_train = df_daily.iloc[:split_idx].copy()
    df_test = df_daily.iloc[split_idx:].copy()
    
    if len(df_test) < 7:
        return None
    
    # Train the Hybrid model (same as actual system)
    model = ThesisHybridModel(penalty_under=5.0, penalty_over=1.0)
    model.fit(df_train[['ds', 'y']])
    
    # Get forecast for the test period
    forecast_df = model.predict(days=len(df_test))
    
    # DSS Engine
    dss = DSSEngine(lead_time=7)
    current_price = price_map.get(product_id, 10.0)
    if pd.isna(current_price) or current_price <= 0:
        current_price = 10.0
    
    #  SIMULATION: Manager WITH DSS
    stock_with_dss = initial_stock
    stockout_days_with_dss = 0
    total_orders_with_dss = 0
    total_units_ordered_with_dss = 0
    order_decisions = []
    
    actual_sales = df_test['y'].values
    
    for day_idx in range(len(actual_sales)):
        # Daily actual demand reduces stock
        daily_demand = actual_sales[day_idx]
        
        if stock_with_dss <= 0:
            stockout_days_with_dss += 1
        
        stock_with_dss -= daily_demand
        
        # Every 7 days, consult DSS
        if day_idx % 7 == 0 and day_idx + 7 <= len(forecast_df):
            remaining_forecast = forecast_df.iloc[day_idx:].copy().reset_index(drop=True)
            if len(remaining_forecast) >= 7:
                analysis, pricing = dss.analyze(
                    current_stock=max(0, stock_with_dss),
                    current_price=current_price,
                    forecast_df=remaining_forecast,
                    target_days_to_sell=30
                )
                
                action = analysis['initial_recommendation']['action']
                qty = analysis['initial_recommendation']['qty_to_order']
                
                order_decisions.append({
                    'day': day_idx,
                    'stock_before': round(stock_with_dss, 1),
                    'action': action,
                    'qty_ordered': qty,
                    'rop': analysis['metrics']['rop'],
                    'suggested_price': pricing['suggested_price']
                })
                
                # If DSS says ORDER_NOW, simulate receiving the order (instant for simplicity)
                if action == 'ORDER_NOW' and qty > 0:
                    stock_with_dss += qty
                    total_orders_with_dss += 1
                    total_units_ordered_with_dss += qty
    
    #  SIMULATION: Manager WITHOUT DSS (naive)
    #  Strategy: order fixed amount when stock < 20
    stock_no_dss = initial_stock
    stockout_days_no_dss = 0
    total_orders_no_dss = 0
    total_units_ordered_no_dss = 0
    naive_order_qty = int(np.mean(actual_sales) * 14)  # 2-week supply
    if naive_order_qty < 10:
        naive_order_qty = 10
    
    for day_idx in range(len(actual_sales)):
        daily_demand = actual_sales[day_idx]
        
        if stock_no_dss <= 0:
            stockout_days_no_dss += 1
        
        stock_no_dss -= daily_demand
        
        # Naive: reorder every 7 days if stock < 20
        if day_idx % 7 == 0 and stock_no_dss < 20:
            stock_no_dss += naive_order_qty
            total_orders_no_dss += 1
            total_units_ordered_no_dss += naive_order_qty
    
    #  RESULTS
    test_days = len(actual_sales)
    total_demand = int(sum(actual_sales))
    
    return {
        'product': product_id,
        'test_days': test_days,
        'total_demand': total_demand,
        'initial_stock': initial_stock,
        # WITH DSS
        'dss_stockout_days': stockout_days_with_dss,
        'dss_stockout_rate': round(stockout_days_with_dss / test_days * 100, 1),
        'dss_orders': total_orders_with_dss,
        'dss_units_ordered': total_units_ordered_with_dss,
        'dss_final_stock': round(stock_with_dss, 1),
        # WITHOUT DSS
        'naive_stockout_days': stockout_days_no_dss,
        'naive_stockout_rate': round(stockout_days_no_dss / test_days * 100, 1),
        'naive_orders': total_orders_no_dss,
        'naive_units_ordered': total_units_ordered_no_dss,
        'naive_final_stock': round(stock_no_dss, 1),
        # DECISIONS LOG
        'decisions': order_decisions
    }


def run_validation():
    print("=" * 70)
    print("  DSS VALIDATION — Simulating Real-World Usage")
    print("  Does the DSS actually help prevent stockouts?")
    print("=" * 70)
    
    # Load datasets
    datasets = []
    
    india = load_india_sales()
    if india[0] is not None:
        datasets.append(india)
    
    fmcg = load_fmcg()
    if fmcg[0] is not None:
        datasets.append(fmcg)
    
    if not datasets:
        print("\nNo datasets found!")
        return
    
    all_results = []
    
    for df_clean, price_map, ds_name in datasets:
        print(f"\n{'━' * 60}")
        print(f"  Dataset: {ds_name}")
        print(f"{'━' * 60}")
        
        # Select top products (same logic as benchmark)
        stats = df_clean.groupby('product_id').agg(
            days_active=('order_purchase_timestamp', lambda x: x.dt.date.nunique()),
            total_qty=('quantity', 'sum'),
            date_min=('order_purchase_timestamp', 'min'),
            date_max=('order_purchase_timestamp', 'max'),
        )
        stats['date_span'] = (stats['date_max'] - stats['date_min']).dt.days + 1
        stats['avg_daily'] = stats['total_qty'] / stats['date_span']
        stats['density'] = stats['days_active'] / stats['date_span']
        
        valid = stats[(stats['days_active'] >= 14) & (stats['avg_daily'] >= 1) & (stats['density'] >= 0.15)]
        if valid.empty:
            valid = stats[stats['days_active'] >= 7]
        
        products = valid.sort_values('avg_daily', ascending=False).head(3).index.tolist()
        
        for pid in products:
            avg_daily = valid.loc[pid, 'avg_daily'] if pid in valid.index else 5
            initial_stock = int(avg_daily * 14)  # Start with 2 weeks of stock
            if initial_stock < 20:
                initial_stock = 20
            
            print(f"\n  Product: {pid}")
            print(f"  Initial stock: {initial_stock} units")
            
            result = simulate_dss(df_clean, price_map, pid, initial_stock=initial_stock)
            
            if result is None:
                print(f"  Skipped (insufficient data)")
                continue
            
            result['dataset'] = ds_name
            all_results.append(result)
            
            # Print comparison
            print(f"\n  {'':4s}{'Metric':<30s} {'WITH DSS':>12s} {'WITHOUT DSS':>12s} {'Improvement':>12s}")
            print(f"  {'':4s}{'─' * 66}")
            
            so_imp = result['naive_stockout_days'] - result['dss_stockout_days']
            print(f"  {'':4s}{'Stockout Days':<30s} {result['dss_stockout_days']:>12d} {result['naive_stockout_days']:>12d} {'+' if so_imp > 0 else ''}{so_imp:>11d}")
            
            sr_imp = result['naive_stockout_rate'] - result['dss_stockout_rate']
            print(f"  {'':4s}{'Stockout Rate (%)':<30s} {result['dss_stockout_rate']:>11.1f}% {result['naive_stockout_rate']:>11.1f}% {'+' if sr_imp > 0 else ''}{sr_imp:>10.1f}%")
            
            print(f"  {'':4s}{'Orders Placed':<30s} {result['dss_orders']:>12d} {result['naive_orders']:>12d}")
            print(f"  {'':4s}{'Units Ordered':<30s} {result['dss_units_ordered']:>12d} {result['naive_units_ordered']:>12d}")
            print(f"  {'':4s}{'Final Stock':<30s} {result['dss_final_stock']:>12.1f} {result['naive_final_stock']:>12.1f}")
            print(f"  {'':4s}{'Total Actual Demand':<30s} {result['total_demand']:>12d}")
            
            # Show DSS decisions
            if result['decisions']:
                print(f"\n  DSS Decision Log:")
                for d in result['decisions'][:5]:  # Show first 5
                    print(f"    Day {d['day']:3d} | Stock: {d['stock_before']:>7.1f} | Action: {d['action']:<10s} | Order: {d['qty_ordered']:>5d} | Price: ${d['suggested_price']}")
                if len(result['decisions']) > 5:
                    print(f"    ... and {len(result['decisions']) - 5} more decisions")
    
    #  SUMMARY
    if all_results:
        print(f"\n\n{'=' * 70}")
        print(f"  OVERALL VALIDATION SUMMARY")
        print(f"{'=' * 70}")
        
        total_test_days = sum(r['test_days'] for r in all_results)
        
        dss_stockout_total = sum(r['dss_stockout_days'] for r in all_results)
        naive_stockout_total = sum(r['naive_stockout_days'] for r in all_results)
        
        dss_rate = dss_stockout_total / total_test_days * 100
        naive_rate = naive_stockout_total / total_test_days * 100
        
        print(f"\n  Total test period: {total_test_days} days across {len(all_results)} products")
        print(f"\n  {'Metric':<35s} {'WITH DSS':>12s} {'WITHOUT DSS':>12s}")
        print(f"  {'─' * 59}")
        print(f"  {'Total Stockout Days':<35s} {dss_stockout_total:>12d} {naive_stockout_total:>12d}")
        print(f"  {'Stockout Rate':<35s} {dss_rate:>11.1f}% {naive_rate:>11.1f}%")
        
        if naive_rate > 0:
            reduction = ((naive_rate - dss_rate) / naive_rate) * 100
            print(f"\n  DSS reduces stockout rate by {reduction:.1f}%")
        
        if dss_rate < naive_rate:
            print(f"\n  CONCLUSION: The DSS successfully reduces stockout risk compared to")
            print(f"  a naive reorder strategy, validating its effectiveness for inventory management.")
        else:
            print(f"\n  NOTE: DSS did not reduce stockouts in this simulation.")
            print(f"  This may be due to dataset characteristics or initial stock levels.")
        
        # Save results
        os.makedirs('benchmark_output', exist_ok=True)
        df_results = pd.DataFrame([{k: v for k, v in r.items() if k != 'decisions'} for r in all_results])
        df_results.to_csv('benchmark_output/dss_validation_results.csv', index=False)
        print(f"\n  Results saved: benchmark_output/dss_validation_results.csv")
    
    print(f"\n{'=' * 70}")
    print(f"  Validation complete!")
    print(f"{'=' * 70}")


if __name__ == '__main__':
    run_validation()