"""
Validation and normalization — single source of truth for all patient data.

All functions are pure (no DB, no I/O). They raise ValueError with short,
plain-English messages that a voice agent can speak aloud.

Public API:
  validate_field(name, value) -> normalized_value   (raises ValueError on bad input)
  validate_patient(data_dict, partial=False) -> (clean_dict, errors_by_field)
"""
import re
import unicodedata
from datetime import date, datetime
from typing import Any, Dict, Optional, Tuple

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

US_STATES: Dict[str, str] = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
    "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN",
    "mississippi": "MS", "missouri": "MO", "montana": "MT", "nebraska": "NE",
    "nevada": "NV", "new hampshire": "NH", "new jersey": "NJ",
    "new mexico": "NM", "new york": "NY", "north carolina": "NC",
    "north dakota": "ND", "ohio": "OH", "oklahoma": "OK", "oregon": "OR",
    "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT",
    "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
    "district of columbia": "DC", "washington dc": "DC", "washington d.c.": "DC",
    "n/a": "NA", "na": "NA", "unknown": "NA", "not provided": "NA",
}

VALID_STATE_CODES = set(US_STATES.values()) | {"NA"}

SEX_MAP = {
    "male": "Male", "m": "Male",
    "female": "Female", "f": "Female",
    "other": "Other", "non-binary": "Other", "nonbinary": "Other",
    "decline": "Decline to Answer",
    "prefer not to say": "Decline to Answer",
    "rather not say": "Decline to Answer",
    "decline to answer": "Decline to Answer",
    "prefer not": "Decline to Answer",
}

# Fields that exist on the patient record (for validate_patient)
PATIENT_FIELDS = {
    "required": [
        "first_name", "last_name", "date_of_birth", "sex",
        "phone_number", "address_line_1", "city", "state", "zip_code",
    ],
    "optional": [
        "email", "address_line_2", "insurance_provider", "insurance_member_id",
        "preferred_language", "emergency_contact_name", "emergency_contact_phone",
    ],
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def _strip_controls(value: str) -> str:
    """Remove control characters and normalize unicode to NFC."""
    normalized = unicodedata.normalize("NFC", value)
    return _CONTROL_CHARS.sub("", normalized)


def _require_str(value: Any, field: str) -> str:
    if value is None:
        raise ValueError(f"Please provide your {field.replace('_', ' ')}.")
    if not isinstance(value, str):
        value = str(value)
    return _strip_controls(value).strip()


# ---------------------------------------------------------------------------
# Individual field validators
# ---------------------------------------------------------------------------

def validate_first_name(value: Any) -> str:
    v = _require_str(value, "first name")
    if not v:
        raise ValueError("First name cannot be empty.")
    if len(v) > 50:
        raise ValueError("First name must be 50 characters or fewer.")
    if not re.match(r"^[A-Za-z\s'\-]+$", v):
        raise ValueError("First name may only contain letters, spaces, hyphens, and apostrophes.")
    return v


def validate_last_name(value: Any) -> str:
    v = _require_str(value, "last name")
    if not v:
        raise ValueError("Last name cannot be empty.")
    if len(v) > 50:
        raise ValueError("Last name must be 50 characters or fewer.")
    if not re.match(r"^[A-Za-z\s'\-]+$", v):
        raise ValueError("Last name may only contain letters, spaces, hyphens, and apostrophes.")
    return v


def validate_date_of_birth(value: Any) -> date:
    """
    Accept MM/DD/YYYY or YYYY-MM-DD only.
    Returns a date object.
    """
    if isinstance(value, date) and not isinstance(value, datetime):
        d = value
    elif isinstance(value, datetime):
        d = value.date()
    else:
        v = _require_str(value, "date of birth")
        d = None
        # Try MM/DD/YYYY
        m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", v)
        if m:
            month, day, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
            try:
                d = date(year, month, day)
            except ValueError:
                raise ValueError("That date doesn't exist. Please check the month, day, and year.")
        else:
            # Try YYYY-MM-DD
            m2 = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", v)
            if m2:
                year, month, day = int(m2.group(1)), int(m2.group(2)), int(m2.group(3))
                try:
                    d = date(year, month, day)
                except ValueError:
                    raise ValueError("That date doesn't exist. Please check the month, day, and year.")
            else:
                raise ValueError(
                    "Please say the date as month, day, year — for example, January 15, 1990."
                )

    if d.year < 1900:
        raise ValueError("The year must be 1900 or later.")
    if d > date.today():
        raise ValueError("That date is in the future. Please provide your actual date of birth.")
    return d


def validate_sex(value: Any) -> str:
    v = _require_str(value, "sex")
    key = v.lower().strip()
    result = SEX_MAP.get(key)
    if result is None:
        raise ValueError(
            "Please say male, female, other, or decline to answer for the sex field."
        )
    return result


def validate_phone_number(value: Any) -> str:
    """
    Strip non-digits. Drop leading 1 if 11 digits. Must be exactly 10 digits.
    Returns 10-digit string.
    """
    if value is None:
        raise ValueError("A phone number is required.")
    raw = _strip_controls(str(value))
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        raise ValueError("A U.S. phone number needs 10 digits.")
    return digits


def validate_emergency_contact_phone(value: Any) -> str:
    """Same rules as phone_number but labeled differently in error messages."""
    if value is None or str(value).strip() == "":
        return None  # optional field
    raw = _strip_controls(str(value))
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        raise ValueError("The emergency contact phone number needs 10 digits.")
    return digits


def validate_email(value: Any) -> str:
    v = _require_str(value, "email address")
    v = v.lower()
    if not re.match(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$", v):
        raise ValueError("That doesn't look like a valid email address.")
    if len(v) > 254:
        raise ValueError("Email address is too long.")
    return v


def validate_state(value: Any) -> str:
    """Accept 2-letter code or full state name. Returns 2-letter uppercase code."""
    v = _require_str(value, "state")
    upper = v.strip().upper()
    if upper in VALID_STATE_CODES:
        return upper
    lower = v.strip().lower()
    code = US_STATES.get(lower)
    if code:
        return code
    raise ValueError(
        f"I didn't recognize that state. Please use a two-letter state code like CA or TX."
    )


def validate_zip_code(value: Any) -> str:
    v = _require_str(value, "ZIP code")
    if not re.fullmatch(r"\d{5}(-\d{4})?", v):
        raise ValueError("ZIP code must be 5 digits, or 5 digits followed by a dash and 4 digits.")
    return v


def validate_city(value: Any) -> str:
    v = _require_str(value, "city")
    if not v:
        raise ValueError("City cannot be empty.")
    if len(v) > 100:
        raise ValueError("City name must be 100 characters or fewer.")
    return v


def validate_address_line_1(value: Any) -> str:
    v = _require_str(value, "street address")
    if not v:
        raise ValueError("Street address cannot be empty.")
    if len(v) > 200:
        raise ValueError("Street address must be 200 characters or fewer.")
    return v


def validate_address_line_2(value: Any) -> Optional[str]:
    if value is None or str(value).strip() == "":
        return None
    v = _strip_controls(str(value)).strip()
    if len(v) > 200:
        raise ValueError("Address line 2 must be 200 characters or fewer.")
    return v or None


def validate_insurance_provider(value: Any) -> Optional[str]:
    if value is None or str(value).strip() == "":
        return None
    v = _strip_controls(str(value)).strip()
    if len(v) > 200:
        raise ValueError("Insurance provider name is too long.")
    return v or None


def validate_insurance_member_id(value: Any) -> Optional[str]:
    if value is None or str(value).strip() == "":
        return None
    v = _strip_controls(str(value)).strip()
    # Strip spaces and dashes, then require alphanumeric only
    cleaned = re.sub(r"[\s\-]", "", v)
    if not re.match(r"^[A-Za-z0-9]+$", cleaned):
        raise ValueError("Insurance member ID may only contain letters and numbers.")
    if len(cleaned) > 50:
        raise ValueError("Insurance member ID is too long.")
    return cleaned


def validate_preferred_language(value: Any) -> str:
    if value is None or str(value).strip() == "":
        return "English"
    v = _strip_controls(str(value)).strip()
    if len(v) > 100:
        raise ValueError("Preferred language name is too long.")
    return v or "English"


def validate_emergency_contact_name(value: Any) -> Optional[str]:
    if value is None or str(value).strip() == "":
        return None
    v = _strip_controls(str(value)).strip()
    if len(v) > 100:
        raise ValueError("Emergency contact name must be 100 characters or fewer.")
    return v or None


# ---------------------------------------------------------------------------
# Field dispatcher
# ---------------------------------------------------------------------------

_VALIDATORS = {
    "first_name": validate_first_name,
    "last_name": validate_last_name,
    "date_of_birth": validate_date_of_birth,
    "sex": validate_sex,
    "phone_number": validate_phone_number,
    "email": validate_email,
    "state": validate_state,
    "zip_code": validate_zip_code,
    "city": validate_city,
    "address_line_1": validate_address_line_1,
    "address_line_2": validate_address_line_2,
    "insurance_provider": validate_insurance_provider,
    "insurance_member_id": validate_insurance_member_id,
    "preferred_language": validate_preferred_language,
    "emergency_contact_name": validate_emergency_contact_name,
    "emergency_contact_phone": validate_emergency_contact_phone,
}


def validate_field(name: str, value: Any) -> Any:
    """
    Validate and normalize a single patient field.

    Returns the normalized value.
    Raises ValueError with a plain-English message on invalid input.
    Raises KeyError if `name` is not a known field.
    """
    fn = _VALIDATORS.get(name)
    if fn is None:
        raise KeyError(f"Unknown field: {name}")
    return fn(value)


def validate_patient(
    data: Dict[str, Any],
    partial: bool = False,
) -> Tuple[Dict[str, Any], Dict[str, str]]:
    """
    Validate and normalize a patient data dictionary.

    Args:
        data: Raw input dict.
        partial: If True, only validate fields that are present (for partial updates).

    Returns:
        (clean_dict, errors_by_field) where errors_by_field maps field names to
        plain-English error messages. clean_dict contains only successfully normalized values.
    """
    clean: Dict[str, Any] = {}
    errors: Dict[str, str] = {}

    all_fields = PATIENT_FIELDS["required"] + PATIENT_FIELDS["optional"]

    for field in all_fields:
        in_data = field in data
        is_required = field in PATIENT_FIELDS["required"]

        if not in_data:
            if is_required and not partial:
                errors[field] = f"Please provide your {field.replace('_', ' ')}."
            # Skip optional fields not in data
            continue

        value = data[field]

        # Treat empty string as "not provided" for optional fields
        if not is_required and (value is None or str(value).strip() == ""):
            fn = _VALIDATORS.get(field)
            if fn:
                try:
                    result = fn(value)
                    if result is not None:
                        clean[field] = result
                except ValueError:
                    pass  # optional field, ignore
            continue

        fn = _VALIDATORS.get(field)
        if fn is None:
            # Pass through unknown fields unchanged
            clean[field] = value
            continue

        try:
            result = fn(value)
            # Only add non-None results (None means "not provided/optional")
            if result is not None:
                clean[field] = result
            elif is_required and not partial:
                errors[field] = f"Please provide your {field.replace('_', ' ')}."
        except ValueError as e:
            errors[field] = str(e)

    return clean, errors
