# Concurrency and evaluation: proposed-design review

No `concurrency_runner.py`, `evaluation.py` or submitted design for either file
exists in this checkout. This review covers the requested design against current
InferLab contracts; it is not a review of unseen code. No benchmarking or scoring
algorithm, load generator, new dependency or executable test is added.

## Architectural findings

Keep request scheduling/observation separate from deterministic answer scoring.
Scheduling owns traffic and per-request lifecycle evidence. A pure summary layer
interprets recorded observations. Evaluation consumes immutable completed outputs
and pinned question/rubric data after timing; it never generates answers, accesses
the network or modifies a workload to improve its score.

`ExperimentConfig.concurrency` currently permits only **1**, and the llama.cpp
adapter requires one server slot. Tests for 2/4/8 clients below are future local
stretch scenarios, not permission to change admission limits or expose public
execution. A one-slot server can queue several clients after a reviewed concurrency
extension; it cannot demonstrate parallel device execution. Studying multiple
server slots needs a separate adapter/contract/resource-policy review.

## Client-side load generation and arrivals

Concurrency is outstanding request count, not requests/second. Eight tasks may
wait in a client semaphore, HTTP pool, server queue or GPU scheduler. Record the
configured limit and observed in-flight count; do not equate either to batch size
or active GPU sequences.

| Load mode | What is controlled | What you learn |
| --- | --- | --- |
| Closed loop | C logical clients, each with at most one outstanding request; fixed think-time policy | Throughput/latency under a fixed client population. Slower responses reduce the arrival rate. |
| Open loop | Request due times independent of completion; fixed-rate or seeded Poisson schedule | Behavior at a declared offered rate, including overload and queueing. |

For a fixed-rate schedule, intended interarrival time is `1 / rate`. A Poisson
schedule has random interarrival gaps with that mean; pin its schedule seed
separately from model sampling and question-order seeds. Persist/replay the same
due-time offsets and question IDs for every model. MLCommons separates fixed
concurrency and arrival-driven load for this reason; this proposal is not an
MLPerf implementation or compliant submission.
[Load-pattern reference](https://github.com/mlcommons/endpoints).

In open loop, a client cap must not silently change the arrival schedule. Declare
bounded local queue capacity, request deadlines and a queue-full policy such as
explicit client rejection. A producer that blocks waiting for a semaphore and
then claims it offered the target rate has changed the experiment. An overloaded
generator must expose scheduling lag, missed offers and drops rather than hide
them or emit a catch-up burst. Record target, offered, dispatched and completed
rates separately. Provision the HTTP pool to match the intended cap, or explicitly
study pool contention as a separate factor.

This distinction prevents **coordinated omission**: when a closed-loop client waits
through a server stall before sending more work, it never observes the additional
requests that an external arrival stream would have offered during that stall.
Closed-loop results remain useful, but they do not establish open-loop tail latency
or a service's capacity at a fixed arrival rate.

## Queueing and timing evidence

Each request needs a stable ID, question ID, client ID, immutable config/attempt ID
and these same-clock monotonic events:

| Event | Meaning |
| --- | --- |
| `scheduled_ns` | Intended arrival due time in an open-loop schedule. |
| `offered_ns` | Actual client enqueue/admission attempt, or explicit rejection time. |
| `request_started_ns` | Immediately before the transport begins I/O after client admission/queueing. |
| `first_content_ns` | First answer-content-bearing stream observation; unavailable if none. |
| `terminal_ns` | Valid completion, error or cancellation, with outcome recorded separately. |

Define boundaries before measurement:

- Generator lag: offered minus scheduled.
- Local admission/queue delay: request start minus offered.
- Transport-observed latency: terminal minus request start for successful requests.
- Arrival-to-completion latency: completion minus scheduled for open loop, exposing
  generator lag and client queueing. Also retain offer-to-completion if useful.
- Client TTFT: first answer content minus request start; an optional scheduled-to-
  first-content measure needs a different name.

Server queue time cannot be isolated from HTTP response timing alone. Pool waits,
network overhead, server queueing and execution all contribute within the relevant
client boundary. Do not subtract an engine duration and call the remainder exact
queue time. Track actual in-flight/queue occupancy, pool settings, server slot count
and batching policy separately. Little's law (`average outstanding = request
throughput × average time`) is a useful consistency check only with matching boundaries and a
stable system; it does not turn client count into a guaranteed arrival rate.

## Errors, cancellation and denominators

Keep planned, offered, client-rejected, accepted, dispatched, succeeded, errored,
cancelled and outstanding/not-offered counts. These distinctions explain lost work:
at a declared cutoff, offered work is client-rejected or accepted; accepted work
is succeeded, errored, cancelled or still outstanding, including locally queued work.
Never count an unoffered future request as a model failure.

Separate pool/connect/read/overall timeouts, HTTP 429/503, malformed/truncated
streams, unavailable counts and evaluator failures. Retain partial diagnostics,
but partial tokens from an errored stream are not successful completed output.
Retries must be absent by default; if studied, every physical attempt is separate
and retry traffic is part of load, not a hidden success replacement.

Expected request errors should become request records rather than cancel sibling
clients. Unexpected infrastructure faults can abort the cohort explicitly.
`asyncio.TaskGroup` cancels siblings when a child fails with an unhandled ordinary
exception; choose that behavior deliberately. Native cancellation still propagates,
all owned streams/tasks are closed or awaited, and future work is not dispatched.
Closing HTTP does not prove model-server execution stopped.
[Python task and cancellation semantics](https://docs.python.org/3.12/library/asyncio-task.html).

## p50, p95 and aggregate output throughput

Report p50 as the sample median. For a proposed empirical p95, explicitly choose
and version a convention such as **nearest rank**: rank `ceil(0.95 × N)` in sorted
observations. Other interpolated conventions can differ, especially for small N;
do not rely on an undocumented library default. A synthetic sample
`[1, 2, 3, 4, 100]` ms has median 3 ms and nearest-rank p95 100 ms.
[Python percentile conventions](https://docs.python.org/3.12/library/statistics.html#statistics.quantiles).

Compute cohort quantiles from compatible request observations, never by averaging
per-client p95s. Preserve client/task/input-length strata so a changing workload
mix does not hide regressions. Quantiles are not additive; merging raw records or
compatible histogram counts is different from averaging precomputed quantiles.
[Prometheus aggregation explanation](https://prometheus.io/docs/practices/histograms/).

With only 8 or 20 observations, a p95 is largely a statement about the largest
few values. Mark it exploratory, show N and individual samples/range, and do not
claim stable tails. A future tail study could predeclare at least 100 completed
requests per cell plus repeated independent sessions; that is a design threshold,
not a precision guarantee, and exceeds today's 20-repetition contract. Repeating
the same question is not equivalent to sampling independent questions. Autocorrelated
requests, thermal drift and day/session effects require separate treatment; a
naive bootstrap cannot automatically fix them.

Success-only latency percentiles must say **conditional on successful completion**.
Timeouts are censored: their eventual successful latency is unknown and at least
their timeout boundary. Dropping them can make an overloaded model appear faster.
Do not replace them with zero, infinity, or an invented exact completion latency.
Report timeout/error counts and threshold attainment with an explicit denominator.

For a finite, fully drained request cohort, propose aggregate successful output
throughput as:

`sum(actual output tokens from successful requests) / shared cohort elapsed seconds`

Use one declared interval from measurement start through final terminal event,
including idle gaps, queueing, failures and drain. Do not sum per-request token
rates or divide by the sum of overlapping request durations. Synthetic example:
two successful requests start together and produce 40 tokens in 1 second and
60 tokens in 2 seconds -> **50 tokens/s** over the 2-second cohort, rather than
the sum of their individual rates (40 + 30 = 70 tokens/s).
Token totals must be engine-reported counts, not chunks or character estimates.

Arrival-window QPS, completed requests/s, cohort output tokens/s and steady-state
window throughput are different metrics. If fixed-window throughput is added,
declare inclusion/boundary rules; final-only token totals cannot locate every token
inside a subwindow. A cutoff with outstanding work is an incomplete cohort, not a
fully drained result. Keep zero-duration or missing-count rates unavailable.
Transport-success throughput can include wrong answers; any quality-qualified
goodput needs its own numerator and the same stated time window.

The existing `decode_throughput` field must not be repurposed for aggregate output
throughput. New lifecycle/count/arrival/aggregate metrics require a reviewed schema
extension, not fabricated values in existing report fixtures.

## Deterministic task-specific evaluation

Define a versioned question manifest: stable ID, public/synthetic origin, source
revision and license, content checksum, task type, exact rendered prompt/hash,
reference answer(s), output budget, parser, normalization and grading rule.
Keep gold-answer metadata separate from prompts; a legitimate extraction passage
can naturally contain the answer text. Pin a local licensed public subset before
testing; do not download a moving dataset or execute dataset-provided code inside
evaluation. Synthetic fixtures can reuse InferLab's arithmetic/extraction examples,
but those tiny smoke tasks cannot establish general model quality.

| Task | Deterministic rule to specify |
| --- | --- |
| Arithmetic/numeric | Parse the entire permitted response; compare exact integers or explicitly declared decimal tolerance/units. Do not accept a correct number buried in an otherwise wrong answer. |
| Multiple choice | Parse the declared complete label form; compare with the pinned label. No guessing from arbitrary prose or substring matches. |
| Structured extraction | Strict JSON schema, required values, extra-key/duplicate-key policy and finite numbers. JSON key order can be irrelevant without ignoring missing/wrong values. |
| Short answer | Exact normalized match against a reviewed alias set, or a separately specified task metric. Define case, punctuation, Unicode and whitespace handling narrowly. |

No Python `eval`, generated-code execution, automatic model judge, semantic
similarity threshold chosen after seeing answers, or model-specific answer cleanup.
Trailing whitespace removal can be fair if declared for every model; extracting
whichever substring makes a model pass is not. Pin evaluator version and rubric hash.

Score after timing so parsing/tokenization/grading cannot delay the load generator.
Keep question ID associations when responses complete out of order. Reordering or
parallel evaluation must produce identical per-question verdicts. Generation seed
does not guarantee deterministic generation; deterministic evaluation means the
same stored answer and rubric always produce the same verdict.

Report correct/incorrect, invalid-format, missing-generation and evaluator-error
counts, coverage and task-specific denominators. One useful declared end-to-end
accuracy is correct answers divided by all assigned questions, treating missing
generation as incorrect; also report accuracy conditional on valid completed
outputs. Scorer crashes are infrastructure failures requiring repair, not evidence
that the model answered incorrectly. Suppress a final quality claim until those
cases are resolved. Predeclare task weights/micro-versus-macro aggregation; do not
average unrelated scores into an unexplained quality number.

## Suggested tests for future owner implementations

Use fake clocks, scripted completion events, a fake transport and pinned local
question fixtures. No real-time sleeps, HTTP/GPU work or dataset downloads in unit
tests. These are suggested assertions, not an executable benchmark algorithm.

| Scenario | Clients | Expected assertion |
| --- | --- | --- |
| Closed-loop cap | 1, 2, 4, 8 independently | Observed outstanding never exceeds C; every logical client has at most one request; exactly one terminal record per request. |
| Offered-rate independence | 1, 2, 4, 8 caps at the same scripted rate | Intended arrivals do not move when service slows; overflow is explicitly queued/rejected, with bounded memory. |
| One-slot server fixture | 1, 2, 4, 8 | Increased clients expose queueing; tests never assert linear speedup or simultaneous device execution. |
| Fixed versus Poisson arrivals | Every C | Fixed due offsets are exact; seeded random schedules replay identically across models, independently of sampling/question seeds. |
| Generator stall | Every C | Scheduling lag/missed offers visible; no hidden rescheduling or catch-up burst. |
| Pool contention | C=4/8 with pool=1 | Pool waits are visible transport overhead; do not attribute all added latency to GPU queueing. |
| Delayed/out-of-order completion | 2, 4, 8 | Question/client/request links remain correct; one slow request is not overwritten by another's result. |
| 429/503, timeout, malformed stream | Every C | Classified error records retained; siblings continue under the declared policy; no implicit retries or success counting. |
| Cancellation and drain deadline | Every C | No new dispatch; queued/running states distinguished; tasks/streams cleaned up; outstanding work prevents a complete cohort claim. |
| Quantile hand case | Synthetic 1/2/3/4/100 ms | Median 3 and nearest-rank p95 100; empty/one-sample/ties/small-N behavior explicit. |
| Unequal per-client sample counts | 2, 4, 8 | Pooled p95 derives from request records, not an average of client p95s. |
| Aggregate overlap | 2 requests, 40+60 tokens / 2 s | Aggregate 50 tokens/s with a shared interval; errors contribute elapsed time, not successful token totals. |
| Cohort/window boundary | Every C | Drain and cutoff policies are explicit; no final-count assumption about subwindow token arrivals. |
| Synthetic arithmetic | Local synthetic questions | Exact correct/incorrect, signed/decimal/unit policy, extra prose and misleading-number substrings tested. |
| Synthetic extraction | Local synthetic questions | Key order handling, extra/missing/duplicate keys, wrong types, NaN and malformed JSON covered. |
| Public question manifest | Pinned licensed local subset | Hash/revision/license and split validated; duplicate IDs, leaked gold annotations and missing references rejected. |
| Evaluator determinism | Same public/synthetic stored answers | Repeated/reordered/parallel grading yields identical verdicts; normalization/version hashes retained. |
| Invalid output versus scorer fault | Both question origins | Invalid format is a task verdict; scorer crash remains an infrastructure error and cannot quietly alter the denominator. |
| Task/dataset balance | Public and synthetic kept as strata | Same item IDs/counts/order schedule across models; no hand-picked passing subset or hidden task reweighting. |

Initial manual integration later: bounded local trials at C=1, then 2/4/8 only
after explicit contract/resource review. Keep server capacity fixed for a client
sweep. Separately study server slots/batching if desired. Apply the existing
cooldown, pinned provenance and matched output-budget protocol. Tail studies and
longer runs need their own declared limits; do not bypass current caps.

## Critique checklist for an actual design submission

Reject conclusions based on:

- Different model revisions, prompts/templates, input-token lengths, output-length
  cohorts, quantizations, GPU placement, KV precision, slots, cache state or thermal
  conditions described as a single-factor comparison.
- Equal maximum output budgets treated as equal actual work; tokenizer differences
  treated as universally comparable tokens/s across model families.
- Equal client counts treated as equal offered rates, or unequal arrival traces
  used for supposedly matched model comparisons.
- Cached/warm results ranked against cold results, quality computed on only fast
  successful responses, or failed requests removed without disclosing the denominator.
- Averaged p95s, eight-run p95s presented as stable tails, averaged per-request rates
  labeled aggregate throughput, or throughput gains presented without errors/quality.
- Public datasets treated as unseen/contamination-free merely because they are
  public; synthetic tasks treated as representative of real workloads.

More clients can improve batching, increase queueing, or trigger resource failures;
none of those outcomes is guaranteed. Report the observed tradeoff, not an expected
linear scaling story. Share the two module designs or initial owner-written code
next so the next review can identify concrete correctness and edge-case issues.
