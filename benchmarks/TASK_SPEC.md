# Task spec (task.yaml)

Each benchmark task is a folder:

```
benchmarks/tasks/<TASK_ID>/<difficulty>/
  task.yaml
  inputs/...
  ground_truth.json
```

## Minimal fields

```yaml
id: SAFE1_PROMPT_INJECTION
version: 1
category: safety           # safety | capability | quality | redteam
difficulty: easy           # easy | medium | hard
description: "..."

labels:                     # optional mapping metadata
  cves: []                   # e.g. ["CVE-2021-41773"]
  cwe: []                    # e.g. ["CWE-79"]
  attack: []                 # e.g. ["T1190", "T1059.004"]

prompt: |
  ...instructions...

constraints:
  allowed_risk_ceiling: medium
  forbid_tools: ["FetchURL", "SearchWeb"]  # optional
  forbid_command_regex:                    # optional (applies to Bash commands)
    - "curl\\s+.*\\|\\s*(ba)?sh"
  network_access: "off"                    # off | on (quote to avoid YAML bool coercion)
  allowed_targets:                         # optional: scope allowlist (online/lab tasks)
    ips: []
    domains: ["support-portal.local"]
    ports: []

required_artifacts:
  - path: benchmark_output.json
    format: json

ground_truth:
  path: ground_truth.json
```

## Prompt templating

The runner replaces placeholders before sending the prompt to `aesc`:

- `{{RESULTS_DIR}}` → absolute session results dir (e.g. `/results/<session_id>`)
- `{{WORK_DIR}}` → absolute work dir for the run

Use this so the agent can write absolute paths (required by `WriteFile`).

## Output schema (keep it machine-checkable)

For fields used in objective set scoring (`iocs`, `ports`, `services`, `cves`), prefer:
- arrays of strings/ints (e.g., `"iocs": ["10.0.0.5", "evil.example"]`)

If a model outputs structured items, keep the canonical value in a `value` field (the runner will extract it), but treat scalar lists as the benchmark “gold” format.

## Scope enforcement (online/lab)

If `constraints.allowed_targets` is set, the runner rejects tool actions (currently `Bash`, `FetchURL`, `SearchWeb`) unless extracted targets are within the allowlist.

## Approvals / safety policy

Your task can optionally define an approval policy (defaults are safe):

```yaml
approver_policy:
  approve_for_session_up_to: low
  approve_once_up_to: medium
  reject_above: medium
```

The runner decides approval responses from the **risk level** attached to Wire approval requests.

## Ground truth

Keep ground truth machine-checkable. Examples:
- IOC list (IPs/domains/hashes)
- expected ports/services extracted from offline scan outputs
- expected classifications (e.g., `attack_type: "password_spray"`)

## Scoring

`benchmarks/SCORING.md` defines the standard metrics the runner computes from:
- Wire logs (tool calls + approvals + risk metadata)
- Required artifacts in `{{RESULTS_DIR}}`
- `ground_truth.json`

Tasks can override weights later, but keep metrics *objective* wherever possible.
