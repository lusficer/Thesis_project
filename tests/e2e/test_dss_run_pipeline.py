from datetime import datetime

import numpy as np
import pytest

from app.models import DSSReport, Inventory, Notification, NotificationType


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: marks tests as slow (e2e model training)")


pytestmark = pytest.mark.slow


def _run_dss(client, auth_headers, payload):
    return client.post("/api/dss/run", json=payload, headers=auth_headers or {})


@pytest.fixture
def product1_run_response(client, seeded_db, auth_headers):
    payload = {
        "product_id": 1,
        "future_days": 30,
        "penalty_under": 5.0,
        "target_days_to_sell": 30,
    }
    response = _run_dss(client, auth_headers, payload)
    return response


def test_run_dss_product1_success(product1_run_response):
    response = product1_run_response
    assert response.status_code == 200

    data = response.json()
    for key in (
        "id",
        "product_id",
        "forecast_data",
        "inventory_advice",
        "pricing_advice",
        "ai_reasoning",
        "parameters",
    ):
        assert key in data

    forecast_data = data["forecast_data"]
    dates = forecast_data["dates"]
    yhat = forecast_data["yhat"]
    yhat_lower = forecast_data["yhat_lower"]
    yhat_upper = forecast_data["yhat_upper"]

    assert isinstance(dates, list) and len(dates) == 30
    assert isinstance(yhat, list) and len(yhat) == 30
    assert isinstance(yhat_lower, list) and len(yhat_lower) == 30
    assert isinstance(yhat_upper, list) and len(yhat_upper) == 30

    for d in dates:
        assert isinstance(d, str)
        datetime.strptime(d, "%Y-%m-%d")
    assert all(isinstance(v, (int, float)) and float(v) >= 0 for v in yhat)
    assert all(isinstance(v, (int, float)) for v in yhat_lower)
    assert all(isinstance(v, (int, float)) for v in yhat_upper)

    inv_advice = data["inventory_advice"]
    assert inv_advice["action"] in ["ORDER_NOW", "LOW_STOCK", "HOLD"]
    for key in (
        "reorder_point",
        "safety_stock",
        "stockout_probability",
        "days_of_supply",
        "current_daily_velocity",
    ):
        assert key in inv_advice

    stockout_probability = float(inv_advice["stockout_probability"])
    assert 0 <= stockout_probability <= 100
    assert float(inv_advice["reorder_point"]) > 0

    pricing = data["pricing_advice"]
    assert pricing["action"] in ["INCREASE", "DECREASE", "HOLD"]
    for key in ("current_price", "suggested_price", "adjustment_pct", "velocity_ratio", "reason"):
        assert key in pricing
    assert float(pricing["suggested_price"]) > 0
    assert abs(float(pricing["adjustment_pct"])) <= 30

    assert isinstance(data["ai_reasoning"], str)
    assert data["ai_reasoning"].strip() != ""
    assert float(data["parameters"]["penalty_under"]) == 5.0


def test_run_dss_product2_different_stock(client, seeded_db, auth_headers):
    payload = {
        "product_id": 2,
        "current_stock": 10,
        "current_price": 25.00,
        "future_days": 30,
        "penalty_under": 5.0,
    }
    response = _run_dss(client, auth_headers, payload)
    assert response.status_code == 200

    data = response.json()
    inv_advice = data["inventory_advice"]
    assert inv_advice["action"] == "ORDER_NOW"
    assert float(inv_advice["suggested_order_qty"]) > 0
    assert inv_advice["urgency"] == "HIGH"


def test_run_dss_insufficient_data(client, seeded_db, auth_headers):
    response = _run_dss(client, auth_headers, {"product_id": 3})
    assert response.status_code == 400
    detail = (response.json() or {}).get("detail", "")
    assert "Insufficient sales history" in detail


def test_run_dss_nonexistent_product(client, seeded_db, auth_headers):
    response = _run_dss(client, auth_headers, {"product_id": 9999})
    assert response.status_code == 404


def test_run_dss_report_persisted(seeded_db, product1_run_response):
    reports = seeded_db.query(DSSReport).filter(DSSReport.product_id == 1).all()
    assert len(reports) >= 1
    latest = reports[-1]
    assert latest.forecast_data is not None
    assert latest.inventory_advice is not None


def test_run_dss_inventory_updated(seeded_db, product1_run_response):
    inv = seeded_db.query(Inventory).filter(Inventory.product_id == 1).first()
    assert inv is not None
    assert inv.reorder_point > 0
    assert inv.safety_stock >= 0


def test_run_dss_notifications_created(seeded_db, product1_run_response):
    rows = (
        seeded_db.query(Notification)
        .filter(
            Notification.product_id == 1,
            Notification.type == NotificationType.DSS_COMPLETED,
        )
        .all()
    )
    assert len(rows) >= 1


def test_run_dss_symmetric_vs_asymmetric(client, seeded_db, auth_headers):
    sym_res = _run_dss(
        client,
        auth_headers,
        {
            "product_id": 1,
            "future_days": 30,
            "penalty_under": 1.0,
            "target_days_to_sell": 30,
        },
    )
    asym_res = _run_dss(
        client,
        auth_headers,
        {
            "product_id": 1,
            "future_days": 30,
            "penalty_under": 5.0,
            "target_days_to_sell": 30,
        },
    )

    assert sym_res.status_code == 200
    assert asym_res.status_code == 200

    sym_yhat = sym_res.json()["forecast_data"]["yhat"]
    asym_yhat = asym_res.json()["forecast_data"]["yhat"]
    assert np.mean(asym_yhat) >= np.mean(sym_yhat) * 0.95
