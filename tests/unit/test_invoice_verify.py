from app.services.ledger import verify_invoice


def test_amount_mismatch_blocks():
    expected = {"client": "Rossi", "net": 1500.0, "vat": 330.0, "total": 1830.0, "status": "draft"}
    observed = {**expected, "net": 150.0, "total": 183.0}
    result = verify_invoice(expected, observed)
    assert result["ok"] is False
    assert result["checks"]["net"] is False


def test_tax_note_and_account_mismatch_block():
    expected = {
        "account": "Andrea Gadducci",
        "client": "Otil SRL",
        "net": 50000.0,
        "vat": 0.0,
        "vat_note": "Dichiarazione d'intento",
        "total": 50000.0,
        "status": "draft",
    }
    observed = {**expected, "vat_note": "", "account": ""}
    result = verify_invoice(expected, observed)
    assert result["ok"] is False
    assert result["checks"]["account"] is False
    assert result["checks"]["vat_note"] is False
