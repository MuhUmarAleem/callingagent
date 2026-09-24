"""
Create the patients and call_logs tables in Postgres.
Run once: python scripts/create_tables.py
"""
from dotenv import load_dotenv
import os
import sys

load_dotenv(override=True)
from sqlalchemy import create_engine, text

from app.config import normalize_database_url
from app.schema import SCHEMA_STATEMENTS

url = normalize_database_url(os.environ["DATABASE_URL"])
engine = create_engine(url, connect_args={"connect_timeout": 15, "prepare_threshold": None})

try:
    with engine.begin() as conn:
        for stmt in SCHEMA_STATEMENTS:
            conn.execute(text(stmt))
    print("OK Tables created successfully.")
    print("  - public.patients")
    print("  - public.call_logs")
    print("  - Trigger: patients_updated_at")
    print("  - Index: patients_phone_active_idx")
except Exception as exc:
    print(f"FAILED: {exc}")
    sys.exit(1)
