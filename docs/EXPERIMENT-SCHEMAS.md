# Reproducible experiment and result schemas

`ExperimentConfig` and `Result` are Pydantic models in
[`inferlab_api.contracts`](../apps/api/src/inferlab_api/contracts.py). They validate
data only. No execution, timestamps collected from clocks, tokenization, model
downloads, storage, new endpoints or benchmark calculations are implemented.

## Identity and provenance

| Requirement | Field(s) |
| --- | --- |
| Stable experiment identity | `ExperimentConfig.experiment_id`, `Result.experiment_id`, `Result.run.experiment_id`; all must agree. |
| Model identity and pin | Config `model_id`, `model_revision`, `model_sha256`, `quantization`; must match result model provenance and registry metadata at submission validation. |
| Engine identity and pin | Config `engine_id`, `engine_version`, `engine_build`, `seed_supported`; must match observed/resolved engine provenance. |
| Prompt/workload | Config `prompt_id`, `workload_id`; provenance workload includes the same prompt ID and workload SHA-256. MVP assumes one registered prompt per workload. No raw prompt or local path is accepted. |
| Context and token budgets | Config `context_tokens`, `input_token_budget`, `max_output_tokens`; input plus maximum output must fit context. |
| Actual token counts | `Result.run.input_tokens` and `output_tokens`, distinct from requested budgets; required for complete runs and nullable on partial failures/cancellation. |
| Sampling and seed | Config `sampling.temperature`, `top_p`, `seed`; a non-null seed requires declared and registry-confirmed support. `null` means no seed requested, not zero. Seed support does not guarantee deterministic output. |
| GPU settings | Config `gpu_device_id`, `gpu_layers`; the same typed fields in hardware provenance must agree. `gpu_layers: null` means unspecified/unavailable, distinct from zero. Hardware `gpu_settings` is a descriptive note, not executable configuration. |
| Repeat protocol | Config `condition`, `warmups`, `repetitions`, `concurrency`, `timeout_seconds`; run `kind`, `repetition`, `attempt` retain per-run identity. |
| Timestamp and device | Run `recorded_at` requires a timezone; hardware records `device_name`, `device_memory_mib`, `driver_version`. This timestamp is provenance, not an elapsed-time clock. |
| Errors | Run `error_code` plus result `errors: [{code, stage}]`; stages are preparation, generation, validation or cleanup. Raw exception text, prompts and paths are excluded. |
| Methodology and synthetic data | `schema_version`, provenance `methodology_version`, `data_kind` and matching label (`DEMO DATA` / `MEASURED DATA`). |

Assign the experiment ID once when defining the experiment and reuse it across
serialization, retries and results; do not derive it from a mutable display name
or generate it on each load. Distinct runs use `run.id`, attempt and repetition.
The schema checks identity links, not persistence uniqueness; a future database
must enforce uniqueness/idempotency. Inputs are required, with no random-ID or
current-time defaults.

Checksums must be 64 lowercase hexadecimal characters. Validation checks format
and equality with supplied registry/provenance values, not actual file contents.
The future worker must verify checksums and effective settings against the local
engine before execution. These records do not add unsupported controls to the
minimal Ollama adapter.

## Validation rules

Unknown fields are rejected, integer controls/counts reject strings and booleans,
sampling values are finite, and seed-capability flags require real booleans.
Existing limits remain context 128-8192, output 1-2048, warmups 0-5,
repetitions 1-20, concurrency exactly 1, timeout 1-3600 seconds and GPU layers
0-200 when specified. Cold configurations require zero warmups.

`Result` is one run with a full config/provenance snapshot, not an aggregate or
publication approval. It checks matching experiment/prompt/model/engine/GPU
identity, condition, per-kind repetition bounds and actual token budgets. TTFT
cannot exceed a present request latency. Missing metrics retain an explicit
unavailable reason; zero remains a valid observed value. Complete results cannot
contain errors; failed/cancelled results must include their primary run error,
and cancellation uses the `cancelled` state/code. Partial diagnostics are retained
but do not establish successful execution or eligibility for aggregation.

The schema-only OpenAPI catalog and generated TypeScript now include `Result`.
Existing JSON demo configs/provenance were migrated to the new required fields;
older config files must be migrated explicitly, not supplied invented defaults.
The health-only API and mock dashboard still do not submit experiments.

## YAML fixtures and checks

All five examples under [`experiments/fixtures`](../experiments/fixtures) are
**DEMO DATA**, including checksums, identities, hardware and metrics:

- `experiment-warm.yaml`: supported seed, warmups and pinned config.
- `experiment-cold.yaml`: zero warmups and unsupported seed represented by null.
- `result-complete.yaml`: complete run with provenance and counts.
- `result-failed.yaml`: timeout with missing counts/measurements.
- `result-cancelled.yaml`: cancellation with partial-result shape.

Load trusted local fixture YAML with `yaml.safe_load`, then pass the resulting
mapping to `ExperimentConfig.model_validate` or `Result.model_validate`. YAML
loading is used by tests only; this does not create a public YAML upload/import
surface. PyYAML and its typing stubs are explicit development dependencies.

```powershell
uv sync --locked
uv run --locked pytest tests/test_experiment_results.py tests/test_contracts.py
npm.cmd run contracts:check
```

Tests cover YAML/JSON round trips and stable IDs, stale provenance, strict limits,
unsupported seeds, missing counts, timezone requirements, output budgets,
warmup/measured indices and contradictory error states. No test contacts a model
server or GPU. After any contract change, regenerate and commit the OpenAPI,
TypeScript and validated JSON fixture artifacts together.

References: [Pydantic validators](https://docs.pydantic.dev/latest/concepts/validators/)
and [PyYAML safe loading](https://pyyaml.org/wiki/PyYAMLDocumentation).
