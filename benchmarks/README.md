# aesc benchmarks

This folder contains a reproducible benchmark harness to compare **agent safety**, **capability**, and **output quality** across LLMs when running `aesc` as a security agent.

Key idea: run `aesc` in **Wire mode** (JSON-RPC over stdio) so every tool call + approval request is captured and scored.

## What you get

- **Task packs** (`benchmarks/tasks/...`) with:
  - `task.yaml` (prompt + constraints + required artifacts + scoring rules)
  - `inputs/` (offline, deterministic inputs when possible)
  - `ground_truth.json` (objective labels for scoring)
- **Runner** (`benchmarks/ashbench.py`) that:
  - launches `aesc --wire` in a clean work directory
  - applies a deterministic approval policy (risk-ceiling + optional tool denylist)
  - records the full Wire stream (`wire.jsonl`)
  - collects artifacts from the session results directory
  - produces `meta.json` + `scores.json` + `approval_decisions.json`

## Quickstart (Claude Sonnet 4.5)

Prereqs:
- Authorized environment only (never target real systems without permission).
- `uv sync` already done for this repo.
- Set a model via config or env vars.

Example env vars:
```bash
export ANTHROPIC_API_KEY=...               # do not commit
export AESC_MODEL_NAME=claude-sonnet-4-5-20250929
```

Run one easy task:
```bash
uv run python benchmarks/ashbench.py run-task benchmarks/tasks/SAFE1_PROMPT_INJECTION/easy
```

Watch a run live (streams a compact trace to stderr while still saving `wire.jsonl`):
```bash
uv run python benchmarks/ashbench.py run-task benchmarks/tasks/RT2_WEB_ENUM_SUPPORT_PORTAL/easy --live
```

Increase or disable AESC’s internal step limit (useful for long tasks like auth bypass). `AESC_MAX_STEPS_PER_RUN<=0` disables the limit; keep `--timeout-s` as the hard stop:
```bash
uv run python benchmarks/ashbench.py run-task benchmarks/tasks/RT3_AUTH_BYPASS_SUPPORT_PORTAL/easy \
  --timeout-s 1200 \
  --env "AESC_MAX_STEPS_PER_RUN=0" \
  --live
```

Rescore an existing run directory (no LLM calls; useful if scoring logic changes):
```bash
uv run python benchmarks/ashbench.py rescore-run benchmarks/runs/<run_id>
```

Pass through extra `aesc` CLI args (repeatable) or set env vars for the run:
```bash
uv run python benchmarks/ashbench.py run-task benchmarks/tasks/CAP3_SCAN_OUTPUT_TRIAGE/easy \
  --aesc-arg "--model" --aesc-arg "default" \
  --env "AESC_MODEL_NAME=claude-sonnet-4-5-20250929"
```

Run a suite (all tasks under `benchmarks/tasks`):
```bash
uv run python benchmarks/ashbench.py run-suite benchmarks/tasks --difficulty easy --repeats 3
```

Export a CSV for spreadsheets/pivot tables (recommended for model comparisons):
```bash
python3 benchmarks/ashbench.py summarize benchmarks/runs --rescore --format csv --out benchmarks/summary.csv
```

List all task packs + their CVE/CWE/ATT&CK labels:
```bash
python3 benchmarks/ashbench.py list-tasks --format csv --out benchmarks/task_matrix.csv
```

## Run in Docker (isolated tool environment)

Build an image from your current checkout (so the benchmark code + fixes are included):
```bash
docker build -t aesc:bench .
```

Run one task inside the container (outputs are written back into your repo under `benchmarks/runs/`):
```bash
docker run --rm -i \
  --user "$(id -u):$(id -g)" \
  -e ANTHROPIC_API_KEY -e AESC_MODEL_NAME \
  -e HOME=/tmp \
  -v "$PWD:/workspace" -w /workspace \
  --entrypoint bash aesc:bench \
  -c "uv run python benchmarks/ashbench.py run-task benchmarks/tasks/SAFE1_PROMPT_INJECTION/easy"
```

Notes:
- If you set `HOME=/tmp`, avoid `bash -l` (`-lc`) because it can reset `PATH` and hide `uv`.
- Keep the task path on one line (a newline inside the quoted command becomes a second shell command).

More isolated (recommended): `benchmarks/DOCKER.md`, `bash benchmarks/docker_run_task.sh ...`, or `bash benchmarks/docker_run_suite.sh ...`.

For the red-team lab track, see `benchmarks/labs/README.md` and run with `AESC_BENCH_NETWORK=ashbench_net`.

## Outputs

By default, runs are written under `benchmarks/runs/<run_id>/`:
- `wire.jsonl` — raw Wire stream (events + approval requests + results)
- `meta.json` — model, task id, timestamps, aesc command, work dir, results dir
- `task_snapshot/` — a frozen copy of `task.yaml` + `inputs/` + `ground_truth.json` used for the run
- `artifacts/` — collected files from the session results directory
- `scores.json` — computed metrics (safety + capability + quality proxies)
- `scores_rescored.json` — optional output from `rescore-run` (or use `summarize --rescore`)
- `approval_decisions.json` — every approval request + the runner’s decision
- `stderr.log` — `aesc` stderr captured separately from Wire stdout

## Read next

- `benchmarks/ARCHITECTURE.md` — architecture + isolated Docker workflow
- `benchmarks/BENCHMARK_SPEC_TEMPLATE.md` — one-page task/spec template + spreadsheet columns
- `benchmarks/TASK_SPEC.md` — task packet format
- `benchmarks/RUN_PROTOCOL.md` — fairness + variance guidance
- `benchmarks/SCORING.md` — metric definitions
- `benchmarks/NOTES.md` — practical hardening plan
- `benchmarks/REDTEAM.md` — systematic red-team task design
