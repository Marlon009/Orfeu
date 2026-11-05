"""Bateria fechada do intérprete (modo restrito): nota automática, sem julgamento humano.

Cada caso diz quais intenções e campos o JSON precisa ter. Um caso passa quando:
- todas as intenções esperadas aparecem;
- nenhuma intenção proibida aparece: caso da loja não pode virar recusa, e recusa não
  pode chamar ferramenta (é o que impede "recusar tudo" ou "nunca recusar" de pontuar bem);
- os campos esperados batem, e os campos que o cliente não disse estão ausentes.

A reserva (`split: holdout`) só roda com --reserva, e cada uso fica registrado em
evals/reserva_usos.jsonl. Ela serve para decidir se uma mudança vai para produção, não
para ajustar o prompt: consultada muitas vezes, deixa de medir generalização.
"""
import argparse
import json
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from . import config, providers
from .db import connect
from .interpreter import SPECIAL_INTENTS, Interpreter
from .rules import normalize, tokens
from .tools import tool_specs

EVALS_DIR = config.ROOT / "evals"
REFUSALS = {"acessorio", "fora_de_escopo"}


def forbidden_intents(expected: list[str], all_intents: list[str]) -> set[str]:
    if set(expected) & REFUSALS:
        return set(all_intents) - set(SPECIAL_INTENTS)  # recusa não chama ferramenta
    if set(expected) - set(SPECIAL_INTENTS):
        return set(REFUSALS)  # pergunta da loja não pode ser recusada
    return set()


def field_matches(name: str, expected, got) -> bool:
    if got is None:
        return False
    if name == "termo":
        return set(tokens(str(expected))) <= set(tokens(str(got)))
    if name == "email_ou_telefone":
        digits = lambda s: "".join(c for c in s if c.isdigit())
        return normalize(expected) == normalize(got) or (digits(expected) and digits(expected) == digits(got))
    if isinstance(expected, (int, float)):
        try:
            return abs(float(got) - expected) < 0.01
        except (TypeError, ValueError):
            return False
    return normalize(str(expected)) == normalize(str(got))


def score(case: dict, raw: dict, grounded: dict, all_intents: list[str]) -> dict:
    got = set(grounded.get("intencoes", []))
    problems = []
    missing = set(case["intencoes"]) - got
    if missing:
        problems.append(f"faltou intenção {sorted(missing)}")
    wrong = got & forbidden_intents(case["intencoes"], all_intents)
    if wrong:
        problems.append(f"intenção proibida {sorted(wrong)}")
    for name, expected in case.get("campos", {}).items():
        if not field_matches(name, expected, grounded.get(name)):
            problems.append(f"{name}: esperado {expected!r}, veio {grounded.get(name)!r}")
    for name in case.get("sem_campos", []):
        if grounded.get(name) not in (None, ""):
            problems.append(f"{name} inventado: {grounded[name]!r}")
    # Campos que o modelo inventou e a conferência literal descartou: a rede de segurança agiu.
    dropped = sorted(k for k in raw if k not in grounded and k != "intencoes")
    return {"id": case["id"], "grupo": case["grupo"], "ok": not problems, "problemas": problems,
            "descartados": dropped, "saida": grounded}


def run(cases: list[dict], client, model: str) -> list[dict]:
    interpreter = Interpreter(tool_specs(connect()))
    all_intents = interpreter.schema["properties"]["intencoes"]["items"]["enum"]
    results = []
    for case in cases:
        context = case.get("contexto", [])
        req = interpreter.request(case["mensagem"], context)
        start = time.monotonic()
        try:
            content = client.chat.completions.create(
                model=model, temperature=config.LLM_TEMPERATURE, messages=req["messages"],
                response_format=req["response_format"]).choices[0].message.content
            raw = json.loads(content)
            grounded = interpreter.ground(content, context + [case["mensagem"]])
            result = score(case, raw, grounded, all_intents)
        except Exception as exc:  # erro conta como falha, nunca some do denominador
            result = {"id": case["id"], "grupo": case["grupo"], "ok": False,
                      "problemas": [f"erro: {exc}"], "descartados": [], "saida": None}
        result["segundos"] = round(time.monotonic() - start, 1)
        results.append(result)
        print(f"{'✅' if result['ok'] else '❌'} {case['id']:9} {result['segundos']:6.1f}s  "
              + "; ".join(result["problemas"]), flush=True)
    return results


def report(results: list[dict], model: str, split: str) -> str:
    by_group = defaultdict(list)
    for r in results:
        by_group[r["grupo"]].append(r)
    passed = sum(r["ok"] for r in results)
    lines = [f"# Bateria do intérprete — `{model}` — {split}", "",
             f"{datetime.now():%d/%m/%Y %H:%M} · temperatura {config.LLM_TEMPERATURE:g}", "",
             f"**Acerto: {passed}/{len(results)} ({passed / len(results):.0%})** · "
             f"tempo médio {sum(r['segundos'] for r in results) / len(results):.0f} s · "
             f"campos inventados descartados pela conferência: {sum(len(r['descartados']) for r in results)}",
             "", "| Grupo | Acerto |", "|---|---|"]
    lines += [f"| {g} | {sum(r['ok'] for r in rs)}/{len(rs)} |" for g, rs in sorted(by_group.items())]
    failures = [r for r in results if not r["ok"]]
    if failures:
        lines += ["", "## Falhas", ""]
        lines += [f"- `{r['id']}`: {'; '.join(r['problemas'])}" for r in failures]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Bateria fechada do intérprete do modo restrito")
    parser.add_argument("--reserva", action="store_true", help="roda a reserva (uso registrado)")
    parser.add_argument("--ids", nargs="*", help="roda só estes casos (para depurar)")
    args = parser.parse_args()

    split = "holdout" if args.reserva else "dev"
    cases = [json.loads(line) for line in (EVALS_DIR / "interpretador.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    cases = [c for c in cases if c["split"] == split and (not args.ids or c["id"] in args.ids)]
    if args.reserva:
        with open(EVALS_DIR / "reserva_usos.jsonl", "a", encoding="utf-8") as ledger:
            ledger.write(json.dumps({"quando": datetime.now().isoformat(timespec="seconds"),
                                     "modelo": config.LLM_MODEL}, ensure_ascii=False) + "\n")

    client = providers.make_client()
    results = run(cases, client, config.LLM_MODEL)
    text = report(results, config.LLM_MODEL, split)
    print("\n" + text)
    if not args.ids:
        out = EVALS_DIR / "resultados"
        out.mkdir(exist_ok=True)
        stem = f"{config.LLM_MODEL.replace(':', '_').replace('/', '_')}_{split}"
        (out / f"{stem}.md").write_text(text, encoding="utf-8")
        (out / f"{stem}.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
