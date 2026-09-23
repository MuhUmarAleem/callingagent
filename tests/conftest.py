"""
Test configuration and fixtures.

The service layer is replaced with an in-memory fake so tests run without
any database connection.
"""
import uuid
from contextlib import ExitStack, contextmanager
from copy import deepcopy
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# In-memory patient store
# ---------------------------------------------------------------------------


class FakeStore:
    """Thread-unsafe in-memory store used by tests."""

    def __init__(self):
        self.patients: Dict[str, Dict[str, Any]] = {}

    def reset(self):
        self.patients.clear()

    def create(self, data: Dict[str, Any]) -> Dict[str, Any]:
        pid = data.get("patient_id") or str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        record = {
            **data,
            "patient_id": pid,
            "created_at": now,
            "updated_at": now,
            "deleted_at": None,
        }
        if isinstance(record.get("date_of_birth"), date):
            record["date_of_birth"] = record["date_of_birth"].isoformat()
        self.patients[pid] = record
        return deepcopy(record)

    def get(self, patient_id: str) -> Optional[Dict[str, Any]]:
        p = self.patients.get(patient_id)
        if p and p.get("deleted_at") is None:
            return deepcopy(p)
        return None

    def find_by_phone(self, phone: str) -> Optional[Dict[str, Any]]:
        for p in self.patients.values():
            if p.get("phone_number") == phone and p.get("deleted_at") is None:
                return deepcopy(p)
        return None

    def list_all(
        self,
        last_name: Optional[str] = None,
        date_of_birth=None,
        phone_number: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        results = []
        for p in self.patients.values():
            if p.get("deleted_at") is not None:
                continue
            if last_name and last_name.lower() not in p.get("last_name", "").lower():
                continue
            if date_of_birth:
                dob_str = date_of_birth.isoformat() if isinstance(date_of_birth, date) else str(date_of_birth)
                if p.get("date_of_birth") != dob_str:
                    continue
            if phone_number and p.get("phone_number") != phone_number:
                continue
            results.append(deepcopy(p))
        results.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return results

    def update(self, patient_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        p = self.patients.get(patient_id)
        if not p or p.get("deleted_at") is not None:
            return None
        update_data = dict(data)
        if isinstance(update_data.get("date_of_birth"), date):
            update_data["date_of_birth"] = update_data["date_of_birth"].isoformat()
        p.update(update_data)
        return deepcopy(p)

    def soft_delete(self, patient_id: str) -> bool:
        p = self.patients.get(patient_id)
        if not p or p.get("deleted_at") is not None:
            return False
        p["deleted_at"] = datetime.now(timezone.utc).isoformat()
        return True

    def phone_conflict(self, phone: str, exclude_id: str) -> Optional[Dict[str, Any]]:
        for p in self.patients.values():
            if (
                p.get("phone_number") == phone
                and p.get("patient_id") != exclude_id
                and p.get("deleted_at") is None
            ):
                return deepcopy(p)
        return None


# Single global store instance
store = FakeStore()


@pytest.fixture(autouse=True)
def reset_store():
    store.reset()
    yield
    store.reset()


@contextmanager
def _fake_get_db():
    yield None


def _noop(*args, **kwargs):
    pass


@pytest.fixture
def client():
    """TestClient with DB and service layer fully mocked."""
    from app.main import create_app

    patches = [
        # DB helpers
        patch("app.db.get_db", _fake_get_db),
        patch("app.db.check_db_health", return_value=True),
        # app.services — canonical definitions
        patch("app.services.create_patient", side_effect=lambda db, data: store.create(data)),
        patch("app.services.get_patient", side_effect=lambda db, pid: store.get(pid)),
        patch("app.services.list_patients", side_effect=lambda db, **kw: store.list_all(**kw)),
        patch("app.services.update_patient", side_effect=lambda db, pid, data: store.update(pid, data)),
        patch("app.services.soft_delete_patient", side_effect=lambda db, pid: store.soft_delete(pid)),
        patch("app.services.find_by_phone", side_effect=lambda db, phone: store.find_by_phone(phone)),
        patch("app.services.phone_exists_for_different_patient", side_effect=lambda db, phone, pid: store.phone_conflict(phone, pid)),
        patch("app.services.upsert_call_log", side_effect=_noop),
        # app.routers.patients — imported names
        patch("app.routers.patients.get_db", _fake_get_db),
        patch("app.routers.patients.create_patient", side_effect=lambda db, data: store.create(data)),
        patch("app.routers.patients.get_patient", side_effect=lambda db, pid: store.get(pid)),
        patch("app.routers.patients.list_patients", side_effect=lambda db, **kw: store.list_all(**kw)),
        patch("app.routers.patients.update_patient", side_effect=lambda db, pid, data: store.update(pid, data)),
        patch("app.routers.patients.soft_delete_patient", side_effect=lambda db, pid: store.soft_delete(pid)),
        patch("app.routers.patients.find_by_phone", side_effect=lambda db, phone: store.find_by_phone(phone)),
        patch("app.routers.patients.phone_exists_for_different_patient", side_effect=lambda db, phone, pid: store.phone_conflict(phone, pid)),
        # app.routers.vapi — imported names
        patch("app.routers.vapi.get_db", _fake_get_db),
        patch("app.routers.vapi.find_by_phone", side_effect=lambda db, phone: store.find_by_phone(phone)),
        patch("app.routers.vapi.create_patient", side_effect=lambda db, data: store.create(data)),
        patch("app.routers.vapi.get_patient", side_effect=lambda db, pid: store.get(pid)),
        patch("app.routers.vapi.update_patient", side_effect=lambda db, pid, data: store.update(pid, data)),
        patch("app.routers.vapi.upsert_call_log", side_effect=_noop),
        patch("app.routers.vapi.phone_exists_for_different_patient", side_effect=lambda db, phone, pid: store.phone_conflict(phone, pid)),
    ]

    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        application = create_app()
        with TestClient(application, raise_server_exceptions=False) as c:
            yield c


# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

VALID_PATIENT = {
    "first_name": "Alice",
    "last_name": "Smith",
    "date_of_birth": "01/15/1990",
    "sex": "female",
    "phone_number": "5551234567",
    "address_line_1": "123 Main St",
    "city": "Los Angeles",
    "state": "CA",
    "zip_code": "90001",
    "email": "alice@example.com",
}
