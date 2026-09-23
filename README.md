# Patient Registration Backend

A voice-agent-first patient registration system built with FastAPI, backed by Supabase Postgres, and integrated with [Vapi](https://vapi.ai) for phone-based registration.

---

## Live Deployment

| Resource | URL |
|---|---|
| **Phone Number** | *(add your Vapi phone number here)* |
| **API Base URL** | *(add your deployment URL here, e.g. https://your-app.railway.app)* |
| **Dashboard** | `<API Base URL>/` |
| **API Docs** | `<API Base URL>/docs` |

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Caller (phone)                        │
└──────────────────────┬──────────────────────────────────┘
                       │ voice
                       ▼
┌─────────────────────────────────────────────────────────┐
│                   Vapi Voice Agent                       │
│  (LLM + telephony + tool-calling)                       │
└──────────┬────────────────────────────────┬─────────────┘
           │ POST /vapi/tools               │ POST /vapi/webhook
           │ (x-vapi-secret)                │ (end-of-call-report)
           ▼                                ▼
┌─────────────────────────────────────────────────────────┐
│               FastAPI Application                        │
│                                                         │
│  ┌─────────────────┐    ┌────────────────────────────┐ │
│  │ /vapi/tools     │    │ /patients (REST API)       │ │
│  │  validate_field │    │  GET /patients             │ │
│  │  lookup_by_phone│    │  GET /patients/{id}        │ │
│  │  save_patient   │    │  POST /patients            │ │
│  │  update_patient │    │  PUT /patients/{id}        │ │
│  └────────┬────────┘    │  DELETE /patients/{id}    │ │
│           │             └────────────────────────────┘ │
│  ┌────────▼────────────────────────────────────────┐   │
│  │              services.py (CRUD)                 │   │
│  └────────────────────┬────────────────────────────┘   │
│                       │ SQLAlchemy (sync)                │
└───────────────────────┼─────────────────────────────────┘
                        ▼
┌─────────────────────────────────────────────────────────┐
│            Supabase Postgres                            │
│  public.patients    public.call_logs                    │
└─────────────────────────────────────────────────────────┘
                        ▲
                        │ read-only polling (GET /patients)
┌─────────────────────────────────────────────────────────┐
│            Dashboard (static/dashboard.html)            │
│  Vanilla JS · auto-refresh every 5s · no build step    │
└─────────────────────────────────────────────────────────┘
```

---

## Tech Choices

| Choice | Justification |
|---|---|
| **FastAPI** | Fast, typed, OpenAPI docs built-in, async-ready when needed |
| **SQLAlchemy 2.x sync** | Simple, reliable; async adds complexity without benefit here |
| **psycopg v3 (binary)** | Native Postgres driver; required for SQLAlchemy 2.x + Postgres |
| **Pydantic v2** | Strong validation; matches FastAPI's native types |
| **pydantic-settings** | Clean env var loading with type coercion |
| **Supabase Postgres** | Managed Postgres with free tier, instant setup |
| **Vanilla JS dashboard** | Zero build step, zero dependencies, just works |
| **Raw SQL via `text()`** | Simple, predictable, no ORM magic hiding query behavior |

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | Yes | Supabase Postgres connection string (`postgresql+psycopg://...`) |
| `VAPI_SHARED_SECRET` | Recommended | Secret for `x-vapi-secret` header validation |
| `API_KEY` | Optional | If set, required on POST/PUT/DELETE `/patients` as `x-api-key` |
| `LOG_LEVEL` | No | `DEBUG`, `INFO` (default), `WARNING`, `ERROR` |

> **Supabase Transaction Pooler note:** If your `DATABASE_URL` uses the pooler port (6543), prepared statements are automatically disabled (`prepare_threshold=None`), which is required for PgBouncer compatibility.

---

## Run Locally

```bash
# 1. Clone and set up environment
git clone <repo>
cd CallingAgent
python -m venv venv
source venv/bin/activate     # Windows: venv\Scripts\activate
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env
# Edit .env with your DATABASE_URL and VAPI_SHARED_SECRET

# 3. Start the server
uvicorn app.main:app --reload --port 8000

# Open http://localhost:8000 for the dashboard
# Open http://localhost:8000/docs for the API explorer
```

---

## Run Tests

Tests run completely offline — no database or network connection needed.

```bash
# Run all tests
pytest tests/ -v

# Run only validation tests
pytest tests/test_validation.py -v

# Run only API tests
pytest tests/test_patients_api.py -v

# Run only Vapi tool tests
pytest tests/test_vapi.py -v
```

---

## Deploy (Docker)

```bash
# Build
docker build -t patient-registration .

# Run
docker run -p 8000:8000 \
  -e DATABASE_URL="postgresql+psycopg://..." \
  -e VAPI_SHARED_SECRET="your-secret" \
  patient-registration
```

**Railway / Render / Fly.io:** Set the env vars in the dashboard and point to the Dockerfile. The app binds to `$PORT` automatically.

---

## How the Voice Tools Work

1. Caller phones the Vapi number.
2. The Vapi LLM greets them and asks if they're new or returning.
3. For new patients, the agent collects fields one by one, calling `validate_field` after each to confirm the value before moving on.
4. `lookup_by_phone` checks for existing registrations at the start of the call.
5. When all required fields are collected, the agent calls `save_patient` which validates server-side and inserts into Postgres.
6. `update_patient` lets returning patients change their information.
7. At call end, Vapi fires `end-of-call-report` to `/vapi/webhook`, which stores the transcript and summary in `call_logs` and links it to the patient.

---

## How Validation is Layered

```
Layer 1 — Voice tool (validate_field):
  Called during the call, after each field. Returns plain-English
  messages the LLM speaks aloud. Catches errors early.

Layer 2 — Service layer (save_patient / update_patient):
  Full server-side re-validation before any DB write.
  Returns ERROR_FIELD with first failing field so agent re-asks.

Layer 3 — REST API (/patients POST/PUT):
  Same validation logic via validate_patient(). Returns 422
  with per-field messages for programmatic callers.

Layer 4 — Database constraints:
  unique index on phone_number WHERE deleted_at IS NULL.
  Last line of defense against race conditions.
```

---

## Known Limitations

- **Free-tier hosting:** Services like Railway or Render free tiers sleep after inactivity. First request after sleep may take 10–30 seconds. Use a paid tier or keep-alive pings for production.
- **No HIPAA compliance:** This system is not HIPAA-compliant. Do not use with real patient data without proper BAA, encryption at rest, audit logging, and access controls.
- **Shared-secret auth only:** The Vapi endpoint uses a single shared secret. For production, use OAuth or signed JWTs.
- **No rate limiting:** Add a rate limiter (e.g., `slowapi`) before public deployment.
- **Soft deletes only:** Deleted patients remain in the database. Add a purge job for real HIPAA compliance.
- **Single region:** No multi-region replication. Supabase free tier is single region.

---

## Next Steps

1. **HIPAA compliance:** Encrypt PII at rest, add audit log table, get BAA with Supabase.
2. **Authentication:** Replace shared secret with signed JWT or mTLS for the Vapi endpoint.
3. **Rate limiting:** Add `slowapi` or an API gateway.
4. **Appointment scheduling:** Add `appointments` table and corresponding Vapi tool.
5. **Multi-language:** Detect caller language and respond in kind.
6. **SMS confirmation:** Send confirmation SMS after successful registration via Twilio.
7. **Admin UI:** Add write-capable admin interface with proper auth.
8. **Monitoring:** Add Sentry or Datadog for error tracking and alerting.
