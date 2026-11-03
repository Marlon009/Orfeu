import os
import tempfile
from pathlib import Path

# Os testes gravam reclamações/interesses; usam um banco descartável, nunca o de desenvolvimento.
os.environ["EMPORIO_DB"] = str(Path(tempfile.mkdtemp()) / "test.db")
