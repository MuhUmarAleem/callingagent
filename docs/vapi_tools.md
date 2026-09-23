# Vapi Tool Definitions & Setup Guide

## Step 1: Set the Server URL

In your Vapi assistant settings → **Server URL**, enter:

```
https://<YOUR_PUBLIC_URL>/vapi/tools
```

Set a **generous timeout** — recommended: **20 seconds** (registration can take a moment to validate and write to the database).

## Step 2: Set the Secret Header

In your Vapi assistant settings → **Server URL Headers**, add:

| Header Name      | Header Value                        |
|------------------|-------------------------------------|
| `x-vapi-secret`  | *(the value of your VAPI_SHARED_SECRET env var)* |

## Step 3: (Optional) Webhook for Call Transcripts

To store transcripts and link them to patients, set the **Server URL** (or a separate webhook URL) to also receive `end-of-call-report` events:

```
https://<YOUR_PUBLIC_URL>/vapi/webhook
```

Use the same `x-vapi-secret` header.

---

## Tool Definitions

Paste each block below into the Vapi dashboard under **Tools → Create Tool → Custom Tool**.

---

### Tool 1: `validate_field`

**Description:**
> Use this tool to validate a single patient registration field before asking for the next one. Call it immediately after the user provides any piece of information. If the result starts with "INVALID:", tell the user what's wrong and ask them to repeat that field. If the result is "OK", move on to the next field.

**Function name:** `validate_field`

**Parameters (JSON Schema):**
```json
{
  "type": "object",
  "properties": {
    "field": {
      "type": "string",
      "description": "The name of the patient field to validate. One of: first_name, last_name, date_of_birth, sex, phone_number, email, address_line_1, address_line_2, city, state, zip_code, insurance_provider, insurance_member_id, preferred_language, emergency_contact_name, emergency_contact_phone"
    },
    "value": {
      "type": "string",
      "description": "The value the patient provided for this field."
    }
  },
  "required": ["field", "value"]
}
```

**Example result strings:**
- `OK`
- `INVALID: A U.S. phone number needs 10 digits.`
- `INVALID: That date is in the future. Please provide your actual date of birth.`

---

### Tool 2: `lookup_by_phone`

**Description:**
> Look up whether a patient is already registered by their phone number. Call this at the start of the call to check if the caller is a returning patient. If FOUND, you can confirm their identity and offer to update their record. If NOT_FOUND, proceed with a new registration.

**Function name:** `lookup_by_phone`

**Parameters (JSON Schema):**
```json
{
  "type": "object",
  "properties": {
    "phone_number": {
      "type": "string",
      "description": "The caller's 10-digit U.S. phone number. Can include formatting like (555) 123-4567."
    }
  },
  "required": ["phone_number"]
}
```

**Example result strings:**
- `FOUND: patient_id=abc123...; name=Alice Smith`
- `NOT_FOUND`
- `INVALID: A U.S. phone number needs 10 digits.`

---

### Tool 3: `save_patient`

**Description:**
> Save a new patient registration after collecting all required information. Call this only when you have all required fields: first_name, last_name, date_of_birth, sex, phone_number, address_line_1, city, state, zip_code. This tool validates everything server-side. If it returns ERROR_FIELD, re-ask only that one field. If it returns SUCCESS, confirm registration and end the call.

**Function name:** `save_patient`

**Parameters (JSON Schema):**
```json
{
  "type": "object",
  "properties": {
    "first_name": { "type": "string", "description": "Patient's first name." },
    "last_name": { "type": "string", "description": "Patient's last name." },
    "date_of_birth": { "type": "string", "description": "Date of birth in MM/DD/YYYY format." },
    "sex": { "type": "string", "description": "Sex: male, female, other, or decline to answer." },
    "phone_number": { "type": "string", "description": "10-digit U.S. phone number." },
    "email": { "type": "string", "description": "Email address (optional)." },
    "address_line_1": { "type": "string", "description": "Street address." },
    "address_line_2": { "type": "string", "description": "Apartment, suite, unit, etc. (optional)." },
    "city": { "type": "string", "description": "City." },
    "state": { "type": "string", "description": "Two-letter state code or full state name." },
    "zip_code": { "type": "string", "description": "ZIP code (5 digits or ZIP+4)." },
    "insurance_provider": { "type": "string", "description": "Insurance company name (optional)." },
    "insurance_member_id": { "type": "string", "description": "Insurance member ID (optional)." },
    "preferred_language": { "type": "string", "description": "Preferred language, defaults to English (optional)." },
    "emergency_contact_name": { "type": "string", "description": "Emergency contact full name (optional)." },
    "emergency_contact_phone": { "type": "string", "description": "Emergency contact phone number (optional)." }
  },
  "required": [
    "first_name", "last_name", "date_of_birth", "sex",
    "phone_number", "address_line_1", "city", "state", "zip_code"
  ]
}
```

**Example result strings:**
- `SUCCESS: saved. patient_id=abc123...; first_name=Alice`
- `SUCCESS: already saved. patient_id=abc123...; first_name=Alice`
- `ERROR_FIELD: date_of_birth - That date is in the future. Please provide your actual date of birth.`
- `ERROR_DUPLICATE: a record already exists for this phone number for Bob Jones`
- `ERROR_SYSTEM: could not save right now`

---

### Tool 4: `update_patient`

**Description:**
> Update specific fields on an existing patient record. Use this when a returning patient (found via lookup_by_phone) wants to change their information. Only include the fields that are being changed. Always include patient_id from the lookup result.

**Function name:** `update_patient`

**Parameters (JSON Schema):**
```json
{
  "type": "object",
  "properties": {
    "patient_id": { "type": "string", "description": "The UUID of the patient to update (from lookup_by_phone result)." },
    "first_name": { "type": "string" },
    "last_name": { "type": "string" },
    "date_of_birth": { "type": "string" },
    "sex": { "type": "string" },
    "phone_number": { "type": "string" },
    "email": { "type": "string" },
    "address_line_1": { "type": "string" },
    "address_line_2": { "type": "string" },
    "city": { "type": "string" },
    "state": { "type": "string" },
    "zip_code": { "type": "string" },
    "insurance_provider": { "type": "string" },
    "insurance_member_id": { "type": "string" },
    "preferred_language": { "type": "string" },
    "emergency_contact_name": { "type": "string" },
    "emergency_contact_phone": { "type": "string" }
  },
  "required": ["patient_id"]
}
```

**Example result strings:**
- `SUCCESS: updated`
- `ERROR_NOT_FOUND`
- `ERROR_FIELD: phone_number - A U.S. phone number needs 10 digits.`
- `ERROR_SYSTEM: could not update right now`

---

## Suggested System Prompt for the Vapi Assistant

```
You are a friendly patient registration assistant for a medical practice. Your job is to register new patients or update existing records by collecting their information over the phone.

WORKFLOW:
1. Greet the caller warmly and ask if they are a new or returning patient.
2. For returning patients: ask for their phone number, call lookup_by_phone to find their record.
3. For new patients: collect fields one at a time in this order:
   - first_name, last_name, date_of_birth, sex
   - phone_number, email (optional)
   - address_line_1, address_line_2 (optional), city, state, zip_code
   - insurance_provider (optional), insurance_member_id (optional)
   - emergency_contact_name (optional), emergency_contact_phone (optional)
4. After each field, call validate_field to confirm it's correct before moving on.
5. Once all required fields are collected, call save_patient.
6. If save_patient returns SUCCESS, congratulate the patient and close the call.
7. If save_patient returns ERROR_FIELD, apologize and re-ask only that field.
8. Speak naturally. Spell out phone numbers digit by digit. Say dates as "Month Day, Year".
9. Never read UUIDs aloud.
```
