"""Modo restrito: o LLM só preenche um formulário JSON, e o código executa.

O schema e a lista de intenções saem do registro de ferramentas (`tool_specs`), então
uma ferramenta nova entra aqui sem mudar este módulo. A saída é forçada ao schema pelo
servidor (`response_format`), e cada campo copiado da mensagem é conferido literalmente:
número de pedido, contato ou valor que não estão no texto do cliente são descartados.
"""
import json
import re

from .rules import normalize

# Intenções que não são ferramentas: o código responde sem consultar nada.
SPECIAL_INTENTS = {
    "acessorio": "pede acessório (cordas, palhetas, cabos, cases, pedais, amplificadores)",
    "fora_de_escopo": "assunto sem relação com a loja ou com instrumentos (receitas, política, programação...)",
    "conversa": "só saudação, agradecimento ou despedida",
}
# Registrar interesse é automático no modo restrito: não depende do modelo lembrar.
AUTOMATIC_TOOLS = {"registrar_interesse"}

EXAMPLES = """Exemplos:
"Quanto custa o Yamaha C40?" -> {"intencoes": ["buscar_produtos"], "termo": "Yamaha C40"}
"violões até 800 reais" -> {"intencoes": ["buscar_produtos"], "categoria": "Violões", "preco_max": 800}
"qual o endereço e o horário?" -> {"intencoes": ["consultar_politica"], "topico": "loja"}
"posso parcelar em 10x?" -> {"intencoes": ["consultar_politica"], "topico": "pagamento"}
"quero devolver o pedido 12, email ana@x.com" -> {"intencoes": ["consultar_pedido", "consultar_politica"], "numero_pedido": 12, "email_ou_telefone": "ana@x.com", "topico": "trocas_devolucoes"}
"cadê meu pedido?" -> {"intencoes": ["consultar_pedido"]}
"vocês têm palheta?" -> {"intencoes": ["acessorio"]}
"me conta uma piada" -> {"intencoes": ["fora_de_escopo"]}
"oi, bom dia!" -> {"intencoes": ["conversa"]}"""


class Interpreter:
    def __init__(self, specs: list[dict]):
        self.tools = {s["function"]["name"]: s["function"] for s in specs
                      if s["function"]["name"] not in AUTOMATIC_TOOLS}
        fields = {}
        for fn in self.tools.values():
            fields.update(fn["parameters"]["properties"])
        fields.pop("descricao", None)  # a reclamação usa a própria mensagem do cliente
        self.fields = fields
        intents = list(self.tools) + list(SPECIAL_INTENTS)
        self.schema = {
            "type": "object",
            "properties": {"intencoes": {"type": "array", "minItems": 1, "maxItems": 3,
                                         "items": {"type": "string", "enum": intents}},
                           **fields},
            "required": ["intencoes"],
            "additionalProperties": False,
        }
        lines = [f"- {name}: {fn['description']}" for name, fn in self.tools.items()]
        lines += [f"- {name}: {text}" for name, text in SPECIAL_INTENTS.items()]
        field_lines = [f"- {k}: {v.get('description', '')}{' (opções: ' + ', '.join(v['enum']) + ')' if 'enum' in v else ''}"
                       for k, v in fields.items()]
        self.prompt = (
            "Você classifica mensagens de clientes de uma loja de instrumentos musicais e preenche um JSON. "
            "Não responda ao cliente.\n\nIntenções (uma ou mais):\n" + "\n".join(lines)
            + "\n\nCampos (preencha só o que estiver escrito na mensagem; não invente):\n" + "\n".join(field_lines)
            + "\n\n" + EXAMPLES)

    def request(self, user_text: str, context: list[str]) -> dict:
        content = user_text if not context else (
            "Mensagens anteriores do cliente: " + " | ".join(context) + f"\nMensagem atual: {user_text}")
        return {"messages": [{"role": "system", "content": self.prompt}, {"role": "user", "content": content}],
                "response_format": {"type": "json_schema",
                                    "json_schema": {"name": "intencao", "schema": self.schema, "strict": True}}}

    def ground(self, raw: str, user_texts: list[str]) -> dict:
        """Valida o JSON e descarta campos que não aparecem no que o cliente escreveu."""
        data = json.loads(raw)
        said = normalize(" ".join(user_texts))
        digits_said = re.findall(r"\d+", said)
        number = data.get("numero_pedido")
        if number is not None and str(number) not in digits_said:
            data.pop("numero_pedido")
        price = data.get("preco_max")
        if price is not None and not any(abs(float(d) - float(price)) < 1 for d in digits_said):
            data.pop("preco_max")
        contact = data.get("email_ou_telefone")
        if contact:
            contact_digits = "".join(c for c in contact if c.isdigit())
            in_text = normalize(contact) in said or (len(contact_digits) >= 8 and contact_digits in "".join(digits_said))
            if not in_text:
                data.pop("email_ou_telefone")
        data["intencoes"] = list(dict.fromkeys(data.get("intencoes") or ["conversa"]))
        return data

    def calls(self, data: dict) -> list[tuple[str, dict]]:
        """Uma chamada por intenção que é ferramenta, com os campos que ela aceita."""
        out = []
        for intent in data["intencoes"]:
            if intent in self.tools:
                accepted = self.tools[intent]["parameters"]["properties"]
                out.append((intent, {k: v for k, v in data.items() if k in accepted and v not in ("", None)}))
        return out
