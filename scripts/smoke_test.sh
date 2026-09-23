#!/usr/bin/env bash
# smoke_test.sh — end-to-end curl smoke test for the Patient Registration API
#
# Usage:
#   chmod +x scripts/smoke_test.sh
#   BASE_URL=https://your-app.railway.app bash scripts/smoke_test.sh
#
# Or against localhost:
#   BASE_URL=http://localhost:8000 bash scripts/smoke_test.sh
#
# Optional: Set API_KEY and VAPI_SECRET if your deployment uses them:
#   API_KEY=mykey VAPI_SECRET=mysecret BASE_URL=http://localhost:8000 bash scripts/smoke_test.sh

set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8000}"
API_KEY="${API_KEY:-}"
VAPI_SECRET="${VAPI_SECRET:-}"
PHONE="5550001111"

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

pass() { echo -e "${GREEN}✓ PASS${NC} $1"; }
fail() { echo -e "${RED}✗ FAIL${NC} $1"; exit 1; }
info() { echo -e "${YELLOW}▶${NC} $1"; }

echo ""
echo "=========================================="
echo "  Patient Registration Smoke Test"
echo "  Base URL: $BASE_URL"
echo "=========================================="
echo ""

# Build auth headers
AUTH_HEADER=""
if [ -n "$API_KEY" ]; then
  AUTH_HEADER="-H 'x-api-key: $API_KEY'"
fi

VAPI_HEADER=""
if [ -n "$VAPI_SECRET" ]; then
  VAPI_HEADER="-H 'x-vapi-secret: $VAPI_SECRET'"
fi

# ---------------------------------------------------------------------------
# 1. Health check
# ---------------------------------------------------------------------------
info "1. Health check"
RESP=$(curl -sf "${BASE_URL}/health")
echo "   Response: $RESP"
echo "$RESP" | grep -q '"status":"ok"' && pass "Health check returned ok" || fail "Health check failed"

# ---------------------------------------------------------------------------
# 2. Vapi validate_field — valid field
# ---------------------------------------------------------------------------
info "2. Vapi validate_field (first_name=Alice)"
RESP=$(curl -sf -X POST "${BASE_URL}/vapi/tools" \
  -H "Content-Type: application/json" \
  ${VAPI_SECRET:+-H "x-vapi-secret: $VAPI_SECRET"} \
  -d '{
    "message": {
      "type": "tool-calls",
      "call": {"id": "smoke-test-call-1"},
      "toolCallList": [{
        "id": "tc-1",
        "type": "function",
        "function": {"name": "validate_field", "arguments": {"field": "first_name", "value": "Alice"}}
      }]
    }
  }')
echo "   Response: $RESP"
echo "$RESP" | grep -q '"result":"OK"' && pass "validate_field returned OK" || fail "validate_field did not return OK"

# ---------------------------------------------------------------------------
# 3. Vapi validate_field — bad date of birth
# ---------------------------------------------------------------------------
info "3. Vapi validate_field (bad DOB)"
RESP=$(curl -sf -X POST "${BASE_URL}/vapi/tools" \
  -H "Content-Type: application/json" \
  ${VAPI_SECRET:+-H "x-vapi-secret: $VAPI_SECRET"} \
  -d '{
    "message": {
      "type": "tool-calls",
      "call": {"id": "smoke-test-call-2"},
      "toolCallList": [{
        "id": "tc-2",
        "type": "function",
        "function": {"name": "validate_field", "arguments": {"field": "date_of_birth", "value": "99/99/9999"}}
      }]
    }
  }')
echo "   Response: $RESP"
echo "$RESP" | grep -q '"result":"INVALID:' && pass "validate_field returned INVALID for bad DOB" || fail "validate_field did not return INVALID"

# ---------------------------------------------------------------------------
# 4. Vapi lookup_by_phone — not found
# ---------------------------------------------------------------------------
info "4. Vapi lookup_by_phone (not registered yet)"
RESP=$(curl -sf -X POST "${BASE_URL}/vapi/tools" \
  -H "Content-Type: application/json" \
  ${VAPI_SECRET:+-H "x-vapi-secret: $VAPI_SECRET"} \
  -d "{
    \"message\": {
      \"type\": \"tool-calls\",
      \"call\": {\"id\": \"smoke-test-call-3\"},
      \"toolCallList\": [{
        \"id\": \"tc-3\",
        \"type\": \"function\",
        \"function\": {\"name\": \"lookup_by_phone\", \"arguments\": {\"phone_number\": \"${PHONE}\"}}
      }]
    }
  }")
echo "   Response: $RESP"
echo "$RESP" | grep -q '"result":"NOT_FOUND"' && pass "lookup_by_phone returned NOT_FOUND" || fail "lookup_by_phone did not return NOT_FOUND"

# ---------------------------------------------------------------------------
# 5. Vapi save_patient — success
# ---------------------------------------------------------------------------
info "5. Vapi save_patient (new patient)"
RESP=$(curl -sf -X POST "${BASE_URL}/vapi/tools" \
  -H "Content-Type: application/json" \
  ${VAPI_SECRET:+-H "x-vapi-secret: $VAPI_SECRET"} \
  -d "{
    \"message\": {
      \"type\": \"tool-calls\",
      \"call\": {\"id\": \"smoke-test-call-4\"},
      \"toolCallList\": [{
        \"id\": \"tc-4\",
        \"type\": \"function\",
        \"function\": {
          \"name\": \"save_patient\",
          \"arguments\": {
            \"first_name\": \"Smoke\",
            \"last_name\": \"Test\",
            \"date_of_birth\": \"01/01/1980\",
            \"sex\": \"other\",
            \"phone_number\": \"${PHONE}\",
            \"address_line_1\": \"1 Test Lane\",
            \"city\": \"Testville\",
            \"state\": \"TX\",
            \"zip_code\": \"75001\"
          }
        }
      }]
    }
  }")
echo "   Response: $RESP"
echo "$RESP" | grep -q '"result":"SUCCESS:' && pass "save_patient succeeded" || fail "save_patient did not return SUCCESS"

# Extract patient_id
PATIENT_ID=$(echo "$RESP" | grep -oP 'patient_id=[a-f0-9\-]+' | head -1 | cut -d= -f2)
echo "   Patient ID: $PATIENT_ID"

# ---------------------------------------------------------------------------
# 6. Vapi lookup_by_phone — now found
# ---------------------------------------------------------------------------
info "6. Vapi lookup_by_phone (now registered)"
RESP=$(curl -sf -X POST "${BASE_URL}/vapi/tools" \
  -H "Content-Type: application/json" \
  ${VAPI_SECRET:+-H "x-vapi-secret: $VAPI_SECRET"} \
  -d "{
    \"message\": {
      \"type\": \"tool-calls\",
      \"call\": {\"id\": \"smoke-test-call-5\"},
      \"toolCallList\": [{
        \"id\": \"tc-5\",
        \"type\": \"function\",
        \"function\": {\"name\": \"lookup_by_phone\", \"arguments\": {\"phone_number\": \"${PHONE}\"}}
      }]
    }
  }")
echo "   Response: $RESP"
echo "$RESP" | grep -q '"result":"FOUND:' && pass "lookup_by_phone returned FOUND" || fail "lookup_by_phone did not return FOUND after save"

# ---------------------------------------------------------------------------
# 7. REST GET /patients (patient should appear)
# ---------------------------------------------------------------------------
info "7. GET /patients (should include new patient)"
RESP=$(curl -sf "${BASE_URL}/patients")
echo "   Response (truncated): ${RESP:0:200}..."
echo "$RESP" | grep -q '"data":\[' && pass "GET /patients returned list" || fail "GET /patients failed"
echo "$RESP" | grep -q 'Smoke' && pass "New patient appears in list" || fail "New patient not in list"

# ---------------------------------------------------------------------------
# 8. REST GET /patients/{id}
# ---------------------------------------------------------------------------
if [ -n "$PATIENT_ID" ]; then
  info "8. GET /patients/${PATIENT_ID}"
  RESP=$(curl -sf "${BASE_URL}/patients/${PATIENT_ID}")
  echo "   Response: ${RESP:0:200}..."
  echo "$RESP" | grep -q '"patient_id"' && pass "GET /patients/{id} succeeded" || fail "GET /patients/{id} failed"
else
  echo -e "${YELLOW}⚠ SKIP${NC} 8. Could not extract patient_id from save_patient response"
fi

# ---------------------------------------------------------------------------
# 9. REST DELETE (cleanup)
# ---------------------------------------------------------------------------
if [ -n "$PATIENT_ID" ]; then
  info "9. DELETE /patients/${PATIENT_ID} (cleanup)"
  RESP=$(curl -sf -X DELETE "${BASE_URL}/patients/${PATIENT_ID}" \
    ${API_KEY:+-H "x-api-key: $API_KEY"})
  echo "   Response: $RESP"
  echo "$RESP" | grep -q '"deleted":true' && pass "DELETE succeeded" || fail "DELETE failed"
fi

echo ""
echo "=========================================="
echo -e "  ${GREEN}All smoke tests passed!${NC}"
echo "=========================================="
echo ""
