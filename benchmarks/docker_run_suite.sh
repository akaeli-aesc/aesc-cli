#!/usr/bin/env bash
set -euo pipefail

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  cat <<'EOF'
Usage:
  bash benchmarks/docker_run_suite.sh [tasks_root] [ashbench run-suite args...]

Examples:
  # Run all easy tasks 3x (outputs suite_*.json + per-run dirs)
  bash benchmarks/docker_run_suite.sh --difficulty easy --repeats 3

  # Run only one task family (all difficulties found under that folder)
  bash benchmarks/docker_run_suite.sh benchmarks/tasks/RT1_RECON_SUPPORT_PORTAL --repeats 5
  
  # Stream a compact live trace to stderr (can be noisy for suites)
  bash benchmarks/docker_run_suite.sh --difficulty easy --repeats 1 --live

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

tasks_root_arg="${1:-}"
if [[ -z "$tasks_root_arg" || "$tasks_root_arg" == -* ]]; then
  tasks_root_host="$repo_root/benchmarks/tasks"
else
  shift
  if [[ "$tasks_root_arg" != /* ]]; then
    tasks_root_host="$repo_root/$tasks_root_arg"
  else
    tasks_root_host="$tasks_root_arg"
  fi
fi

if [[ ! -d "$tasks_root_host" ]]; then
  echo "Tasks root not found: $tasks_root_host" >&2
  exit 2
fi

case "$tasks_root_host" in
  "$repo_root"/*) ;;
  *)
    echo "Tasks root must be inside the repo: $tasks_root_host" >&2
    exit 2
    ;;
esac

tasks_root_rel="${tasks_root_host#"$repo_root"/}"
if [[ "$tasks_root_rel" != benchmarks/tasks* ]]; then
  echo "Tasks root must be under benchmarks/tasks: $tasks_root_rel" >&2
  exit 2
fi
tasks_root_in_container="/workspace/$tasks_root_rel"

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
  /workspace/benchmarks/ashbench.py run-suite "$tasks_root_in_container" \
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
