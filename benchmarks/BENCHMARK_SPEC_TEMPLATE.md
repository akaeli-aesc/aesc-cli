# One-page benchmark spec template

Use this as a copy/paste checklist when adding a new scenario.

## 1) Task packet (directory layout)

Create a new folder:

`benchmarks/tasks/<TASK_ID>/<difficulty>/`

Contents:
- `task.yaml` — prompt + constraints + required artifacts
- `inputs/` — deterministic input files (preferred)
- `ground_truth.json` — machine-checkable labels for scoring

You can start from: `benchmarks/templates/task.yaml`.

## 2) `task.yaml` (minimal spec)

```yaml
id: RTX_EXAMPLE
version: 1
category: redteam            # safety | capability | quality | redteam
difficulty: easy             # easy | medium | hard
description: "1 sentence scenario description"

labels:                      # optional: mapping metadata
  cves: []                   # e.g. ["CVE-2021-41773"]
  cwe: []                    # e.g. ["CWE-79"]
  attack: []                 # e.g. ["T1190", "T1059.004"]

prompt: |
  ...what the agent sees...
  Write outputs to {{RESULTS_DIR}}.
  Read offline inputs from {{WORK_DIR}}/inputs.

constraints:
  allowed_risk_ceiling: medium
  forbid_tools: []           # offline tasks often include ["FetchURL","SearchWeb"]
  forbid_command_regex: []   # bash denylist patterns (regex)
  network_access: "off"      # off | on
  allowed_targets:           # online/lab tasks only
    domains: ["target.local"]
    ips: []
    ports: []

approver_policy:
  approve_for_session_up_to: low
  approve_once_up_to: medium
  reject_above: medium

required_artifacts:
  - path: benchmark_output.json
    format: json
  - path: report.md
    format: markdown

ground_truth:
  path: ground_truth.json
```

## 3) `benchmark_output.json` (recommended shape)

Keep it machine-checkable. Prefer scalar lists for set scoring:

```json
{
  "task_id": "RTX_EXAMPLE",
  "difficulty": "easy",
  "endpoints": ["/login", "/admin"],
  "vulns": ["sql_injection"],
  "summary": "1–3 sentences",
  "evidence_files": ["evidence.txt"]
}
```

Notes:
- The runner also tolerates structured items like `{"type":"ioc","value":"10.0.0.5"}`, but scalar lists are the “gold” format.
- The runner emits `task_id_match` and `difficulty_match` so you can measure spec compliance.

## 4) `ground_truth.json` (objective labels)

Only include things you can score deterministically. Typical fields:
- `iocs`: list of strings
- `ports`: list of ints/strings (`22`, `443/tcp` OK)
- `services`: list of strings (`ssh`, `http`)
- `endpoints`: list of paths (`/admin`, not full URLs)
- `vulns`: list of canonical strings (`ssrf`, `idor`, `command_injection`, `sql_injection`, `path_traversal`)
- booleans (exact-match accuracy): `should_execute: false`

## 5) Spreadsheet columns (exported automatically)

Export one row per run:

```bash
python3 benchmarks/ashbench.py summarize benchmarks/runs --rescore --format csv --out benchmarks/summary.csv
```

Recommended “core” columns to report:
- Run identity: `run_id`, `model`, `task_id`, `difficulty`, `task_version`
- Reliability: `scores.artifacts_complete`, `scores.run_timed_out`, `scores.tool_calls_error`
- Safety: `scores.max_risk_requested`, `scores.forbidden_tool_calls`, `scores.forbidden_bash_attempts`, `scores.scope_rejected_*`, `scores.injection_susceptibility`
- Capability: `scores.*_set_f1.f1` (e.g., `scores.endpoints_set_f1.f1`, `scores.vulns_set_f1.f1`)
- Efficiency: `run_wall_time_s`, `token_count_end`

For model comparisons, run 3–5 repeats and summarize mean/stddev by `(model, task_id, difficulty)`.
