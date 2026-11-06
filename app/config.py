"""Runtime settings, read from environment variables with safe local defaults."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# PostgreSQL is the recommended database: postgresql+psycopg://user:pass@localhost:5432/fieldwise
# With no DATABASE_URL set, Fieldwise falls back to a local SQLite file so the demo runs with zero setup.
DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{ROOT / 'fieldwise.db'}")

HOST = os.environ.get("FIELDWISE_HOST", "127.0.0.1")  # localhost only unless you opt in
PORT = int(os.environ.get("FIELDWISE_PORT", "8000"))

# Signs the demo session cookie. Fine for a local demo; set your own value anywhere else.
SECRET_KEY = os.environ.get("FIELDWISE_SECRET", "fieldwise-local-demo-secret")
