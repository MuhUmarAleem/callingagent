"""
API tests for /patients endpoints using the in-memory fake store.
No database connection required.
"""
import pytest
from tests.conftest import VALID_PATIENT


class TestHealth:
    def test_health_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["status"] == "ok"
        assert body["data"]["db"] == "ok"


class TestCreatePatient:
    def test_create_success(self, client):
        resp = client.post("/patients", json=VALID_PATIENT)
        assert resp.status_code == 201
        body = resp.json()
        assert body["error"] is None
        data = body["data"]
        assert "patient_id" in data
        assert data["first_name"] == "Alice"
        assert data["last_name"] == "Smith"
        # Phone should be stored normalized (10 digits)
        assert data["phone_number"] == "5551234567"
        # Sex should be normalized
        assert data["sex"] == "Female"
        # State normalized
        assert data["state"] == "CA"

    def test_create_missing_required_field(self, client):
        data = {**VALID_PATIENT}
        del data["phone_number"]
        resp = client.post("/patients", json=data)
        assert resp.status_code == 422
        body = resp.json()
        assert body["error"]["code"] == "validation_error"
        assert "phone_number" in body["error"]["fields"]

    def test_create_bad_dob(self, client):
        data = {**VALID_PATIENT, "date_of_birth": "not-a-date"}
        resp = client.post("/patients", json=data)
        assert resp.status_code == 422
        assert "date_of_birth" in resp.json()["error"]["fields"]

    def test_create_future_dob(self, client):
        data = {**VALID_PATIENT, "date_of_birth": "12/31/2099"}
        resp = client.post("/patients", json=data)
        assert resp.status_code == 422
        assert "date_of_birth" in resp.json()["error"]["fields"]

    def test_create_bad_phone(self, client):
        data = {**VALID_PATIENT, "phone_number": "123"}
        resp = client.post("/patients", json=data)
        assert resp.status_code == 422
        assert "phone_number" in resp.json()["error"]["fields"]

    def test_create_duplicate_phone_409(self, client):
        client.post("/patients", json=VALID_PATIENT)
        resp2 = client.post("/patients", json={**VALID_PATIENT, "email": "other@example.com"})
        assert resp2.status_code == 409
        assert resp2.json()["error"]["code"] == "duplicate_phone"

    def test_create_invalid_email(self, client):
        data = {**VALID_PATIENT, "email": "bademail"}
        resp = client.post("/patients", json=data)
        assert resp.status_code == 422
        assert "email" in resp.json()["error"]["fields"]

    def test_create_bad_state(self, client):
        data = {**VALID_PATIENT, "state": "ZZ"}
        resp = client.post("/patients", json=data)
        assert resp.status_code == 422
        assert "state" in resp.json()["error"]["fields"]

    def test_create_full_state_name(self, client):
        data = {**VALID_PATIENT, "state": "California"}
        resp = client.post("/patients", json=data)
        assert resp.status_code == 201
        assert resp.json()["data"]["state"] == "CA"

    def test_create_formatted_phone(self, client):
        data = {**VALID_PATIENT, "phone_number": "(555) 123-4567"}
        resp = client.post("/patients", json=data)
        assert resp.status_code == 201
        assert resp.json()["data"]["phone_number"] == "5551234567"


class TestGetPatient:
    def test_get_existing(self, client):
        create_resp = client.post("/patients", json=VALID_PATIENT)
        pid = create_resp.json()["data"]["patient_id"]

        resp = client.get(f"/patients/{pid}")
        assert resp.status_code == 200
        assert resp.json()["data"]["patient_id"] == pid

    def test_get_not_found(self, client):
        import uuid
        resp = client.get(f"/patients/{uuid.uuid4()}")
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "not_found"

    def test_get_bad_uuid(self, client):
        resp = client.get("/patients/not-a-uuid")
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "bad_uuid"


class TestListPatients:
    def test_list_empty(self, client):
        resp = client.get("/patients")
        assert resp.status_code == 200
        assert resp.json()["data"] == []

    def test_list_returns_created(self, client):
        client.post("/patients", json=VALID_PATIENT)
        resp = client.get("/patients")
        assert len(resp.json()["data"]) == 1

    def test_list_filter_last_name(self, client):
        client.post("/patients", json=VALID_PATIENT)
        client.post("/patients", json={**VALID_PATIENT, "last_name": "Jones", "phone_number": "5559999999"})
        resp = client.get("/patients?last_name=Smith")
        data = resp.json()["data"]
        assert len(data) == 1
        assert data[0]["last_name"] == "Smith"

    def test_list_filter_phone(self, client):
        client.post("/patients", json=VALID_PATIENT)
        resp = client.get("/patients?phone_number=5551234567")
        assert len(resp.json()["data"]) == 1

    def test_list_filter_bad_phone(self, client):
        resp = client.get("/patients?phone_number=123")
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "bad_filter"

    def test_list_filter_bad_dob(self, client):
        resp = client.get("/patients?date_of_birth=notadate")
        assert resp.status_code == 400

    def test_soft_deleted_excluded_from_list(self, client):
        create_resp = client.post("/patients", json=VALID_PATIENT)
        pid = create_resp.json()["data"]["patient_id"]
        client.delete(f"/patients/{pid}")
        resp = client.get("/patients")
        assert resp.json()["data"] == []


class TestUpdatePatient:
    def test_partial_update_success(self, client):
        create_resp = client.post("/patients", json=VALID_PATIENT)
        pid = create_resp.json()["data"]["patient_id"]

        resp = client.put(f"/patients/{pid}", json={"city": "San Francisco"})
        assert resp.status_code == 200
        assert resp.json()["data"]["city"] == "San Francisco"
        # Other fields unchanged
        assert resp.json()["data"]["first_name"] == "Alice"

    def test_update_not_found(self, client):
        import uuid
        resp = client.put(f"/patients/{uuid.uuid4()}", json={"city": "NYC"})
        assert resp.status_code == 404

    def test_update_bad_uuid(self, client):
        resp = client.put("/patients/bad-id", json={"city": "NYC"})
        assert resp.status_code == 400

    def test_update_invalid_field(self, client):
        create_resp = client.post("/patients", json=VALID_PATIENT)
        pid = create_resp.json()["data"]["patient_id"]
        resp = client.put(f"/patients/{pid}", json={"phone_number": "123"})
        assert resp.status_code == 422

    def test_update_duplicate_phone_409(self, client):
        r1 = client.post("/patients", json=VALID_PATIENT)
        r2 = client.post("/patients", json={**VALID_PATIENT, "phone_number": "5559998888"})
        pid2 = r2.json()["data"]["patient_id"]
        # Try to update patient 2 with patient 1's phone
        resp = client.put(f"/patients/{pid2}", json={"phone_number": "5551234567"})
        assert resp.status_code == 409


class TestDeletePatient:
    def test_soft_delete_success(self, client):
        create_resp = client.post("/patients", json=VALID_PATIENT)
        pid = create_resp.json()["data"]["patient_id"]

        resp = client.delete(f"/patients/{pid}")
        assert resp.status_code == 200
        assert resp.json()["data"]["deleted"] is True

    def test_get_after_delete_returns_404(self, client):
        create_resp = client.post("/patients", json=VALID_PATIENT)
        pid = create_resp.json()["data"]["patient_id"]
        client.delete(f"/patients/{pid}")

        resp = client.get(f"/patients/{pid}")
        assert resp.status_code == 404

    def test_delete_not_found(self, client):
        import uuid
        resp = client.delete(f"/patients/{uuid.uuid4()}")
        assert resp.status_code == 404

    def test_delete_already_deleted(self, client):
        create_resp = client.post("/patients", json=VALID_PATIENT)
        pid = create_resp.json()["data"]["patient_id"]
        client.delete(f"/patients/{pid}")
        resp = client.delete(f"/patients/{pid}")
        assert resp.status_code == 404
