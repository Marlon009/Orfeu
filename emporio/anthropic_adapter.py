"""Claude pelo SDK oficial da Anthropic, atrás da mesma interface que o agente já usa.

O agente fala o formato de chat da OpenAI (`client.chat.completions.create`). Este adaptador
traduz esse formato para a Messages API e de volta, para o agente não ter dois caminhos:
- mensagens `system` viram o `system` da requisição;
- `tool_calls` e mensagens `tool` viram blocos `tool_use` e `tool_result`;
- `response_format` com `json_schema` vira `output_config.format` (saída estruturada);
- a resposta original do Claude (incluindo blocos de raciocínio) é guardada e devolvida
  intacta na volta do loop de ferramentas, como a API exige.

`temperature` não é enviado: a API do Claude não aceita mais esse parâmetro.
"""
import json
from types import SimpleNamespace

MAX_TOKENS = 16000
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AnthropicChat:
    def __init__(self, client, effort: str = "low"):
        self.client = client
        self.effort = effort
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))
        self._raw_turns: dict[str, list] = {}  # id do 1º tool_use -> conteúdo original da resposta

    def _convert(self, messages: list[dict]) -> tuple[str, list[dict]]:
        system = [m["content"] for m in messages if m["role"] == "system" and m.get("content")]
        out: list[dict] = []
        for m in messages:
            role = m["role"]
            if role == "system":
                continue
            if role == "tool":
                block = {"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": m["content"]}
                # Todos os resultados de uma rodada vão numa única mensagem do usuário.
                if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list):
                    out[-1]["content"].append(block)
                else:
                    out.append({"role": "user", "content": [block]})
            elif role == "assistant" and m.get("tool_calls"):
                first_id = m["tool_calls"][0]["id"]
                if first_id in self._raw_turns:
                    out.append({"role": "assistant", "content": self._raw_turns[first_id]})
                else:
                    blocks = [{"type": "tool_use", "id": c["id"], "name": c["function"]["name"],
                               "input": json.loads(c["function"]["arguments"] or "{}")
                               if isinstance(c["function"]["arguments"], str) else c["function"]["arguments"]}
                              for c in m["tool_calls"]]
                    out.append({"role": "assistant", "content": blocks})
            elif m.get("content"):
                out.append({"role": role, "content": m["content"]})
        return "\n\n".join(system), out

    def create(self, model: str, messages: list[dict], tools: list[dict] | None = None,
               response_format: dict | None = None, temperature: float | None = None):
        system, converted = self._convert(messages)
        output_config: dict = {"effort": self.effort}
        if response_format and response_format.get("type") == "json_schema":
            output_config["format"] = {"type": "json_schema",
                                       "schema": response_format["json_schema"]["schema"]}
        kwargs = {"model": model, "max_tokens": MAX_TOKENS, "messages": converted,
                  "output_config": output_config}
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = [{"name": t["function"]["name"], "description": t["function"]["description"],
                                "input_schema": t["function"]["parameters"]} for t in tools]
        # Se o Claude recusar por política, a própria API tenta de novo com o modelo indicado.
        response = self.client.beta.messages.create(betas=[FALLBACK_BETA], fallbacks="default", **kwargs)

        if response.stop_reason == "refusal":
            # Conteúdo vazio: o agente responde com a mensagem segura.
            return _completion("", None)
        text = "".join(b.text for b in response.content if b.type == "text")
        calls = [SimpleNamespace(id=b.id, function=SimpleNamespace(name=b.name, arguments=json.dumps(b.input)))
                 for b in response.content if b.type == "tool_use"]
        if calls:
            self._raw_turns[calls[0].id] = response.content
        return _completion(text, calls or None)


def _completion(content: str, tool_calls):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=tool_calls))])
