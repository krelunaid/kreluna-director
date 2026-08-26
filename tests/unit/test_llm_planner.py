import json
from pathlib import Path

import httpx
import pytest
from kreluna_shared.llm import build_system_prompt, parse_llm_payload, plan_with_llm
from kreluna_shared.planner import apply_policy
from kreluna_shared.policy import load_policy

ROOT = Path(__file__).resolve().parents[2]


def fake_model(reply: str) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        assert request.headers["Authorization"] == "Bearer chiave-finta"
        body = json.loads(request.content)
        assert body["temperature"] == 0
        assert "Kreluna Director" in body["messages"][0]["content"]
        return httpx.Response(200, json={"choices": [{"message": {"content": reply}}]})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def ask(reply: str, message: str = "senti, fai la fattura a Andrea Gadducci per 5.000 euro di manodopera"):
    async with fake_model(reply) as client:
        return await plan_with_llm(
            message,
            base_url="https://modello.esempio/v1",
            api_key="chiave-finta",
            model="modello-test",
            client=client,
        )


@pytest.mark.asyncio
async def test_grok_46_uses_low_reasoning_for_fast_operational_chat():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        reply = json.dumps({"understood": False, "question": "Per quale cliente?"})
        return httpx.Response(200, json={"choices": [{"message": {"content": reply}}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await plan_with_llm(
            "prepara una fattura",
            base_url="https://api.x.ai/v1",
            api_key="chiave-finta",
            model="grok-4.6",
            client=client,
        )

    assert seen["reasoning_effort"] == "low"
    assert seen["max_tokens"] == 260


def test_prompt_lists_studio_programs_and_forbids_invented_amounts():
    prompt = build_system_prompt()
    assert "PC-FATTURE" in prompt
    assert "Webdesk" in prompt
    assert "IPSOA" in prompt
    assert "Sito CGN" in prompt
    assert "invoice_prepare_demo" in prompt
    assert "Non inventare MAI importi" in prompt
    assert "payment_prepare" not in prompt
    assert "invoice_submit_demo" not in prompt


@pytest.mark.asyncio
async def test_free_italian_becomes_a_task():
    plan = await ask(
        json.dumps(
            {
                "understood": True,
                "summary": "Mando PC-FATTURE: fattura a Andrea Gadducci, 5.000 euro di manodopera.",
                "tasks": [
                    {
                        "goal": "Compilare la fattura a Andrea Gadducci",
                        "capability": "invoice_prepare_demo",
                        "args": {
                            "client_name": "Andrea Gadducci",
                            "description": "Manodopera",
                            "net_eur": 5000,
                        },
                    }
                ],
            }
        )
    )
    assert plan is not None
    assert plan.ok
    assert plan.source == "llm"
    assert plan.tasks[0].capability == "invoice_prepare_demo"
    assert plan.tasks[0].args["net_eur"] == 5000


@pytest.mark.asyncio
async def test_model_cannot_invent_the_amount():
    plan = await ask(
        json.dumps(
            {
                "understood": True,
                "summary": "Fattura a Gadducci.",
                "tasks": [
                    {
                        "goal": "Fattura",
                        "capability": "invoice_prepare_demo",
                        "args": {"client_name": "Andrea Gadducci", "description": "Manodopera"},
                    }
                ],
            }
        )
    )
    assert plan is not None
    assert not plan.ok
    assert not plan.denied
    assert plan.tasks == []
    assert "importo" in plan.summary


@pytest.mark.asyncio
async def test_model_cannot_choose_a_forbidden_capability():
    for capability in ("arbitrary_remote_shell", "invoice_submit_demo", "payment_prepare", ""):
        plan = await ask(
            json.dumps(
                {
                    "understood": True,
                    "summary": "Faccio tutto io.",
                    "tasks": [{"goal": "x", "capability": capability, "args": {}}],
                }
            )
        )
        assert plan is not None, capability
        assert plan.denied is True, capability
        assert plan.tasks == [], capability


@pytest.mark.asyncio
async def test_model_cannot_grant_itself_approval_free_risk():
    plan = await ask(
        json.dumps(
            {
                "understood": True,
                "summary": "Preparo il DURC.",
                "tasks": [
                    {
                        "goal": "DURC",
                        "capability": "durc_prepare",
                        "args": {"client_name": "Andrea Gadducci"},
                        "risk": "low",
                        "needs_approval": False,
                    }
                ],
            }
        ),
        message="Prepara il DURC per Andrea Gadducci",
    )
    assert plan is not None and plan.ok
    engine = load_policy(ROOT / "policies" / "default.yaml")
    checked = apply_policy(plan, engine, "active")
    assert checked.ok
    assert checked.tasks[0].risk.value == "medium"


@pytest.mark.asyncio
async def test_question_when_the_model_is_unsure():
    plan = await ask(json.dumps({"understood": False, "question": "Per quale cliente?"}))
    assert plan is not None
    assert not plan.ok
    assert not plan.denied
    assert plan.summary == "Per quale cliente?"
    assert plan.source == "llm-ask"


@pytest.mark.asyncio
async def test_informational_answer_is_returned_without_creating_a_task():
    plan = await ask(
        json.dumps(
            {
                "understood": False,
                "answer": (
                    "Per adempimento intendo una pratica o una scadenza dello studio, "
                    "per esempio una dichiarazione o un versamento."
                ),
            }
        ),
        message="che vuol dire adempimento?",
    )
    assert plan is not None and plan.ok
    assert plan.source == "llm-answer"
    assert plan.tasks == []
    assert "pratica" in plan.summary


@pytest.mark.asyncio
async def test_recipes_and_movies_are_kept_out_of_the_professional_assistant():
    for message in ("Dammi la ricetta della carbonara", "Cercami un film da vedere stasera"):
        plan = await ask(
            json.dumps({"understood": False, "answer": "Ecco una risposta generica che non deve passare."}),
            message=message,
        )
        assert plan is not None and plan.ok
        assert plan.source == "llm-domain"
        assert "solo con contabilità" in plan.summary
        assert "carbonara" not in plan.summary
        assert "stasera" not in plan.summary


@pytest.mark.asyncio
async def test_recent_conversation_is_sent_to_the_model():
    def contextual(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["messages"][-3:] == [
            {"role": "user", "content": "Mi fai una dichiarazione dei redditi?"},
            {"role": "assistant", "content": "Quale adempimento ti serve?"},
            {"role": "user", "content": "Che vuol dire?"},
        ]
        reply = {"understood": False, "answer": "Per adempimento intendo il lavoro fiscale da preparare."}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(reply)}}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(contextual)) as client:
        plan = await plan_with_llm(
            "Che vuol dire?",
            base_url="https://modello.esempio/v1",
            api_key="chiave-finta",
            model="modello-test",
            client=client,
            history=[
                {"role": "user", "content": "Mi fai una dichiarazione dei redditi?"},
                {"role": "assistant", "content": "Quale adempimento ti serve?"},
            ],
        )
    assert plan is not None and plan.source == "llm-answer"
    assert "lavoro fiscale" in plan.summary


@pytest.mark.asyncio
async def test_broken_or_chatty_answers_do_not_crash():
    fenced = await ask('```json\n{"understood": false, "question": "Quanto?"}\n```')
    assert fenced is not None and fenced.summary == "Quanto?"
    invalid = await ask("non ho capito niente")
    assert invalid is not None and invalid.source == "llm-error"
    assert invalid.diagnostic == {
        "code": "invalid_response",
        "detail": "risposta del provider priva di un piano JSON valido",
    }
    assert await ask('{"understood": true, "tasks": []}') is not None


@pytest.mark.asyncio
async def test_provider_refusing_json_mode_is_retried_without_it():
    seen: list[bool] = []

    def picky(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        asked_json = "response_format" in body
        seen.append(asked_json)
        if asked_json:
            return httpx.Response(400, json={"error": "response_format non supportato"})
        reply = json.dumps({"understood": False, "question": "Per quale cliente?"})
        return httpx.Response(200, json={"choices": [{"message": {"content": reply}}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(picky)) as client:
        plan = await plan_with_llm(
            "fai quella cosa",
            base_url="https://api.x.ai/v1",
            api_key="chiave-finta",
            model="grok-4.6",
            client=client,
        )
    assert seen == [True, False]
    assert plan is not None
    assert plan.summary == "Per quale cliente?"


@pytest.mark.asyncio
async def test_no_key_means_no_call():
    async with fake_model("{}") as client:
        assert (
            await plan_with_llm(
                "ciao",
                base_url="https://modello.esempio/v1",
                api_key="",
                model="modello-test",
                client=client,
            )
            is None
        )


@pytest.mark.asyncio
async def test_model_down_is_reported_instead_of_falling_back_silently():
    def broken(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "giù"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(broken)) as client:
        plan = await plan_with_llm(
            "ciao",
            base_url="https://modello.esempio/v1",
            api_key="chiave-finta",
            model="modello-test",
            client=client,
        )
    assert plan is not None
    assert plan.source == "llm-error"
    assert plan.diagnostic and plan.diagnostic["code"] == "provider_unavailable"
    assert "Nessun lavoro" in plan.summary


def test_payload_without_json_is_rejected():
    assert parse_llm_payload("nessun json qui") is None
