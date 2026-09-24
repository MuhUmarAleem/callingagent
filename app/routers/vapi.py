"""
Vapi voice tool endpoints.

POST /vapi/tools  — handles tool-calls from the Vapi voice agent
POST /vapi/webhook — handles end-of-call-report and other events (P1)

Vapi request format (tool-calls):
  {
    "message": {
      "type": "tool-calls",
      "call": {"id": "..."},
      "toolCallList": [              <- primary format
        {
          "id": "...",
          "type": "function",
          "function": {"name": "...", "arguments": {...} or "<json string>"}
        }
      ]
      // OR
      "toolCalls": [...]              <- alternate format, same structure
    }
  }

Response (always HTTP 200):
  {"results": [{"toolCallId": "...", "result": "<single-line string>"}]}
"""
import hmac
import json
import logging
import re
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.db import get_db
from app.services import (
    create_patient,
    find_by_phone,
    get_call_draft,
    get_patient,
    merge_call_draft,
    phone_exists_for_different_patient,
    update_patient,
    upsert_call_log,
)
from app.validation import validate_field, validate_patient, validate_phone_number

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/vapi", tags=["vapi"])


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def _extract_provided_secret(
    x_vapi_secret: Optional[str],
    authorization: Optional[str],
) -> Optional[str]:
    """Accept either x-vapi-secret or Authorization: Bearer <token> (Vapi default)."""
    if x_vapi_secret:
        return x_vapi_secret
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() == "bearer" and token:
        return token.strip()
    return authorization.strip() or None


def _check_secret(provided: Optional[str]) -> bool:
    settings = get_settings()
    secret = settings.vapi_shared_secret
    if not secret:
        logger.warning("VAPI_SHARED_SECRET is not set — skipping authentication check.")
        return True
    if not provided:
        return False
    try:
        return hmac.compare_digest(provided, secret)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Request parsing helpers
# ---------------------------------------------------------------------------


def _parse_arguments(raw: Any) -> Dict[str, Any]:
    """Parse tool arguments whether they arrive as dict or JSON string."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            result = json.loads(raw)
            if isinstance(result, dict):
                return result
        except (json.JSONDecodeError, ValueError):
            pass
    return {}


def _normalize_tool_name(name: str) -> str:
    key = re.sub(r"[^a-z0-9]", "", (name or "").lower())
    return {
        "validatefield": "validate_field",
        "lookupbyphone": "lookup_by_phone",
        "savepatient": "save_patient",
        "updatepatient": "update_patient",
    }.get(key, name)


def _normalize_one_tool(item: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(item, dict):
        return None
    nested = item.get("toolCall")
    if isinstance(nested, dict):
        item = nested
    func = item.get("function") if isinstance(item.get("function"), dict) else {}
    name = func.get("name") or item.get("name") or ""
    raw_args = (
        func.get("arguments")
        or func.get("parameters")
        or item.get("arguments")
        or item.get("parameters")
        or {}
    )
    if not name:
        return None
    return {
        "id": item.get("id") or func.get("id") or "",
        "name": _normalize_tool_name(str(name)),
        "arguments": _parse_arguments(raw_args),
    }


def _extract_tool_calls(message: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Extract tool calls from every Vapi payload shape we have seen:
    toolCallList, toolCalls, toolWithToolCallList, functionCall.
    """
    raw_calls: List[Any] = []
    for key in ("toolCallList", "toolCalls"):
        value = message.get(key)
        if isinstance(value, list) and value:
            raw_calls = value
            break

    if not raw_calls:
        bundled = message.get("toolWithToolCallList")
        if isinstance(bundled, list):
            raw_calls = bundled

    if not raw_calls:
        singular = message.get("functionCall") or message.get("toolCall")
        if isinstance(singular, dict):
            raw_calls = [singular]

    artifact = message.get("artifact")
    if not raw_calls and isinstance(artifact, dict):
        for key in ("toolCallList", "toolCalls"):
            value = artifact.get(key)
            if isinstance(value, list) and value:
                raw_calls = value
                break

    normalized = []
    seen = set()
    for item in raw_calls:
        parsed = _normalize_one_tool(item)
        if not parsed:
            continue
        marker = (parsed["id"], parsed["name"], json.dumps(parsed["arguments"], sort_keys=True, default=str))
        if marker in seen:
            continue
        seen.add(marker)
        normalized.append(parsed)
    return normalized


# ---------------------------------------------------------------------------
# Masking for safe logging
# ---------------------------------------------------------------------------


def _mask(value: Optional[str], visible: int = 4) -> str:
    if not value:
        return "***"
    if len(value) <= visible:
        return "***"
    return value[:visible] + "***"


def _masked_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    masked = {**data}
    if "phone_number" in masked:
        masked["phone_number"] = _mask(str(masked["phone_number"]))
    if "email" in masked:
        parts = str(masked["email"]).split("@")
        masked["email"] = _mask(parts[0]) + "@" + (parts[1] if len(parts) > 1 else "***")
    return masked


# ---------------------------------------------------------------------------
# Individual tool handlers
# Each returns a single-line plain-English result string.
# ---------------------------------------------------------------------------


def _phone_digits(value: Any) -> str:
    """Digits only; drop a leading US country code 1 when 11 digits are present."""
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) == 11 and digits.startswith("1"):
        return digits[1:]
    return digits


def _wait_for_full_phone(value: Any) -> Optional[str]:
    """If the caller is still saying digits, tell the assistant to stay silent."""
    digits = _phone_digits(value)
    if 1 <= len(digits) < 10:
        return (
            f"WAIT: only {len(digits)} of 10 digits so far. "
            "Stay completely silent. Do not speak and do not tell the caller this is invalid. "
            "They are still saying the phone number."
        )
    return None


CORE_VOICE_FIELDS = ("first_name", "last_name", "date_of_birth", "sex", "phone_number")
VOICE_DEFAULTS = {
    "address_line_1": "Not provided",
    "city": "Unknown",
    "state": "NA",
    "zip_code": "00000",
}


def _jsonable(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _persist_clean_patient(db, clean: Dict[str, Any], call_id: Optional[str]) -> str:
    existing = find_by_phone(db, clean["phone_number"])
    if existing:
        same_person = (
            existing["first_name"].lower() == clean["first_name"].lower()
            and existing["last_name"].lower() == clean["last_name"].lower()
            and str(existing["date_of_birth"]) == (
                clean["date_of_birth"].isoformat()
                if hasattr(clean["date_of_birth"], "isoformat")
                else str(clean["date_of_birth"])
            )
        )
        if same_person:
            if call_id:
                upsert_call_log(db, call_id, patient_id=existing["patient_id"])
            return (
                f"SUCCESS: already saved. patient_id={existing['patient_id']}; "
                f"first_name={existing['first_name']}"
            )
        return (
            f"ERROR_DUPLICATE: a record already exists for this phone number "
            f"for {existing['first_name']} {existing['last_name']}"
        )

    patient = create_patient(db, clean)
    if call_id:
        upsert_call_log(db, call_id, patient_id=patient["patient_id"])
    logger.info(
        "save_patient success patient_id=%s payload=%s",
        patient["patient_id"],
        json.dumps(_masked_payload(clean), default=str),
    )
    return f"SUCCESS: saved. patient_id={patient['patient_id']}; first_name={patient['first_name']}"


def _try_finalize_draft(call_id: Optional[str]) -> Optional[str]:
    """Save a patient once the call has name, DOB, sex, and phone."""
    if not call_id:
        return None
    with get_db() as db:
        draft = get_call_draft(db, call_id)
        if not all(draft.get(field) for field in CORE_VOICE_FIELDS):
            return None
        payload = {**VOICE_DEFAULTS, **{k: v for k, v in draft.items() if v not in (None, "")}}
        clean, errors = validate_patient(payload)
        if errors:
            logger.info("draft incomplete call_id=%s missing=%s", call_id, list(errors.keys()))
            return None
        try:
            return _persist_clean_patient(db, clean, call_id)
        except Exception as exc:
            logger.error("finalize draft failed call_id=%s: %s", call_id, exc)
            return None


def _remember_fields(call_id: Optional[str], fields: Dict[str, Any]) -> Optional[str]:
    if not call_id or not fields:
        return None
    serializable = {k: _jsonable(v) for k, v in fields.items() if v is not None}
    with get_db() as db:
        merge_call_draft(db, call_id, serializable)
    return _try_finalize_draft(call_id)


def _tool_validate_field(args: Dict[str, Any], call_id: Optional[str] = None) -> str:
    field = args.get("field", "").strip()
    value = args.get("value")

    if not field:
        return "INVALID: Please provide a field name."

    if field in ("phone_number", "emergency_contact_phone"):
        waiting = _wait_for_full_phone(value)
        if waiting:
            return waiting

    try:
        normalized = validate_field(field, value)
    except KeyError:
        return f"INVALID: I don't know the field '{field}'."
    except ValueError as e:
        return f"INVALID: {e}"

    saved = _remember_fields(call_id, {field: normalized})
    if saved and saved.startswith("SUCCESS"):
        return f"OK. {saved}"
    return "OK"


def _tool_lookup_by_phone(args: Dict[str, Any]) -> str:
    raw_phone = args.get("phone_number", "")
    waiting = _wait_for_full_phone(raw_phone)
    if waiting:
        return waiting
    try:
        phone = validate_phone_number(raw_phone)
    except ValueError as e:
        return f"INVALID: {e}"

    with get_db() as db:
        patient = find_by_phone(db, phone)

    if patient is None:
        return "NOT_FOUND"
    return f"FOUND: patient_id={patient['patient_id']}; name={patient['first_name']} {patient['last_name']}"


def _tool_save_patient(args: Dict[str, Any], call_id: Optional[str]) -> str:
    """
    Validate and save a patient.
    Idempotent: same phone + same name + same DOB returns success without duplicate error.
    """
    import time as _time

    clean, errors = validate_patient(args, partial=False)

    if errors:
        # Keep collecting; a later finalize can still save core identity fields.
        _remember_fields(call_id, {k: v for k, v in args.items() if v not in (None, "")})
        first_field, first_msg = next(iter(errors.items()))
        return f"ERROR_FIELD: {first_field} - {first_msg}"

    for attempt in range(2):
        try:
            with get_db() as db:
                merge_call_draft(
                    db,
                    call_id or "",
                    {k: _jsonable(v) for k, v in clean.items()},
                )
                return _persist_clean_patient(db, clean, call_id)
        except Exception as exc:
            logger.warning("save_patient attempt %d failed: %s", attempt + 1, exc)
            if attempt == 0:
                _time.sleep(0.5)
            else:
                logger.error("save_patient failed after retry: %s", exc)
                return "ERROR_SYSTEM: could not save right now"


def _tool_update_patient(args: Dict[str, Any]) -> str:
    patient_id_raw = args.get("patient_id", "")

    # Validate UUID
    try:
        patient_id = str(uuid.UUID(str(patient_id_raw)))
    except (ValueError, AttributeError):
        return "ERROR_FIELD: patient_id - That is not a valid patient ID."

    # Remove patient_id from the update payload
    update_args = {k: v for k, v in args.items() if k != "patient_id"}

    if not update_args:
        return "ERROR_FIELD: fields - No fields were provided to update."

    clean, errors = validate_patient(update_args, partial=True)

    if errors:
        first_field, first_msg = next(iter(errors.items()))
        return f"ERROR_FIELD: {first_field} - {first_msg}"

    try:
        with get_db() as db:
            existing = get_patient(db, patient_id)
            if existing is None:
                return "ERROR_NOT_FOUND"

            # Phone conflict check
            if "phone_number" in clean:
                conflict = phone_exists_for_different_patient(db, clean["phone_number"], patient_id)
                if conflict:
                    return (
                        f"ERROR_DUPLICATE: this phone number already belongs to "
                        f"{conflict['first_name']} {conflict['last_name']}"
                    )

            updated = update_patient(db, patient_id, clean)
            if updated is None:
                return "ERROR_NOT_FOUND"

        logger.info("update_patient success patient_id=%s", patient_id)
        return "SUCCESS: updated"

    except Exception as exc:
        logger.error("update_patient error patient_id=%s: %s", patient_id, exc)
        return "ERROR_SYSTEM: could not update right now"


# ---------------------------------------------------------------------------
# Tool dispatcher
# ---------------------------------------------------------------------------

TOOL_HANDLERS = {
    "validate_field": _tool_validate_field,
    "lookup_by_phone": lambda args, call_id: _tool_lookup_by_phone(args),
    "save_patient": _tool_save_patient,
    "update_patient": lambda args, call_id: _tool_update_patient(args),
}


def _dispatch_tool(name: str, args: Dict[str, Any], call_id: Optional[str]) -> str:
    handler = TOOL_HANDLERS.get(name)
    if handler is None:
        return f"ERROR_UNKNOWN_TOOL: '{name}' is not a recognized tool."
    return handler(args, call_id)


# ---------------------------------------------------------------------------
# GET probes (browsers use GET; Vapi uses POST)
# ---------------------------------------------------------------------------


@router.get("/tools")
@router.get("/webhook")
def vapi_get_probe(request: Request):
    """Browsers hit these with GET. Vapi always uses POST."""
    return {
        "ok": True,
        "path": request.url.path,
        "message": "This URL is live. Vapi must POST here; opening it in a browser will not run a tool call.",
    }


# ---------------------------------------------------------------------------
# POST /vapi/tools
# ---------------------------------------------------------------------------


@router.post("/tools")
async def vapi_tools(
    request: Request,
    x_vapi_secret: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """
    Handle all Vapi tool-call requests.
    Always returns HTTP 200 with {"results": [...]}.
    """
    if not _check_secret(_extract_provided_secret(x_vapi_secret, authorization)):
        # Return 401 for auth failures (not a tool call error)
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    message = body.get("message") if isinstance(body.get("message"), dict) else body
    if not isinstance(message, dict):
        message = {}

    msg_type = message.get("type", "")
    call_info = message.get("call", {})
    call_id = call_info.get("id") if isinstance(call_info, dict) else message.get("callId")

    if msg_type == "end-of-call-report":
        _store_end_of_call(message)
        saved = _try_finalize_draft(call_id)
        logger.info("end-of-call via tools call_id=%s saved=%s", call_id, bool(saved))
        return JSONResponse({"results": [], "received": True})

    tool_calls = _extract_tool_calls(message)
    if not tool_calls:
        tool_calls = _extract_tool_calls(body if isinstance(body, dict) else {})

    logger.info(
        "vapi_tools type=%s tools=%s call_id=%s keys=%s",
        msg_type or "unknown",
        [tc["name"] for tc in tool_calls] or ["none"],
        call_id,
        list(message.keys())[:12],
    )

    if not tool_calls:
        return JSONResponse({"results": []})

    results = []
    for tc in tool_calls:
        tc_id = tc["id"]
        name = tc["name"]
        args = tc["arguments"]
        start = time.monotonic()

        try:
            result_str = _dispatch_tool(name, args, call_id)
        except Exception as exc:
            logger.exception("Unexpected error in tool %s", name)
            result_str = "ERROR_SYSTEM: an unexpected error occurred"

        elapsed_ms = int((time.monotonic() - start) * 1000)
        logger.info(
            "tool_call call_id=%s tool=%s outcome=%s latency_ms=%d",
            call_id,
            name,
            result_str[:80],
            elapsed_ms,
        )

        results.append({"toolCallId": tc_id, "result": result_str})

    return JSONResponse({"results": results})


def _store_end_of_call(message: Dict[str, Any]) -> Optional[str]:
    call_obj = message.get("call", {})
    call_id = call_obj.get("id") if isinstance(call_obj, dict) else message.get("callId")
    artifact = message.get("artifact", {}) or {}
    transcript = artifact.get("transcript") or message.get("transcript")
    analysis = message.get("analysis", {}) or {}
    summary = analysis.get("summary") or message.get("summary")
    if call_id:
        with get_db() as db:
            upsert_call_log(
                db,
                call_id=call_id,
                transcript=transcript,
                summary=summary,
            )
        logger.info("end-of-call-report stored call_id=%s", call_id)
    else:
        logger.warning("end-of-call-report missing call id, skipping")
    return call_id


# ---------------------------------------------------------------------------
# POST /vapi/webhook  (P1: end-of-call-report)
# ---------------------------------------------------------------------------


@router.post("/webhook")
async def vapi_webhook(
    request: Request,
    x_vapi_secret: Optional[str] = Header(default=None),
    authorization: Optional[str] = Header(default=None),
):
    """
    Handle Vapi webhook events.
    Currently processes end-of-call-report to store transcript and summary.
    Always returns 200 immediately.
    """
    if not _check_secret(_extract_provided_secret(x_vapi_secret, authorization)):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    try:
        body = await request.json()
    except Exception:
        logger.warning("vapi_webhook received non-JSON body")
        return JSONResponse({"received": True})

    try:
        message = body.get("message") if isinstance(body.get("message"), dict) else body
        if not isinstance(message, dict):
            message = {}
        if message.get("type") == "end-of-call-report":
            call_id = _store_end_of_call(message)
            _try_finalize_draft(call_id)
    except Exception as exc:
        logger.error("vapi_webhook processing error: %s", exc)

    return JSONResponse({"received": True})
