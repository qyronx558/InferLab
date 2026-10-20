# ADR-001: Static public snapshots, local private execution

Date: 2026-10-20. Status: proposed for MVP; no infrastructure provisioned.

## Context

InferLab needs public benchmark reading with the laptop powered off, one authenticated experiment owner, and no cloud hosting spend. The [rulebook](../InferLab_Production_Prompt_Rulebook.pdf) (pp. 1-3, 8-11) recommends Pages plus published snapshots and warns that free hosting does not include continuous GPU compute. A live backend is unnecessary for the public reading requirement.

## Decision

Host the built React site and reviewed, sanitized versioned JSON on Cloudflare Pages Free using its provider subdomain. Keep FastAPI, SQLite, one worker and inference engines on the owner's laptop; administer through an authenticated loopback console. Publish explicitly from a validated local export. Public browsing has no dependency on private services or cloud database availability.

No Pages Functions, Redis, hosted GPU, cloud API, paid telemetry, paid subscription or purchased domain in MVP. Neon/PostgreSQL and an authenticated remote-access channel require a later decision with fresh quota/security checks. Zero cost is a constrained operating target, not a perpetual pricing or uptime guarantee.

## Current constraints and operating budgets

Official sources checked 2026-10-20; recheck before deployment and monthly thereafter. These are provider limits versus stricter InferLab budgets, not measured usage.

| Component | Published free-tier constraint | InferLab budget / behavior |
| --- | --- | --- |
| Pages builds | 500 builds/month, one concurrent build, 20-minute build timeout | At most 100 builds/month; manual reviewed batches, not deploy-per-run. Warn at 80 builds; pause nonessential builds at 100. [Pages limits](https://developers.cloudflare.com/pages/platform/limits/) |
| Pages files | 20,000 files/site, 25 MiB maximum individual asset | At most 2,000 files/release and 5 MiB/asset; fail export/build preflight above either bound. No model weights or bulky traces. [Pages limits](https://developers.cloudflare.com/pages/platform/limits/) |
| Public delivery | Static requests are free and unlimited when Functions are not invoked | Use static routes only; no dynamic request quota dependency. Provider terms and availability still apply. [Pages pricing](https://developers.cloudflare.com/pages/functions/pricing/) |
| CI | Standard hosted runners are free for public repositories; private repositories have plan-specific included minutes/storage; larger runners are charged | CPU-only standard runners or local checks; no GPU/model downloads, larger runners or paid overages. For private repos verify remaining allocation before enabling CI. [GitHub Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions) |
| Private compute and data | Existing laptop and disk, no cloud allocation | One active GPU job, bounded runtime/queue, local database and backups. Laptop power, internet and replacement storage are owner costs. |

Provider/account usage can be shared across projects. Admin checks actual usage and quota headroom before publishing. Never enable paid fallback automatically. On quota/build failure, keep the previous deployed snapshot, record the error, reduce release size/frequency or wait for reset. If the provider suspends the site itself, availability is not guaranteed; the last exported bundle allows redeployment elsewhere after review.

## Alternatives considered

| Option | Outcome |
| --- | --- |
| Public tunnel to local FastAPI/GPU | Rejected for MVP: adds internet attack surface and laptop uptime dependency. Authenticated remote admin only may be reconsidered. |
| Always-on free cloud API + Neon queue | Deferred: public snapshots already satisfy reading; adds compute/storage/sleep limits and credentials without MVP benefit. |
| Pages Functions + cloud queue/database | Deferred: introduces dynamic quotas and changes the rulebook's preferred Python/local boundary. |
| Paid VM, GPU service or hosted database | Excluded by cloud spend requirement. |
| Local-only site | Rejected: cannot serve public viewers while laptop is off. |

## Consequences and reconsideration triggers

Public results remain readable while local execution is offline, and no anonymous route reaches the GPU. Results update only after explicit publication; live worker state and remote offline submission are unavailable. Admin availability follows laptop/API availability. TLS/session setup, backups and publishing remain owner responsibilities.

Revisit this decision when remote administration becomes necessary, more than one worker/user is needed, the 100-report planning limit is reached, budgets are exceeded for two consecutive months, or hosting terms change. Any replacement must preserve authenticated bounded execution, static offline-readable results, exportability, and explicit cost review. See [release gates](DEFINITION-OF-DONE.md).
