import os
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
POLICIES_DIR = ROOT / "data" / "policies"
DB_PATH = Path(os.getenv("EMPORIO_DB", ROOT / "data" / "emporio.db"))

# Provedor do LLM: local (Ollama) ou API (OpenAI, Gemini, Anthropic). Cada um traz seus
# padrões; LLM_BASE_URL, LLM_MODEL e LLM_API_KEY, se definidos, têm prioridade.
# `python -m emporio.providers` diz o que falta para o provedor escolhido.
PROVIDERS = {
    "ollama": {"base_url": "http://localhost:11434/v1", "model": "huihui_ai/qwen2.5-abliterate:latest",
               "key_env": None, "package": "openai"},
    "openai": {"base_url": "https://api.openai.com/v1", "model": "", "key_env": "OPENAI_API_KEY",
               "package": "openai"},
    "gemini": {"base_url": "https://generativelanguage.googleapis.com/v1beta/openai/", "model": "",
               "key_env": "GEMINI_API_KEY", "package": "openai"},
    "anthropic": {"base_url": "", "model": "claude-opus-5-5", "key_env": "ANTHROPIC_API_KEY",
                  "package": "anthropic"},
}
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama")
if LLM_PROVIDER not in PROVIDERS:
    raise SystemExit(f"LLM_PROVIDER inválido: {LLM_PROVIDER!r}. Opções: {', '.join(PROVIDERS)}")
_provider = PROVIDERS[LLM_PROVIDER]
LLM_BASE_URL = os.getenv("LLM_BASE_URL", _provider["base_url"])
LLM_MODEL = os.getenv("LLM_MODEL", _provider["model"])
LLM_API_KEY = os.getenv("LLM_API_KEY") or os.getenv(_provider["key_env"] or "", "") or (
    "ollama" if LLM_PROVIDER == "ollama" else "")
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0"))  # não enviado ao Claude, que não aceita mais
LLM_EFFORT = os.getenv("LLM_EFFORT", "low")  # só Claude: esforço de raciocínio; "low" serve bem para chat
# "livre" (function calling) ou "restrito" (formulário JSON validado); ver agent.py.
AGENT_MODE = os.getenv("EMPORIO_MODE", "livre")

# Os dados são um snapshot que termina em março/2026, então "hoje" é configurável
# para que prazos (devolução, garantia, atraso de entrega) façam sentido.
REFERENCE_DATE = date.fromisoformat(os.getenv("EMPORIO_TODAY", "2026-03-25"))
TIMEZONE = ZoneInfo("America/Campo_Grande")


def now() -> datetime:
    """Data de referência com a hora real de Campo Grande; EMPORIO_NOW fixa as duas (testes e exemplos)."""
    fixed = os.getenv("EMPORIO_NOW")
    if fixed:
        return datetime.fromisoformat(fixed)
    return datetime.combine(REFERENCE_DATE, datetime.now(TIMEZONE).time().replace(microsecond=0))

LOW_STOCK_THRESHOLD = int(os.getenv("LOW_STOCK_THRESHOLD", "2"))
HISTORY_TURNS = int(os.getenv("HISTORY_TURNS", "6"))
