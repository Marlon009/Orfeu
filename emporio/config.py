import os
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
POLICIES_DIR = ROOT / "data" / "policies"
DB_PATH = Path(os.getenv("EMPORIO_DB", ROOT / "data" / "emporio.db"))

# Qualquer servidor compatível com a API da OpenAI (Ollama, vLLM, OpenAI...).
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:11434/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "ollama")
LLM_MODEL = os.getenv("LLM_MODEL", "huihui_ai/qwen2.5-abliterate:latest")
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0"))
# "livre" (function calling) ou "restrito" (formulário JSON validado); ver agent.py.
AGENT_MODE = os.getenv("EMPORIO_MODE", "livre")

# Os dados são um snapshot que termina em março/2026, então "hoje" é configurável
# para que prazos (devolução, garantia, atraso de entrega) façam sentido.
REFERENCE_DATE = date.fromisoformat(os.getenv("EMPORIO_TODAY", "2026-03-25"))

LOW_STOCK_THRESHOLD = int(os.getenv("LOW_STOCK_THRESHOLD", "2"))
HISTORY_TURNS = int(os.getenv("HISTORY_TURNS", "6"))
