# RTX 4060 quantization comparison protocol

Status: **unresolved configuration plan, not benchmark results**. Deliverables are
the three YAML files in [`experiments/plans/rtx4060`](../experiments/plans/rtx4060)
and test-only plan validation. No runner, evaluator, quantizer, telemetry loop,
binary/model download, server launch or measurements are implemented or performed.

## Pin one exact model before admission

No model or immutable revision has been selected. `artifacts.yaml` therefore
requires real model identity, full source commit/snapshot checksum, tokenizer and
prompt-template checksums, layer count and supported context. Engine build/binary
hash, conversion/quantizer builds and actual device/driver/host settings are also
unresolved. These nulls block ready-plan validation. Do not replace them with
invented hashes or assume files with similar names share a source.

All four GGUFs must descend from the **same verified FP16 conversion** of that
revision. Q4_K_M, Q5_K_M and Q8_0 are quantized directly from it, not from each other.
Record each artifact's distinct SHA-256 and file size; each quantized variant's
parent hash must equal the FP16 artifact hash. No importance matrix is used in this
version. Verify identical tokenizer/BOS/EOS and prompt rendering behavior for all
four artifacts. A different fine-tune, merged adapter, template or tokenizer starts
a separate plan. Variant registry IDs differ because the files differ; their
source identity/revision must not.

The layer levels require at least 24 transformer layers and native support for
8192 context tokens. Otherwise revise/version the entire plan before trials;
never change levels for one quantization. Layer 24 is not claimed to be full
offload: inspect actual placement, including any separately handled output layer.

## Controlled matrix

| Series | Quantizations | Context tokens | GPU weight layers | Purpose |
| --- | --- | --- | --- | --- |
| Context capacity | Q4_K_M, Q5_K_M, Q8_0, FP16 if admitted | 1024, 2048, 4096, 8192 | **8 fixed** | Isolate allocated context with identical prompts. |
| GPU layers | Same four | **2048 fixed** | 0, 8, 16, 24 | Isolate offload at fixed context. |

There are **32 candidate cells**, including independent anchors at context=2048 /
layers=8 in both series. Keep those series/experiment identities separate and
inspect anchor drift rather than pooling them as independent new settings.
Each cell uses three prompts, producing at most **96 experiment configs**.
Each has 2 warmups and 8 measured repetitions: at most 192 warmup and 768 measured
requests, excluding preflight. Respect the PRD's 10 submissions/day cap and keep
a balanced quantization quartet in the same session/day where possible.

This tests **allocated context capacity**, not increasing prompt length. Prompts,
input token sequences and output budgets stay fixed across context settings.
A context-occupancy/long-prompt sweep changes workload length and needs a separate
protocol. Weight quantization does not imply KV-cache quantization.

## Feasibility per cell

Use already installed files/binaries. Capture desktop/laptop form factor,
TGP/power mode, CPU/RAM, OS, driver, engine build and actual available memory.
Nominal 8 GB is not free memory. Do not pool desktop/laptop results or equate
weight-file size with resident memory. NVIDIA lists the desktop RTX 4060 with
8 GB; local inventory is authoritative for this machine.
[NVIDIA specifications](https://www.nvidia.com/en-us/geforce/graphics-cards/40-series/rtx-4060-4060ti/).

Before admission, verify identity, effective flags, actual placement, context,
prompt token counts, host memory and worst-case workload headroom. Account for
weights, KV cache, workspaces, driver/desktop use and host allocations. Proposed
minimums are **1024 MiB free GPU and 2048 MiB free host memory** under the intended
preflight workload. These are policy margins, not fit guarantees. Sampling can
miss peaks; check allocation failures, paging and server diagnostics too.

FP16 remains conditional at partial offload. If an artifact is missing, headroom
is insufficient, paging invalidates comparison, or a cell OOMs, retain it as
`admission: skipped` with its reason and no numeric result. Other quantizations
can also be infeasible. Never rescue FP16 by changing model, context, KV precision,
layer count or batch size, or enabling automatic fallback within the cell.
Lower offload is already a separate controlled layer trial.

`pending` means no capacity decision was made. Admit/skip only after saving local
preflight evidence. Shape validation cannot prove that evidence or hardware exists.
`readiness: ready` needs complete pins, verified token counts and no pending cells;
it is neither public execution permission nor an automatic dispatch trigger.

## Fixed settings and procedure

1. Freeze the files and hashes. Use the exact raw UTF-8 strings in `prompts.yaml`;
   their committed SHA-256 values hash those actual synthetic strings. No extra
   template, whitespace, system/history text or reasoning mode may differ.
   Verify matching token IDs and full input counts, including special tokens,
   across variants. `input_tokens: null` stays unresolved until tokenization;
   512 is the input budget, not a claimed count.
2. Hold YAML controls fixed: engine/build, threads 4/4, batch/ubatch 512/128,
   one slot/request, FP16 K/V, KV offload policy, flash attention off, mmap with
   lazy loading off, GPU/split settings, no prompt reuse, LoRA, speculation,
   automatic fitting or context shift. Use temperature 0, top-p 1, seed 42,
   disabled top-k/min-p and no repetition penalty. Seed support does not guarantee
   identical output. Verify support/effective settings in the pinned binary using
   the official [llama-server reference](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md).
3. The existing transport exposes only part of these controls. These YAMLs are
   inert plan envelopes, not HTTP payloads or a claim that today's adapter applies
   every field. Manual controls or a future reviewed implementation must verify
   them. No raw shell strings or filesystem paths are added to the plan.
4. Follow the declared cell order. Rotate quantization order by cell:
   Q4/Q5/Q8/FP16, Q5/Q8/FP16/Q4, Q8/FP16/Q4/Q5, FP16/Q4/Q5/Q8; repeat for the
   layer series. Keep skipped positions. This balances starting positions across
   settings, **not within a cell**. Preserve session/day/order metadata; a future
   independent replication can reverse the complete schedule with a new plan ID.
5. On configuration change, stop the old server manually and confirm work ended
   before loading the next settings/artifact. Disable startup warmup and idle
   sleep, keep loading separate, then discard **2 warmups per prompt/config**.
   A restart needs fresh warmups. Preflight, loading and warmups are not measured
   repetitions.
6. Before each cell and measured repetition, wait **at least 30 seconds**, then
   require temperature at or below idle baseline +3 C for **10 seconds**, checked
   once per second. Capture initial idle baseline over 30 seconds under the same
   AC/power/fan policy. At **300 seconds** without recovery, defer/skip with
   `thermal_timeout`. Unverifiable thermal readings also defer the cell. These
   are stabilization criteria, not manufacturer safety limits. Keep the model
   resident through cooldown; re-prepare and record any unexpected unload/sleep.
7. Run **8 measured attempts per prompt/config**, concurrency 1, with **600 seconds
   maximum per experiment**, including warmups and cooldown. If slow CPU/FP16
   cells cannot finish within this scope, retain incomplete attempts and stop;
   do not extend deadlines or replace failures. Every attempt/error is evidence.
8. Use monotonic client TTFT/total-latency boundaries and retain actual token
   counts, stop reasons, errors/cancellations and hardware conditions. Chunks are
   not token counts; sparse NVML values are observed peaks. Disclose background
   load or throttling; a resumed session is a new attempt.

Layer 0 requests zero GPU **weight** layers; it does not promise zero GPU memory
or operations under a fixed KV/runtime policy. These are system/hybrid results
unless actual placement proves otherwise, not isolated kernel throughput.

## Output matching and quality

Every prompt has the **same 128-token maximum** in every cell. Respect EOS; do not
pad, force extra tokens or increase budgets. Keep actual output-length/stop-reason
cohorts. Compare quantization end-to-end latency/rates only for identical prompt,
context, layer count and matching actual output length/stop policy. Otherwise
show the mismatch and avoid a speedup claim. TTFT still needs matching prompt
tokenization and measurement boundaries. Compare context/layer effects within
one quantization, holding the other axis fixed.

The performance list prompt may hit its budget; it is not a quality answer.
Score the two separate golden tasks after timing: arithmetic equals `42` after
trimming outer whitespace; extraction parses as exactly
`{"name":"Mira","color":"blue"}`, with no extra keys, prose or Markdown fences.
JSON key order is irrelevant. All 8 attempts on each quality prompt must pass for
a configuration to qualify. Retain failures rather than dropping repetitions.
This tiny synthetic suite is a smoke check, not general accuracy evidence.

Use admitted **FP16 in the identical context/layer cell** as the preferred output
reference. Otherwise explicitly label Q8_0 at that cell as a quantized reference,
provided it passes golden checks. If neither qualifies, report no reference.
Never substitute another model/revision or compare FP16 CPU with quantized GPU as
a matched quantization speedup.

Show individual runs, medians/ranges and sample/error counts. Do not pool series,
prompts, unequal lengths, days or changed placement into one speed number. Keep
skipped/incomplete/quality-failed cells visible. Publication, real statistics and
evaluation algorithms remain future owner work.

## Validation

```powershell
uv run --locked pytest tests/test_quantization_plan.py
```

Tests cover 32 cells, isolated axes, prompt hashes, same-source lineage, distinct
artifact hashes, immutable pins, seed/KV controls, cooldown, readiness, skips and
mapping to existing `ExperimentConfig`. Synthetic pins/token counts occur only in
temporary test doubles. No verified identity or measurements are fabricated in
committed YAML, and no production validator, CLI or executor is added.
