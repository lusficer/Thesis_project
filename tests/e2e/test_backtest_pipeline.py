import pytest

from app.models import SalesHistory


pytestmark = pytest.mark.slow


def _run_backtest(client, auth_headers, payload):
    return client.post("/api/dss/backtest", json=payload, headers=auth_headers or {})


@pytest.fixture
def product1_backtest_response(client, seeded_db, auth_headers):
    response = _run_backtest(
        client,
        auth_headers,
        {"product_id": 1, "simulation_days": 30, "initial_stock": 100},
    )
    assert response.status_code == 200
    return response


def test_backtest_product1_basic(product1_backtest_response):
    data = product1_backtest_response.json()

    for key in (
        "product_id",
        "simulation_days",
        "dss_stockout_days",
        "dss_service_level",
        "naive_stockout_days",
        "naive_service_level",
        "oracle_stockout_days",
        "oracle_service_level",
        "stockout_reduction_pct",
        "methodology_note",
        "daily_data",
    ):
        assert key in data

    assert data["simulation_days"] == 30
    assert isinstance(data["daily_data"], list)
    assert len(data["daily_data"]) == 30

    for row in data["daily_data"]:
        for k in ("day", "date", "demand", "dss_stock", "naive_stock", "oracle_stock"):
            assert k in row
        assert row["dss_stock"] >= 0
        assert row["naive_stock"] >= 0
        assert row["oracle_stock"] >= 0


def test_backtest_oracle_upper_bound(product1_backtest_response):
    data = product1_backtest_response.json()

    assert data["oracle_service_level"] >= data["dss_service_level"]
    assert data["oracle_service_level"] >= data["naive_service_level"]
    assert data["oracle_stockout_days"] <= data["dss_stockout_days"]
    assert data["oracle_stockout_days"] <= data["naive_stockout_days"]
    assert data["oracle_stockout_days"] == 0


def test_backtest_dss_beats_naive(client, seeded_db, auth_headers):
    res = _run_backtest(
        client,
        auth_headers,
        {"product_id": 1, "simulation_days": 30, "initial_stock": 200},
    )
    assert res.status_code == 200
    data = res.json()

    assert data["dss_service_level"] >= (data["naive_service_level"] - 5.0)
    assert (
        data["stockout_reduction_pct"] >= 0
        or data["dss_stockout_days"] <= data["naive_stockout_days"]
    )


def test_backtest_service_level_math(product1_backtest_response):
    data = product1_backtest_response.json()
    expected = (1 - (data["dss_stockout_days"] / data["simulation_days"])) * 100
    assert abs(data["dss_service_level"] - expected) < 0.5


def test_backtest_insufficient_data(client, seeded_db, auth_headers):
    res = _run_backtest(client, auth_headers, {"product_id": 3, "simulation_days": 30})
    assert res.status_code == 400


def test_backtest_demand_consistency(seeded_db, product1_backtest_response):
    data = product1_backtest_response.json()
    backtest_demand_sum = sum(int(row["demand"]) for row in data["daily_data"])

    test_sales = (
        seeded_db.query(SalesHistory)
        .filter(SalesHistory.product_id == 1)
        .order_by(SalesHistory.date.asc())
        .all()
    )
    assert len(test_sales) >= 30
    expected_sum = sum(int(s.quantity_sold) for s in test_sales[-30:])
    assert backtest_demand_sum == expected_sum


def test_backtest_daily_data_stock_trajectory(product1_backtest_response):
    data = product1_backtest_response.json()
    daily = data["daily_data"]

    for strategy_key in ("dss_stock", "naive_stock", "oracle_stock"):
        decreases = 0
        increases = 0
        for i in range(1, len(daily)):
            prev_stock = int(daily[i - 1][strategy_key])
            curr_stock = int(daily[i][strategy_key])
            demand = int(daily[i]["demand"])

            assert curr_stock >= 0
            if demand > 0 and curr_stock < prev_stock:
                decreases += 1
            if curr_stock > prev_stock:
                increases += 1  # possible reorder/delivery day

        assert decreases > 0
        assert increases < len(daily)
