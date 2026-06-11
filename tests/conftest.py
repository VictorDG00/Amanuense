import pytest


@pytest.fixture(autouse=True)
def _llm_env(monkeypatch):
    """Agentes instanciam o LLMClient no __init__; os testes nunca chamam a
    API, mas o client exige uma chave e criaria o cache sqlite no repo."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("AMANUENSE_LLM_CACHE", "0")
