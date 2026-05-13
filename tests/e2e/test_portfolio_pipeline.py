import time

import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: marks tests as slow (e2e model training)")


pytestmark = pytest.mark.slow


def _start_recompute_job(client, auth_headers):
    res = client.post("/api/dss/recompute-forecasts", headers=auth_headers or {})
    assert res.status_code == 200
    payload = res.json()
    assert isinstance(payload.get("job_id"), str) and payload["job_id"].strip()
    assert payload.get("status") == "pending"
    return payload["job_id"]


def _wait_recompute_done(client, auth_headers, job_id: str, timeout_sec: int = 120):
    deadline = time.time() + timeout_sec
    latest = None

    # TestClient often buffers SSE and waits for stream close (can take 300s
    # by endpoint design), so poll in-memory job state directly for E2E.
    from app.api import dss as dss_api

    while time.time() <= deadline:
        latest = dss_api._recompute_jobs.get(job_id)
        if latest and latest.get("status") in ("done", "error"):
            break
        time.sleep(0.5)

    return latest


@pytest.fixture(scope="module")
def recompute_done(client, seeded_db):
    job_id = _start_recompute_job(client, {})
    final = _wait_recompute_done(client, {}, job_id, timeout_sec=180)
    assert final is not None
    assert final.get("status") == "done"
    return final


def test_portfolio_empty_before_recompute(client, seeded_db, auth_headers):
    res = client.get("/api/dss/portfolio", headers=auth_headers or {})
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list)
    assert len(data) >= 1

    sparse = next((r for r in data if r.get("product_id") == 3), None)
    assert sparse is not None
    assert sparse.get("status") == "insufficient_data"


def test_recompute_forecasts_returns_job_id(client, seeded_db, auth_headers):
    _start_recompute_job(client, auth_headers)


def test_recompute_forecasts_completes(recompute_done):
    final = recompute_done
    assert final.get("status") == "done"
    assert int(final.get("products_processed", 0)) >= 2
    assert int(final.get("progress", 0)) == 100


def test_portfolio_after_recompute(client, seeded_db, auth_headers, recompute_done):
    res = client.get("/api/dss/portfolio", headers=auth_headers or {})
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list)
    assert len(data) >= 2

    for item in data:
        if item.get("status") == "ok":
            for key in (
                "product_id",
                "product_name",
                "category",
                "current_stock",
                "current_price",
                "avg_daily_forecast",
                "reorder_point",
                "safety_stock",
                "stockout_probability",
                "velocity_ratio",
                "recommended_action",
                "price_change_pct",
            ):
                assert key in item
            assert item["recommended_action"] in ["ORDER_NOW", "LOW_STOCK", "HOLD", None]
            prob = item.get("stockout_probability")
            assert prob is None or (0 <= float(prob) <= 100)
            avg_daily = item.get("avg_daily_forecast")
            assert avg_daily is None or float(avg_daily) >= 0

    sparse = next((r for r in data if r.get("product_id") == 3), None)
    assert sparse is not None
    assert sparse.get("status") == "insufficient_data"


def test_portfolio_meta(client, seeded_db, auth_headers, recompute_done):
    res = client.get("/api/dss/portfolio/meta", headers=auth_headers or {})
    assert res.status_code == 200
    data = res.json()

    for k in ("last_computed_at", "products_cached", "total_products", "model_version"):
        assert k in data
    assert isinstance(data["products_cached"], int)
    assert isinstance(data["total_products"], int)
    assert isinstance(data["model_version"], str)
    assert data["products_cached"] >= 2
    assert data["model_version"] == "hybrid_asym_v1"


def test_portfolio_action_distribution(client, seeded_db, auth_headers, recompute_done):
    res = client.get("/api/dss/portfolio", headers=auth_headers or {})
    assert res.status_code == 200
    rows = res.json()

    ok_rows = [r for r in rows if r.get("status") == "ok"]
    assert len(ok_rows) > 0

    counts = {}
    for r in ok_rows:
        action = r.get("recommended_action")
        assert action in ["ORDER_NOW", "LOW_STOCK", "HOLD"]
        counts[action] = counts.get(action, 0) + 1

    assert sum(counts.values()) == len(ok_rows)
