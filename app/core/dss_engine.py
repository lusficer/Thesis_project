"""
═══════════════════════════════════════════════════════════════
  DSSEngine — Inventory Management & Dynamic Pricing Logic
  Decision Support System for eCommerce optimization
═══════════════════════════════════════════════════════════════
"""

import numpy as np
from scipy.stats import norm


class DSSEngine:
    """
    Decision Support System engine combining:
    - Inventory management: Safety stock, ROP, stockout probability
    - Dynamic pricing: Velocity-based pricing rules with guardrails

    analyze() return dict structure
    ────────────────────────────────
    {
        "inventory_advice": {
            "action":               "ORDER_NOW" | "LOW_STOCK" | "HOLD",
            "urgency":              "HIGH" | "MEDIUM" | "LOW",
            "suggested_order_qty":  int,
            "qty_to_order":         int,          # alias
            "reorder_point":        float,
            "safety_stock":         float,
            "safety_stock_needed":  float,        # alias
            "stockout_probability": float,        # 0-100
            "expected_demand_30d":  float,
            "days_of_supply":       float,
            "current_daily_velocity": float,
            "lead_time_demand":     float,
            "volatility_score":     float,
        },
        "pricing_advice": {
            "action":           "INCREASE" | "DECREASE" | "HOLD",
            "current_price":    float,
            "suggested_price":  float,
            "adjustment_pct":   float,        # signed %
            "change_percent":   float,        # alias
            "reason":           str,
            "velocity_ratio":   float,
            "target_velocity":  float,
            "actual_velocity":  float,
            "guardrail_note":   str | None,
        },
        "ai_narrative": str,
    }
    """

    def __init__(self, lead_time: int = 7):
        """
        Parameters
        ----------
        lead_time : int
            Replenishment delay in days (default 7).
        """
        self.lead_time = lead_time

        # Velocity thresholds
        self.FAST_THRESHOLD  = 1.5
        self.MODERATE_FAST   = 1.1
        self.SLOW_THRESHOLD  = 0.8
        self.VERY_SLOW       = 0.5

    # ──────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────

    def analyze(
        self,
        forecast_df,
        current_stock: float,
        current_price: float,
        target_days_to_sell: int = 30,
    ) -> dict:
        """
        Full DSS analysis: inventory + pricing recommendations.

        Parameters
        ----------
        forecast_df          : pd.DataFrame with at minimum column 'yhat'
                               (also accepts 'ds', 'yhat_lower', 'yhat_upper')
        current_stock        : current on-hand inventory units
        current_price        : current selling price
        target_days_to_sell  : target sell-through window in days (default 30)

        Returns
        -------
        dict — see class docstring for full schema
        """
        # ══════════════════════════════════════════════════════════════
        # PART 1: INVENTORY ANALYSIS
        # ══════════════════════════════════════════════════════════════

        forecast_values = forecast_df["yhat"].values

        # ── 1.1 Forecast metrics ──────────────────────────────────────
        lead_slice = forecast_values[: self.lead_time]
        future_demand_7d       = float(np.sum(lead_slice))
        current_daily_velocity = float(np.mean(lead_slice)) if len(lead_slice) > 0 else 0.0

        demand_std     = float(np.std(forecast_values))
        volatility_score = demand_std / current_daily_velocity if current_daily_velocity > 0 else 0.0

        # 30-day expected demand (capped at available forecast length)
        expected_demand_30d = float(np.sum(forecast_values[:30]))

        # Days of supply
        days_of_supply = (
            current_stock / current_daily_velocity
            if current_daily_velocity > 0
            else float("inf")
        )

        # ── 1.2 Stockout probability ──────────────────────────────────
        if demand_std > 0:
            z_score      = (current_stock - future_demand_7d) / (demand_std * np.sqrt(self.lead_time))
            stockout_prob = (1 - norm.cdf(z_score)) * 100
        else:
            stockout_prob = 100.0 if current_stock < future_demand_7d else 0.0

        stockout_prob = float(np.clip(stockout_prob, 0, 100))

        # ── 1.3 Safety stock (adaptive service level) ─────────────────
        target_risk = 0.02 if volatility_score > 0.5 else 0.05
        desired_z   = norm.ppf(1 - target_risk)
        safety_stock = float(max(0.0, desired_z * demand_std * np.sqrt(self.lead_time)))

        # ── 1.4 Reorder point ─────────────────────────────────────────
        reorder_point = float(max(0.0, future_demand_7d + safety_stock))

        # ── 1.5 Action recommendation ─────────────────────────────────
        if current_stock < reorder_point:
            inv_action   = "ORDER_NOW"
            qty_to_order = int(np.ceil(reorder_point - current_stock))
            urgency      = "HIGH"
        elif stockout_prob > 30:
            inv_action   = "LOW_STOCK"
            qty_to_order = int(np.ceil(safety_stock))
            urgency      = "MEDIUM"
        else:
            inv_action   = "HOLD"
            qty_to_order = 0
            urgency      = "LOW"

        inventory_advice = {
            "action":                 inv_action,
            "urgency":                urgency,
            "suggested_order_qty":    qty_to_order,
            "qty_to_order":           qty_to_order,          # alias
            "reorder_point":          round(reorder_point, 2),
            "safety_stock":           round(safety_stock, 2),
            "safety_stock_needed":    round(safety_stock, 2), # alias
            "stockout_probability":   round(stockout_prob, 2),
            "expected_demand_30d":    round(expected_demand_30d, 2),
            "days_of_supply":         round(days_of_supply, 2) if days_of_supply != float("inf") else 9999,
            "current_daily_velocity": round(current_daily_velocity, 2),
            "lead_time_demand":       round(future_demand_7d, 2),
            "volatility_score":       round(volatility_score, 2),
        }

        # ══════════════════════════════════════════════════════════════
        # PART 2: DYNAMIC PRICING
        # ══════════════════════════════════════════════════════════════

        # ── 2.1 Velocity metrics ──────────────────────────────────────
        target_velocity = (
            current_stock / target_days_to_sell if target_days_to_sell > 0 else 0.0
        )
        actual_velocity = current_daily_velocity
        velocity_ratio  = (
            actual_velocity / target_velocity if target_velocity > 0 else 1.0
        )

        # ── 2.2 Velocity-based pricing rules ──────────────────────────
        price_change_pct = 0.0
        reason           = "Velocity within normal range"

        if velocity_ratio >= self.FAST_THRESHOLD:
            price_change_pct = 8.0
            reason = f"High velocity ({velocity_ratio:.1f}x target)"
        elif velocity_ratio >= self.MODERATE_FAST:
            price_change_pct = 3.0
            reason = f"Moderate velocity ({velocity_ratio:.1f}x target)"
        elif velocity_ratio < self.SLOW_THRESHOLD and current_stock > reorder_point:
            if velocity_ratio < self.VERY_SLOW:
                price_change_pct = -10.0
                reason = f"Very low velocity ({velocity_ratio:.1f}x target)"
            else:
                price_change_pct = -4.0
                reason = f"Low velocity ({velocity_ratio:.1f}x target)"

        # ── 2.3 Scarcity premium override ─────────────────────────────
        guardrail_note = None
        if stockout_prob > 80 and price_change_pct < 10:
            price_change_pct = 10.0
            reason = "Critical scarcity detected (stockout risk > 80%)"

        # ── 2.4 Guardrails ±30 % ─────────────────────────────────────
        raw_suggested = current_price * (1 + price_change_pct / 100)
        min_price     = current_price * 0.70
        max_price     = current_price * 1.30
        suggested_price = float(np.clip(raw_suggested, min_price, max_price))

        if suggested_price != raw_suggested:
            guardrail_note = "Price capped at ±30% guardrail."

        actual_change_pct = ((suggested_price - current_price) / current_price) * 100

        # Determine pricing action label
        if actual_change_pct > 0.5:
            price_action = "INCREASE"
        elif actual_change_pct < -0.5:
            price_action = "DECREASE"
        else:
            price_action = "HOLD"

        pricing_advice = {
            "action":          price_action,
            "current_price":   round(current_price, 2),
            "suggested_price": round(suggested_price, 2),
            "adjustment_pct":  round(actual_change_pct, 2),   # ← required by dss.py
            "change_percent":  round(actual_change_pct, 2),   # alias
            "reason":          reason,
            "velocity_ratio":  round(velocity_ratio, 2),
            "target_velocity": round(target_velocity, 2),
            "actual_velocity": round(actual_velocity, 2),
            "guardrail_note":  guardrail_note,
        }

        # ── Narrative ─────────────────────────────────────────────────
        ai_narrative = self._generate_simple_narrative(inventory_advice, pricing_advice)

        return {
            "inventory_advice": inventory_advice,
            "pricing_advice":   pricing_advice,
            "ai_narrative":     ai_narrative,
        }

    # ──────────────────────────────────────────────────────────────────
    # Private helpers
    # ──────────────────────────────────────────────────────────────────

    @staticmethod
    def _generate_simple_narrative(inv_advice: dict, price_advice: dict) -> str:
        stockout     = inv_advice["stockout_probability"]
        action       = inv_advice["action"]
        price_change = price_advice["adjustment_pct"]
        lines        = []

        if action == "ORDER_NOW":
            lines.append(
                f"⚠️ URGENT: Stockout risk at {stockout:.1f}%. "
                f"Reorder {inv_advice['suggested_order_qty']} units immediately."
            )
        elif action == "LOW_STOCK":
            lines.append(
                f"⚠️ LOW STOCK: Stockout risk at {stockout:.1f}%. "
                f"Consider ordering {inv_advice['suggested_order_qty']} units."
            )
        else:
            lines.append(
                f"✅ STOCK OK: Stockout risk at {stockout:.1f}%. No immediate action needed."
            )

        if abs(price_change) > 0.5:
            direction = "increase" if price_change > 0 else "decrease"
            lines.append(
                f"💡 PRICING: Suggest {direction} price by {abs(price_change):.1f}% "
                f"to ${price_advice['suggested_price']:.2f}."
            )
            lines.append(f"   Reason: {price_advice['reason']}")
        else:
            lines.append(
                f"💡 PRICING: Current price is optimal (${price_advice['current_price']:.2f})."
            )

        if price_advice.get("guardrail_note"):
            lines.append(f"   ⚡ {price_advice['guardrail_note']}")

        return "\n".join(lines)
