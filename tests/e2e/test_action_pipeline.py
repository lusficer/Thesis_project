import pytest

from app.models import (
    DSSReport,
    Inventory,
    InventoryTransaction,
    Notification,
    NotificationType,
    Product,
    TransactionType,
)


pytestmark = pytest.mark.slow


def _run_dss(client, auth_headers, payload):
    return client.post("/api/dss/run", json=payload, headers=auth_headers or {})


def test_confirm_order_flow(client, seeded_db, auth_headers):
    run_res = _run_dss(
        client,
        auth_headers,
        {"product_id": 2, "current_stock": 10, "penalty_under": 5.0},
    )
    assert run_res.status_code == 200
    run_data = run_res.json()
    report_id = int(run_data["report_id"])
    suggested_qty = int(run_data["inventory_advice"]["suggested_order_qty"])
    assert suggested_qty > 0

    inv_before = seeded_db.query(Inventory).filter(Inventory.product_id == 2).first()
    assert inv_before is not None
    stock_before = int(inv_before.current_stock)

    txn_before = (
        seeded_db.query(InventoryTransaction)
        .filter(InventoryTransaction.product_id == 2)
        .count()
    )

    confirm_res = client.post(
        "/api/dss/confirm-order",
        json={"report_id": report_id},
        headers=auth_headers or {},
    )
    assert confirm_res.status_code == 200
    confirm_data = confirm_res.json()
    assert confirm_data["success"] is True
    assert (
        "Stock-in confirmed" in confirm_data["message"]
        or f"+{suggested_qty} units" in confirm_data["message"]
    )

    seeded_db.refresh(inv_before)
    assert int(inv_before.current_stock) == stock_before + suggested_qty

    txns = (
        seeded_db.query(InventoryTransaction)
        .filter(InventoryTransaction.product_id == 2)
        .order_by(InventoryTransaction.id.asc())
        .all()
    )
    assert len(txns) == txn_before + 1
    latest_txn = txns[-1]
    assert latest_txn.type == TransactionType.IN
    assert (latest_txn.reference or "").startswith("DSS-")

    notifs = (
        seeded_db.query(Notification)
        .filter(
            Notification.product_id == 2,
            Notification.type == NotificationType.ORDER_CONFIRMED,
            Notification.dss_report_id == report_id,
        )
        .all()
    )
    assert len(notifs) >= 1


def test_confirm_order_custom_quantity(client, seeded_db, auth_headers):
    run_res = _run_dss(
        client,
        auth_headers,
        {"product_id": 2, "current_stock": 10, "penalty_under": 5.0},
    )
    assert run_res.status_code == 200
    report_id = int(run_res.json()["report_id"])

    inv = seeded_db.query(Inventory).filter(Inventory.product_id == 2).first()
    assert inv is not None
    stock_before = int(inv.current_stock)

    res = client.post(
        "/api/dss/confirm-order",
        json={"report_id": report_id, "quantity": 42},
        headers=auth_headers or {},
    )
    assert res.status_code == 200
    assert res.json()["success"] is True

    seeded_db.refresh(inv)
    assert int(inv.current_stock) == stock_before + 42


def test_apply_price_flow(client, seeded_db, auth_headers):
    run_res = _run_dss(
        client,
        auth_headers,
        {"product_id": 1, "current_stock": 100, "current_price": 10.0, "penalty_under": 5.0},
    )
    assert run_res.status_code == 200
    run_data = run_res.json()
    report_id = int(run_data["report_id"])
    suggested_price = float(run_data["pricing_advice"]["suggested_price"])
    assert suggested_price > 0

    apply_res = client.post(
        "/api/dss/apply-price",
        json={"report_id": report_id},
        headers=auth_headers or {},
    )
    assert apply_res.status_code == 200
    apply_data = apply_res.json()
    assert apply_data["success"] is True
    assert "old_price" in apply_data and "new_price" in apply_data

    p1 = seeded_db.query(Product).filter(Product.id == 1).first()
    assert p1 is not None
    assert abs(float(p1.current_price) - suggested_price) < 1e-9


def test_apply_price_guardrail_rejection(client, seeded_db, auth_headers):
    run_res = _run_dss(
        client,
        auth_headers,
        {"product_id": 1, "current_stock": 100, "current_price": 10.0, "penalty_under": 5.0},
    )
    assert run_res.status_code == 200
    report_id = int(run_res.json()["report_id"])

    res = client.post(
        "/api/dss/apply-price",
        json={"report_id": report_id, "approved_price": 15.0},
        headers=auth_headers or {},
    )
    assert res.status_code == 400
    detail = (res.json() or {}).get("detail", "").lower()
    assert ("exceeds" in detail) or ("guardrail" in detail)


def test_confirm_order_invalid_report(client, seeded_db, auth_headers):
    res = client.post(
        "/api/dss/confirm-order",
        json={"report_id": 99999},
        headers=auth_headers or {},
    )
    assert res.status_code == 404


def test_apply_price_invalid_report(client, seeded_db, auth_headers):
    res = client.post(
        "/api/dss/apply-price",
        json={"report_id": 99999},
        headers=auth_headers or {},
    )
    assert res.status_code == 404


def test_no_orphan_side_effect_records(seeded_db):
    # Sanity check for this module: action-generated rows remain linked to a report.
    orphan_notifications = (
        seeded_db.query(Notification)
        .filter(
            Notification.type.in_([NotificationType.ORDER_CONFIRMED, NotificationType.PRICE_UPDATED]),
            Notification.dss_report_id.is_(None),
        )
        .count()
    )
    orphan_transactions = (
        seeded_db.query(InventoryTransaction)
        .filter(
            InventoryTransaction.reference.like("DSS-%"),
        )
        .all()
    )
    assert orphan_notifications == 0
    for txn in orphan_transactions:
        report_id = txn.reference.split("DSS-")[-1]
        assert report_id.isdigit()
        report = seeded_db.query(DSSReport).filter(DSSReport.id == int(report_id)).first()
        assert report is not None
