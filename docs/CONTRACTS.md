# InferLab wire contracts (rulebook Prompt 04)

The authoritative definitions are in `apps/api/src/inferlab_api/contracts.py`.
They cover the [PRD](PRD.md) without implementing benchmark math, execution, a
queue, storage, authentication or new HTTP endpoints. FastAPI remains health-only.
The contract layer does not execute core metrics or start the worker. Separately,
the owner authorized CPU-only metric helpers; see [METRICS.md](METRICS.md).

Pinned experiment configs, per-run `Result` provenance, YAML fixtures and their
validation rules are described in [EXPERIMENT-SCHEMAS.md](EXPERIMENT-SCHEMAS.md).

## Source and generated artifacts

| Artifact | Role |
| --- | --- |
| `contracts/openapi.json` | Generated OpenAPI 3.1 component schemas; `paths` is intentionally empty, not an advertised API implementation. |
| `contracts/fixtures/demo.json` | Synthetic wire examples validated by Pydantic. Includes registry, experiments, runs, summaries, reports, heartbeat, submission/receipt and all lifecycle phases. |
| `apps/web/src/api/generated.ts` | Generated TypeScript component types from the OpenAPI file. |
| `apps/web/src/api/types.ts` | Convenient named aliases to generated types; no duplicated field definitions. |
| `apps/web/src/api/fixtures.generated.ts` | Same JSON fixtures emitted as `as const satisfies ContractCatalog` for compile-time checking. |

```powershell
# After editing Python contracts or the source JSON fixtures:
npm.cmd run contracts:generate
# Read-only validation and drift detection:
npm.cmd run contracts:check
.\scripts\check.ps1
```

Commit the source JSON and generated artifacts together. CI checks the OpenAPI
export, Pydantic fixture validation, generated types/fixtures, and the TypeScript
build. Formatting tools skip generated files. The generator makes no network
requests and does not import or start FastAPI. An invalid fixture or stale output
fails checks; generated files are never silently fixed during CI.

## Request and data shapes

- **Engine / model / workload registry:** fixed engine IDs (`ollama`, `llama.cpp`),
  version/build, seed capability, model revision/SHA-256, quantization, context
  capability, workload hash and public/synthetic data policy. Metadata includes no
  executable paths, download URLs, raw prompts, credentials or host identifiers.
- **ExperimentSubmitRequest / ExperimentConfig:** name and idempotency key; registry
  IDs; warm/cold condition; context/input/output budgets; temperature/top-p/seed;
  warmups/repetitions; concurrency 1; GPU device/layers; bounded timeout. Config
  rejects unknown fields, unsafe ID syntax, coercible strings/booleans for integer
  limits, excessive sizes, cold warmups, and budgets exceeding context. Registry
  resolution additionally rejects unknown IDs, unsupported engine/model pairs,
  excessive model context and unsupported seeds. Actual admission/auth/queue caps
  remain future server responsibilities; defining a request does not accept it.
- **Experiment / Job / SubmissionReceipt:** stable IDs, resolved provenance, config,
  lifecycle phase, display state, attempt number, aware timestamps, cancellation
  request flag and safe error code. Receipt means pending/queued, never successful
  execution. The public mock adapter has no mutation hook that submits, retries,
  cancels or persists a job; the separate authenticated admin client does.
- **RunMetrics / Summary:** typed `ms`, `tok/s`, `MiB` and `score` measurements,
  input/output counts, warmup/measured kind, condition, repetition, attempt, run IDs,
  error code, accepted sample count and precomputed summary values. No timing,
  throughput, percentile, quality or aggregation algorithm is provided. Validators
  only check bounds, references and consistency.
- **PublishedReport:** explicitly published, demo/measured label, publication date,
  config, model/engine/workload/device/driver/methodology provenance, accepted
  completed measured runs, summary and limitations. It rejects mismatched IDs,
  mixed attempts/conditions, warmup/failed/cancelled evidence and private extra
  fields. This validates a shape; the later publishing/privacy review still must
  check content, licenses and secrets before any real deployment.
- **WorkerHeartbeat:** server observation and last-seen timestamps, online/offline/
  unknown availability, idle/running mode, active job and pause flag. Online means
  last seen <=90 seconds ago; offline means older. Unknown/offline cannot claim
  live execution. All timestamps require timezone information.

Required nullable measurements use `value: null` with an `unavailable_reason`.
A present value requires a null reason. Missing values never become zero; NaN,
infinity, negatives and wrong units are rejected. Pydantic also enforces semantic
cross-field constraints that TypeScript alone cannot express. TypeScript types
do not validate untrusted network JSON at runtime; the current adapter accepts
only the committed fixtures validated in CI. A future live adapter must add a
runtime validation boundary.

## Lifecycle versus availability

| Persisted job phase | Display state |
| --- | --- |
| queued, leased | pending |
| running | running |
| completed | complete |
| failed | failed |
| cancelled | cancelled |
| No reachable resource | unavailable (response/query state, never a persisted job phase) |

A completed response envelope means a resource was read, not that its contained
job completed. Job timestamps/phase/state must agree. Failed jobs require an error;
complete jobs cannot contain an error or a committed cancellation request.
Incomplete attempts cannot contribute a successful summary or published report.

`Resource[T]` is a discriminated union of `{ state: "complete", label, data: T }`
and `{ state: "unavailable", reason, data: null }`. Query presentation separately
maps initial fetch to pending, cached refresh to running, success to complete,
transport error to failed and an explicit mock cancellation to cancelled. None
of these query transitions edits a job. Worker offline does not mean job failed,
and never hides cached public reports.

## Mock adapter and TanStack Query

`mock-api.ts` returns independent copies of the generated fixtures through typed
async reads. It contains no `fetch`, HTTP client, backend URL or submit operation.
Hooks cover registry, experiment list, runs, summaries, published reports and
heartbeat. The dashboard consumes these hooks through a presentation adapter
which formats dates and values without calculating benchmark metrics.

Each app/provider has its own QueryClient. Local demo snapshots seed the success
cache. Keys include contract version, resource and scenario so an error preview
cannot poison the success cache. Retry, reconnect/window-focus refetch and polling
are disabled. `networkMode: "always"` is safe here because reads are local fixtures;
the authenticated admin console uses a separate provider and HTTP client instead.
No offline mutation is queued or replayed. The worker fixture is offline while
published report reads remain complete.

The header/mobile preview selector and URL support `?state=loading`, `error`,
`empty`, `unavailable` and `cancelled`. Loading uses an abortable unresolved mock
read, error simulates transport failure, and the last two explicitly distinguish
unavailability/cancellation from failure. Reset restores the independent cached
demo snapshot. All views and JSON exports retain DEMO DATA labeling; the fake
revisions/checksums and example numbers must not be treated as real evidence.

Contract tests exercise bounds, unknown input, missing values, finite units,
phase consistency, safe publication evidence, heartbeat threshold/timezones and
registry resolution. Hook/UI tests cover all six display states, fixture isolation,
cancelled requests, offline cache reads and null metrics. Browser checks verify
public navigation still works after network offline with an offline worker.
