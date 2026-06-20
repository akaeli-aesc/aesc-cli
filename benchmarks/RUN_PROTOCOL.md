# Run protocol (fair model comparisons)

To compare models, keep *everything except the model* constant:

## Fix the environment

- Same `aesc` commit + Docker image (if using Docker)
- Same task pack versions (`task.yaml` + `inputs/` + `ground_truth.json`)
- Same tool availability and timeouts
- Same approval policy (risk ceiling + tool denylist)

## Fix LLM parameters

- Same temperature/top_p (or provider defaults, but document them)
- Same context window limits
- Same thinking mode setting

## Repeats and variance

Run each task **3–5 times per model** and report:
- mean + stddev for each metric
- failure rate (timeouts, missing artifacts)

## Offline-first tasks

Prefer offline, deterministic inputs (logs, scan outputs, code snippets) for:
- reproducibility
- safety (no accidental scanning)
- stable scoring

Use live lab targets only for a separate “online” track with strict authorization.

## Reporting

Always publish:
- the task pack (inputs + ground truth)
- the runner version
- the exact model identifiers (e.g., `claude-sonnet-4-5-20250929`)

