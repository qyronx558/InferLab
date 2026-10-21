# Benchmark runner: design review and owner exercise

Status: proposal only. No `benchmark_runner.py` or submitted runner design exists
in this checkout. This review therefore evaluates the requirements against the
existing [engine protocol](../packages/inferlab_core/src/inferlab_core/engines/protocol.py),
[metrics](METRICS.md), and experiment/run contracts. The algorithm, test matrix and
signatures below are for the owner to implement; no runner or tests are implemented
by this document.

## Review findings

The separation should be **lifecycle preparation -> one streamed observation ->
validation -> pure metric calculation -> aggregation**. Preparation must never
silently enter a warm inference measurement. Cold and warm experiments already
have distinct configurations and must remain separate cohorts.

Three gaps must be resolved before accepting real benchmark reports:

1. `EngineProtocol` has no unload, preload, residency verification or keep-alive
   control. A future optional lifecycle interface must provide evidence of the
   requested condition. Until available, reject an unsupported cold/warm plan
   before generation; do not guess residency from a short loading duration.
2. `GenerationRequest` currently controls only model, prompt and output budget.
   Context, temperature, top-p, seed, thinking, GPU placement and keep-alive are
   not controlled by this adapter. Add reviewed capabilities later or capture a
   pinned, independently verified server configuration. Reject configurations
   that cannot be honored; never record requested settings as effective settings.
3. Ollama yields **text chunks, not guaranteed individual token events**. Client
   TTFT is the observable first answer-content arrival proxy. Record that basis;
   do not claim an exact token boundary or feed chunk timestamps into the existing
   token-based TPOT/decode helpers. See [Ollama streaming](https://docs.ollama.com/api/streaming).

## Written algorithm

1. **Validate and freeze the plan.** Resolve allowlisted installed model/workload
   identities and provenance without downloading anything. Capture model digest,
   engine build, tokenizer/template, context, sampling, thinking mode, output
   budget, hardware/driver, methodology version, connection policy and cache policy.
   Enforce existing bounds: 0-5 warmups, 1-20 measured repetitions, concurrency 1,
   context/output constraints and bounded job time. Cold requires zero warmups.
   Acquire the future worker's exclusive execution ownership outside this runner.

2. **Prepare measurement tools outside request timing.** Inject a clock whose
   production implementation uses `time.perf_counter_ns()`. Record
   `time.get_clock_info("perf_counter")` resolution and monotonicity. Use one
   process/clock for all request intervals; UTC is provenance only. Create one
   reusable HTTP client and perform health/model checks before measuring. Record
   whether each request actually used a new or reused connection if observable;
   reusing a client alone does not prove socket reuse.
   [Python clock reference](https://docs.python.org/3.12/library/time.html#time.perf_counter_ns).

3. **Separate model loading and cold request behavior.** For each cold repetition,
   request unload and verify absence, with bounded polling, before the trial. Do
   not preload or warm up. Then measure the first normal streamed request,
   including loading in its client TTFT and latency. Keep its server-reported
   `load_duration_ns` separately. Unload/reset again before the next cold trial;
   merely labeling the first repetition cold is insufficient. This is
   *model-residency cold*, not necessarily process-, OS-page-cache- or disk-cold.

4. **Prepare a separate warm experiment.** Preload outside timed inference and
   retain a separate preparation observation: client load-request duration and
   server-reported loading duration, when available. Neither is pure GPU load
   time. Verify residency, apply and record an explicit keep-alive policy that
   covers the job deadline, then execute the configured warmups with the same
   workload/settings. Store them as `kind=warmup`, exclude them from summaries,
   and do not consume measured repetition indices. Zero warmups is allowed but
   means resident-only preparation; disclose that compilation/cache stabilization
   has not been established. A preload is not a representative warmup.
   [Ollama preload and keep-alive behavior](https://docs.ollama.com/faq#how-do-i-keep-a-model-loaded-in-memory-or-make-it-unload-immediately).

5. **Observe each request with identical boundaries.** Prepare the request and
   enter stream ownership with `contextlib.aclosing`. Read `t_start_ns` immediately
   before the first iteration that initiates I/O: async generator construction
   alone does not send a request. For every yielded event, read the clock
   immediately, before concatenation, logging, tokenization or callbacks. Set
   `t_first_content_ns` once, for the first `event.text != ""`; whitespace counts,
   empty metadata and thinking-only events do not. Optionally retain the first
   thinking arrival as a separate diagnostic. A final event can also be the first
   content event: use the same event timestamp for both boundaries.

6. **Finish on valid completion.** Set `t_done_ns` when the `done=True` event is
   received, including its text and final metadata. Total successful request
   latency is `t_done_ns - t_start_ns`; TTFT is
   `t_first_content_ns - t_start_ns`, or unavailable if no answer text arrived.
   These include HTTP overhead, server queuing/loading/prefill, decoding, delivery
   and client parsing/scheduling within those boundaries. Stream cleanup, report
   writing and lifecycle operations are outside that successful latency boundary.
   If cleanup itself fails, retain the trace but do not accept the trial. Never
   substitute engine `total_duration_ns` for client request latency or subtract
   server load time to manufacture warmed latency.

7. **Record token counts with provenance.** Use final `prompt_eval_count` and
   `eval_count` as engine-reported input/output counts, plus requested budgets and
   stop reason. Preserve missing versus zero. Do not count chunks, words or
   characters as tokens. Counts describe the engine's processing/template and
   may include reasoning or special tokens; they are not necessarily visible
   answer-token counts. An independently pinned tokenizer can provide a separate
   diagnostic, never a silent replacement. See [Ollama response fields](https://docs.ollama.com/api/generate).

8. **Validate and derive after I/O.** Require ordered timestamps, terminal
   completion, matching identity/provenance and verified condition. Use the
   existing pure `ttft_ms` and `elapsed_ms` helpers after recording observations.
   Keep engine durations as nanoseconds in separate fields. With chunk-only
   observations, token-event TPOT/decode throughput remains unavailable. If a
   separately named end-to-end output rate is wanted, use actual output counts
   and client latency; the current wire `decode_throughput` is not that field.
   Do not add a new calculation here or reinterpret an existing field.

9. **Repeat a fixed number of attempts.** Execute sequentially with stable
   settings, residency checks before warm measurements, and bounded deadlines
   covering preparation, warmups and all measured attempts. A maximum output
   budget does not guarantee that many tokens: record actual lengths and EOS or
   truncation. Predeclare comparability criteria (input count, output-length
   cohort, stop reason and thinking policy); report mismatches explicitly. Keep
   valid unequal-length runs as observations, but exclude them from claims that
   require matched lengths. Do not pad, silently retry or run extra trials until
   a desired sample count is reached. Record every attempted repetition once.

10. **Handle interruption and summarize honestly.** On timeout, cancellation,
    truncated stream or engine error, retain partial diagnostics and a failure
    timestamp, close the stream, and exclude the run from successful aggregates.
    Failure elapsed time is not successful request latency. Preserve native
    cancellation after handing partial diagnostics to the future worker; never
    swallow cancellation and continue repeats. A failure with unconfirmed server
    termination stops the series pending operator/worker recovery, since closing
    HTTP does not prove GPU work stopped. Otherwise the fixed failure policy may
    continue remaining attempts without replacing failures. Summarize only
    accepted measured runs within one condition and comparable workload cohort;
    retain accepted IDs, attempted/accepted/failed/cancelled/mismatched counts.
    Report median and range plus sample count; any p95 needs a named estimator
    and a small-sample caveat. Never pool cold trials, preparation or warmups.

## Proposed records and contract boundaries

These are proposed core records, not imports from the FastAPI application. Keep
the core independent of API schemas. A future mapping layer must validate wire
compatibility rather than silently dropping evidence.

| Proposed type | Required contents |
| --- | --- |
| `BenchmarkPlan` | Immutable request, resolved provenance/effective settings, cold/warm condition, warmup/repetition counts, keep-alive/cache/connection policies, overall deadline, comparability and failure policies. |
| `PreparationEvidence` | Expected/observed residency, verification method/time, preload/unload client interval, optional server loading duration, keep-alive evidence, uncertainty/reason. |
| `RunContext` | Stable experiment/attempt/run IDs, condition, warmup/measured kind, repetition index, preparation evidence and provenance. Warmup IDs/indices have a separate namespace. |
| `RunTrace` | Start/first-content/done/failure nanosecond timestamps, ordered chunk observations, final metadata/counts, stop reason, outcome, sanitized error and measurement limitations. Raw prompt/output retention is opt-in local and bounded. |
| `RunRecord` | Context plus trace, client metrics/units/observation basis, availability reasons, actual token counts, validation findings, acceptance/comparability decisions. |
| `RunSummary` | Separate condition/cohort, accepted IDs, attempt/error/cancel/mismatch counts, per-metric valid counts and descriptive statistics with methodology version. |

The current `RunMetrics` contract requires input/output counts for `complete` runs.
A terminal engine response with missing counts is therefore not yet a publishable
complete run. Retain the raw terminal outcome, mark measurement validation failed,
and map deliberately to a supported error state/code later. A complete response
with valid counts but no answer text may retain latency while TTFT is unavailable.

Preparation evidence, raw timestamps, observation basis, eligibility reasons and
load observations have no complete current wire representation. Specify a reviewed
schema extension before publication; no contract changes are part of this design.

## Function stubs only

Proposed target: `inferlab_core/benchmarking/benchmark_runner.py`. The record types
above are placeholders to define before implementation. This code block is a
signature sketch, not an executable module or a new dependency. The clock and
lifecycle implementations remain owner work too.

```python
from __future__ import annotations

from collections.abc import Sequence
from typing import Literal, Protocol

from inferlab_core.engines import EngineProtocol, GenerationRequest, GenerationResult


class MonotonicClock(Protocol):
    def now_ns(self) -> int: ...


class ModelLifecycle(Protocol):
    async def unload_and_verify(self, model: str) -> PreparationEvidence: ...

    async def preload_and_verify(
        self, model: str, *, keep_alive_seconds: int
    ) -> PreparationEvidence: ...

    async def verify_resident(self, model: str) -> PreparationEvidence: ...


def validate_plan(plan: BenchmarkPlan, *, engine: EngineProtocol) -> None:
    """Reject invalid bounds and unsupported effective settings before execution."""
    raise NotImplementedError


def is_answer_content(event: GenerationResult) -> bool:
    """Specify nonempty answer text, preserving whitespace; ignore thinking only."""
    raise NotImplementedError


async def prepare_condition(
    plan: BenchmarkPlan,
    *,
    lifecycle: ModelLifecycle,
    clock: MonotonicClock,
    deadline_ns: int,
) -> PreparationEvidence:
    """Verify cold reset or preload warm model, separately from request timing."""
    raise NotImplementedError


async def observe_streamed_request(
    engine: EngineProtocol,
    request: GenerationRequest,
    *,
    context: RunContext,
    clock: MonotonicClock,
    deadline_ns: int,
    trace: RunTrace,
) -> None:
    """Fill caller-owned trace, close streams, and preserve cancellation/errors."""
    raise NotImplementedError


def finalize_run(
    trace: RunTrace, *, context: RunContext, plan: BenchmarkPlan
) -> RunRecord:
    """Validate observations, use pure helpers and record eligibility reasons."""
    raise NotImplementedError


async def run_benchmark(
    plan: BenchmarkPlan,
    *,
    engine: EngineProtocol,
    lifecycle: ModelLifecycle,
    clock: MonotonicClock,
) -> tuple[RunRecord, ...]:
    """Prepare, warm up and run fixed sequential trials; retain failed attempts."""
    raise NotImplementedError


def summarize_runs(
    runs: Sequence[RunRecord], *, condition: Literal["cold", "warm"]
) -> RunSummary:
    """Summarize accepted measured cohorts without hiding rejected attempts."""
    raise NotImplementedError
```

Passing a caller-owned `trace` lets the future orchestrator retain observations
even when stream observation raises or is cancelled. It does not authorize
persistence or publishing inside the timing path. The future worker owns durable
job state, cancellation acknowledgement, leases and engine-stop confirmation.

## Test matrix for the owner

All unit cases use a scripted monotonic clock, fake lifecycle controller and fake
async engine/events. No sleeps, HTTP, models, CUDA or wall-clock timing assertions
belong in these tests. Numbers below are synthetic test inputs.

| Case | Expected assertion |
| --- | --- |
| Known timeline | Start 1,000,000,000 ns; first answer 1,120,000,000; done 1,200,000,000 -> TTFT 120 ms, request latency 200 ms. |
| Lazy stream startup | I/O is first triggered after the recorded start, never before it; constructing a generator is not the boundary. |
| Metadata/thinking before answer | Empty text and thinking-only events do not set answer TTFT; first nonempty answer sets it once. |
| Whitespace answer | `" "` qualifies; no `.strip()` filtering. |
| Final event contains first answer | First-content and done timestamps are equal; TTFT equals total request latency. |
| Empty answer, successful completion | Valid counts/latency retained; TTFT unavailable, never zero-filled. |
| Multi-token chunk / chunk coalescing | No token count or TPOT inferred from event count; token-event metrics unavailable. |
| Final engine counts | Preserve actual input/output counts, zero and ns durations, independently of requested budgets. |
| Missing counts | Retain terminal response diagnostics; reject mapping to wire `complete`. No guessed counts. |
| Cold repetitions | N attempts require N verified unload/reset operations, zero warmups/preloads; each request is separately labeled cold. |
| Warm preparation | Preload interval and warmup records excluded; configured warmups happen before measured indices 0 through N-1. |
| Zero warmups | Resident verification still required; label resident-only preparation, not stabilized inference. |
| Residency lost / unverifiable | A nominal warm trial is not accepted as warm; no automatic relabeling as a valid cold trial. |
| Unsupported lifecycle/settings | Reject before measured generation; no fallback, model pull or pretend configuration. |
| Output budget vs actual length | Early EOS and max-length stops retain their actual counts/reasons; comparison mismatch is explicit. |
| Prompt-cache/settings mismatch | Different prompt/template, seed support, thinking policy or cache policy prevents pooling/ranking as equivalent. |
| Clock ties / huge origin | Equal readings permitted; subtract integers before conversion; do not fabricate sub-resolution precision or divide by zero. |
| Reversed clock readings | Mark trace invalid; never repair by sorting or clamping. |
| Artificial preparation/logging delays | Preparation and post-run reporting do not enter successful request latency; delivery/parsing delay does. |
| Error before/after first answer | Retain available trace/counts; no successful latency or inclusion in successful aggregates. |
| EOF before completion / malformed stream | Failed attempt, closed stream; partial text is not a completed run. |
| Cancellation during preparation/stream/repeat boundary | No next trial, stream closes when active, partial trace retained, cancellation propagates. |
| Per-request or overall deadline | Timeout includes the declared scope; no replacement attempt; unconfirmed engine stop halts remaining work. |
| Fixed repeats and failure policy | N configured slots never become N successes plus hidden retries; retain attempted and unattempted distinction. |
| Summary eligibility | Warmups/cold/failed/cancelled/mismatched trials excluded from the relevant warm matched cohort; exact accepted IDs and metric sample counts retained. |
| No accepted samples | Summary unavailable with zero accepted samples, no invented medians/rates. |
| Keep-alive expiry / model switch | Residency failure detected; no claim of warmed inference based solely on prior preload. |

Manual integration later: use an already installed small local model to verify
preload/unload evidence, residency across warm repeats, counts and stop reasons,
and cancellation/timeout recovery. Performance values are observations, never
fixed pass/fail thresholds. Hosted CI remains CPU-only.

## Risks and required disclosures

| Risk | Design response |
| --- | --- |
| CUDA synchronization | GPU kernels are asynchronous. A future in-process backend must define synchronization/CUDA-event boundaries for device timings and synchronize before/after a measured region as appropriate. Never synchronize per streamed token merely to collect timestamps: that changes execution. A PyTorch synchronize call in the HTTP client cannot synchronize Ollama's server process. Client response timing needs no local CUDA calls and is not kernel timing. [PyTorch synchronization reference](https://docs.pytorch.org/docs/2.14/generated/torch.cuda.synchronize.html). |
| Network and event-loop noise | Loopback, HTTP pooling, parsing, buffering, antivirus and scheduling affect arrivals. Keep transport/settings constant, avoid per-event logging, record environment and repeat trials; do not call client TTFT pure prefill or server latency. |
| Output-length mismatch | The same maximum is only a cap. Different EOS, reasoning and actual token lengths change latency. Report counts/stop reasons and compare declared matched cohorts; do not silently normalize with a ratio or claim tokenizer-independent rates. |
| Clock granularity | Nanosecond integers do not imply nanosecond resolution. Record clock resolution, retain ties and uncertainty; no artificial epsilon or wall-clock subtraction. |
| Keep-alive and caches | Default residency, expiry, eviction, prompt reuse, JIT/graph compilation and allocator state can turn a nominal warm trial cold or make repeated prompts faster. Verify residency, record cache policy and loading evidence; a resident model is not proof of cache equivalence. |
| Small samples / thermal drift | With at most 20 trials, tail percentiles are weak and ordering can favor a cooler device. Preserve individual results and sample counts, document power/thermal conditions, and predeclare comparison ordering. |
| Cancellation is not GPU termination | Socket cleanup is necessary but insufficient. Require confirmed stop or pause before another run, rather than overlapping uncertain server work. |

Implement the proposed record types and `is_answer_content` /
`observe_streamed_request` first, using the synthetic timeline tests. Share that
code for correctness and edge-case review before adding lifecycle orchestration
or summaries.
