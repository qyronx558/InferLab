# InferLab

Local LLM inference benchmarking with a public, read-only portfolio of reviewed
results. This is the public dashboard design-system preview with engineering
guardrails (rulebook Prompts 01-04), plus the explicitly authorized CPU metric
helpers from the tutoring step and a standalone local Ollama HTTP transport. Public
displayed results are labeled DEMO DATA until an operator explicitly publishes
reviewed static snapshots. Real benchmark algorithms and cloud deployment are not
implemented yet; the authenticated local API, admin console, private worker queue
and static snapshot exporter are.

## Windows setup

Install Node.js **22.13+ in the 22.x line, or 24.x**, npm **10 or 11**, and
[uv](https://docs.astral.sh/uv/getting-started/installation/). Python **3.12** is
required; uv can download it if absent. Setup downloads dependencies and may
download Python; it does not download models or provision cloud resources.
The system's older `python` can remain installed: uv selects `.python-version`.

From a fresh clone in PowerShell:

```powershell
.\scripts\setup.ps1
```

If execution policy blocks local scripts, use a process-only override:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup.ps1
```

To select an existing Python 3.12 interpreter explicitly:

```powershell
.\scripts\setup.ps1 -Python 'C:\path\to\Python312\python.exe'
```

Setup uses `npm ci` and `uv sync --locked`; commit both `package-lock.json` and
`uv.lock`. It copies placeholder environment examples only when `.env` files do
not exist. No virtual-environment activation is necessary. Python members use
editable src-layout installs, and `inferlab_core` is independently buildable.
Dependency ranges constrain compatible releases; lockfiles record exact resolved
versions. Regenerate locks deliberately when upgrading dependencies.

## Run each app

Use separate PowerShell terminals from the repository root:

```powershell
# Frontend: http://127.0.0.1:5173
.\scripts\dev.ps1 -App web
# Equivalent: npm.cmd run dev:web

# API: http://127.0.0.1:8000/health
.\scripts\dev.ps1 -App api
# Equivalent: uv run --locked uvicorn inferlab_api.main:app --host 127.0.0.1 --port 8000 --reload --no-access-log --no-proxy-headers

# Worker: polls privately when configured; otherwise prints "not configured"
.\scripts\dev.ps1 -App worker
# Equivalent: uv run --locked inferlab-worker
```

Stop development servers with Ctrl+C. `/health` returns
`{"status":"ok","execution":"not_configured"}`; it reports process liveness,
not GPU readiness. The public site does not call the API; the authenticated
`/admin` console does. The worker polls the local
database only after operator configuration and opens no network listener.
Env example files are not loaded automatically;
the frontend example sets only a public display title.

## Local database

SQLAlchemy models and Alembic migrations support SQLite development and an
operator-supplied PostgreSQL URL. Database creation/migration is explicit; the
API opens a database engine only with an explicitly configured environment URL and
never migrates during startup:

```powershell
uv run --locked alembic upgrade head
uv run --locked alembic current
uv run --locked alembic check
uv run --locked pytest tests/test_database.py
```

The default file is `.local/inferlab.db`. See [DATABASE.md](docs/DATABASE.md) for
`INFERLAB_DATABASE_URL`, PostgreSQL, typed units, privacy and retention. Raw prompts
and bulky traces are not database fields. The worker supervises an injected
owner-authored benchmark plugin; no default benchmark runner is installed.

## Publish static snapshots

The public dashboard reads `/data/v1/manifest.json` when a reviewed release exists,
verifies every asset's size and SHA-256 checksum, and displays the snapshot date and
release ID. Without a manifest it falls back to bundled demo data. Publishing is an
explicit operator step; builds and API startup never publish automatically.

```powershell
# Validate without replacing the public release:
uv run --locked inferlab-publish --validate-only --fixture contracts/fixtures/demo.json

# Publish the reviewed fixture (or omit --fixture to read published_reports):
uv run --locked inferlab-publish --fixture contracts/fixtures/demo.json
```

The default output is `apps/web/public/data`, which receives `v1/manifest.json`,
immutable hashed reports, models and methodology assets. Use `--output` to stage a
different static root. The exporter enforces the 100-report, 2,000-file and 5 MiB
per-asset limits, rejects secret/path/raw-log canaries, and replaces `v1` atomically
only after validation succeeds. See [ARCHITECTURE.md](docs/ARCHITECTURE.md) for the
public contract and [DEFINITION-OF-DONE.md](docs/DEFINITION-OF-DONE.md) for the
publication boundary.

The [API guide](docs/API.md) documents published-only public reads and authenticated
experiment CRUD, rename/archive, cancel/retry, worker heartbeat, pagination,
idempotency and errors. Admin mutations require locally trusted HTTPS, a provisioned
Argon2id password hash and CSRF protection. An injected operator admission provider
supplies approved registry/provenance; the default submission provider returns 503.
The public dashboard remains mock-only; the authenticated `/admin` console uses the
live API, and no worker execution is started by an HTTP request.

The [private worker guide](docs/WORKER.md) covers fixed registry policy, exclusive
GPU/process locks, 120-second fenced leases, heartbeats, one-hour job budgets,
cancellation, bounded retries and restart recovery. Apply migration `0003` before
using the worker. Failure/restart tests use CPU fixtures and spawned Python
processes, without downloading models or implementing benchmark algorithms.

## Verify

```powershell
.\scripts\check.ps1
# Individual checks:
npm.cmd run contracts:check
npm.cmd run format:check
npm.cmd run lint
npm.cmd run typecheck
npm.cmd run build
npm.cmd test
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy
uv run --locked pytest -m "not gpu"
uv run --locked pre-commit run --all-files

# Independently build the core wheel:
uv build --package inferlab-core
# Preview compiled static frontend at http://127.0.0.1:4173:
npm.cmd run preview:web
```

Expected: contract drift checks, formatting/lint/types/build and CPU-only tests
pass, worker exits without executing jobs, core wheel builds under `dist/`.
Frontend tests cover the public dashboard, its typed demo queries and the live admin
console. GitHub Actions repeats the
checks on pull requests and pushes to main with no GPU or secrets. See the
[release gate checklist](docs/RELEASE-GATES.md) for the mapping to owner-recorded
evidence, and [CONTRIBUTING.md](CONTRIBUTING.md) for optional hooks, test
conventions, secret scanning guidance and the boundary around owner-written benchmark
algorithms.

The public dashboard routes are Overview (`/`), Experiments, Compare, Models, Reports
and Methodology, plus the printable comparison report at `/compare/report`.
Search/filter experiments, change comparison models, inspect feedback states with the
header's preview selector, and export clearly labeled demo JSON. Compare renders six
lazily loaded Plotly views with model revision, quantization, prompt distribution,
sample count and hardware context beside each value; CSV/JSON exports and the printable
report carry the same context and an observational, no-causation notice. The
authenticated admin console is under `/admin` (login, experiment list, new experiment
and experiment detail). See [the design-system guide](docs/DESIGN-SYSTEM.md)
for components, tokens and accessibility conventions. Optional local browser checks:

```powershell
npm.cmd exec --workspace @inferlab/web -- playwright install chromium
npm.cmd run test:e2e
```

These checks use headless Chromium on CPU to inspect desktop/mobile layouts,
keyboard navigation and automated accessibility. They are separate from hosted CI.

The [contract guide](docs/CONTRACTS.md) describes the Pydantic source, generated
TypeScript, state/availability mapping, validated fixture bundle and TanStack Query
hooks. Regenerate after changing a contract or source fixture:

```powershell
npm.cmd run contracts:generate
npm.cmd run contracts:check
```

The public mock adapter makes no HTTP requests. Worker offline and API unavailable
are distinct from job failure; cached published demo reports remain readable. The
admin console uses a separate typed HTTP client with runtime response validation.
All public fixture numbers/checksums are synthetic. No benchmark math or new public
endpoints are implemented by the contract layer.

The [metric guide](docs/METRICS.md) explains the implemented TTFT, TPOT, throughput,
elapsed-time and dense KV-cache helpers. This step was AI-assisted at the owner's
explicit request; it does not add an inference runner. Try the synthetic examples:

```powershell
uv run --locked python examples/metrics_walkthrough.py
uv run --locked pytest tests/test_metrics.py
```

The [Ollama transport guide](docs/OLLAMA.md) covers `EngineProtocol`, async generate
and NDJSON streaming, health/model information, typed errors, timeout configuration
and cancellation. The adapter requires an already installed local model and never
pulls models. It is not wired into the worker, API or dashboard. Benchmark timing
and calculations remain owner TODOs at this boundary. Run its CPU-only mocks with:

```powershell
uv run --locked pytest tests/test_ollama.py
```

The [llama-server transport guide](docs/LLAMA-CPP.md) adds the same protocol for a
manually started local llama.cpp server, with validated GPU-layer/context startup
settings and SSE streaming. InferLab does not download or launch the binary. Run
the shared HTTP parity tests with:

```powershell
uv run --locked pytest tests/test_engine_parity.py tests/test_llama_cpp.py
```

## Security and scope

Development servers bind to loopback. Plain HTTP supports liveness and read-only
development; admin authentication and mutations require HTTPS. See the API guide
for local TLS and session setup, and the
[single-admin auth ADR](docs/ADR-002-single-admin-auth.md) for the security
decision. Do not forward these ports, bind to `0.0.0.0`, or
deploy this API as a public inference service. Default access logging is disabled
to avoid retaining query strings. No default credentials are included.

Never put secrets in `VITE_` variables: they become public bundle content. Keep
model weights, databases, traces and `.env` files out of Git. Setup preserves
existing `.env` files and does not modify experiments or model data. Dependency
install/build hooks execute third-party code; review lockfile changes. No cloud
keys, paid services, automatic model downloads, Docker or hosted GPU jobs are included.

Read the [PRD](docs/PRD.md), [architecture](docs/ARCHITECTURE.md),
[zero-cost ADR](docs/ADR-001-zero-cost.md),
[single-admin auth ADR](docs/ADR-002-single-admin-auth.md), and
[definition of done](docs/DEFINITION-OF-DONE.md). Those describe future MVP targets;
their release gates are not complete in this skeleton. The
[production rulebook](InferLab_Production_Prompt_Rulebook.pdf) reserves benchmark
algorithms for the owner and sequences the later implementation stages.
