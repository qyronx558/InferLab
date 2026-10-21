# NVML lesson and proposed gpu_profiler.py interfaces

This is an owner implementation exercise. There is no profiler implementation,
NVML dependency installation, hardware probe, sampling loop or new benchmark
calculation in this change. The proposed target is
`inferlab_core/benchmarking/gpu_profiler.py`; the snippets below are design sketches.
NVML telemetry remains an opt-in stretch capability under the [PRD](PRD.md).

## What to read

Use NVIDIA's [`nvidia-ml-py` distribution](https://pypi.org/project/nvidia-ml-py/),
which exposes the Python module `pynvml`. It wraps the installed NVML library;
installing Python bindings does not install or repair a GPU driver. Its functions
return structured values and raise `NVMLError` subclasses on NVML failures.

The lifecycle is: initialize NVML, select one device, obtain a handle, query it,
then release the initialization with shutdown in a `finally` block. Prefer a
configured device UUID; an index is not a permanent identity or necessarily the
same ordinal that a CUDA process sees. Keep UUID/PID details local unless an
approved export policy permits them.

| Reading | NVML query / fields | Meaning and units |
| --- | --- | --- |
| Used / free / total memory | `nvmlDeviceGetMemoryInfo`; versioned memory-info API when supported | Device memory bytes. Preserve directly reported counters; divide by `2**20` only for MiB presentation. |
| GPU utilization | `nvmlDeviceGetUtilizationRates(...).gpu` | Kernel-active time percentage over the driver's recent sampling window, not FLOPS or percent of theoretical compute. |
| Memory activity | `nvmlDeviceGetUtilizationRates(...).memory` | Memory read/write activity percentage, **not memory occupancy**. |
| GPU temperature | `nvmlDeviceGetTemperatureV` where exposed/supported; legacy `nvmlDeviceGetTemperature(handle, NVML_TEMPERATURE_GPU)` for a documented compatible fallback | GPU sensor temperature in degrees Celsius, not VRAM temperature. |
| Sampling time | Host `time.perf_counter_ns()` before and after the query group | A monotonic observation interval, not a hardware sensor timestamp. Add an aware UTC timestamp separately for logs. |

The [NVIDIA API header](https://github.com/NVIDIA/go-nvml/blob/main/pkg/nvml/nvml.h)
documents these semantics, versioned structures and the legacy temperature API's
deprecation. Record the binding, NVML, driver and API versions used. Do not silently
switch accounting versions between baseline and inference observations. Preserve
reserved-memory fields where supported; do not invent a universal
`total = used + free + reserved` equation or derive free memory by subtraction.

Memory, utilization and temperature are separate queries. Bracketing them with
host timestamps makes their acquisition span visible; it does not make the values
an atomic device snapshot. Keep these timestamps in the same clock domain as the
future benchmark runner. Wall-clock adjustments must not change measured intervals.

## Device memory versus process memory

Device-used memory can include the model server, desktop/browser, other clients,
runtime allocations and driver accounting. It is not a model's KV cache size or
the Python caller's memory. The inference allocations generally belong to
`llama-server` or an Ollama runner process, not InferLab's HTTP client.

Process queries such as `nvmlDeviceGetComputeRunningProcesses` are a separate,
optional feature. Process trees, worker replacement, permissions, PID reuse and
graphics clients complicate attribution. Never assume the sum of listed compute
process allocations equals the device counter. On Windows WDDM, per-process
`usedGpuMemory` can be unavailable; normalize an unavailable sentinel or `None`
to a missing reading, never a huge allocation or zero. Record physical-device,
MIG-instance or process scope explicitly and never mix those scopes. See NVIDIA's
[device-query reference](https://docs.nvidia.com/deploy/archive/R550/nvml-api/group__nvmlDeviceQueries.html)
and the current header linked above.

For the first implementation, collect **device-level** memory only. Unsupported
process attribution must not be replaced by a device reading labeled as process
memory. Framework allocated/reserved memory and NVML device memory are also
different measurements; a future in-process profiler may report both separately.

## Baseline subtraction

Proposed convention: take several valid, quiet pre-run device-memory observations
and use their median as baseline `B`. Retain the baseline samples, range, timestamps,
API version, device/scope and phase. A wide baseline range is a warning that the
comparison is noisy; choose a stability threshold before collecting data.

Report all three values separately:

- Absolute observed peak: largest valid device-used reading within the run window.
- Baseline: `B`, with its acquisition phase and sample count.
- Baseline-relative change: `observed_peak - B`, an attribution estimate only.

**Synthetic exercise:** baseline readings 190, 200 and 210 MiB give `B = 200 MiB`.
Run readings 240, 280 and 260 MiB give an observed peak of 280 MiB and a change
of 80 MiB. This is not evidence that the model allocated exactly 80 MiB.

For a **cold** run, capture baseline before loading; its change may include weights,
CUDA context, caches and inference allocations. For a **warm** run, capture baseline
after loading and warmups; the change describes extra activity above resident
state. Those changes answer different questions. Keep loading, warmup and measured
inference windows separate. Unloading a model does not guarantee allocator, OS or
driver memory immediately returns to an earlier baseline.

If an unrelated application releases memory, the change can be negative. Preserve
that signed value and flag interference; do not silently clamp it to zero. With
missing baseline or no valid run samples, the corresponding statistic is unavailable.
Device mismatch, mixed scope/API version or reversed timing invalidates subtraction.
Do not subtract baselines from utilization or temperature by default.

The existing nonnegative wire `peak_vram` must never receive a signed delta. Any
future mapping should explicitly describe an **absolute observed device peak**,
with sampling/scope metadata. Baseline deltas need their own reviewed schema;
no schema changes or publication behavior are added here.

## Sampling interval and short peaks

Start with a configurable **100 ms** polling interval as an engineering hypothesis,
then measure overhead and actual gaps on your machine. A faster interval can catch
more memory changes but consumes more CPU/driver work and may disturb request
timing. Run blocking NVML calls in one owned sampling thread rather than inside
the streaming-content callback or an asyncio event loop. Do not add CUDA
synchronization to the HTTP client for telemetry: it cannot synchronize the
model server's CUDA context.

Polling cadence and sensor refresh cadence differ. NVIDIA describes utilization
windows of roughly 1/6 second to 1 second depending on the product. Faster polling
can therefore return repeated utilization values; repeated values are not
independent measurements. Temperature may also refresh more slowly than polls.
[NVML utilization definition](https://docs.nvidia.com/deploy/archive/R470/nvml-api/structnvmlUtilization__t.html).

A memory allocation that rises at 20 ms and is freed at 40 ms is invisible to
polls at 0 and 100 ms. Driver update lag and scheduling jitter can add further
gaps. Therefore `max(sampled_used)` is an **observed peak**, not a guaranteed true
peak. Even a poll immediately after completion cannot recover an earlier peak.
For memory headroom, leave margin; for allocator-specific exact peaks, investigate
engine/framework instrumentation in a separate future task.

The future loop should sample immediately, then target fixed monotonic deadlines.
When reads overrun an interval, skip missed deadlines and record gaps instead of
issuing a burst of backdated samples. Use an interruptible wait; stopping must not
wait an entire long interval. Store actual query start/end times, requested interval,
missed/dropped count and any buffer overflow. Bound retention by duration and sample
count. A query can itself stall; an interruptible wait cannot cancel an arbitrary
native driver call, so a strict shutdown deadline needs stronger isolation later.

For report eligibility, a conservative initial rule is to use only observations
whose entire query span lies within the measured region; retain overlapping/boundary
observations as diagnostics. Record that rule and the number of eligible samples.
Very short requests may have no eligible observations, which is unavailable rather
than zero. All missing readings stay missing; never forward-fill them into a peak.

## Errors and lifecycle

| Failure | Proposed treatment |
| --- | --- |
| Binding absent, library not found, driver not loaded, version mismatch | Mark profiling unavailable with a typed reason; no auto-install, shell fallback or fabricated zero. Optional inference may continue according to the declared policy. |
| Unknown device / invalid configuration | Fail preflight clearly; never switch silently to GPU 0. |
| Not-supported sensor/function | Mark only that metric unavailable; retain independent valid readings. Use a documented version fallback only for capability/version absence, and record which API was selected. |
| No permission | Report unavailable for that field; do not try privilege escalation. |
| GPU lost / invalidated handle | End the profiling session, retain partial observations and mark coverage incomplete. Do not aggregate stale readings or reacquire a different device silently. |
| Unknown/transient read failure | Retain a gap and safe error code. Any recovery policy must be bounded and explicit. |
| Shutdown failure | Record cleanup failure without masking the original error or cancellation; release only initialization owned by this session. |

NVML issues do not automatically mean the generation request failed. Keep profiling
availability separate from job state. A report that requires complete GPU telemetry
can reject incomplete coverage without converting a successful inference into a
made-up GPU measurement. Record errors per metric/session, not raw private exception
text. NVIDIA's [Python binding documentation](https://pypi.org/project/nvidia-ml-py/)
describes its NVML-to-Python exception mapping.

Define ownership precisely: if initialization succeeds but device selection fails,
the backend's `open` must clean up that initialization before raising. The collector
calls `close` only after a successful `open`. If device loss occurs during a sample,
retain earlier valid fields, mark remaining fields unavailable with `device_lost`,
and stop collection after retaining that partial observation.

## Proposed interfaces, with no sampling implementation

The backend owns the optional lazy `pynvml` import, handle and initialization.
`NvmlReader` returns typed counters or raises a future `GpuQueryError` carrying a
safe reason. The sampler owns clocking, per-field failure handling, waiting and
retention. A separate pure summary stage owns baseline selection and observed
peak calculations; none are implemented below.

```python
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from threading import Event
from typing import Literal, Protocol

type GpuUnavailableReason = Literal[
    "binding_missing", "library_missing", "driver_unavailable", "version_mismatch",
    "not_supported", "permission_denied", "device_lost", "query_failed"
]


@dataclass(frozen=True)
class Reading[T]:
    value: T | None
    unavailable_reason: GpuUnavailableReason | None


@dataclass(frozen=True)
class MemoryCounters:
    total_bytes: int
    used_bytes: int
    free_bytes: int
    reserved_bytes: int | None
    api_version: str


@dataclass(frozen=True)
class UtilizationCounters:
    gpu_percent: int
    memory_active_percent: int


@dataclass(frozen=True)
class GpuSample:
    device_uuid: str
    query_started_ns: int
    query_finished_ns: int
    captured_at: datetime
    memory: Reading[MemoryCounters]
    utilization: Reading[UtilizationCounters]
    temperature_c: Reading[int]


class Clock(Protocol):
    def now_ns(self) -> int: ...
    def utc_now(self) -> datetime: ...


class Waiter(Protocol):
    def wait_until_ns(self, deadline_ns: int, *, stop: Event) -> None: ...


class NvmlReader(Protocol):
    def open(self, device_uuid: str) -> GpuIdentity: ...
    def memory(self) -> MemoryCounters: ...
    def utilization(self) -> UtilizationCounters: ...
    def temperature_c(self) -> int: ...
    def close(self) -> None: ...


def sample_once(
    reader: NvmlReader, *, device_uuid: str, clock: Clock
) -> GpuSample:
    """Read independent metrics with host time bounds; retain per-field failures."""
    raise NotImplementedError


def collect_profile(
    reader: NvmlReader,
    *,
    device_uuid: str,
    config: SamplingConfig,
    clock: Clock,
    waiter: Waiter,
    stop: Event,
) -> ProfileTrace:
    """Own initialization, bounded sampling and cleanup; never execute inference."""
    raise NotImplementedError


def summarize_profile(
    samples: Sequence[GpuSample],
    *,
    baseline_samples: Sequence[GpuSample],
    run_started_ns: int,
    run_finished_ns: int,
    phase: Literal["cold", "loading", "warmup", "warm"],
) -> GpuProfileSummary:
    """Report scoped observed peaks, baseline/delta and coverage limitations."""
    raise NotImplementedError
```

Types left for you to define: `GpuIdentity` (device UUID, scope, device name,
driver/NVML/binding versions and selected APIs), `SamplingConfig` (positive interval,
duration and retention limits), `ProfileTrace` (samples, identity, gaps, errors and
completion/coverage status), `GpuProfileSummary` (absolute peak, baseline, signed
delta, units, phase, eligible count and limitations). Add validation so present
readings have no unavailable reason, missing readings require one, byte counters
are nonnegative integers, percentages lie in 0-100, timestamps are ordered and
UTC timestamps are aware. Reject booleans masquerading as integers. Temperature
must be a genuine sensor integer; zero is not an error sentinel.

## Mockable test plan

Inject a fake `NvmlReader`, scripted clock and waiter. No test should import
`pynvml`, call a driver, sleep in real time or require a GPU. Error fakes should
raise your own `GpuQueryError`, leaving native exception translation to separate
backend tests with mocked bindings.

| Case | Expected result |
| --- | --- |
| One valid sample | Used/free bytes, both utilization fields, temperature and device identity preserved exactly; host timestamps bracket all three queries. |
| Units | 1,048,576 reported bytes displays as 1 MiB; occupancy and memory activity remain distinct. |
| Genuine zero | Zero utilization/temperature/used bytes remain valid readings, not unavailable. |
| Partial sensor failure | Temperature unsupported while memory/utilization succeed: only temperature is missing with its reason. |
| Missing process value | Sentinel/None is unavailable; device bytes never substitute for process bytes. |
| Initialization failure | No sensor reads; profiling unavailable; no unowned shutdown. |
| Failure after open | Owned initialization closed exactly once; primary error preserved. |
| Device lost | End session with incomplete coverage; no stale carry-forward or implicit device switch. |
| Known baseline/peak | Synthetic baseline 190/200/210 MiB and run 240/280/260 MiB -> baseline 200, observed peak 280, signed delta 80 MiB. |
| Negative delta | Baseline 300 MiB and observed peak 280 MiB -> -20 MiB, with interference warning; no clamping. |
| No valid samples / baseline absent | Corresponding results unavailable, not zero; sample/error counts preserved. |
| Device/scope/API mismatch | Reject baseline subtraction across incompatible observations. |
| Boundary overlap | Query spanning run start/end retained diagnostically but excluded by the declared eligibility rule. |
| Wall-clock jump | UTC can jump while monotonic observation ordering remains valid; no wall-clock elapsed math. |
| Interval overrun | A 150 ms read at a 100 ms cadence records lateness/skipped deadline; no fabricated historical sample or catch-up burst. |
| Stop during wait | Fake waiter signals stop; no extra scheduled poll; cleanup once. |
| Buffer bound | Explicit dropped count/coverage warning; never pretend a truncated buffer contains the whole run. |
| Short hidden peak | A scripted 20-40 ms peak between 0/100 ms observations is absent from reported samples; summary says observed, not true peak. |
| Repeated utilization | Same driver-window values remain repeated observations; do not count them as independent evidence. |
| Import safety | Importing future profiler module on CPU-only CI must not load NVML or start a thread. |

Two example tests to adapt **after defining the proposed records**:

```python
from unittest.mock import Mock


def test_sample_preserves_raw_fields_and_host_time_bounds():
    reader = Mock(spec=NvmlReader)
    reader.memory.return_value = MemoryCounters(
        total_bytes=8 * 2**30, used_bytes=200 * 2**20,
        free_bytes=7992 * 2**20, reserved_bytes=None, api_version="fixture-v1",
    )
    reader.utilization.return_value = UtilizationCounters(25, 8)
    reader.temperature_c.return_value = 42
    clock = Mock(spec=Clock)
    clock.now_ns.side_effect = [1_000_000_000, 1_002_000_000]
    # Provide a fixed timezone-aware datetime, not the current wall clock.
    clock.utc_now.return_value = FIXED_UTC

    sample = sample_once(reader, device_uuid="GPU-fixture", clock=clock)

    assert sample.memory.value == reader.memory.return_value
    assert sample.utilization.value == UtilizationCounters(25, 8)
    assert sample.temperature_c.value == 42
    assert sample.query_started_ns == 1_000_000_000
    assert sample.query_finished_ns == 1_002_000_000
    assert sample.captured_at == FIXED_UTC


def test_stop_before_open_does_not_touch_driver():
    reader = Mock(spec=NvmlReader)
    stop = Event()
    stop.set()

    trace = collect_profile(
        reader, device_uuid="GPU-fixture", config=VALID_CONFIG,
        clock=Mock(spec=Clock), waiter=Mock(spec=Waiter), stop=stop,
    )

    reader.open.assert_not_called()
    reader.close.assert_not_called()
    assert trace.samples == ()
```

`FIXED_UTC` and `VALID_CONFIG` are test fixture placeholders. These test sketches
are not installed in the test suite and make no claim that sampling already works.

Your first task: define the records and implement **`sample_once` only**, including
partial sensor errors and clock bounds. Share it for review. Then implement the
stop-aware bounded loop and pure baseline/summary functions in separate steps.
