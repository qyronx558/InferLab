# Persistence and migrations

SQLAlchemy models live in `apps/api/src/inferlab_api/database/models.py`.
Alembic revisions under `migrations/versions` are the schema history. Importing
models or starting the health-only API opens no database and performs no DDL.
There are no queue, benchmark, authentication or deployment services in this change.

## Local SQLite and PostgreSQL selection

From the repository root after setup:

```powershell
uv sync --locked
# Default: creates .local/inferlab.db only when explicitly invoked.
uv run --locked alembic upgrade head
uv run --locked alembic current
uv run --locked alembic check
```

The explicit engine/session factories and Alembic use `INFERLAB_DATABASE_URL`, then
`DATABASE_URL`, then `sqlite:///./.local/inferlab.db`. An explicit factory URL or
Alembic `config.attributes["database_url"]` takes precedence for tests/tools.
They do not automatically load `.env` files. Relative SQLite paths use the process
working directory; use an absolute URL outside repository-root development.

For an existing owner-controlled PostgreSQL database, set a process variable:

```powershell
# Replace placeholders locally; never commit or print the resulting credential URL.
$env:INFERLAB_DATABASE_URL = 'postgresql+psycopg://USER:PASSWORD@127.0.0.1:5432/inferlab'
uv run --locked alembic upgrade head
```

`postgres://` and `postgresql://` normalize to psycopg 3; unsupported database
drivers are rejected. No PostgreSQL server, Docker container, paid service or
database account is provisioned. Configure TLS appropriately for an external
PostgreSQL server. Engines disable parameter echoing; avoid enabling SQL/debug
logging or pasting database URLs into errors/issues. Environment URLs bypass
Alembic INI interpolation, including percent-encoded passwords.

SQLite uses explicit transaction behavior, enables foreign keys on **every new
connection**, and sets a five-second busy timeout. This is a single-worker local
development choice, not an assertion of PostgreSQL-like multi-writer behavior.
Pooled sessions must be scoped and closed by the calling service. Use
`with session_factory(engine)() as session:` and explicit transaction/commit policy;
no global session or automatic commit is installed.

## Tables and guarantees

| Model/table | Evidence and constraints |
| --- | --- |
| `ModelRegistry` / `model_registry` | Installed model identifier, revision, SHA-256, quantization, context limit and license metadata. No executable/download path or model bytes. Composite pin referenced by experiments prevents changing/deleting referenced identity. |
| `Experiment` / `experiments` | Normalized config plus workload/prompt IDs/hash, engine pins, GPU/device/driver/methodology and creation timestamp. Bounds match current single-client contracts, including seed support, token/context budget and cold/warmup separation. |
| `Job` / `jobs` | Idempotency key and request-metadata hash, lifecycle phase, attempt, optional worker/lease/fencing metadata, cancellation and terminal timestamps/errors. Named unique nullable active slot permits at most one leased/running job. |
| `RunMetric` / `run_metrics` | One observed run, identified by job/attempt/kind/repetition, condition and outcome. Composite foreign keys reject job/experiment and experiment/condition mismatches. Counts are separate from requested budgets. |
| `PublishedReport` / `published_reports` | Bounded validated public-contract snapshot, canonical payload hash, publication timestamp and experiment reference. ORM insertion verifies stored config/provenance, matching completed run evidence and completed job attempt; accepted-run links are inserted in the same transaction. ORM updates are rejected; create a new report version. This is storage, not approval or a deployment receipt. |
| `published_report_runs` | Association table with report/run/experiment composite foreign keys. Prevents cross-experiment evidence links and deletion of linked runs or reports without explicit archival. |
| `AuditEvent` / `audit_events` | Fixed actor/action/outcome/subject/reason vocabulary and timestamp. No free-form request/exception body, IP, username, user agent or session token. Opaque subject IDs intentionally survive subject archival without cascading audit deletion. |

Queue, experiment/run lookup, lease expiry, report lookup and retention timestamps
are indexed. Referenced model/experiment/job/run evidence uses restrictive foreign
keys rather than implicit cascading deletion. Unpublished queued jobs can coexist;
only leased/running rows occupy the unique active slot.

These are persistence constraints, **not a queue implementation**. The future
worker must use atomic conditional claims/updates, database-authoritative lease
time, fencing checks and a local execution lock. A unique slot does not expire a
lease, terminate GPU work or reconcile stale attempts. `Job.attempt` records the
current attempt; `RunMetric.attempt` retains per-attempt evidence. A separate
append-only JobAttempt/lease-event history remains a later architecture task.

Cross-row admission rules still belong in future transactional services: registry
capability checks, per-kind repetition limit against a particular experiment,
actual input/output budgets and stale-worker completion checks. Report insertion
checks its evidence but does not calculate summaries, verify model files, or prove
privacy/license review and admin approval. Direct SQL/bulk writes bypass Python
identifier, finite-value, JSON and ORM report/evidence validators; restrict write access and
use reviewed service paths. Database foreign keys/checks remain active for direct
SQL. Report snapshots and linked experiment/run evidence have ORM update guards,
not a database role/trigger immutability guarantee.
Future multi-writer publication services must lock source rows or otherwise
serialize evidence validation and snapshot insertion; mapper checks alone are not
a complete cross-transaction publication protocol.

## Typed measurements and time

Unit-bearing numeric columns make the persisted unit fixed by schema:

| Column | Unit / bounds |
| --- | --- |
| `ttft_ms`, `request_latency_ms` | milliseconds, finite and nonnegative |
| `decode_tokens_per_second` | tokens/second; not aggregate cohort throughput |
| `peak_vram_mib` | MiB; an absolute observed peak, not a signed baseline delta |
| `quality_score` | score in [0, 1] |
| `input_tokens`, `output_tokens` | nonnegative integer token counts |
| `trace_bytes` | external artifact byte size |

Each optional numeric measurement has its own `*_reason`. A null measurement
requires a known unavailable reason; a present measurement requires a null reason.
Zero remains a valid value. Application binds reject booleans, strings, NaN,
infinity and negatives; database checks bound values and availability pairs.
Completed runs require counts and no error. Failed/cancelled runs retain diagnostics
with explicit error state. TTFT cannot exceed a present request latency. This is
validation only: existing metric helpers are not called by persistence.

All timestamps require aware datetimes at ORM/Core typed binding. They normalize
to UTC; SQLite stores UTC-naive database values and the type restores UTC on read,
while PostgreSQL uses timezone-aware timestamps. Never use database UTC timestamps
for benchmark elapsed-time subtraction; monotonic timing remains owner work.

## Privacy, artifacts and retention

There are no raw prompt, generated-answer, token-stream, NVML-trace or arbitrary
log columns. Store registered public/synthetic prompt IDs and checksums. A validated
report snapshot contains only the existing allowlisted public contract and is
capped at 256 KiB. Human-written titles/metadata can still contain private text;
content/privacy review remains necessary before approving a snapshot.

Bulky traces belong under the owner-controlled, Git-ignored `benchmark_artifacts/`
root. A run stores only an optional SHA-256, byte count and expiry timestamp; all
three must be present together. Use opaque content-addressed storage, not user
paths/URLs. No artifact reader/writer or filesystem cleanup is implemented. Raw
personal prompts and response text should stay disabled even in traces unless the
owner explicitly opts into a reviewed local retention policy. Do not put them into
audit subjects, filenames, exception messages or credentials-bearing URLs.

Retention follows the architecture:

- Raw traces: **7 days** by default; preserve run measurements/provenance after
  trace removal. Future cleanup should verify the configured storage root and
  checksum reference, remove only expired owned files, and clear the reference
  transactionally with recoverable bookkeeping.
- Audit events: **90 days** by default; prune using the timestamp index in bounded
  batches, recording a safe retention event. No automatic pruning runs here.
- Published snapshots and linked accepted metrics/provenance: retain until a
  deliberate reviewed archive/withdrawal. Foreign keys protect accidental deletion;
  deleting a database row cannot recall public copies.
- Unpublished experiment/job metadata: retain until deliberate owner archival in
  this stage; no silent deletion or invented retention job. Delete dependent rows
  in an explicit reviewed order only after protecting any published evidence.

Review storage monthly. Before migration/archival, export an owner-controlled
database backup and approved bundles outside Git; keep the last seven backup sets
per the architecture. For active SQLite use an online backup API or stop writers
before copying; copying only the main file during writes may omit transactional
state. PostgreSQL needs its own consistent backup/restore procedure. A downgrade
is a schema operation, not a backup or cross-engine data transfer.

## Migration development and verification

Revision `0002` adds administrative experiment labels/version/archive timestamps,
server-side session digests, durable idempotency responses and one serialized API
admission/rate-limit row. It expands audit actions for rename/archive/logout without
modifying benchmark evidence. API successes and their audit/idempotency records
commit together. Rate charges commit before the mutation so failed validation also
counts. Keep idempotency tombstones while experiment IDs remain reserved, including
after archival; deleting them permits unsafe replay. Expired sessions can be removed
by the operator (a new login also clears older sessions). No automatic purge runs.

The `0002` downgrade refuses to narrow audit action constraints while new action
records remain; export/archive those explicitly before a deliberate downgrade.
Downgrade drops session/idempotency/label data and is for disposable databases;
restore a consistent backup when rolling back retained installations.

```powershell
uv run --locked alembic revision --autogenerate -m 'describe change'
# Review all generated DDL and test it before applying to retained data.
uv run --locked pytest tests/test_database.py
```

Revisions contain explicit frozen schema operations and do not import live model
metadata. Alembic's environment imports metadata for comparison only. New SQLite
alterations should use reviewed batch migrations; automatic generation is not
proof of a safe data migration. Initial downgrade removes all application tables
and their data: use it only for disposable development/test databases.

Tests migrate fresh SQLite files through upgrade/downgrade/re-upgrade, compare the
migrated schema against ORM metadata, persist synthetic evidence and exercise
indexes, checks, foreign keys, units, UTC and privacy surfaces. They also compile
PostgreSQL upgrade/downgrade SQL offline using the psycopg dialect. Offline DDL
validation is **not a live PostgreSQL migration test**; test against a disposable
owner-controlled PostgreSQL database before adopting it. No test contacts a remote
database or uses GPU/cloud credentials.

References: [SQLAlchemy constraints](https://docs.sqlalchemy.org/en/20/core/constraints.html),
[SQLite transactions/FKs](https://docs.sqlalchemy.org/en/20/dialects/sqlite.html),
[PostgreSQL/psycopg](https://docs.sqlalchemy.org/en/20/dialects/postgresql.html), and
[Alembic batch migrations](https://alembic.sqlalchemy.org/en/latest/batch.html).
