"""
Create the patients and call_logs tables in Supabase.
Run once: python scripts/create_tables.py
"""
from dotenv import load_dotenv
import os, sys

load_dotenv(override=True)
from sqlalchemy import create_engine, text

url = os.environ["DATABASE_URL"]
engine = create_engine(url, connect_args={"connect_timeout": 15, "prepare_threshold": None})

SCHEMA = """
-- Enable UUID generation
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- -----------------------------------------------------------------------
-- patients
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.patients (
    patient_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    first_name          TEXT NOT NULL,
    last_name           TEXT NOT NULL,
    date_of_birth       DATE NOT NULL,
    sex                 TEXT NOT NULL CHECK (sex IN ('Male','Female','Other','Decline to Answer')),
    phone_number        CHAR(10) NOT NULL,
    email               TEXT,
    address_line_1      TEXT NOT NULL,
    address_line_2      TEXT,
    city                TEXT NOT NULL,
    state               CHAR(2) NOT NULL,
    zip_code            TEXT NOT NULL,
    insurance_provider  TEXT,
    insurance_member_id TEXT,
    preferred_language  TEXT NOT NULL DEFAULT 'English',
    emergency_contact_name  TEXT,
    emergency_contact_phone CHAR(10),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at          TIMESTAMPTZ
);

-- Unique active phone number
CREATE UNIQUE INDEX IF NOT EXISTS patients_phone_active_idx
    ON public.patients (phone_number)
    WHERE deleted_at IS NULL;

-- Auto-update updated_at on every row change
CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS patients_updated_at ON public.patients;
CREATE TRIGGER patients_updated_at
    BEFORE UPDATE ON public.patients
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

-- -----------------------------------------------------------------------
-- call_logs
-- -----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.call_logs (
    call_id     TEXT PRIMARY KEY,
    patient_id  UUID REFERENCES public.patients(patient_id) ON DELETE SET NULL,
    transcript  TEXT,
    summary     TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

try:
    with engine.begin() as conn:
        conn.execute(text(SCHEMA))
    print("✓ Tables created successfully.")
    print("  - public.patients")
    print("  - public.call_logs")
    print("  - Trigger: patients_updated_at")
    print("  - Index: patients_phone_active_idx")
except Exception as exc:
    print(f"✗ Failed: {exc}")
    sys.exit(1)
