# Release gate checklist

This checklist maps the CPU-only automated evidence in this repository to the
owner-recorded gates in [DEFINITION-OF-DONE.md](DEFINITION-OF-DONE.md). A green local
or CI run is necessary but is not release approval. The owner still records the
commit/release ID, date, environment, commands, expected/actual outcomes and manual
evidence.

## Automated CPU gates

Run these from the repository root:

```powershell
npm.cmd run contracts:check
npm.cmd run format:check
npm.cmd run lint
npm.cmd run build
npm.cmd test
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy
uv run --locked pytest -m "not gpu"
uv run --locked pre-commit run --all-files
```

| Gate | Automated coverage | Pass criterion |
| --- | --- | --- |
| Contracts and schemas | `tests/test_contracts.py`, `tests/test_experiment_results.py`, contract generation check | Fixtures, strict field bounds, labels, provenance and job-state invariants validate; generated TypeScript matches Pydantic. |
| API authorization and sessions | `tests/test_api.py`, `tests/test_database.py` | Private routes reject anonymous/expired sessions; login, CSRF, origin, rotation, lockout, logout and mutation limits fail closed. |
| CORS, Host and request bounds | `tests/test_api.py`, `tests/test_scaffold.py` | Only the exact console origin is credentialed; foreign origins, loopback Host violations, compressed bodies and bodies over 64 KiB are rejected. |
| Input injection and traversal | `tests/test_api.py`, `tests/test_contracts.py`, `tests/test_llama_cpp.py` | Shell, path, URL, unknown registry IDs and cursor traversal are rejected without echoing private input. |
| Secret disclosure | `tests/test_api.py`, `tests/test_publish.py`, `tests/test_ollama.py`, `tests/test_llama_cpp.py` | Unexpected errors and engine failures are redacted; credentials, paths, prompts and raw logs never enter errors, audits or public assets. |
| Bounded generation | `tests/test_engine_parity.py`, `tests/test_llama_cpp.py` | `GenerationRequest` accepts 1-2048 output tokens only; larger or non-integer budgets fail before any HTTP request. |
| SSRF and redirects | `tests/test_engine_parity.py`, `tests/test_ollama.py`, `tests/test_llama_cpp.py` | Engine origins must be credential-free loopback origins; redirects, retries, remote hosts and metadata-style addresses are not followed. |
| Synthetic regression | `tests/test_metrics.py`, `tests/test_synthetic_benchmark_regression.py` | Fixed CPU timelines preserve units, zero versus unavailable, large clock origins and deterministic metric values. |
| Worker idempotency and recovery | `tests/test_worker.py` | Duplicate completions save once; conflicting replays, stale leases and invalid batches never write partial success. |
| Publication integrity | `tests/test_publish.py`, `tests/test_api.py` | Hashed paths bind report IDs and checksums; duplicate IDs, traversal paths, malformed snapshots, oversized assets and canaries abort before replacing the previous release. |
| Frontend snapshot loading | `apps/web/src/api/snapshot.test.ts`, `apps/web/src/components/SnapshotNotice.test.tsx` | Content type, exact size, SHA-256, strict schemas, labels and cross-asset references are verified; corrupt snapshots fall back with an error notice; dates and release IDs are visible. |
| Browser smoke and accessibility | `apps/web/e2e/dashboard.spec.ts` (optional, not run by hosted CI) | Demo, published and corrupt-snapshot states disclose their source; routes remain keyboard-accessible and pass automated WCAG checks. |

## Security and privacy checklist

- [ ] No wildcard credentialed CORS, non-loopback Host or plain-HTTP admin mutation accepted.
- [ ] Anonymous, expired, revoked and rotated sessions cannot read private routes or mutate evidence.
- [ ] CSRF token, exact Origin and idempotency key are required for mutations; reused keys cannot cross request boundaries.
- [ ] Request bodies and generation budgets remain bounded; no automatic model download, shell command or arbitrary URL execution exists.
- [ ] Engine transports use loopback origins only and do not follow redirects, use proxies or retry unexpectedly.
- [ ] Errors, audits and logs contain no credentials, prompts, local paths, session tokens or raw traces.
- [ ] Published assets contain no credentials, private prompts, local paths, raw logs, unpublished experiment IDs, private registry data, queue state, sessions or audit events.
- [ ] Manifest and report paths are immutable hashed paths; exact size and SHA-256 are verified before display.
- [ ] A failed publish leaves the previous release readable; withdrawal does not claim to recall downloaded copies.
- [ ] Dependency and secret scans have no open critical/high finding that blocks release; any accepted advisory is recorded.

## Owner-recorded manual gates

These cannot be established by CPU fixtures and must be evidenced separately:

- [ ] D01: exercise the deployed static site with the local API, worker and engines powered off.
- [ ] D10: run at least one actual owner-hardware benchmark with documented provenance and reproduction steps.
- [ ] D12: deploy the exact approved manifest, verify the live assets, then demonstrate rollback and failure recovery.
- [ ] D14: record actual hosting plan, usage, quota headroom and confirmation that no paid fallback or hosted GPU job exists.
- [ ] D15: record audit retention and restore the latest database plus release bundle into a clean environment.

Release passes only when all D01-D15 have evidence, no critical/high security finding
remains open and the owner approves the reviewed public payload.
