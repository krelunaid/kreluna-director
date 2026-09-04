from pathlib import Path

import pytest
from agent.capabilities import CAPABILITY_ALLOWLIST, invoice_demo, portal


@pytest.mark.parametrize("handler", [invoice_demo.prepare, invoice_demo.submit])
async def test_obsolete_demo_calls_refused(handler):
    with pytest.raises(RuntimeError, match="SIMULATORE_FATTURE_RIMOSSO"):
        await handler(client_name="Cliente prova")


def test_no_simulator_window_source_or_registered_handler():
    root = Path(invoice_demo.__file__).resolve().parents[1]
    assert not (root / "tools/mac_gestionale_ui.py").exists()
    assert CAPABILITY_ALLOWLIST["invoice_prepare_demo"] is portal.open_legacy_invoice_in_webdesk
    assert CAPABILITY_ALLOWLIST["invoice_submit_demo"] is portal.refuse_legacy_invoice_submit
