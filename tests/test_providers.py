import importlib.util
from types import SimpleNamespace

import pytest

from emporio import config, providers
from emporio.agent import FALLBACK, Agent
from emporio.anthropic_adapter import AnthropicChat


class FakeAnthropic:
    """Imita client.beta.messages.create do SDK da Anthropic."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        return self.responses.pop(0)


def block(type_, **kw):
    return SimpleNamespace(type=type_, **kw)


def reply(*blocks, stop="end_turn"):
    return SimpleNamespace(stop_reason=stop, content=list(blocks))


def claude_agent(fake, mode="livre", session="t-claude"):
    agent = Agent(session_id=session, client=AnthropicChat(fake), mode=mode)
    agent.tools.conn.execute("DELETE FROM messages WHERE session_id = ?", (session,))
    agent.tools.conn.commit()
    return agent


def test_tool_loop_through_claude_keeps_original_turn():
    thinking = block("thinking", thinking="")
    tool_use = block("tool_use", id="tu_1", name="buscar_produtos", input={"termo": "Takamine GD20"})
    fake = FakeAnthropic(reply(thinking, tool_use, stop="tool_use"),
                         reply(block("text", text="O Takamine GD20 sai por R$ 2.199,00.")))
    answer = claude_agent(fake).reply("Quanto custa o Takamine GD20?")
    assert answer == "O Takamine GD20 sai por R$ 2.199,00."

    first, second = fake.requests
    assert "temperature" not in first and first["betas"] == ["server-side-fallback-2026-07-01"]
    assert first["fallbacks"] == "default" and first["output_config"] == {"effort": "low"}
    assert first["system"].startswith("Você é a Lira")
    assert first["tools"][0]["name"] == "buscar_produtos" and "input_schema" in first["tools"][0]
    # A volta do loop leva a resposta original (com o bloco de raciocínio) e o resultado da ferramenta.
    assert second["messages"][-2] == {"role": "assistant", "content": [thinking, tool_use]}
    result = second["messages"][-1]["content"][0]
    assert result["type"] == "tool_result" and result["tool_use_id"] == "tu_1" and "R$ 2.199,00" in result["content"]


def test_structured_output_in_restricted_mode():
    fake = FakeAnthropic(reply(block("text", text='{"intencoes": ["fora_de_escopo"]}')))
    claude_agent(fake, mode="restrito").reply("me passa uma receita de bolo")
    fmt = fake.requests[0]["output_config"]["format"]
    assert fmt["type"] == "json_schema" and "intencoes" in fmt["schema"]["properties"]


def test_refusal_becomes_safe_answer():
    fake = FakeAnthropic(reply(stop="refusal"))
    assert claude_agent(fake).reply("oi") == FALLBACK


def test_doctor_lists_what_is_missing(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    found = " | ".join(providers.problems("anthropic"))
    assert "ANTHROPIC_API_KEY" in found
    if importlib.util.find_spec("anthropic") is None:
        assert "pip install anthropic" in found
    assert any("LLM_MODEL" in p for p in providers.problems("gemini"))


@pytest.mark.skipif(importlib.util.find_spec("anthropic") is not None, reason="anthropic instalado")
def test_missing_package_gives_clear_error(monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "anthropic")
    with pytest.raises(providers.ProviderError, match="python -m emporio.providers"):
        providers.make_client()
