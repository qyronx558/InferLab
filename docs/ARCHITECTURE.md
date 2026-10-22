# InferLab architecture

Status: proposed MVP design, 2026-10-20. Follows the [PRD](PRD.md) and rulebook's static publishing boundary. No services are provisioned by this specification.

## Components and trust boundaries

```text
Public browser --HTTPS--> Cloudflare Pages: React build + sanitized JSON snapshots
                               No route to laptop or inference engines

Admin browser --loopback HTTPS--> local FastAPI + built React admin console
                                           |
                                      local SQLite
                                           |
                                one private Python worker
                                           |
                              loopback Ollama (later llama.cpp)

Admin-approved local export --reviewed deployment--> Pages release
```

Frontend target: React, TypeScript, Vite, Tailwind, shadcn/ui, TanStack Query; Plotly when needed. Backend target: Python, FastAPI, Pydantic, SQLAlchemy. SQLite is sufficient for the single-machine MVP; PostgreSQL compatibility and migrations are a later gate before adopting Neon. No Redis, cloud queue, Pages Functions, cloud database, or always-on cloud API is required for MVP.

Local API and inference engines bind only to loopback. Admin UI is served on the local API origin behind locally trusted TLS; public Pages never calls localhost. Worker accesses the local queue through shared application contracts and its own database connection, not a publicly addressable worker HTTP server. Remote admin requires a separate reviewed, authenticated access design and is stretch.

## Public read API: static resources

All paths below are on the Pages origin, unauthenticated, and contain published data only. They are versioned JSON resources, not live FastAPI endpoints. `GET`/`HEAD` only; no public mutation handler exists. Client-side filters operate on the manifest (maximum 100 reports); no unbounded public search endpoint is needed.

| Method / path | Contract |
| --- | --- |
| GET `/data/v1/manifest.json` | Schema version, release ID/date, published report IDs and summaries, resource paths and SHA-256 hashes. |
| GET `/data/v1/reports/{report_id}.{hash}.json` | Immutable sanitized report, underlying public run IDs/measurements, reproducibility metadata, methods version. |
| GET `/data/v1/models.{hash}.json` | Metadata only for models in this release. |
| GET `/data/v1/methodology.{hash}.json` | Versioned metric definitions, units, conditions, limitations and protocol. |

Manifest uses revalidation (`no-cache`); hashed assets may be cached immutably. JSON paths must return actual JSON or 404, never SPA HTML fallback. Build validates IDs, schema, finite metrics, sizes and same-origin manifest paths. UI validates responses, uses allowlisted ID formats, rejects unknown versions and displays integrity/load errors. Checksums detect corruption; hosting/deploy credentials remain the authenticity trust root.

No unpublished experiment ID, private registry entry, queue status, heartbeat, log, session or audit event appears in these resources. Withdrawal removes references and files in a new release; old deployments must also be removed when necessary. Downloaded/cached copies cannot be recalled, so privacy review precedes every publication.

## Private local API

Implemented endpoint scope and setup are in [API.md](API.md). FastAPI also offers
unauthenticated local read mirrors at `/api/v1/public/reports`,
`/api/v1/public/reports/{id}` and `/api/v1/public/metadata`, backed exclusively by
stored published snapshots. This does not deploy a cloud API or replace the
independent public static export. The dashboard still uses explicit demo fixtures.
The table below includes future worker/publication routes; those are not exposed
by this CRUD stage. Current experiment detail returns config and latest job;
attempt-history/metric pagination remains future work.

Prefix `/api/v1`; every route below requires the single-admin session except explicit authentication bootstrap. Authenticated non-admin identities are denied; hiding controls is not authorization.

| Method / path | Behavior |
| --- | --- |
| POST `/auth/login` | Local bootstrap exception: verify preprovisioned admin credential, establish session; rate-limited and audited. No registration. |
| POST `/auth/logout` | Revoke current session. |
| GET `/auth/session` | Current admin identity and CSRF token; unauthorized if not signed in. |
| GET `/registry` | Approved model, engine and workload IDs and effective bounds. |
| GET `/experiments?cursor=&limit=` | Private experiment history; limit defaults to 20, maximum 100. |
| POST `/experiments` | Validate config and idempotency key; atomically save experiment/job/audit event; return 202 with IDs and queued status. |
| GET `/experiments/{id}` | Config, attempt history, saved metrics, sanitized diagnostics and current state. |
| PATCH `/experiments/{id}` | Rename administrative metadata with expected version; config/evidence are immutable. |
| DELETE `/experiments/{id}` | Archive private metadata with expected version; preserve evidence, idempotency tombstones and published snapshots. Active jobs must acknowledge cancellation first. |
| POST `/experiments/{id}/cancel` | Idempotent cancellation request; queued jobs cancel immediately, active jobs acknowledge after stopping. Completed jobs return conflict. |
| POST `/experiments/{id}/retry` | Explicit retry of failed/cancelled experiment creates a linked new job; enforces limits and idempotency. |
| GET `/worker` | Availability, last heartbeat, active job and stop-switch state. |
| POST `/worker/pause` | Stop new claims and request cancellation of active work. Resume requires explicit admin action via `POST /worker/resume`. |
| POST `/publications/preview` | Validate completed experiment IDs and generate exact sanitized staged release; no deployment. |
| POST `/publications` | Approve a preview hash and record immutable export/audit entry; returns staged release, not a claim that it is publicly deployed. |
| GET `/publications/{id}` | Export validation, approval and separately recorded deployment outcome. |

Deployment/withdrawal is an explicit admin-operated release step using a scoped deployment credential kept outside the browser and repository. MVP has no public publishing webhook. Worker operations (claim, start, renew, finish, fail, acknowledge cancellation) are internal application/database contracts, not admin-accessible arbitrary job-state setters.

Errors: 401 missing/expired auth, 403 authorization/origin/CSRF failure, 404 missing resource, 409 state/idempotency conflict, 413 oversized body, 422 invalid config, 429 limit exceeded, 503 unavailable. Responses carry safe error codes and request IDs, never traces/secrets. Mutations use idempotency keys; repeating a key with the same body returns the original outcome, different body returns 409. No automatic client retries of submissions with a new key.

## Identity and input bounds

Use a maintained authentication library with standard password hashing (Argon2id), one locally provisioned admin, no custom crypto and no web signup/reset endpoint. Local auth avoids a cloud identity dependency; a managed provider is preferable if remote access is later required. Provisioning/recovery is an operator-only local procedure that invalidates sessions. Sessions are server-side, expire after 12 hours, and use Secure/HttpOnly/SameSite=Strict cookies. Local TLS setup and certificate trust are release prerequisites.

All mutations require an exact trusted Origin and CSRF protection, including login origin checks. CORS allows only the configured local console origin, never wildcard origins with credentials. Validate Host headers against loopback allowlist to resist DNS rebinding. Rate-limit login to 5 failures/15 minutes and mutations to 20/minute; persist login lockouts across API restarts. Audit login failures, submission, cancel/retry, pause/resume and publication approval without storing credentials.

Initial server/worker enforced bounds: 64 KiB API bodies; registry IDs only; context 128-8192 tokens subject to model capability; output 1-2048 tokens; input plus output must fit context; 0-5 warmups; 1-20 measured repetitions; concurrency 1; maximum 10 pending jobs; maximum 1 hour/job, including all runs; at most 10 submissions/day. Registry policy may tighten these limits for 8 GB VRAM. No shell strings, executable paths, uploaded scripts, arbitrary URLs/model repositories, or raw private prompt input is accepted. The worker revalidates saved configs and pins model checksums before execution.

## Persistence and worker recovery

Entities: ModelRegistry, immutable ExperimentConfig, Job, JobAttempt, RunMetric, Publication and AuditEvent. Record typed units and missing-value reasons. Raw traces remain outside the database under bounded local storage. Use unique idempotency keys, one active lease constraint, foreign keys, and atomic conditional state transitions. Index queue state/time and experiment IDs. Publication embeds a methodology version; later edits never reinterpret old measurements silently.

- Worker polls every 5 seconds while idle and healthy, heartbeats every 30 seconds, and claims oldest queued work atomically. A local process/GPU lock plus database lease prevents a second worker from executing concurrently.
- Each attempt receives a fencing token and 120-second lease, renewed every 30 seconds. Start/renew/completion require current token and unexpired lease. Lease time uses database authority; elapsed benchmark timing uses monotonic clocks.
- Active worker stops inference if it cannot renew before expiry. After sleep/disconnect, stop the stale engine request before reclaiming or starting work. If engine termination cannot be confirmed, pause the queue for operator intervention; do not risk overlapping GPU execution.
- Expired leases are reconciled on worker startup/poll, after confirming the engine stopped; API status reads remain read-only. No cloud scheduler is needed. The expired attempt is failed with `worker_lost` (or timeout/cancellation when applicable). It is never completed from partial metrics. While API is offline the UI shows unavailable rather than a fresh state.
- Allow at most one automatic retry (two attempts/job total) for transient engine/network/worker-loss errors after 30 seconds, only once the old execution is confirmed stopped. Validation, checksum, OOM/resource-limit and timeout errors do not automatically retry. An admin-requested retry creates a new linked job, retaining prior evidence.
- The [implemented private worker](WORKER.md) retains terminal `JobAttempt` records while an eligible nonterminal job moves from leased/running back to queued. Terminal jobs never reopen automatically. Both attempts share the first lease's deadline; the one-hour budget is not reset by retry. A process lock, child execution lock and parent-death watchdog prevent orphan Python runners from overlapping a restart. Engine stop confirmation is an additional requirement; process exit alone is insufficient.
- Completion atomically stores accepted measurements and terminal state, unique by attempt/run index. Identical repeated completion returns the existing receipt; conflicting or stale completion is rejected. Exactly-once physical execution after a crash is not promised; stale results cannot overwrite accepted results.
- Cancellation is recorded durably and checked between runs and at each heartbeat. Cancellation and completion use atomic conditional updates: if cancellation is committed first, completion is rejected; if completion is committed first, cancellation returns conflict. Stop active engine work within 30 seconds while the worker is responsive; otherwise reconcile on recovery. Cancelled or failed attempts retain diagnostics but are excluded from successful aggregates and publishing.

## Publication, operations and security risks

Publish pipeline: completed runs -> explicit allowlist projection -> schema/privacy/license checks -> versioned JSON and checksums -> local preview -> admin approval tied to payload hash -> deploy full release -> verify manifest and reports -> record deployment receipt. A successful run or export is not a successful deploy. Rollback deploys the last verified bundle. Models/engine binaries and benchmark data never run in hosted CI.

Keep local audit events 90 days and raw traces 7 days by default; retain published provenance and accepted metrics until deliberate archival. Review storage monthly. Before migrations/publication, export the local database and approved release bundle to owner-controlled storage outside Git; keep the last 7 backup sets. Target recovery point is the last backup (at most 24 hours during active operation), recovery time 1 hour after hardware is available. No paid backup or telemetry service is assumed.

| Threat / failure | Required mitigation | Residual risk |
| --- | --- | --- |
| Unauthorized GPU use, CSRF, stolen session | Loopback only, per-route auth, strict origins/Host, CSRF, rate/resource limits, expiry and revocation | Compromised owner machine/account can execute authorized jobs; pause and revoke credentials. |
| Command/path injection, SSRF, unsafe model execution | Registry IDs, typed allowlists, no shell/path/URL requests; manually reviewed engines/models | Malicious installed binaries/models remain an operator supply-chain risk. |
| Secret/private data disclosure or stored XSS | Allowlisted export, escaped text/no arbitrary report HTML, CSP, privacy scan, public-only workloads; no secrets in VITE variables | Public copies persist; remove affected deployments, rotate leaked secrets. |
| Replay, duplicate workers, stale completion | Persistent idempotency, local GPU lock, atomic leases/fencing, bounded retries and completion uniqueness | Work may repeat after interruption; publish only accepted complete attempts. |
| GPU OOM, thermal stress, queue flooding | Single job, model-specific bounds, deadlines, stop switch and bounded queue | Laptop sleep/heat still interrupts runs; disclose conditions. |
| Misleading benchmarks | Pinned provenance, fair measured baseline, warm/cold separation, units, sample counts and errors | Small samples and device-specific conclusions require explicit caveats. |
| Quota exhaustion, deploy compromise, data loss | Static serving, quota preflight, scoped deploy token, reviewed releases, exports/restore drill | No guaranteed availability; provider/account compromise can alter public artifacts. |

Free-tier budgets and downgrade/stop behavior are specified in [ADR-001](ADR-001-zero-cost.md). Verification requirements are in [DEFINITION-OF-DONE.md](DEFINITION-OF-DONE.md).
