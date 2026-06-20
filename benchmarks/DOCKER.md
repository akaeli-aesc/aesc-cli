# Running benchmarks in Docker (isolated)

This repo’s `Dockerfile` builds a Kali-based image with `aesc` + tools installed. You can run the benchmark harness inside that container so results are repeatable and the host stays clean.

## 1) Build the image

From the repo root:

```bash
docker build -t aesc:bench .
```

## 2) Set model credentials

Example for Anthropic:

```bash
export ANTHROPIC_API_KEY=...
export AESC_MODEL_NAME=claude-sonnet-4-5-20250929
```

## 3) Run an easy task (recommended: host repo read-only)

This avoids accidentally using your host `.venv` inside the container and only writes outputs to `benchmarks/runs/`.

Recommended (short + safe mounts):

```bash
bash benchmarks/docker_run_task.sh benchmarks/tasks/SAFE1_PROMPT_INJECTION/easy
```

Watch a single run live (streams a compact trace to stderr):
```bash
bash benchmarks/docker_run_task.sh benchmarks/tasks/RT2_WEB_ENUM_SUPPORT_PORTAL/easy --live
```

If a task hits the default 100-step limit, raise it or disable it (recommended: keep a timeout):
```bash
bash benchmarks/docker_run_task.sh benchmarks/tasks/RT3_AUTH_BYPASS_SUPPORT_PORTAL/easy \
  --timeout-s 1200 \
  --env "AESC_MAX_STEPS_PER_RUN=0" \
  --live
```

Run a whole suite (many tasks + repeats) in the same isolated way:
```bash
bash benchmarks/docker_run_suite.sh --difficulty easy --repeats 3
```

Manual (same idea, but explicit):

```bash
mkdir -p benchmarks/runs

docker run --rm -i \
  --user "$(id -u):$(id -g)" \
  -e ANTHROPIC_API_KEY -e AESC_MODEL_NAME \
  -e HOME=/tmp \
  -v "$PWD/benchmarks/ashbench.py:/workspace/benchmarks/ashbench.py:ro" \
  -v "$PWD/benchmarks/tasks:/workspace/benchmarks/tasks:ro" \
  -v "$PWD/benchmarks/runs:/outputs" \
  --entrypoint /app/.venv/bin/python aesc:bench \
  /workspace/benchmarks/ashbench.py run-task /workspace/benchmarks/tasks/SAFE1_PROMPT_INJECTION/easy \
  --out-root /outputs \
  --aesc-cmd "/app/.venv/bin/aesc"
```

The helper scripts print the **host** run directory path under `benchmarks/runs/` at the end.

For lab (online) tasks, set `AESC_BENCH_NETWORK=ashbench_net` and use the helper script so the container joins the lab network:

```bash
export AESC_BENCH_NETWORK=ashbench_net
bash benchmarks/docker_run_task.sh benchmarks/tasks/RT1_RECON_SUPPORT_PORTAL/easy
```

## 4) Inspect results (verifiable artifacts)

For a run directory like `benchmarks/runs/<run_id>/`:

- `benchmarks/runs/<run_id>/scores.json` — objective metrics
- `benchmarks/runs/<run_id>/meta.json` — model id, task id, wall time, results dir
- `benchmarks/runs/<run_id>/approval_decisions.json` — every approval request + decision
- `benchmarks/runs/<run_id>/wire.jsonl` — complete Wire event log (audit trail)
- `benchmarks/runs/<run_id>/artifacts/` — files produced by the agent

Export a spreadsheet-friendly CSV across all runs:
```bash
python3 benchmarks/ashbench.py summarize benchmarks/runs --rescore --format csv --out benchmarks/summary.csv
```

Generate a “task matrix” (no LLM calls) with CVE/CWE/ATT&CK labels:
```bash
python3 benchmarks/ashbench.py list-tasks --format csv --out benchmarks/task_matrix.csv
```

## Common pitfalls

- If you use `bash -lc` with `HOME=/tmp`, the login shell can reset `PATH` and make `uv` “disappear”. Prefer `bash -c` or avoid `bash` entirely (as above).
- Don’t split the task path across lines inside a quoted command string; a newline becomes a second shell command.
- Without `--user "$(id -u):$(id -g)"`, Docker will write root-owned run directories into `benchmarks/runs/` which can be annoying to clean up.
