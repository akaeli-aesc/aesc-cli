#!/usr/bin/env bash
set -euo pipefail

if [[ "${1:-}" == "" || "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  cat <<'EOF'
Usage:
  bash benchmarks/docker_run_task.sh <task_dir> [ashbench args...]

Examples:
  bash benchmarks/docker_run_task.sh benchmarks/tasks/SAFE1_PROMPT_INJECTION/easy
  bash benchmarks/docker_run_task.sh benchmarks/tasks/CAP3_SCAN_OUTPUT_TRIAGE/easy --timeout-s 900
  bash benchmarks/docker_run_task.sh benchmarks/tasks/RT2_WEB_ENUM_SUPPORT_PORTAL/easy --live

Env overrides:
  AESC_BENCH_IMAGE      Docker image tag (default: ash:bench)
  AESC_BENCH_OUT_ROOT   Host output dir (default: benchmarks/runs)
  AESC_BENCH_NETWORK    Docker network name (optional; required for lab tasks)
EOF
  exit 2
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
image="${AESC_BENCH_IMAGE:-ash:bench}"
out_root_host="${AESC_BENCH_OUT_ROOT:-benchmarks/runs}"

task_arg="$1"
shift

if [[ "$task_arg" != /* ]]; then
  task_host="$repo_root/$task_arg"
else
  task_host="$task_arg"
fi

if [[ ! -d "$task_host" ]]; then
  echo "Task directory not found: $task_host" >&2
  exit 2
fi

case "$task_host" in
  "$repo_root"/*) ;;
  *)
    echo "Task directory must be inside the repo: $task_host" >&2
    exit 2
    ;;
esac

task_rel="${task_host#"$repo_root"/}"
if [[ "$task_rel" != benchmarks/tasks/* ]]; then
  echo "Task directory must be under benchmarks/tasks/: $task_rel" >&2
  exit 2
fi
task_in_container="/workspace/$task_rel"

mkdir -p "$repo_root/$out_root_host"

network_args=()
if [[ -n "${AESC_BENCH_NETWORK:-}" ]]; then
  network_args+=(--network "$AESC_BENCH_NETWORK")
fi

set +e
run_out="$(
  docker run --rm -i \
  --user "$(id -u):$(id -g)" \
  "${network_args[@]}" \
  -e ANTHROPIC_API_KEY -e AESC_MODEL_NAME \
  -e HOME=/tmp \
  -v "$repo_root/benchmarks/ashbench.py:/workspace/benchmarks/ashbench.py:ro" \
  -v "$repo_root/benchmarks/tasks:/workspace/benchmarks/tasks:ro" \
  -v "$repo_root/$out_root_host:/outputs" \
  --entrypoint /app/.venv/bin/python \
  "$image" \
  /workspace/benchmarks/ashbench.py run-task "$task_in_container" \
  --out-root /outputs \
  --ash-cmd "/app/.venv/bin/ash" \
  "$@"
)"
status=$?
set -e

if [[ $status -ne 0 ]]; then
  if [[ -n "${run_out:-}" ]]; then
    printf '%s\n' "$run_out"
  fi
  exit "$status"
fi

run_line="$(printf '%s\n' "$run_out" | awk 'NF{last=$0} END{print last}')"
if [[ "$run_line" == /outputs/* ]]; then
  echo "$repo_root/$out_root_host/${run_line#/outputs/}"
else
  echo "$run_line"
fi
