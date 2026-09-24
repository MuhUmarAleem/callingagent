"""
Idempotent Postgres schema used by startup and scripts/create_tables.py.

Statements are separate because psycopg cannot run a multi-statement script
in a single execute() call.
"""

SCHEMA_STATEMENTS = [
    'CREATE EXTENSION IF NOT EXISTS "pgcrypto"',
    """
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
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS patients_phone_active_idx
        ON public.patients (phone_number)
        WHERE deleted_at IS NULL
    """,
    """
    CREATE OR REPLACE FUNCTION public.set_updated_at()
    RETURNS TRIGGER LANGUAGE plpgsql AS $$
    BEGIN
        NEW.updated_at = now();
        RETURN NEW;
    END;
    $$
    """,
    "DROP TRIGGER IF EXISTS patients_updated_at ON public.patients",
    """
    CREATE TRIGGER patients_updated_at
        BEFORE UPDATE ON public.patients
        FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()
    """,
    """
    CREATE TABLE IF NOT EXISTS public.call_logs (
        call_id     TEXT PRIMARY KEY,
        patient_id  UUID REFERENCES public.patients(patient_id) ON DELETE SET NULL,
        transcript  TEXT,
        summary     TEXT,
        created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS public.call_drafts (
        call_id    TEXT PRIMARY KEY,
        fields     JSONB NOT NULL DEFAULT '{}'::jsonb,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
]
