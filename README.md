# InferLab

Local LLM inference benchmarking with a public, read-only portfolio of reviewed
results. This is the dashboard design-system preview with engineering guardrails
(rulebook Prompts 01-04). Every displayed result is labeled DEMO DATA. Real
measurements, authentication, execution, database, publishing and cloud deployment
are not implemented yet.

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
# Equivalent: uv run --locked uvicorn inferlab_api.main:app --host 127.0.0.1 --port 8000 --reload

# Worker: prints "not configured" and exits successfully
.\scripts\dev.ps1 -App worker
# Equivalent: uv run --locked inferlab-worker
```

Stop development servers with Ctrl+C. `/health` returns
`{"status":"ok","execution":"not_configured"}`; it reports process liveness,
not GPU readiness. The web app does not call the API. The worker neither polls
nor opens a network listener. API/worker env examples are reserved, not loaded yet;
the frontend example sets only a public display title.

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
Frontend tests cover the dashboard and typed local queries. GitHub Actions repeats the
checks on pull requests and pushes to main with no GPU or secrets. See
[CONTRIBUTING.md](CONTRIBUTING.md) for optional hooks, test conventions, secret
scanning guidance and the boundary around owner-written benchmark algorithms.

The dashboard routes are Overview (`/`), Experiments, Compare, Models, Reports and
Methodology. Search/filter experiments, change comparison models, inspect feedback
states with the header's preview selector, and export clearly labeled demo JSON.
See [the design-system guide](docs/DESIGN-SYSTEM.md) for components, tokens and
accessibility conventions. Optional local browser checks:

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

The mock adapter makes no HTTP requests. Worker offline and API unavailable are
distinct from job failure; cached published demo reports remain readable. All
fixture numbers/checksums are synthetic. No benchmark math or new endpoints are
implemented by the contract layer.

## Security and scope

Development servers bind to loopback. Plain HTTP is for this health-only scaffold;
the authenticated console must implement the PRD's TLS/session/origin requirements
before any experiment mutation exists. Do not forward these ports, bind to
`0.0.0.0`, or deploy this API as a public inference service. No CORS bypass,
credentials or submission endpoints are included.

Never put secrets in `VITE_` variables: they become public bundle content. Keep
model weights, databases, traces and `.env` files out of Git. Setup preserves
existing `.env` files and does not modify experiments or model data. Dependency
install/build hooks execute third-party code; review lockfile changes. No cloud
keys, paid services, ML algorithms, Docker or hosted GPU jobs are included.

Read the [PRD](docs/PRD.md), [architecture](docs/ARCHITECTURE.md),
[zero-cost ADR](docs/ADR-001-zero-cost.md), and
[definition of done](docs/DEFINITION-OF-DONE.md). Those describe future MVP targets;
their release gates are not complete in this skeleton. The
[production rulebook](InferLab_Production_Prompt_Rulebook.pdf) reserves benchmark
algorithms for the owner and sequences the later implementation stages.
