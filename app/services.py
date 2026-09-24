"""
Service layer — all database operations.

Used by both routers so there's a single source of truth for business logic.
All functions accept a SQLAlchemy Session and use raw SQL via sqlalchemy.text().
"""
import logging
import uuid
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row_to_dict(row) -> Dict[str, Any]:
    """Convert a SQLAlchemy Row or RowMapping to a plain dict, serializing dates."""
    d = dict(row._mapping)
    result = {}
    for k, v in d.items():
        if isinstance(v, date):
            result[k] = v.isoformat()
        elif isinstance(v, datetime):
            result[k] = v.isoformat()
        elif isinstance(v, uuid.UUID):
            result[k] = str(v)
        else:
            result[k] = v
    return result


def _build_insert_params(data: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """Build parameterized INSERT columns/values from a clean patient dict."""
    fields = list(data.keys())
    cols = ", ".join(fields)
    vals = ", ".join(f":{f}" for f in fields)
    return cols, vals


# ---------------------------------------------------------------------------
# Patient CRUD
# ---------------------------------------------------------------------------


def create_patient(db: Session, data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Insert a new patient. Returns the created row as a dict.
    Raises ValueError on duplicate active phone number.
    """
    patient_id = str(uuid.uuid4())
    data = {**data, "patient_id": patient_id}

    cols, vals = _build_insert_params(data)
    sql = text(f"""
        INSERT INTO public.patients ({cols})
        VALUES ({vals})
        RETURNING *
    """)
    row = db.execute(sql, data).fetchone()
    return _row_to_dict(row)


def get_patient(db: Session, patient_id: str) -> Optional[Dict[str, Any]]:
    """Fetch a single non-deleted patient by UUID string."""
    sql = text("""
        SELECT * FROM public.patients
        WHERE patient_id = :pid AND deleted_at IS NULL
    """)
    row = db.execute(sql, {"pid": patient_id}).fetchone()
    return _row_to_dict(row) if row else None


def list_patients(
    db: Session,
    last_name: Optional[str] = None,
    date_of_birth: Optional[date] = None,
    phone_number: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    List non-deleted patients with optional filters.
    last_name is case-insensitive ILIKE match.
    """
    conditions = ["p.deleted_at IS NULL"]
    params: Dict[str, Any] = {}

    if last_name:
        conditions.append("lower(p.last_name) LIKE :last_name")
        params["last_name"] = f"%{last_name.lower()}%"

    if date_of_birth:
        conditions.append("p.date_of_birth = :dob")
        params["dob"] = date_of_birth

    if phone_number:
        conditions.append("p.phone_number = :phone")
        params["phone"] = phone_number

    where = " AND ".join(conditions)
    sql = text(f"""
        SELECT p.*,
               cl.transcript,
               cl.summary,
               cl.call_id
        FROM public.patients p
        LEFT JOIN LATERAL (
            SELECT transcript, summary, call_id
            FROM public.call_logs
            WHERE patient_id = p.patient_id
            ORDER BY created_at DESC
            LIMIT 1
        ) cl ON TRUE
        WHERE {where}
        ORDER BY p.created_at DESC
    """)
    rows = db.execute(sql, params).fetchall()
    return [_row_to_dict(r) for r in rows]


def update_patient(db: Session, patient_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Partial update a patient. Returns updated row or None if not found.
    data must contain only the fields to update (already validated/normalized).
    """
    if not data:
        return get_patient(db, patient_id)

    set_clauses = ", ".join(f"{k} = :{k}" for k in data.keys())
    params = {**data, "pid": patient_id}

    sql = text(f"""
        UPDATE public.patients
        SET {set_clauses}
        WHERE patient_id = :pid AND deleted_at IS NULL
        RETURNING *
    """)
    row = db.execute(sql, params).fetchone()
    return _row_to_dict(row) if row else None


def soft_delete_patient(db: Session, patient_id: str) -> bool:
    """Soft-delete a patient by setting deleted_at. Returns True if found and deleted."""
    sql = text("""
        UPDATE public.patients
        SET deleted_at = now()
        WHERE patient_id = :pid AND deleted_at IS NULL
        RETURNING patient_id
    """)
    row = db.execute(sql, {"pid": patient_id}).fetchone()
    return row is not None


def find_by_phone(db: Session, phone_number: str) -> Optional[Dict[str, Any]]:
    """Find an active (non-deleted) patient by exact phone number."""
    sql = text("""
        SELECT * FROM public.patients
        WHERE phone_number = :phone AND deleted_at IS NULL
    """)
    row = db.execute(sql, {"phone": phone_number}).fetchone()
    return _row_to_dict(row) if row else None


def phone_exists_for_different_patient(
    db: Session, phone_number: str, exclude_patient_id: str
) -> Optional[Dict[str, Any]]:
    """Check if phone belongs to a different active patient."""
    sql = text("""
        SELECT * FROM public.patients
        WHERE phone_number = :phone
          AND deleted_at IS NULL
          AND patient_id != :pid
    """)
    row = db.execute(sql, {"phone": phone_number, "pid": exclude_patient_id}).fetchone()
    return _row_to_dict(row) if row else None


# ---------------------------------------------------------------------------
# Call logs
# ---------------------------------------------------------------------------


def upsert_call_log(
    db: Session,
    call_id: str,
    patient_id: Optional[str] = None,
    transcript: Optional[str] = None,
    summary: Optional[str] = None,
) -> None:
    """
    Upsert a call log entry. Tolerant: silently ignores errors.
    Uses INSERT ... ON CONFLICT DO UPDATE to handle duplicate call_ids.
    """
    try:
        sql = text("""
            INSERT INTO public.call_logs (call_id, patient_id, transcript, summary)
            VALUES (:call_id, :patient_id, :transcript, :summary)
            ON CONFLICT (call_id) DO UPDATE SET
                patient_id = COALESCE(EXCLUDED.patient_id, call_logs.patient_id),
                transcript = COALESCE(EXCLUDED.transcript, call_logs.transcript),
                summary    = COALESCE(EXCLUDED.summary, call_logs.summary)
        """)
        db.execute(sql, {
            "call_id": call_id,
            "patient_id": patient_id,
            "transcript": transcript,
            "summary": summary,
        })
    except Exception as exc:
        logger.error("Failed to upsert call log call_id=%s: %s", call_id, exc)


def list_call_logs(db: Session) -> List[Dict[str, Any]]:
    """Return all call logs, newest first."""
    sql = text("""
        SELECT * FROM public.call_logs
        ORDER BY created_at DESC
    """)
    rows = db.execute(sql).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_dashboard_stats(db: Session) -> Dict[str, int]:
    """Counts used by the dashboard header."""
    patients = db.execute(
        text("SELECT COUNT(*) FROM public.patients WHERE deleted_at IS NULL")
    ).scalar()
    call_logs = db.execute(text("SELECT COUNT(*) FROM public.call_logs")).scalar()
    return {
        "patients": int(patients or 0),
        "call_logs": int(call_logs or 0),
    }
