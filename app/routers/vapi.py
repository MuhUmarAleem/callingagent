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
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.db import get_db
from app.services import find_by_phone, create_patient, get_patient, update_patient, upsert_call_log, phone_exists_for_different_patient
from app.validation import validate_field, validate_patient, validate_phone_number

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/vapi", tags=["vapi"])


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def _check_secret(provided: Optional[str]) -> bool:
    settings = get_settings()
    secret = settings.vapi_shared_secret
    if not secret:
        logger.warning("VAPI_SHARED_SECRET is not set — skipping authentication check.")
        return True
    if not provided:
        return False
    return hmac.compare_digest(provided, secret)


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


def _extract_tool_calls(message: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Extract tool calls from the Vapi message body.
    Supports both toolCallList and toolCalls keys.
    Each item is normalized to: {"id": "...", "name": "...", "arguments": {...}}
    """
    raw_calls = message.get("toolCallList") or message.get("toolCalls") or []
    normalized = []

    for item in raw_calls:
        # Both formats use id at the top level
        call_id = item.get("id", "")

        # Function info can be at top level (older format) or nested under "function"
        func = item.get("function", {})
        name = func.get("name") or item.get("name", "")
        raw_args = func.get("arguments") or item.get("arguments", {})
        arguments = _parse_arguments(raw_args)

        normalized.append({"id": call_id, "name": name, "arguments": arguments})

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


def _tool_validate_field(args: Dict[str, Any]) -> str:
    field = args.get("field", "").strip()
    value = args.get("value")

    if not field:
        return "INVALID: Please provide a field name."

    try:
        validate_field(field, value)
        return "OK"
    except KeyError:
        return f"INVALID: I don't know the field '{field}'."
    except ValueError as e:
        return f"INVALID: {e}"


def _tool_lookup_by_phone(args: Dict[str, Any]) -> str:
    raw_phone = args.get("phone_number", "")
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
        # Return the first error so the agent re-asks one thing at a time
        first_field, first_msg = next(iter(errors.items()))
        return f"ERROR_FIELD: {first_field} - {first_msg}"

    # Check for existing patient with same phone
    for attempt in range(2):
        try:
            with get_db() as db:
                existing = find_by_phone(db, clean["phone_number"])

                if existing:
                    # Same person? Check name + DOB
                    same_person = (
                        existing["first_name"].lower() == clean["first_name"].lower()
                        and existing["last_name"].lower() == clean["last_name"].lower()
                        and existing["date_of_birth"] == clean["date_of_birth"].isoformat()
                    )
                    if same_person:
                        # Link call to existing patient
                        if call_id:
                            upsert_call_log(db, call_id, patient_id=existing["patient_id"])
                        return f"SUCCESS: already saved. patient_id={existing['patient_id']}; first_name={existing['first_name']}"
                    else:
                        return (
                            f"ERROR_DUPLICATE: a record already exists for this phone number "
                            f"for {existing['first_name']} {existing['last_name']}"
                        )

                patient = create_patient(db, clean)

                # Link call log to new patient
                if call_id:
                    upsert_call_log(db, call_id, patient_id=patient["patient_id"])

            logger.info(
                "save_patient success patient_id=%s payload=%s",
                patient["patient_id"],
                json.dumps(_masked_payload(clean), default=str),
            )
            return f"SUCCESS: saved. patient_id={patient['patient_id']}; first_name={patient['first_name']}"

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
    "validate_field": lambda args, call_id: _tool_validate_field(args),
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
# POST /vapi/tools
# ---------------------------------------------------------------------------


@router.post("/tools")
async def vapi_tools(request: Request, x_vapi_secret: Optional[str] = Header(default=None)):
    """
    Handle all Vapi tool-call requests.
    Always returns HTTP 200 with {"results": [...]}.
    """
    if not _check_secret(x_vapi_secret):
        # Return 401 for auth failures (not a tool call error)
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    message = body.get("message", {})
    call_info = message.get("call", {})
    call_id = call_info.get("id") if isinstance(call_info, dict) else None

    tool_calls = _extract_tool_calls(message)

    if not tool_calls:
        # Not a tool-calls message type — return empty results
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


# ---------------------------------------------------------------------------
# POST /vapi/webhook  (P1: end-of-call-report)
# ---------------------------------------------------------------------------


@router.post("/webhook")
async def vapi_webhook(request: Request, x_vapi_secret: Optional[str] = Header(default=None)):
    """
    Handle Vapi webhook events.
    Currently processes end-of-call-report to store transcript and summary.
    Always returns 200 immediately.
    """
    if not _check_secret(x_vapi_secret):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    try:
        body = await request.json()
    except Exception:
        logger.warning("vapi_webhook received non-JSON body")
        return JSONResponse({"received": True})

    try:
        message = body.get("message", {})
        msg_type = message.get("type", "")

        if msg_type == "end-of-call-report":
            # Extract call ID — Vapi nests it inside message.call.id
            call_obj = message.get("call", {})
            call_id = (
                call_obj.get("id")
                if isinstance(call_obj, dict)
                else message.get("callId")
            )

            # Transcript: message.artifact.transcript (string) or message.transcript
            artifact = message.get("artifact", {}) or {}
            transcript = (
                artifact.get("transcript")
                or message.get("transcript")
            )

            # Summary: message.analysis.summary or message.summary
            analysis = message.get("analysis", {}) or {}
            summary = (
                analysis.get("summary")
                or message.get("summary")
            )

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

    except Exception as exc:
        logger.error("vapi_webhook processing error: %s", exc)

    return JSONResponse({"received": True})
