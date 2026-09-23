"""
REST API for patient records.

All responses use the envelope:
  Success: {"data": ..., "error": null}
  Error:   {"data": null, "error": {"code": str, "message": str, "fields": {...}}}

Soft-deleted patients are excluded from all operations.
Optional API key enforcement on mutating endpoints.
"""
import logging
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from pydantic import BaseModel

from app.config import get_settings
from app.db import get_db
from app.services import (
    create_patient,
    find_by_phone,
    get_patient,
    list_patients,
    phone_exists_for_different_patient,
    soft_delete_patient,
    update_patient,
)
from app.validation import validate_date_of_birth, validate_patient, validate_phone_number

logger = logging.getLogger(__name__)

router = APIRouter(tags=["patients"])


# ---------------------------------------------------------------------------
# Envelope helpers
# ---------------------------------------------------------------------------


def ok(data: Any, status_code: int = 200):
    from fastapi.responses import JSONResponse
    return JSONResponse(content={"data": data, "error": None}, status_code=status_code)


def err(code: str, message: str, fields: Optional[Dict] = None, status_code: int = 400):
    from fastapi.responses import JSONResponse
    return JSONResponse(
        content={
            "data": None,
            "error": {
                "code": code,
                "message": message,
                "fields": fields or {},
            },
        },
        status_code=status_code,
    )


# ---------------------------------------------------------------------------
# API key guard
# ---------------------------------------------------------------------------


def check_api_key(x_api_key: Optional[str] = Header(default=None)):
    settings = get_settings()
    if settings.api_key:
        if x_api_key != settings.api_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing x-api-key header.",
            )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/health")
def health_check():
    """Health check. Verifies DB connectivity."""
    from app.db import check_db_health
    db_ok = check_db_health()
    if db_ok:
        return ok({"status": "ok", "db": "ok"})
    return err("db_down", "Database is unreachable.", status_code=503)


@router.get("/patients")
def list_patients_route(
    last_name: Optional[str] = Query(default=None),
    date_of_birth: Optional[str] = Query(default=None),
    phone_number: Optional[str] = Query(default=None),
):
    """List patients with optional filters."""
    dob_filter = None
    phone_filter = None

    if date_of_birth:
        try:
            dob_filter = validate_date_of_birth(date_of_birth)
        except ValueError as e:
            return err("bad_filter", f"Invalid date_of_birth filter: {e}", status_code=400)

    if phone_number:
        try:
            phone_filter = validate_phone_number(phone_number)
        except ValueError as e:
            return err("bad_filter", f"Invalid phone_number filter: {e}", status_code=400)

    with get_db() as db:
        patients = list_patients(db, last_name=last_name, date_of_birth=dob_filter, phone_number=phone_filter)

    return ok(patients)


@router.get("/patients/{patient_id}")
def get_patient_route(patient_id: str):
    """Get a single patient by UUID."""
    try:
        uuid.UUID(patient_id)
    except ValueError:
        return err("bad_uuid", "That is not a valid patient ID.", status_code=400)

    with get_db() as db:
        patient = get_patient(db, patient_id)

    if patient is None:
        return err("not_found", "Patient not found.", status_code=404)

    return ok(patient)


@router.post("/patients", dependencies=[Depends(check_api_key)])
def create_patient_route(request: Request, body: Dict[str, Any]):
    """Create a new patient record."""
    clean, errors = validate_patient(body, partial=False)

    if errors:
        return err(
            "validation_error",
            "One or more fields are invalid.",
            fields=errors,
            status_code=422,
        )

    # Check for duplicate phone
    with get_db() as db:
        existing = find_by_phone(db, clean["phone_number"])
        if existing:
            return err(
                "duplicate_phone",
                f"A patient with this phone number is already registered as "
                f"{existing['first_name']} {existing['last_name']}.",
                status_code=409,
            )

        try:
            patient = create_patient(db, clean)
        except Exception as exc:
            # Handle DB-level unique constraint violation
            msg = str(exc).lower()
            if "unique" in msg or "duplicate" in msg:
                return err("duplicate_phone", "A patient with this phone number already exists.", status_code=409)
            logger.exception("Unexpected error creating patient")
            raise

    logger.info("Patient created patient_id=%s", patient["patient_id"])
    return ok(patient, status_code=201)


@router.put("/patients/{patient_id}", dependencies=[Depends(check_api_key)])
def update_patient_route(patient_id: str, body: Dict[str, Any]):
    """Partial update of a patient record."""
    try:
        uuid.UUID(patient_id)
    except ValueError:
        return err("bad_uuid", "That is not a valid patient ID.", status_code=400)

    clean, errors = validate_patient(body, partial=True)

    if errors:
        return err(
            "validation_error",
            "One or more fields are invalid.",
            fields=errors,
            status_code=422,
        )

    # If phone is being updated, check for conflicts
    if "phone_number" in clean:
        with get_db() as db:
            conflict = phone_exists_for_different_patient(db, clean["phone_number"], patient_id)
            if conflict:
                return err(
                    "duplicate_phone",
                    f"This phone number already belongs to "
                    f"{conflict['first_name']} {conflict['last_name']}.",
                    status_code=409,
                )

    with get_db() as db:
        # Verify patient exists
        existing = get_patient(db, patient_id)
        if existing is None:
            return err("not_found", "Patient not found.", status_code=404)

        try:
            updated = update_patient(db, patient_id, clean)
        except Exception as exc:
            msg = str(exc).lower()
            if "unique" in msg or "duplicate" in msg:
                return err("duplicate_phone", "A patient with this phone number already exists.", status_code=409)
            logger.exception("Unexpected error updating patient")
            raise

    if updated is None:
        return err("not_found", "Patient not found.", status_code=404)

    return ok(updated)


@router.delete("/patients/{patient_id}", dependencies=[Depends(check_api_key)])
def delete_patient_route(patient_id: str):
    """Soft-delete a patient (sets deleted_at)."""
    try:
        uuid.UUID(patient_id)
    except ValueError:
        return err("bad_uuid", "That is not a valid patient ID.", status_code=400)

    with get_db() as db:
        deleted = soft_delete_patient(db, patient_id)

    if not deleted:
        return err("not_found", "Patient not found.", status_code=404)

    return ok({"deleted": True, "patient_id": patient_id})
