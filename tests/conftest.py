import os
import tempfile
from pathlib import Path

# Os testes gravam reclamações/interesses; usam um banco descartável, nunca o de desenvolvimento.
os.environ["EMPORIO_DB"] = str(Path(tempfile.mkdtemp()) / "test.db")
# Configuração e login do dono também vão para um diretório descartável.
os.environ["EMPORIO_SETTINGS"] = str(Path(tempfile.mkdtemp()) / "orfeu.env")
os.environ["EMPORIO_OWNER"] = str(Path(tempfile.mkdtemp()) / "dono.json")
