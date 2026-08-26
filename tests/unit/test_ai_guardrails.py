import json

import httpx
import pytest
from kreluna_shared.llm import plan_with_llm
from kreluna_shared.planner import plan_deterministic


def model_saying(payload: dict) -> httpx.AsyncClient:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(payload)}}]})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def ask(payload: dict, message: str):
    async with model_saying(payload) as client:
        return await plan_with_llm(
            message,
            base_url="https://modello.esempio/v1",
            api_key="chiave-finta",
            model="modello-test",
            client=client,
        )


def invoice(client_name: str, amount: float) -> dict:
    return {
        "understood": True,
        "summary": "Preparo la fattura.",
        "tasks": [
            {
                "goal": "Fattura",
                "capability": "invoice_prepare_demo",
                "args": {"client_name": client_name, "description": "Consulenza", "net_eur": amount},
            }
        ],
    }


@pytest.mark.asyncio
async def test_model_cannot_invent_a_client_and_an_amount_out_of_thin_air():
    plan = await ask(invoice("Kreluna", 1000), "puoi fare fatture?")
    assert plan is not None
    assert not plan.ok
    assert plan.tasks == []
    assert "invento" in plan.summary


@pytest.mark.asyncio
async def test_model_cannot_change_the_amount_the_owner_said():
    plan = await ask(invoice("Andrea Gadducci", 9000), "fattura a Gadducci per 5.000 euro di consulenza")
    assert plan is not None and not plan.ok
    assert "importo" in plan.summary


@pytest.mark.asyncio
async def test_model_cannot_swap_the_client():
    plan = await ask(invoice("Mario Rossi", 5000), "fattura a Gadducci per 5.000 euro di consulenza")
    assert plan is not None and not plan.ok
    assert "cliente" in plan.summary


@pytest.mark.asyncio
async def test_amount_and_client_from_the_message_are_accepted():
    plan = await ask(invoice("Andrea Gadducci", 5000), "fattura a Gadducci per 5.000 euro di consulenza")
    assert plan is not None and plan.ok
    assert plan.tasks[0].args["net_eur"] == 5000

    spoken = await ask(
        invoice("Andrea Gadducci", 37500),
        "fai la fattura ad Andrea Gadducci per 35-40 mila euro di manodopera",
    )
    assert spoken is not None and spoken.ok


@pytest.mark.asyncio
async def test_client_without_an_amount_field_is_still_checked():
    payload = {
        "understood": True,
        "summary": "Preparo il DURC.",
        "tasks": [{"goal": "DURC", "capability": "durc_prepare", "args": {"client_name": "Bianchi Laura"}}],
    }
    good = await ask(payload, "serve il DURC per la ditta Bianchi")
    assert good is not None and good.ok
    invented = await ask(payload, "serve il DURC per quel cliente di ieri")
    assert invented is not None and not invented.ok


@pytest.mark.asyncio
async def test_model_cannot_invent_studio_workflow_details():
    contract = {
        "understood": True,
        "summary": "Preparo il contratto.",
        "tasks": [{"goal": "Contratto", "capability": "contratti_prepare", "args": {"client_name": "Andrea Gadducci", "contract_type": "locazione"}}],
    }
    rejected = await ask(contract, "prepara un contratto per Andrea Gadducci")
    assert rejected is not None and not rejected.ok
    accepted = await ask(contract, "prepara un contratto di locazione per Andrea Gadducci")
    assert accepted is not None and accepted.ok


@pytest.mark.asyncio
async def test_model_cannot_turn_an_ordinary_visura_into_a_historical_one():
    payload = {
        "understood": True,
        "summary": "Preparo la visura.",
        "tasks": [{"goal": "Visura", "capability": "visure_prepare", "args": {"client_name": "Andrea Gadducci", "visura_type": "historical"}}],
    }
    rejected = await ask(payload, "prepara una visura per Andrea Gadducci")
    assert rejected is not None and not rejected.ok
    accepted = await ask(payload, "prepara una visura storica per Andrea Gadducci")
    assert accepted is not None and accepted.ok


@pytest.mark.asyncio
async def test_explicit_tax_exemption_cannot_be_replaced_with_vat_22():
    payload = invoice("Otil Srl", 50000)
    payload["tasks"][0]["args"].update(
        {"account_name": "Andrea Gadducci", "description": "Manodopera", "vat_rate": 0.22}
    )
    plan = await ask(
        payload,
        "fattura per Gadduci di mandoperda 50000 euro a Otil Srl "
        "senza IVA con dichiarazione d intento",
    )
    assert plan is not None and plan.ok
    assert plan.tasks[0].args["vat_rate"] == 0
    assert plan.tasks[0].args["vat_note"] == "Dichiarazione d'intento"


def test_a_question_gets_the_list_of_what_it_can_do():
    for question in ("puoi fare fatture?", "cosa sai fare?", "aiuto", "come funziona?"):
        plan = plan_deterministic(question)
        assert not plan.ok, question
        assert not plan.denied, question
        assert plan.tasks == [], question
        assert plan.source == "deterministic-help", question
        assert "Visure" in plan.summary and "DURC" in plan.summary
        assert "Approva" in plan.summary


def test_an_order_is_still_an_order():
    plan = plan_deterministic("puoi farmi la visura per Gadducci")
    assert plan.ok
    assert plan.tasks[0].capability == "visure_prepare"
