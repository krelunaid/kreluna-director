import json

import httpx
import pytest
from app.config import Settings, settings
from app.services.ai import check_ai_health
from app.services.planning import plan_message


def test_provider_configs_keep_credentials_and_models_separate():
    configured = Settings(
        _env_file=None,
        kreluna_llm_provider="grok",
        kreluna_grok_api_key="grok-key",
        kreluna_grok_model="grok-model",
        kreluna_openai_api_key="openai-key",
        kreluna_openai_model="openai-model",
        kreluna_ollama_model="llama-local",
    )

    grok = configured.ai_provider_config("grok")
    openai = configured.ai_provider_config("openai")
    ollama = configured.ai_provider_config("ollama")
    assert (grok.api_key, grok.model) == ("grok-key", "grok-model")
    assert (openai.api_key, openai.model) == ("openai-key", "openai-model")
    assert ollama.configured and ollama.api_key == ""


@pytest.mark.asyncio
async def test_health_check_verifies_the_configured_model():
    config = Settings(
        _env_file=None,
        kreluna_openai_api_key="openai-key",
        kreluna_openai_model="model-present",
    ).ai_provider_config("openai")

    def healthy(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/models"
        assert request.headers["Authorization"] == "Bearer openai-key"
        return httpx.Response(200, json={"data": [{"id": "model-present"}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(healthy)) as client:
        result = await check_ai_health(config, client=client, force=True)
    assert result["connected"] is True
    assert result["status"] == "connected"


@pytest.mark.asyncio
async def test_health_check_reports_a_missing_model():
    config = Settings(
        _env_file=None,
        kreluna_grok_api_key="grok-key",
        kreluna_grok_model="configured-model",
    ).ai_provider_config("grok")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, json={"data": [{"id": "different-model"}]})
        )
    ) as client:
        result = await check_ai_health(config, client=client, force=True)
    assert result["connected"] is False
    assert result["status"] == "model_missing"


@pytest.mark.asyncio
async def test_ollama_health_uses_local_tags_without_an_api_key():
    config = Settings(
        _env_file=None,
        kreluna_ollama_model="llama3.2",
    ).ai_provider_config("ollama")

    def healthy(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/tags"
        assert "Authorization" not in request.headers
        return httpx.Response(200, json={"models": [{"name": "llama3.2:latest"}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(healthy)) as client:
        result = await check_ai_health(config, client=client, force=True)
    assert result["connected"] is True


@pytest.mark.asyncio
async def test_planner_uses_the_selected_providers_matching_model(monkeypatch):
    monkeypatch.setattr(settings, "kreluna_grok_base_url", "https://api.x.ai/v1")
    monkeypatch.setattr(settings, "kreluna_grok_api_key", "grok-key")
    monkeypatch.setattr(settings, "kreluna_grok_model", "grok-model")

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert request.url.host == "api.x.ai"
        assert request.headers["Authorization"] == "Bearer grok-key"
        assert body["model"] == "grok-model"
        reply = {"understood": False, "question": "Per quale cliente?"}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(reply)}}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        plan = await plan_message("organizza quella pratica", client=client, provider="grok")
    assert plan.source == "llm-ask"
