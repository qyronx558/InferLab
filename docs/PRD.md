# InferLab product requirements

Status: draft specification, 2026-10-20. No implementation or benchmark results are delivered by this document.

Source: [Production Prompt Rulebook](../InferLab_Production_Prompt_Rulebook.pdf), Prompt 00 (p. 3), master rules (pp. 2-3), and launch requirements (pp. 8-11). Later prompts inform the target design; they do not authorize implementation now.

## Purpose and users

InferLab is a small public portfolio of reproducible local LLM inference benchmarks. It explains measurement methods and lets one authenticated owner run, review, and publish experiments on their laptop. Public unrestricted GPU execution is explicitly excluded.

| User | Allowed actions |
| --- | --- |
| Public viewer | Browse published results, model metadata, comparisons, and method explanations; download sanitized published JSON. No account required. |
| Single admin | Authenticate to the local console; submit bounded experiments, inspect private runs, cancel/retry jobs, review snapshots, publish or withdraw reports. |
| Local worker (service, not a user role) | Execute authorized queued jobs and save measurements. Cannot submit new experiments or publish reports. |

## Assumptions and boundaries

- One owner, one laptop with RTX 4060 8 GB, one active GPU job; models are installed manually and pinned. Ollama is the first engine; llama.cpp is a stretch adapter.
- The owner writes the Python benchmark, profiling, and evaluation algorithms. AI assistance may produce scaffolding, frontend, tests, and documentation, as the rulebook specifies.
- The admin uses the console on the laptop in MVP. Public deployment contains no working admin API. Remote submission while the laptop is off is not required.
- Only synthetic/public, licensed workloads are used. Model weights, private prompts, raw logs, secrets, and local filesystem paths stay local.
- Small portfolio target: up to 100 published reports and 10 experiment submissions/day. These are planning limits, not observed usage.
- Zero cost means no recurring cloud hosting fee within current free allocations. Hardware, electricity, internet, and optional domain costs are excluded; neither continuous compute nor an SLA is promised.

## MVP versus stretch

| Area | MVP | Stretch, after MVP acceptance |
| --- | --- | --- |
| Public reading | Static overview, report list/detail, model catalog, methodology, two-report comparison, JSON download; snapshot date and provenance visible | Rich Plotly analyses, CSV/print exports, broader filtering |
| Experiments | Local authenticated console; approved Ollama model/workload registry; bounded config; queue/status, cancellation and explicit retry | llama.cpp parity, quantization/offloading matrices, concurrency sweeps and quality evaluation |
| Measurements | Warm/cold separation, streaming TTFT, request latency, output throughput, token counts, repetitions and error counts; unavailable metrics explicitly null | NVML telemetry, peak VRAM, richer quality and statistical analysis |
| Publishing | Admin reviews a sanitized, versioned snapshot; validation and checksum gates; explicit deploy; last good release survives failures | Automated approved publishing workflow, richer report editing |
| Operations | Local SQLite queue, one worker, lease/heartbeat, bounded retries, audit events, backup/restore instructions, manual stop switch | PostgreSQL/Neon if justified; authenticated remote admin channel; stronger account recovery/MFA |

An MVP report must retain model revision/checksum, engine version/build, quantization, context, workload ID/hash, input/output token counts, output budget, sampling/seed support, warmups, repetitions, concurrency, device/driver, timestamps, run IDs, units, failures, and methodology version. Unsupported measurements are marked unavailable, never zero-filled. Speedup claims require a measured matching baseline; differing hardware/workloads or cold/warm conditions must be disclosed and not ranked as equivalent.

## Screens

| Screen / route | Audience and required behavior |
| --- | --- |
| Overview `/` | Public: latest published highlights and snapshot date; empty state before first publication. |
| Reports `/reports` and `/reports/:id` | Public: published summaries and traceable metrics, units, sample sizes, limitations, JSON download. |
| Compare `/compare` | Public: select two published reports; show controlled variables and flag incompatible comparisons. |
| Models `/models` | Public: models referenced by published reports only, revisions and licensing references. |
| Methodology `/methodology` | Public: metric definitions, warm/cold protocol, fair baseline rules and reproduction steps. |
| Sign in `/admin/login` | Local console only: single-admin login and explicit authentication error state. |
| Experiments `/admin/experiments` and `/admin/experiments/new` | Local admin: queue/history, worker last seen, validated form; offline queue confirmation. |
| Experiment detail `/admin/experiments/:id` | Local admin: config, attempts, status/errors, cancellation, retry, measurements and publish preview. |
| Publish review `/admin/publish` | Local admin: exact public payload, validation/privacy findings, deployment status and withdrawal instructions. |

All screens require keyboard operation, clear loading/empty/error states, and readable mobile layouts. Local console outage must show unavailable status, never imply success. Public `/admin/*` routes explain that administration is local and expose no controls or credentials.

## Workflows and availability

1. Viewer loads deployed snapshots without contacting the laptop, local API, model server, or a cloud database.
2. Admin authenticates locally, selects registry IDs and bounded settings, and submits an idempotent request. A durable queue receipt means accepted, not started or completed.
3. Worker leases one job, records actual runs and completes atomically. Admin reviews successful measurements; completion never automatically publishes.
4. Publish review validates an allowlisted snapshot and stages it locally. Admin explicitly deploys the reviewed release to Pages. Failed validation/build/deploy leaves the previous release active.

Worker availability is separate from job state: online after a heartbeat within 90 seconds, offline after that threshold, unknown when the API cannot be reached. Idle/running are online substatuses. Heartbeat every 30 seconds; local admin UI polls at most every 10 seconds while visible. Offline submissions may queue only while the local API/database is available and must warn that no start time is guaranteed. If the laptop/API is off, submission fails visibly; the browser must not silently replay it later. Public pages say “Published snapshot, as of …; local execution is not live” and do not infer current worker health.

The job lifecycle is `queued -> leased -> running -> completed | failed | cancelled`, with expired attempts retried only under the bounded policy in [ARCHITECTURE.md](ARCHITECTURE.md). Cancellation is cooperative; interrupted/partial runs cannot become successful reports.

## Scope exclusions

No anonymous or public job submission, inference chat/API, public GPU access, multi-user registration, teams, billing, model hosting/downloads, arbitrary code/plugins/URLs/paths, automatic engine installation, distributed/multi-GPU workers, hosted GPU CI, 24/7 execution, paid services, custom domain purchase, or production SLA. Public offline behavior means the laptop may be off; a viewer still needs internet to fetch the deployed site. Stretch features are not MVP release requirements.

## Acceptance

API access boundaries, threats, and recovery behavior are defined in [ARCHITECTURE.md](ARCHITECTURE.md). Hosting tradeoffs and current limits are in [ADR-001-zero-cost.md](ADR-001-zero-cost.md). Release gates and measurable evidence are in [DEFINITION-OF-DONE.md](DEFINITION-OF-DONE.md); none is claimed passed by this draft.
