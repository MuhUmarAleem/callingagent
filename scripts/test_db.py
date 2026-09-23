"""Quick DB connectivity and schema check."""
from dotenv import load_dotenv
import os, sys

load_dotenv(override=True)

from sqlalchemy import create_engine, text

url = os.environ.get("DATABASE_URL", "")
if not url:
    print("ERROR: DATABASE_URL not set in .env")
    sys.exit(1)

host_part = url.split("@")[-1]
print(f"Connecting to: {host_part}")

engine = create_engine(
    url,
    pool_pre_ping=True,
    connect_args={"connect_timeout": 15, "prepare_threshold": None},
)

try:
    with engine.connect() as conn:
        row = conn.execute(text("SELECT current_database(), current_user, version()")).fetchone()
        print("✓ Connection: SUCCESS")
        print(f"  Database : {row[0]}")
        print(f"  User     : {row[1]}")
        print(f"  PG       : {row[2][:70]}")

        tables = conn.execute(text("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_name IN ('patients', 'call_logs')
            ORDER BY table_name
        """)).fetchall()

        found = [t[0] for t in tables]
        print(f"  Tables   : {found}")

        if "patients" not in found:
            print("  WARNING: 'patients' table not found — run the Supabase SQL setup first")
        else:
            cnt = conn.execute(
                text("SELECT COUNT(*) FROM public.patients WHERE deleted_at IS NULL")
            ).scalar()
            print(f"  Active patients: {cnt}")

        if "call_logs" not in found:
            print("  WARNING: 'call_logs' table not found")
        else:
            log_cnt = conn.execute(text("SELECT COUNT(*) FROM public.call_logs")).scalar()
            print(f"  Call logs: {log_cnt}")

        print("\n✓ Database is healthy and ready.")

except Exception as exc:
    print(f"\n✗ Connection FAILED: {exc}")
    sys.exit(1)
