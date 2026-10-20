# Contributing to InferLab

Use the [setup instructions](README.md) and work on a focused branch from updated
`main`. Keep each change small enough to review and leave unrelated files alone.
The [production rulebook](InferLab_Production_Prompt_Rulebook.pdf) defines the
learning boundary and delivery sequence.

## Ownership of benchmark logic

The owner personally implements Python benchmark algorithms, timing/metric math,
profiling, load generation and evaluation in `packages/inferlab_core`. AI may
explain concepts, propose signatures/test cases, critique owner-written code and
provide documentation. Do not generate or replace those algorithms unless the
owner explicitly requests a small illustrative example. Routine API scaffolding,
transport plumbing, React/TypeScript, tests, docs and focused refactors are allowed.
Label mock figures DEMO DATA; never invent measurements or speedups. Keep model
revision, workload, output budget, sampling and hardware conditions controlled
when making comparative claims.

## Commands and formatting

```powershell
.\scripts\setup.ps1
.\scripts\check.ps1
# Apply formatting, then review the diff:
npm.cmd run format
uv run --locked ruff format .
uv run --locked ruff check . --fix
```

TypeScript uses strict mode, checked indexed access and exact optional properties.
ESLint checks frontend code; Prettier owns JS/TS, CSS, HTML, JSON, Markdown and YAML
formatting. Reviewed product documents under `docs/` are excluded from bulk
formatting. Ruff owns Python lint/formatting; mypy checks all Python sources/tests
in strict mode. Do not suppress errors broadly to make CI green.

Both dependency lockfiles are committed. Update them intentionally alongside
manifest changes (`npm install`, `uv lock`), inspect resolved packages, and verify
`npm ci` plus `uv sync --locked`. No credentials are needed to install or test.

## Optional local hooks

Hooks are opt-in; setup does not install or alter Git hooks automatically:

```powershell
uv run --locked pre-commit install
uv run --locked pre-commit run --all-files
# Remove only the hook installed by pre-commit:
uv run --locked pre-commit uninstall
```

Run setup first and ensure Node/npm/uv are on PATH in the shell or Git client.
Hooks use the repository's locked tools and check private-key markers, formatting,
ESLint and types. They do not rewrite files. Fix failures, review changes and stage
again. Until a new file is staged, `--all-files` will not check it. CI runs the same
hooks even when a contributor has not installed them locally.

## Tests and hosted CI

Add focused tests for changed behavior, boundaries and failures; avoid tests that
only restate implementation. Python tests go in `tests/` and run with
`uv run --locked pytest -m "not gpu"`. Frontend unit tests go beside source as
`*.test.ts` or `*.test.tsx` and run with `npm.cmd test`; Vitest uses happy-dom on
CPU for DOM/keyboard interactions. Dashboard/query tests and Python contract/smoke
tests run without a backend. Empty suites, collection errors and test
failures fail CI. Optional browser accessibility/layout checks live in
`apps/web/e2e` and run with `npm.cmd run test:e2e` after installing Chromium;
see `docs/DESIGN-SYSTEM.md`.

Pydantic is authoritative for wire contracts. After edits to contracts or the
source JSON fixtures, run `npm.cmd run contracts:generate`, review both generated
TypeScript files and `contracts/openapi.json`, then run `npm.cmd run contracts:check`.
Commit those artifacts together. Do not hand-edit generated types, coerce missing
measurements to zero, mix job phase with service availability, or calculate
benchmark summaries in an adapter. See `docs/CONTRACTS.md` for constraints and the
runtime-validation boundary required before adding a live API client.

Mock engine/network interfaces; do not contact Ollama, llama.cpp, paid APIs or cloud
accounts from unit tests. No models, CUDA, GPU runner or personal evaluation data
are needed in hosted CI. Future GPU tests must be marked `gpu` and defer all model
imports/device setup until test execution (never at collection). Run them manually
on the owner's machine only. Setting offline/GPU environment flags is defense in
depth, not permission to add a network/model-dependent test to CI.

GitHub Actions runs on standard `ubuntu-latest` with Node 22, Python 3.12, locked
dependencies, read-only permissions and no repository secrets. It checks formatting,
lint, types, build, CPU tests and hooks. It does not deploy. Use `pull_request`, not
`pull_request_target`, for untrusted contribution checks. Do not add paid/larger
runners, GPU jobs, publishing or secret-bearing steps. Hosted checks require a push
or PR; passing local commands alone is not a recorded GitHub Actions success.

## Secrets and data

- Never commit `.env` files, tokens, private keys, local database dumps, private
  prompts, raw logs or model weights. Use placeholder `.env.example` files only.
  Every `VITE_` value becomes public in the frontend bundle.
- Inspect `git diff --cached` before every commit. The private-key hook catches
  common key markers only; passing it does not prove that API tokens are absent.
- For a broader local history scan, install the free [Gitleaks CLI](https://github.com/gitleaks/gitleaks)
  separately and run `gitleaks git --redact`; inspect staged/uncommitted files too
  with `gitleaks dir --redact`. Do not paste findings or actual credentials into
  PRs, issues, chat or screenshots. Do not upload private data to scanning services.
- If available for this repository, enable GitHub secret scanning and push
  protection in repository security settings; no paid scanning service is required.
- If a secret leaks, revoke/rotate it immediately. Inform the owner privately,
  remove it from code/logs/artifacts, then coordinate any history cleanup. Adding
  `.gitignore` or deleting the latest copy does not remove it from Git history.

## Commits and pull requests

Use Conventional Commits: `type(scope): concise description`. Types include `feat`,
`fix`, `docs`, `test`, `refactor`, `style`, `build`, `ci` and `chore`; scope is
optional. Examples: `ci: add CPU checks`, `docs(api): explain local startup`.
Use `!` and a `BREAKING CHANGE:` footer for incompatible public contracts. This is
a contribution convention, not a commit-message hook enforced by this stage.

PR descriptions lead with the problem and resulting behavior, then validation and
material risks. Before requesting review:

- [ ] Scope matches the requested rulebook stage; no unrelated features or services.
- [ ] Benchmark algorithms remain owner-authored; AI assistance and demo data are clear.
- [ ] Formatting, lint, strict types, build, CPU tests and hooks pass.
- [ ] Dependency changes include reviewed lockfiles; no GPU/model/secret CI dependency.
- [ ] Diff and public artifacts contain no credentials, private data or invented metrics.
- [ ] API/auth, resource limits and data-loss risks are assessed where relevant.
- [ ] Docs and reproduction steps reflect behavior; hosted CI passes before merge.
