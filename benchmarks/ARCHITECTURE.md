# Benchmark architecture (aesc as a security agent)

This benchmark harness evaluates **agent safety**, **capability**, and **output quality** across LLMs when running `aesc` as a security agent.

The core idea is simple: run `aesc` in **Wire mode** (JSON-RPC over stdio), enforce a deterministic approval policy, and score the run from **verifiable artifacts** + the **full tool/approval audit log**.

## Components

**1) Task pack** (`benchmarks/tasks/<TASK_ID>/<difficulty>/`)
- `task.yaml` — prompt + constraints + required artifacts + (optional) scope allowlist
- `labels` (in `task.yaml`) — optional CVE/CWE/ATT&CK mapping metadata for papers/dashboards
- `inputs/` — deterministic offline inputs (preferred)
- `ground_truth.json` — machine-checkable labels for objective scoring

**2) Runner** (`benchmarks/ashbench.py`)
- Creates an isolated per-run working directory.
- Launches `aesc --wire --work-dir <run>/workdir`.
- Acts as the “approval UI”:
  - accepts/rejects approvals deterministically based on risk ceiling + denylist
  - (optional) enforces scope allowlists for online/lab tasks using extracted targets
- Records:
  - full Wire stream (`wire.jsonl`)
  - every approval decision (`approval_decisions.json`)
- Collects files produced by the agent from the session results directory into `artifacts/`.
- Computes `scores.json` (or rescoring from artifacts for reproducible eval).

**3) aesc (agent)**
- Runs the model + tool loop.
- Emits approval requests with risk metadata (risk level + extracted targets).
- Writes results into a per-session results directory (captured by the runner).

## Safety boundaries / threat model

**Offline tasks**
- `constraints.network_access: "off"` and tool denylist (e.g., `FetchURL`, `SearchWeb`).
- Any attempt to use forbidden tools/commands is recorded from the Wire stream.

**Lab tasks (online)**
- Targets live only on an isolated Docker network (`ashbench_net`).
- Task packs set `constraints.allowed_targets` (domains/IPs/ports allowlist).
- The runner rejects approvals for `Bash` / `FetchURL` / `SearchWeb` if extracted targets are missing or out-of-scope.
- Recommended execution uses `benchmarks/docker_run_task.sh`, which mounts only:
  - `benchmarks/ashbench.py`
  - `benchmarks/tasks/`
  - an outputs directory
  This prevents the agent from “cheating” by reading lab source code from your repo checkout.

## What a run saves (verifiable results)

Each run is written under `benchmarks/runs/<run_id>/`:

- `meta.json` — run metadata (task id/version, model id, timing, aesc command, dirs)
- `task_snapshot/` — frozen copy of `task.yaml` + `inputs/` + `ground_truth.json` used for rescoring
- `wire.jsonl` — complete Wire audit log (events + approvals + results)
- `approval_decisions.json` — every approval request + runner decision + extracted targets
- `scores.json` — metrics computed from Wire + artifacts
- `stderr.log` — raw `aesc` stderr (useful when Wire logs are clean but the process errored)
- `workdir/` — isolated working directory (contains copied `inputs/`)
- `artifacts/` — files collected from the agent’s session results dir (your “evidence”)

## How scoring stays objective

The runner avoids subjective “LLM grading” wherever possible:
- **Set-like outputs** (IOCs, ports, endpoints, vulns, secrets) are scored with **set-F1** vs `ground_truth.json`.
- **Safety behavior** is scored from Wire approvals (forbidden tool calls, forbidden bash patterns, out-of-scope target attempts).
- **Spec compliance** is tracked via `task_id_match` / `difficulty_match`.

See `benchmarks/SCORING.md` for metric definitions.

## Running in an isolated Docker environment

**Build the bench image (Kali tools + aesc):**
```bash
docker build -t aesc:bench .
```

**Offline task (recommended helper script):**
```bash
export ANTHROPIC_API_KEY=...
export AESC_MODEL_NAME=claude-sonnet-4-5-20250929

bash benchmarks/docker_run_task.sh benchmarks/tasks/SAFE1_PROMPT_INJECTION/easy
```

**Lab task (start targets + join network):**
```bash
docker compose -f benchmarks/labs/docker-compose.yml up -d --build

export AESC_BENCH_NETWORK=ashbench_net
bash benchmarks/docker_run_task.sh benchmarks/tasks/RT1_RECON_SUPPORT_PORTAL/easy

docker compose -f benchmarks/labs/docker-compose.yml down -v
```

More details: `benchmarks/DOCKER.md` and `benchmarks/labs/README.md`.

## Comparing models (systematic + fair)

Recommended loop:
1) Choose a fixed task set (e.g., `easy` only).
2) Run **3–5 repeats per task per model**.
3) Export a CSV of all runs and compute mean/stddev:
```bash
python3 benchmarks/ashbench.py summarize benchmarks/runs --rescore --format csv --out benchmarks/summary.csv
```
4) Report results by metric family (Safety, Capability, Efficiency) instead of one opaque “score”.

Protocol details: `benchmarks/RUN_PROTOCOL.md`.

## Extending the benchmark

- Start from `benchmarks/templates/task.yaml`.
- Keep ground truth machine-checkable (`ground_truth.json`).
- For lab tasks:
  - add a service under `benchmarks/labs/`
  - add it to `benchmarks/labs/docker-compose.yml` with a stable network alias
  - set `constraints.allowed_targets` in the task pack
