from __future__ import annotations

from agent.capabilities import invoice_demo


class _Response:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"observed": {"draft_id": "demo-draft"}}


class _Client:
    async def post(self, *_args, **_kwargs) -> _Response:
        return _Response()


async def test_demo_invoice_always_uses_the_local_visible_window(monkeypatch):
    calls: list[dict] = []

    def fake_fill(**kwargs):
        calls.append(kwargs)
        return [
            {
                "kind": "screenshot",
                "metadata": {"program": "gestionale-fatture-demo"},
            }
        ]

    monkeypatch.setattr(invoice_demo, "fill_invoice_on_pc", fake_fill)

    result = await invoice_demo.prepare(
        client=_Client(),
        director_url="https://director.example",
        device_id="device-1",
        task_id="task-1",
        sign_request=lambda _path, body: body,
        account_name="Studio Demo",
        client_name="Cliente Prova SRL",
        description="Consulenza amministrativa",
        net_eur=100,
        vat_rate=0.22,
    )

    assert len(calls) == 1
    assert calls[0]["client_name"] == "Cliente Prova SRL"
    assert result["method"] == "ui_visible"
    assert result["program"] == "PC-FATTURE (prova locale)"
    assert result["live_target"] == {
        "configured": False,
        "filled": False,
        "sent": False,
        "message": "Prova locale: nessun portale fiscale aperto.",
    }
    assert result["evidence"][0]["metadata"]["draft_id"] == "demo-draft"
