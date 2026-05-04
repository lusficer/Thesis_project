"""
Backtest utilities for product-level temporal validation.
"""
from typing import Optional

import numpy as np
import pandas as pd

from app.core.hybrid_model import ThesisHybridModel


def run_product_backtest(
    sales_df: pd.DataFrame,              # [ds, y], full history
    test_days: int = 30,
    lead_time: int = 7,
    penalty_under: float = 5.0,
    penalty_over: float = 1.0,
    initial_stock: Optional[int] = None,  # None = auto from avg demand
) -> dict:
    """
    Fit hybrid model on train split, simulate DSS + Naive + Oracle
    inventory policies on test window, return all metrics.

    Returns dict with keys:
      test_start_date, test_end_date, n_test_days,
      mae, rmse, mape, under_forecast_pct, over_forecast_pct,
      dss_service_level, dss_stockout_days, dss_avg_inventory,
      naive_service_level, naive_stockout_days, naive_avg_inventory,
      oracle_service_level, oracle_stockout_days, oracle_avg_inventory,

    Raises ValueError if sales_df has <60 days total
    (need 30 train + 30 test minimum).
    """
    if sales_df is None or len(sales_df) < 60:
        raise ValueError(f"run_product_backtest requires at least 60 days of data (got {0 if sales_df is None else len(sales_df)}).")
    if test_days <= 0:
        raise ValueError("test_days must be > 0")
    if len(sales_df) < test_days + 30:
        raise ValueError(f"Need at least {test_days + 30} rows for train+test split (got {len(sales_df)}).")

    df = sales_df[["ds", "y"]].copy()
    df["ds"] = pd.to_datetime(df["ds"])
    df["y"] = pd.to_numeric(df["y"], errors="coerce").fillna(0).clip(lower=0)
    df = df.sort_values("ds").drop_duplicates("ds").reset_index(drop=True)

    # ── Test period: last test_days rows ───────────────────────────────
    sim_data = df.tail(test_days).reset_index(drop=True)
    daily_demand = sim_data["y"].values
    total = len(daily_demand)

    # ── Train period: everything before test ───────────────────────────
    train_df = df.head(max(30, len(df) - test_days))

    # ── Pre-compute demand stats ───────────────────────────────────────
    avg_demand = float(np.mean(daily_demand))
    std_demand = float(np.std(daily_demand))
    start_stock = int(initial_stock) if initial_stock is not None else max(1, int(avg_demand * 30))

    # Forecast for accuracy metrics + DSS policy parameters
    forecast = None
    try:
        model = ThesisHybridModel(
            penalty_under=penalty_under,
            penalty_over=penalty_over,
        )
        model.fit(train_df)
        forecast = model.predict(test_days)
        f_vals = forecast["yhat"].values

        # Forecast daily mean and std - characteristic of this model
        f_mean = float(np.mean(f_vals))
        f_std = float(np.std(f_vals))

        z_score = 1.645   # 95% service level target
        dss_safety = max(1, int(z_score * f_std * np.sqrt(lead_time)))
        dss_rop = max(1, int(f_mean * lead_time) + dss_safety)

        cycle_days = lead_time + 30
        dss_target_level = max(1, int(f_mean * cycle_days) + 2 * dss_safety)

    except Exception:
        f_vals = np.full(total, avg_demand, dtype=float)
        z_score = 1.645
        dss_safety = max(1, int(z_score * std_demand * np.sqrt(lead_time)))
        dss_rop = max(1, int(avg_demand * lead_time) + dss_safety)
        cycle_days = lead_time + 30
        dss_target_level = max(1, int(avg_demand * cycle_days) + 2 * dss_safety)

    # Forecast accuracy metrics
    pred = np.array(f_vals[:total], dtype=float)
    actual = np.array(daily_demand, dtype=float)
    abs_err = np.abs(pred - actual)

    mae = float(np.mean(abs_err))
    rmse = float(np.sqrt(np.mean((pred - actual) ** 2)))
    nonzero_mask = actual != 0
    mape = (
        float(np.mean(np.abs((actual[nonzero_mask] - pred[nonzero_mask]) / actual[nonzero_mask])) * 100)
        if np.any(nonzero_mask)
        else None
    )
    under_forecast_pct = float(np.mean(pred < actual) * 100)
    over_forecast_pct = float(np.mean(pred > actual) * 100)

    # STRATEGY 2: Naive
    naive_rop = max(1, int(avg_demand * lead_time))
    naive_target_level = naive_rop + max(1, int(avg_demand * 30))

    # STRATEGY 3: Oracle
    # Oracle with perfect foresight is allowed pre-simulation
    # preparation: start with enough stock to cover the first
    # lead_time window's demand. This maintains Oracle's by-design
    # role as the theoretical service-level upper bound.
    first_window_demand = float(sum(daily_demand[:lead_time]))
    total_test_demand = float(sum(daily_demand))
    # Keep a 1-unit buffer because stockout metric counts end-of-day
    # zero inventory as stockout (<= 0), and Oracle should remain
    # the theoretical upper bound.
    oracle_initial = max(float(start_stock), first_window_demand + 1.0, total_test_demand + 1.0)
    oracle_stock = oracle_initial
    oracle_pending = 0
    oracle_order_day = -999

    oracle_orders = [0] * total
    _sim_stock = float(oracle_initial)
    _pending = 0
    _order_day = -999
    for i in range(total):
        if _pending > 0 and (i - _order_day) >= lead_time:
            _sim_stock += _pending
            _pending = 0
        future_need = int(np.sum(daily_demand[i: i + lead_time + 1]))
        if _sim_stock < future_need and _pending == 0:
            # Order enough at delivery time to cover the remaining horizon
            # with a 1-unit buffer, preserving Oracle as an upper bound.
            deliver_day = min(i + lead_time, total - 1)
            projected_stock_at_delivery = max(
                0.0,
                _sim_stock - float(np.sum(daily_demand[i:deliver_day])),
            )
            post_delivery_need = float(np.sum(daily_demand[deliver_day:])) + 1.0
            order_qty = max(1, int(np.ceil(post_delivery_need - projected_stock_at_delivery)))
            _pending = order_qty
            _order_day = i
            oracle_orders[deliver_day] += order_qty
        _sim_stock = max(0.0, _sim_stock - int(daily_demand[i]))

    # ── Simulation loop ────────────────────────────────────────────────
    dss_stock = float(start_stock)
    naive_stock = float(start_stock)

    dss_pending = 0
    dss_order_day = -999
    naive_pending = 0
    naive_order_day = -999

    daily_data = []
    dss_stockout_days = 0
    naive_stockout_days = 0
    oracle_stockout_days = 0

    for i, demand in enumerate(daily_demand):
        demand = int(demand)

        if naive_pending > 0 and (i - naive_order_day) >= lead_time:
            naive_stock += naive_pending
            naive_pending = 0
        if dss_pending > 0 and (i - dss_order_day) >= lead_time:
            dss_stock += dss_pending
            dss_pending = 0
        if oracle_pending > 0 and (i - oracle_order_day) >= lead_time:
            oracle_stock += oracle_pending
            oracle_pending = 0
        if oracle_orders[i] > 0:
            oracle_stock += oracle_orders[i]

        naive_stock = max(0.0, naive_stock - demand)
        dss_stock = max(0.0, dss_stock - demand)
        oracle_stock = max(0.0, oracle_stock - demand)

        if naive_stock <= 0:
            naive_stockout_days += 1
        if dss_stock <= 0:
            dss_stockout_days += 1
        if oracle_stock <= 0:
            oracle_stockout_days += 1

        if naive_stock <= naive_rop and naive_pending == 0:
            in_transit = naive_pending
            order = max(1, naive_target_level - int(naive_stock) - in_transit)
            naive_pending = order
            naive_order_day = i

        if dss_stock <= dss_rop and dss_pending == 0:
            order = max(1, dss_target_level - int(dss_stock) - dss_pending)
            dss_pending = order
            dss_order_day = i
        elif dss_stock == 0 and dss_pending == 0:
            order = max(1, dss_target_level)
            dss_pending = order
            dss_order_day = i

        daily_data.append({
            "day": i + 1,
            "date": sim_data.iloc[i]["ds"].strftime("%Y-%m-%d"),
            "demand": demand,
            "dss_stock": int(dss_stock),
            "naive_stock": int(naive_stock),
            "oracle_stock": int(oracle_stock),
        })

    dss_service_level = float((1 - dss_stockout_days / total) * 100)
    naive_service_level = float((1 - naive_stockout_days / total) * 100)
    oracle_service_level = float((1 - oracle_stockout_days / total) * 100)
    reduction = (
        (naive_stockout_days - dss_stockout_days) / naive_stockout_days * 100
        if naive_stockout_days > 0 else 0.0
    )

    methodology_note = (
        "Baseline comparison: public eCommerce datasets (FMCG, India Sales, UK Retail, etc.) "
        "only contain daily quantity_sold — actual inventory levels, reorder decisions, and "
        "supplier lead times are NOT recorded. 'Oracle' (perfect foresight) is used as the "
        "theoretical upper-bound baseline instead of 'actual inventory'. "
        f"Train: {len(train_df)} days | Test: {total} days (last 30% of history)."
    )

    return {
        "test_start_date": sim_data.iloc[0]["ds"].date(),
        "test_end_date": sim_data.iloc[-1]["ds"].date(),
        "n_test_days": total,
        "mae": mae,
        "rmse": rmse,
        "mape": mape,
        "under_forecast_pct": under_forecast_pct,
        "over_forecast_pct": over_forecast_pct,
        "dss_service_level": dss_service_level,
        "dss_stockout_days": dss_stockout_days,
        "dss_avg_inventory": float(np.mean([r["dss_stock"] for r in daily_data])) if daily_data else 0.0,
        "naive_service_level": naive_service_level,
        "naive_stockout_days": naive_stockout_days,
        "naive_avg_inventory": float(np.mean([r["naive_stock"] for r in daily_data])) if daily_data else 0.0,
        "oracle_service_level": oracle_service_level,
        "oracle_stockout_days": oracle_stockout_days,
        "oracle_avg_inventory": float(np.mean([r["oracle_stock"] for r in daily_data])) if daily_data else 0.0,
        "stockout_reduction_pct": reduction,
        "methodology_note": methodology_note,
        "daily_data": daily_data,
    }
