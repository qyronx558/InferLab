# InferLab local HTTP API

This stage implements persisted CRUD and published-only reads. It does not run
benchmarks, start a shell, load/download models, publish new reports, or dispatch
GPU work. The public website still uses static exports and works independently of
this local API. The authenticated admin console under `/admin` uses this API; the
public dashboard continues to use explicit demo fixtures.

## Endpoints

All paths below have prefix `/api/v1`. Public means no authentication; the server
still binds to loopback and must not be internet exposed.

| Access | Method and path | Response |
| --- | --- | --- |
| Public | `GET /public/reports?limit=20&cursor=REPORT-id` | Published snapshots only, with next cursor |
| Public | `GET /public/reports/{id}` | One validated immutable published snapshot or 404 |
| Public | `GET /public/metadata?limit=20&cursor=REPORT-id` | Per-report model, engine and methodology version from those same snapshots |
| Bootstrap | `POST /auth/login` | Password verification; session cookie and CSRF token |
| Admin | `GET /auth/session` | Admin identity, CSRF token, expiry |
| Admin | `POST /auth/logout` | 204; revoke session and expire cookie |
| Admin | `GET /registry` | Operator-approved engines/models/workloads |
| Admin | `GET /experiments?limit=20&cursor=EXP-id` | Unarchived private records, config and latest job |
| Admin | `POST /experiments` | 202; immutable config and queued job |
| Admin | `GET /experiments/{id}` | Config, administrative version/name, latest job |
| Admin | `PATCH /experiments/{id}` | Rename only; `{name, expected_version}` |
| Admin | `DELETE /experiments/{id}` | Archive; `{expected_version}`, returns archived record |
| Admin | `POST /experiments/{id}/cancel` | Cancel queued work or request cooperative cancellation |
| Admin | `POST /experiments/{id}/retry` | 202; new queued job linked to same experiment, retain old job |
| Admin | `GET /worker` | Last durable heartbeat, availability, active job and pause state |

Pagination sorts ascending by immutable resource ID. Limits are 1–100, default
20. The next cursor is the last returned ID when another item exists. Cursors
are validated IDs, not encoded SQL/paths. A moving collection is not a consistent
snapshot: new IDs sorting behind a cursor require a fresh listing. No private
registry, job, audit or session data is returned by public metadata queries.

All experiment writes require `Idempotency-Key`, a 1–64 character approved ID.
Create also requires the same key in `ExperimentSubmitRequest.idempotency_key`.
See the existing Pydantic schemas for the complete bounded config. Unknown fields,
shell commands, paths, URLs, raw prompts and model-download options are rejected.
Cancel/retry accept no body, null or an empty object; other body fields fail validation.

Same key + canonical validated body + method/path returns the original response
and status, even after restart, rename or archival. Changed requests return 409.
The namespace is global to the one admin, across operations. Successful outcomes
are stored atomically with mutation and audit; unsuccessful attempts do not reserve
a key. JSON whitespace/key order does not change identity. Every replay still
requires a valid session, Origin/CSRF and the mutation rate limit. On transient
503 retry the same key; never invent a new submission key. Stale metadata versions
return 409. Experiment IDs and archived evidence remain reserved indefinitely.

## State and resource policy

`queued → leased → running → completed | failed | cancelled`. Queued work can
cancel; leased work may fail/cancel before starting. Terminal jobs never transition
backwards. Explicit retry creates a distinct queued job. API clients cannot set
phases, acquire leases or acknowledge completion through arbitrary state patches.
`lifecycle.check_transition` defines the complete transition policy.

Queued cancel is immediate. Active cancel records `cancellation_requested=true`
without claiming inference stopped; phase stays leased/running until worker
acknowledgement. Archive rejects active jobs, cancels queued work, hides the private
record and preserves evidence. Renames affect administrative labels only. Archival
does not withdraw a published snapshot. Explicit retries revalidate allowlists,
pins and recorded hardware/driver/methodology identity; changed provenance needs
a new experiment ID.

`GET /worker` is read-only. No heartbeat returns `availability="unknown"`; a
heartbeat within 90 seconds is `online`, otherwise `offline`. Online reports `idle`
or `running` with the active job ID; offline/unknown never claims live execution.
The persisted pause flag is returned separately. This route does not claim that
the worker is healthy, that a model is resident, or that GPU work has started.

Existing config caps apply: context 8192, output 2048, warmups 5, repetitions 20,
concurrency exactly 1, deadline 3600 seconds, GPU layers 0–200 plus narrower operator
bounds. Admission allows at most 10 queued jobs and 10 new jobs per rolling 24 hours
(retries count). Authenticated mutations, including invalid requests and replays,
are limited to 20 per fixed one-minute window after valid Origin/CSRF checks.
Bodies are limited to 64 KiB, including chunked bodies; compressed inputs are rejected.

Every write acquires the singleton database admission row before resource reads.
PostgreSQL uses its row lock; SQLite reserves its writer lock. Queue/day checks,
experiment/job/idempotency and success audit commit together. SQLite contention
can return safe 503; clients retry with the original key. The [private worker](WORKER.md)
uses this same serialization boundary for claims, renewals, completion and recovery.
It performs stop verification through the operator's local plugin. API status reads
remain read-only; recovery occurs on worker startup/poll. Live engine stop behavior
and GPU release gates still require owner hardware evidence.

## Operator setup (PowerShell)

Run from the repository root. Example files are not auto-loaded. Provision one
Argon2id hash interactively; no plaintext password or default credential is saved:

```powershell
uv sync --locked
$env:INFERLAB_DATABASE_URL = 'sqlite:///./.local/inferlab.db'
uv run --locked alembic upgrade head
$env:INFERLAB_ADMIN_PASSWORD_HASH = uv run --locked python -c "from getpass import getpass; from argon2 import PasswordHasher; print(PasswordHasher().hash(getpass('Admin password: ')))"
$env:INFERLAB_CONSOLE_ORIGIN = 'https://127.0.0.1:5173'

# Use an operator-created, locally trusted certificate/key outside the repository.
uv run --locked uvicorn inferlab_api.main:app --host 127.0.0.1 --port 8000 --ssl-certfile C:\LOCAL-TLS\cert.pem --ssl-keyfile C:\LOCAL-TLS\key.pem --no-access-log --no-proxy-headers
```

Certificates and trust setup are operator prerequisites; none are generated or
committed here. The configured console must also use HTTPS. `scripts/dev.ps1 -App api`
continues to serve plain HTTP for liveness/read-only development; login and all
authenticated operations fail closed on HTTP. No forwarding headers are trusted
by these commands. No automatic migrations occur. With no explicit database URL,
the default app retains liveness but database routes return 503.

`create_app(engine=..., settings=..., runner=..., clock=...)` is the composition
root. `get_session`, `get_runner`, `get_settings`, `get_now` and authorization
dependencies can also be overridden using FastAPI's dependency overrides.
`RunnerPort.registry()` returns an operator-controlled approved snapshot;
`resolve(config)` returns validated pinned provenance and narrower device limits.
It must be a local admission operation, not inference or a model download. Approved
snapshots can remain available while the worker is offline, allowing durable queueing.
The default port returns 503 for new submissions/registry access. Wire the owner's
admission provider into an operator-owned factory and run `uvicorn module:factory
--factory` when available; no demo runner is installed in production.

The schema-only dashboard catalog at `contracts/openapi.json` remains unchanged.
The running app's `/openapi.json` documents actual routes and cookie authentication;
the Pydantic HTTP models are in `inferlab_api/http_contracts.py`. The authenticated
admin console uses a typed client with runtime response validation and does not
reuse the public dashboard's demo fixture adapter.

## Sessions, errors and audits

Argon2id uses the maintained argon2-cffi `PasswordHasher`. Opaque session tokens
are generated with `secrets`; only an HMAC-SHA256 digest keyed by the configured
password hash is stored. Sessions expire after 12 hours; cookies are host-only,
Secure, HttpOnly, SameSite=Strict. A new login revokes prior sessions, and logout
revokes the current session. Login requires the exact configured Origin, and
mutations additionally require `X-CSRF-Token`. Host accepts only
localhost/127.0.0.1; credentialed CORS allows the exact HTTPS console origin. Five
failed passwords lock login for 15 minutes, persisted across restart. Changing
`INFERLAB_ADMIN_PASSWORD_HASH` changes the session lookup key, so all existing
sessions become unusable immediately. Stop the API, replace the hash and restart;
no manual session-table deletion is required. See
[ADR-002](ADR-002-single-admin-auth.md) for the authentication decision.

Application errors use `{error: {code, message, request_id}}`, with no request body,
SQL, trace, local path, engine response or password echoed. Typical statuses:
401 auth, 403 TLS/origin/CSRF, 404 unknown/archived, 409 version/state/key conflict,
413 size, 415 encoding, 422 validation/allowlist, 429 rate/cap, 503 missing
configuration/storage contention, 500 unexpected internal failure. Framework Host
and CORS preflight rejection responses use their standard 400 representation.
Responses disable caching and include a generated request ID; credentials/CSRF
responses must never enter shared caches. Access logging is disabled in the provided
commands to avoid recording query strings.

Login failures, login/logout and successful submit/update/delete/cancel/retry
events store bounded action, actor, outcome, subject and timestamp. Replays do not
duplicate success events. Failed authenticated requests have redacted failure
events recorded after rollback, with system attribution if no identity was verified;
denial auditing is best effort if storage is unavailable. No raw prompts, bodies,
passwords, cookies, tokens or arbitrary diagnostic strings are stored in audits.
HTTP audit IDs use `AUD-<request_id>` to correlate them with response request IDs.
Retention follows [DATABASE.md](DATABASE.md); backups and idempotency tombstones
need deliberate operator management. No audit-reading, registration, download,
file-serving, arbitrary URL or shell endpoint exists.

## Verification and remaining release gates

```powershell
uv run --locked pytest tests/test_api.py tests/test_database.py tests/test_scaffold.py
.\scripts\check.ps1
```

CPU tests cover access boundaries, durable sessions/idempotency, config caps,
rollback, cursor pages, safe errors, origin/CSRF/TLS, rate limits, archive/report
isolation, duplicate concurrent admission and the complete transition matrix.
No GPU, network engine or cloud account is needed. Live PostgreSQL, local browser
TLS/cookie behavior, actual engine stop/recovery and end-to-end publishing remain
release gates; worker fencing/recovery has CPU failure tests, and offline PostgreSQL
migration SQL is checked separately.

References: [FastAPI dependency injection](https://fastapi.tiangolo.com/tutorial/dependencies/),
[argon2-cffi PasswordHasher](https://argon2-cffi.readthedocs.io/en/stable/howto.html),
[SQLAlchemy transactions](https://docs.sqlalchemy.org/en/20/orm/session_transaction.html).
