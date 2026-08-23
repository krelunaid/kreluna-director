from app.services.ledger import verify_invoice


def test_amount_mismatch_blocks():
    expected = {"client": "Rossi", "net": 1500.0, "vat": 330.0, "total": 1830.0, "status": "draft"}
    observed = {**expected, "net": 150.0, "total": 183.0}
    result = verify_invoice(expected, observed)
    assert result["ok"] is False
    assert result["checks"]["net"] is False
