"""
Tests for /vapi/tools endpoint.
Covers: each tool, both request formats, wrong secret, unknown tool.
No database connection required.
"""
import json
import uuid

import pytest
from tests.conftest import VALID_PATIENT, store


def vapi_request(tool_name: str, arguments: dict, call_id: str = "call-test-123"):
    """Build a standard Vapi tool-calls request body."""
    return {
        "message": {
            "type": "tool-calls",
            "call": {"id": call_id},
            "toolCallList": [
                {
                    "id": "tc-001",
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "arguments": arguments,
                    },
                }
            ],
        }
    }


def vapi_request_alt_format(tool_name: str, arguments: dict, call_id: str = "call-test-123"):
    """Alternate Vapi format: toolCalls with arguments as JSON string."""
    return {
        "message": {
            "type": "tool-calls",
            "call": {"id": call_id},
            "toolCalls": [
                {
                    "id": "tc-001",
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "arguments": json.dumps(arguments),  # JSON string variant
                    },
                }
            ],
        }
    }


VAPI_HEADERS = {"x-vapi-secret": "test-secret"}


@pytest.fixture(autouse=True)
def set_vapi_secret(monkeypatch):
    """Set VAPI_SHARED_SECRET for tests."""
    import app.config as cfg
    # Clear lru_cache
    cfg.get_settings.cache_clear()
    monkeypatch.setenv("VAPI_SHARED_SECRET", "test-secret")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://test:test@localhost/test")
    yield
    cfg.get_settings.cache_clear()


class TestVapiAuth:
    def test_wrong_secret_rejected(self, client):
        resp = client.post(
            "/vapi/tools",
            json=vapi_request("validate_field", {"field": "first_name", "value": "Alice"}),
            headers={"x-vapi-secret": "WRONG"},
        )
        assert resp.status_code == 401

    def test_missing_secret_rejected(self, client):
        resp = client.post(
            "/vapi/tools",
            json=vapi_request("validate_field", {"field": "first_name", "value": "Alice"}),
        )
        assert resp.status_code == 401

    def test_correct_secret_accepted(self, client):
        resp = client.post(
            "/vapi/tools",
            json=vapi_request("validate_field", {"field": "first_name", "value": "Alice"}),
            headers=VAPI_HEADERS,
        )
        assert resp.status_code == 200


class TestValidateFieldTool:
    def test_valid_field_returns_ok(self, client):
        resp = client.post(
            "/vapi/tools",
            json=vapi_request("validate_field", {"field": "first_name", "value": "Alice"}),
            headers=VAPI_HEADERS,
        )
        assert resp.status_code == 200
        results = resp.json()["results"]
        assert len(results) == 1
        assert results[0]["toolCallId"] == "tc-001"
        assert results[0]["result"] == "OK"

    def test_invalid_field_returns_invalid_prefix(self, client):
        resp = client.post(
            "/vapi/tools",
            json=vapi_request("validate_field", {"field": "date_of_birth", "value": "not-a-date"}),
            headers=VAPI_HEADERS,
        )
        result = resp.json()["results"][0]["result"]
        assert result.startswith("INVALID:")

    def test_future_dob_invalid(self, client):
        resp = client.post(
            "/vapi/tools",
            json=vapi_request("validate_field", {"field": "date_of_birth", "value": "12/31/2099"}),
            headers=VAPI_HEADERS,
        )
        result = resp.json()["results"][0]["result"]
        assert "INVALID" in result
        assert "future" in result.lower()

    def test_valid_phone_ok(self, client):
        resp = client.post(
            "/vapi/tools",
            json=vapi_request("validate_field", {"field": "phone_number", "value": "5551234567"}),
            headers=VAPI_HEADERS,
        )
        assert resp.json()["results"][0]["result"] == "OK"

    def test_bad_phone_invalid(self, client):
        resp = client.post(
            "/vapi/tools",
            json=vapi_request("validate_field", {"field": "phone_number", "value": "123"}),
            headers=VAPI_HEADERS,
        )
        result = resp.json()["results"][0]["result"]
        assert result.startswith("INVALID:")

    def test_unknown_field_name(self, client):
        resp = client.post(
            "/vapi/tools",
            json=vapi_request("validate_field", {"field": "nonexistent", "value": "x"}),
            headers=VAPI_HEADERS,
        )
        result = resp.json()["results"][0]["result"]
        assert "INVALID" in result

    def test_alt_format_json_string_args(self, client):
        """Test the variant where arguments arrive as a JSON string."""
        resp = client.post(
            "/vapi/tools",
            json=vapi_request_alt_format("validate_field", {"field": "first_name", "value": "Bob"}),
            headers=VAPI_HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["results"][0]["result"] == "OK"


class TestLookupByPhoneTool:
    def test_not_found(self, client):
        resp = client.post(
            "/vapi/tools",
            json=vapi_request("lookup_by_phone", {"phone_number": "5550000000"}),
            headers=VAPI_HEADERS,
        )
        assert resp.json()["results"][0]["result"] == "NOT_FOUND"

    def test_found_after_save(self, client):
        # First save a patient directly in store
        store.create({
            "patient_id": str(uuid.uuid4()),
            "first_name": "Alice",
            "last_name": "Smith",
            "date_of_birth": "1990-01-15",
            "sex": "Female",
            "phone_number": "5551234567",
            "address_line_1": "123 Main St",
            "city": "LA",
            "state": "CA",
            "zip_code": "90001",
        })
        resp = client.post(
            "/vapi/tools",
            json=vapi_request("lookup_by_phone", {"phone_number": "5551234567"}),
            headers=VAPI_HEADERS,
        )
        result = resp.json()["results"][0]["result"]
        assert result.startswith("FOUND:")
        assert "Alice" in result
        assert "Smith" in result

    def test_invalid_phone_format(self, client):
        resp = client.post(
            "/vapi/tools",
            json=vapi_request("lookup_by_phone", {"phone_number": "999"}),
            headers=VAPI_HEADERS,
        )
        result = resp.json()["results"][0]["result"]
        assert result.startswith("INVALID:")

    def test_formatted_phone_normalized(self, client):
        store.create({
            "patient_id": str(uuid.uuid4()),
            "first_name": "Bob",
            "last_name": "Jones",
            "date_of_birth": "1985-03-20",
            "sex": "Male",
            "phone_number": "5559998888",
            "address_line_1": "456 Oak Ave",
            "city": "NYC",
            "state": "NY",
            "zip_code": "10001",
        })
        resp = client.post(
            "/vapi/tools",
            json=vapi_request("lookup_by_phone", {"phone_number": "(555) 999-8888"}),
            headers=VAPI_HEADERS,
        )
        result = resp.json()["results"][0]["result"]
        assert result.startswith("FOUND:")


class TestSavePatientTool:
    def test_save_success(self, client):
        resp = client.post(
            "/vapi/tools",
            json=vapi_request("save_patient", VALID_PATIENT),
            headers=VAPI_HEADERS,
        )
        assert resp.status_code == 200
        result = resp.json()["results"][0]["result"]
        assert result.startswith("SUCCESS: saved.")
        assert "patient_id=" in result
        assert "Alice" in result

    def test_save_missing_field_returns_error_field(self, client):
        data = {**VALID_PATIENT}
        del data["last_name"]
        resp = client.post(
            "/vapi/tools",
            json=vapi_request("save_patient", data),
            headers=VAPI_HEADERS,
        )
        result = resp.json()["results"][0]["result"]
        assert result.startswith("ERROR_FIELD:")
        assert "last_name" in result

    def test_save_bad_dob(self, client):
        data = {**VALID_PATIENT, "date_of_birth": "not-a-date"}
        resp = client.post(
            "/vapi/tools",
            json=vapi_request("save_patient", data),
            headers=VAPI_HEADERS,
        )
        result = resp.json()["results"][0]["result"]
        assert result.startswith("ERROR_FIELD:")

    def test_save_idempotent_same_person(self, client):
        """Calling save_patient twice with same phone+name+DOB should return 'already saved'."""
        resp1 = client.post(
            "/vapi/tools",
            json=vapi_request("save_patient", VALID_PATIENT),
            headers=VAPI_HEADERS,
        )
        assert resp1.json()["results"][0]["result"].startswith("SUCCESS: saved.")

        resp2 = client.post(
            "/vapi/tools",
            json=vapi_request("save_patient", VALID_PATIENT),
            headers=VAPI_HEADERS,
        )
        result2 = resp2.json()["results"][0]["result"]
        assert result2.startswith("SUCCESS: already saved.")

    def test_save_duplicate_different_person(self, client):
        """Same phone but different name should return ERROR_DUPLICATE."""
        client.post(
            "/vapi/tools",
            json=vapi_request("save_patient", VALID_PATIENT),
            headers=VAPI_HEADERS,
        )
        different_person = {**VALID_PATIENT, "first_name": "Bob", "last_name": "Jones"}
        resp = client.post(
            "/vapi/tools",
            json=vapi_request("save_patient", different_person),
            headers=VAPI_HEADERS,
        )
        result = resp.json()["results"][0]["result"]
        assert result.startswith("ERROR_DUPLICATE:")
        assert "Alice" in result

    def test_save_alt_format(self, client):
        """Test save_patient with toolCalls+JSON-string arguments."""
        resp = client.post(
            "/vapi/tools",
            json=vapi_request_alt_format("save_patient", VALID_PATIENT),
            headers=VAPI_HEADERS,
        )
        result = resp.json()["results"][0]["result"]
        assert result.startswith("SUCCESS: saved.")


class TestUpdatePatientTool:
    def test_update_success(self, client):
        # First create a patient
        pid = store.create({
            "patient_id": str(uuid.uuid4()),
            "first_name": "Alice",
            "last_name": "Smith",
            "date_of_birth": "1990-01-15",
            "sex": "Female",
            "phone_number": "5551234567",
            "address_line_1": "123 Main St",
            "city": "LA",
            "state": "CA",
            "zip_code": "90001",
        })["patient_id"]

        resp = client.post(
            "/vapi/tools",
            json=vapi_request("update_patient", {"patient_id": pid, "city": "San Francisco"}),
            headers=VAPI_HEADERS,
        )
        result = resp.json()["results"][0]["result"]
        assert result == "SUCCESS: updated"

    def test_update_not_found(self, client):
        resp = client.post(
            "/vapi/tools",
            json=vapi_request("update_patient", {"patient_id": str(uuid.uuid4()), "city": "NYC"}),
            headers=VAPI_HEADERS,
        )
        result = resp.json()["results"][0]["result"]
        assert result == "ERROR_NOT_FOUND"

    def test_update_bad_patient_id(self, client):
        resp = client.post(
            "/vapi/tools",
            json=vapi_request("update_patient", {"patient_id": "not-a-uuid", "city": "NYC"}),
            headers=VAPI_HEADERS,
        )
        result = resp.json()["results"][0]["result"]
        assert result.startswith("ERROR_FIELD:")

    def test_update_bad_field_value(self, client):
        pid = store.create({
            "patient_id": str(uuid.uuid4()),
            "first_name": "Alice",
            "last_name": "Smith",
            "date_of_birth": "1990-01-15",
            "sex": "Female",
            "phone_number": "5551234567",
            "address_line_1": "123 Main St",
            "city": "LA",
            "state": "CA",
            "zip_code": "90001",
        })["patient_id"]

        resp = client.post(
            "/vapi/tools",
            json=vapi_request("update_patient", {"patient_id": pid, "phone_number": "bad"}),
            headers=VAPI_HEADERS,
        )
        result = resp.json()["results"][0]["result"]
        assert result.startswith("ERROR_FIELD:")


class TestUnknownTool:
    def test_unknown_tool_returns_error(self, client):
        resp = client.post(
            "/vapi/tools",
            json=vapi_request("nonexistent_tool", {}),
            headers=VAPI_HEADERS,
        )
        assert resp.status_code == 200
        result = resp.json()["results"][0]["result"]
        assert "ERROR_UNKNOWN_TOOL" in result

    def test_always_http_200(self, client):
        """Even completely broken input should return HTTP 200."""
        resp = client.post(
            "/vapi/tools",
            json={"message": {"type": "tool-calls", "toolCallList": [{"id": "x", "function": {"name": "bad_tool", "arguments": {}}}]}},
            headers=VAPI_HEADERS,
        )
        assert resp.status_code == 200


class TestMultipleToolCalls:
    def test_multiple_results_returned(self, client):
        body = {
            "message": {
                "type": "tool-calls",
                "call": {"id": "call-multi"},
                "toolCallList": [
                    {
                        "id": "tc-001",
                        "type": "function",
                        "function": {"name": "validate_field", "arguments": {"field": "first_name", "value": "Alice"}},
                    },
                    {
                        "id": "tc-002",
                        "type": "function",
                        "function": {"name": "validate_field", "arguments": {"field": "phone_number", "value": "123"}},
                    },
                ],
            }
        }
        resp = client.post("/vapi/tools", json=body, headers=VAPI_HEADERS)
        assert resp.status_code == 200
        results = resp.json()["results"]
        assert len(results) == 2
        assert results[0]["toolCallId"] == "tc-001"
        assert results[0]["result"] == "OK"
        assert results[1]["toolCallId"] == "tc-002"
        assert results[1]["result"].startswith("INVALID:")
