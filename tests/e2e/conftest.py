from datetime import date, timedelta
from decimal import Decimal
import random
import re

try:
    import pytest
except ModuleNotFoundError:
    class _PytestShim:
        @staticmethod
        def fixture(*_args, **_kwargs):
            def decorator(func):
                return func
            return decorator

    pytest = _PytestShim()


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: marks tests as slow (e2e model training)")


def _classify_test_type(nodeid: str) -> str:
    if "test_backtest_pipeline.py" in nodeid:
        return "Backtest E2E"
    if "test_dss_run_pipeline.py" in nodeid:
        return "DSS Run E2E"
    if "test_action_pipeline.py" in nodeid:
        return "Action E2E"
    if "test_portfolio_pipeline.py" in nodeid:
        return "Portfolio E2E"
    return "E2E"


def _humanize_test_name(nodeid: str) -> str:
    test_name = nodeid.split("::")[-1]
    test_name = re.sub(r"^test_", "", test_name)
    return test_name.replace("_", " ").strip().capitalize()


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    terminalreporter.write_sep("-", "E2E test outcomes")
    ordered = [("passed", "PASS"), ("failed", "FAIL"), ("error", "ERROR"), ("skipped", "SKIP")]
    has_rows = False
    for key, label in ordered:
        for report in terminalreporter.stats.get(key, []):
            nodeid = getattr(report, "nodeid", "")
            if "tests/e2e/" not in nodeid:
                continue
            has_rows = True
            terminalreporter.write_line(
                f"[{label}] {_classify_test_type(nodeid)} :: {_humanize_test_name(nodeid)}"
            )
    if not has_rows:
        terminalreporter.write_line("No e2e test cases were executed.")


@pytest.fixture(scope="session")
def test_db():
    import importlib
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from app.database import Base, get_db
    from app.main import app as fastapi_app
    from app.services import forecast_cache, backtest_cache

    importlib.import_module("app.models")  # ensure model tables are registered on Base.metadata
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    fastapi_app.dependency_overrides[get_db] = override_get_db
    original_forecast_sessionlocal = forecast_cache.SessionLocal
    original_backtest_sessionlocal = backtest_cache.SessionLocal
    forecast_cache.SessionLocal = TestingSessionLocal
    backtest_cache.SessionLocal = TestingSessionLocal

    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        forecast_cache.SessionLocal = original_forecast_sessionlocal
        backtest_cache.SessionLocal = original_backtest_sessionlocal
        fastapi_app.dependency_overrides.pop(get_db, None)
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture(scope="session")
def client(test_db):
    from fastapi.testclient import TestClient
    from app.main import app as fastapi_app

    with TestClient(fastapi_app) as c:
        yield c


@pytest.fixture(scope="module")
def seeded_db(test_db):
    from app.models import Inventory, Product, SalesHistory

    db = test_db

    products = [
        Product(sku="TEST-001", name="Test Widget A", base_price=Decimal("10.00"), current_price=Decimal("10.00")),
        Product(sku="TEST-002", name="Test Widget B", base_price=Decimal("25.00"), current_price=Decimal("25.00")),
        Product(sku="TEST-003", name="Test Sparse", base_price=Decimal("5.00"), current_price=Decimal("5.00")),
    ]
    db.add_all(products)
    db.flush()

    db.add_all(
        [
            Inventory(product_id=products[0].id, current_stock=100),
            Inventory(product_id=products[1].id, current_stock=50),
            Inventory(product_id=products[2].id, current_stock=200),
        ]
    )

    end_date = date.today() - timedelta(days=1)

    def make_sales(product_id: int, days: int, qty_min: int, qty_max: int, seed: int, unit_price: Decimal):
        rng = random.Random(seed)
        start_date = end_date - timedelta(days=days - 1)
        rows = []
        for i in range(days):
            d = start_date + timedelta(days=i)
            qty = rng.randint(qty_min, qty_max)
            rows.append(
                SalesHistory(
                    product_id=product_id,
                    date=d,
                    quantity_sold=qty,
                    revenue=Decimal(qty) * unit_price,
                )
            )
        return rows

    db.add_all(make_sales(products[0].id, 120, 5, 15, 42, Decimal("10.00")))
    db.add_all(make_sales(products[1].id, 90, 10, 30, 43, Decimal("25.00")))
    db.add_all(make_sales(products[2].id, 25, 1, 8, 44, Decimal("5.00")))

    db.commit()
    return db


@pytest.fixture
def auth_headers(client):
    register_payload = {
        "email": "e2e.test@example.com",
        "password": "TestPass123!",
        "full_name": "E2E Tester",
    }
    register_res = client.post("/api/auth/register", json=register_payload)
    if register_res.status_code == 404:
        return {}

    login_payload = {"email": register_payload["email"], "password": register_payload["password"]}
    login_res = client.post("/api/auth/login", json=login_payload)
    if login_res.status_code == 404:
        return {}

    token = (login_res.json() or {}).get("access_token")
    if not token:
        return {}

    return {"Authorization": f"Bearer {token}"}
