"""Provider endpoints: a Base URL belongs only to the active chat provider.

Saving a custom Base URL for OpenAI used to make a Gemini or Anthropic model
list request (and key check) send that provider's key to the OpenAI host.
"""

import core.providers
from core.providers import get_base_url, list_models, provider_key_check
from core.settings import PROVIDER_BASE_URLS

CUSTOM = "https://openai-proxy.example/v1"


def test_base_url_is_reused_only_for_its_own_provider():
    settings = {"provider": "openai", "base_url": f"{CUSTOM}/"}

    assert get_base_url("openai", settings) == CUSTOM
    assert get_base_url("gemini", settings) == PROVIDER_BASE_URLS["gemini"]
    assert get_base_url("anthropic", settings) == PROVIDER_BASE_URLS["anthropic"]
    assert get_base_url("hf", settings) == PROVIDER_BASE_URLS["hf"]


def test_base_url_is_kept_when_the_provider_matches():
    settings = {"provider": "gemini", "base_url": "https://gemini-proxy.example"}

    assert get_base_url("gemini", settings) == "https://gemini-proxy.example"


def test_model_discovery_uses_the_requested_provider_endpoint(monkeypatch):
    calls = []

    def fake_models_get(url, *, timeout, headers=None, params=None):
        calls.append(url)

        class FakeResponse:
            def json(self):
                return {
                    "models": [
                        {
                            "name": "models/gemini-2.5-flash",
                            "displayName": "Gemini 2.5 Flash",
                            "supportedGenerationMethods": ["generateContent"],
                        }
                    ]
                }

        return FakeResponse()

    monkeypatch.setattr(core.providers, "provider_models_get", fake_models_get)
    settings = {
        "provider": "openai",
        "base_url": CUSTOM,
        "api_keys": {"gemini": "g" * 25},
    }

    assert list_models("gemini", settings) == [
        {"id": "gemini-2.5-flash", "name": "Gemini 2.5 Flash"}
    ]
    assert calls == [f"{PROVIDER_BASE_URLS['gemini']}/models"]


def test_key_check_uses_the_requested_provider_endpoint(monkeypatch):
    core.providers.STATUS_CACHE.clear()
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)

        class FakeResponse:
            status_code = 200
            ok = True

        return FakeResponse()

    monkeypatch.setattr(core.providers.requests, "get", fake_get)
    settings = {
        "provider": "openai",
        "base_url": CUSTOM,
        "api_keys": {"gemini": "g" * 25},
    }

    result = provider_key_check("gemini", settings)

    assert result["ready"] is True
    assert calls == [f"{PROVIDER_BASE_URLS['gemini']}/models"]
