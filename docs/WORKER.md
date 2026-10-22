# Private experiment worker

`inferlab-worker` is a local database poller. It has no HTTP server, listening port,
public worker endpoint, shell-command field, dynamic job import, binary installer
or model downloader. The API queues authorized records; the worker executes only
through an operator-installed, owner-authored Python runner plugin. Benchmark
timing, generation loops, profiling, evaluation and metric calculations remain
outside this orchestration layer. The default command claims nothing until configured.

## Setup

Run from the repository root with Python 3.12. Example environment files are not
auto-loaded. Use the same migrated SQLite/PostgreSQL database as the local API.

```powershell
uv sync --locked
$env:INFERLAB_DATABASE_URL = 'sqlite:///./.local/inferlab.db'
uv run --locked alembic upgrade head

# Operator-provisioned files/module; these placeholders are not installed plugins.
$env:INFERLAB_WORKER_POLICY_FILE = 'C:\LOCAL-CONFIG\worker-policy.json'
$env:INFERLAB_RUNNER_FACTORY = 'owner_inferlab.runner:create_runner'
# All workers for this GPU share ONE database and BOTH associated lock files.
$env:INFERLAB_GPU_LOCK_FILE = 'C:\LOCAL-CONFIG\inferlab-gpu.lock'

uv run --locked inferlab-worker
# Poll/recover once and exit (may execute one eligible job):
uv run --locked inferlab-worker --once
# After operator investigation/confirmed engine stop, explicitly resume:
uv run --locked inferlab-worker --resume
```

Without `INFERLAB_GPU_LOCK_FILE`, the process lock is `~/.inferlab-gpu.lock`;
the child execution lock appends `.execution`. Do not delete/replace active lock
files. All processes using this GPU must use the same paths and database. Run one
owner account on one laptop with dedicated local inference servers. OS locks are
not a distributed lock across hosts/users/filesystems and do not prevent unrelated
programs from using the GPU. Multi-host/shared GPU scheduling is out of scope.

Policy JSON is an operator-owned `WorkerPolicy`, at most 256 KiB, containing:

| Field | Requirement |
| --- | --- |
| `registry` | Existing `Registry` schema: approved engines with version/build, exact model revision/checksum/quantization, supported context and public/synthetic workload checksums. Never load demo fixture metadata as a production approval. |
| `gpu_device_id` | Fixed approved device ID, e.g. `gpu-0` |
| `max_output_tokens` | 1–2048; default 2048; may tighten API limits |
| `max_runtime_seconds` | 1–3600; default 3600; may tighten API limits |
| `max_gpu_layers` | 0–200; default 200; may tighten API limits |

The policy is validated and copied once per worker startup. It is not sourced
from a queued request. A policy change requires restarting the worker; revoked or
over-budget saved jobs fail validation instead of silently changing their config.
The job must also have a matching successful API idempotency/admission receipt.
Directly inserted/unreceipted jobs, archived experiments, mismatched pins and
tampered receipt/config pairs never reach a runner. The database and local policy
are trusted operator resources, not defenses against an attacker with database
write or arbitrary local Python-code access.

## Runner plugin boundary

The private module factory returns `RunnerPlugin` from
`worker/src/inferlab_worker/contracts.py`. The factory reference comes only from
operator process environment, never an experiment record or public request.
Use an importable `module:factory` with no-argument construction; it runs in fresh
spawned Python processes on Windows and Linux. Module import/construction must not
start GPU work, download anything or open a public listener.

The interface is:

```python
def verify_installation(config: ExperimentConfig, expected: ExecutionIdentity) -> bool: ...
def run(config: ExperimentConfig, attempt: int, cancellation: Cancellation) -> RunBatch: ...
def stop_and_confirm() -> bool: ...
```

`verify_installation` checks the actual local model revision/checksum, engine
version/build, approved workload content, device/driver and methodology against
the supplied pins/identity before inference. A false result is a non-retryable
validation failure. Do not infer a checksum from a model name. No default hook
pretends an installation was verified.

`run` is the owner's benchmark execution implementation. It must apply the provided
token, context, timeout, repetition, warmup and concurrency bounds to every engine
request, poll cancellation between/during requests, and return all expected run
records. It cannot substitute a model or load an unapproved prompt. There is no
benchmark algorithm in this worker. Raise `RunnerFailure` with the safe vocabulary
for known failures; map engine OOM/timeout/validation accurately so they are not
retried as generic process loss. Unknown child crashes are `worker_lost`.

`stop_and_confirm` must stop/confirm **all worker-owned engine work**, including
orphaned server requests after restart, and is run in a separate bounded process.
Its factory instance is fresh, so in-memory handles from `run` are insufficient.
Use a dedicated engine's trustworthy administrative stop/idle mechanism or require
operator shutdown of the server. A client HTTP disconnect, killing Python, engine
health, or a momentarily low NVML utilization sample does not prove work stopped.
Return false if uncertain. No implementation that blindly returns true is supplied.
GPU release verification needs actual owner hardware evidence before production use.

## Claim, execute and finish

1. Acquire the host process lock. If an orphan holds the execution lock, wait
   without claiming. Each execution/probe child holds that second lock, checks
   supervisor liveness before using the engine, and has a parent-death watchdog.
   A late-starting orphan cannot start work after its supervisor is gone.
2. Verify the engine stopped before startup recovery. Failure persists a queue
   pause. A successful probe does not implicitly clear an existing pause;
   `--resume` is the explicit operator action.
3. Poll every five seconds. Serialize claims with the same database admission row
   used by API mutations. Select oldest eligible queued work, validate its receipt,
   config, registry pins and narrower local bounds, then atomically lease one job.
   A unique active-slot constraint and the OS locks prevent a second compliant worker.
4. Increment a durable global fencing token and save a `JobAttempt`. A lease lasts
   at most 120 seconds and is capped by the job deadline. Record running before
   dispatching a spawned Python child. Refresh the lease every 30 seconds, poll
   cancellation/state at most every second, and maintain private heartbeat metadata.
5. Supervise with a monotonic deadline. The total job budget starts at the first
   claim, includes preparation/all runs/retry backoff, and is at most one hour.
   Queued time before the first claim does not consume it. A retry shares the
   original database deadline. Database UTC also detects expired leases/deadlines
   after laptop sleep/reboot. Lease decisions use database time after locking,
   not a worker-supplied wall clock; benchmark metric clocks remain the owner's code.
   After each successful heartbeat commit, the supervisor atomically forwards its
   expiry to the child in a private bounded file. The child watchdog independently
   enforces that expiry, a monotonic renewal ceiling and the job runtime deadline,
   even if the supervisor blocks in a database call. It exits on missing/corrupt
   renewal data; it cannot renew its own authority. This monitoring adds small
   process/file overhead that should be disclosed in benchmark methodology.
6. On cancellation/deadline/shutdown/lost lease, signal cancellation, allow at most
   five seconds of cooperative Python shutdown, then terminate/kill the child with
   bounded joins. Engine stop verification has a five-second timeout; uncertainty
   pauses the queue and never releases it for another GPU job. Cleanup has bounded
   grace beyond the execution deadline; an external server that cannot be stopped
   requires operator intervention and cannot be promised a physical GPU deadline.
7. Accept results only from an exited child with a full bounded JSON result
   (256 KiB maximum), verified engine stop, current worker/token/attempt, unexpired
   lease/deadline, no cancellation/pause, and exactly the expected warmup/measured
   indices. Check condition, experiment, token counts and typed measurement contracts.
   Missing/duplicate/over-budget/incomplete runs never complete a job.
8. Assign deterministic run IDs from job/token/kind/index. In one transaction,
   write every run, completion digest, terminal job/attempt and audit event. Identical
   replay returns the existing outcome; conflicting/stale completion is rejected.
   A constraint failure rolls back the entire batch. No summary math or publication
   occurs. A successful result is not automatically a public report.

The plugin is trusted to apply engine-side output limits; the supervisor cannot
inspect/limit an arbitrary external server's hidden generation loop. It additionally
rejects reported output above the cap. OS-process isolation controls the Python
runner, not an unrelated GPU server; the stop-confirmation contract is mandatory.
Database/storage calls use the existing bounded SQLite busy timeout. Keep the
database clock synchronized; large wall-clock changes require operator review.

## Failure and restart policy

| Event | Durable outcome |
| --- | --- |
| Queued cancellation | API cancels immediately; worker ignores terminal record |
| Active cancellation | Preserve running phase until stop confirmation, then cancelled; no retry/accepted partial metrics |
| Engine/network/worker loss | Fail attempt; only after confirmed stop, requeue once with at least 30-second backoff and remaining original deadline |
| OOM, checksum/validation, timeout | Failed, no automatic retry |
| Second attempt fails | Failed, no third automatic attempt |
| Parent/child crash or laptop shutdown | No inferred success. Next worker stops orphan work and reconciles the expired attempt; partial data is not accepted |
| Engine stop cannot be confirmed | Failed attempt where applicable, persisted pause; explicit operator resume required |
| Database unavailable during completion | Stop local work; leave unresolved lease/evidence for recovery. No invented successful receipt |
| Database commit succeeded but caller lost acknowledgement | Replaying the same fenced batch is a no-op; accepted rows/audit are not duplicated |

An eligible nonterminal job can move `leased/running → queued` only through the
worker's fenced retry transaction; its preceding attempt remains terminal failed.
Completed/failed/cancelled jobs never reopen automatically. API-requested retries
create a new job and remain subject to API queue/daily admission caps. Two attempts
per job do not promise exactly-once physical execution after a crash; accepted
measurements are fenced and idempotent.

An automatic retry also needs a free slot below the ten-pending-job limit. If the
queue filled while an older admitted job ran, that attempt fails terminally rather
than exceeding the queue bound. The owner can request a new job after capacity frees.

Interrupted attempts retain safe failure metadata, not partially accepted success
rows or raw output. Each completed attempt needs a full batch. Raw prompts and
bulky traces are not worker result fields. Private temporary files contain typed
metrics only and are cleaned after normal execution; abrupt termination may leave
an owner-private OS temp directory to remove after ensuring its process is gone.
Retain attempt/audit evidence according to [DATABASE.md](DATABASE.md).

On an uncertain stop: stop the worker, stop/inspect its dedicated engine processes,
fix the plugin's stop verification, and restart with `--resume`. Do not delete
leases, reset fencing counters, remove lock files or mark jobs complete by hand.
Stop all workers before database restoration/migrations; never restore over a live
writer. There is no remote resume/claim/finish endpoint in this stage.

## Measurable verification

```powershell
uv run --locked pytest tests/test_worker.py tests/test_database.py tests/test_api.py
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check.ps1
```

CPU tests assert single-slot concurrent claims; fixed receipt/model policy; token
and runtime caps; renewable/stale fences; exactly two attempts with durable backoff;
shutdown/restart histories; cancellation vs completion; no partial writes; conflicting
and duplicate completion; database outage/lost acknowledgement; persisted stop pause;
OS lock release after process death; orphan-child exit; hard kill of a noncooperative
runner; stop-probe timeout; and real spawned success/timeout with database time.
All runner outputs are synthetic fixtures. No model, CUDA, paid service or network
engine is used. CI remains CPU-only. SQLite migrations/tests run live; PostgreSQL
DDL is checked offline, while live PostgreSQL and actual GPU/engine shutdown tests
remain owner-run release gates.

References: [Python multiprocessing](https://docs.python.org/3.12/library/multiprocessing.html),
[SQLAlchemy transactions](https://docs.sqlalchemy.org/en/20/orm/session_transaction.html).
