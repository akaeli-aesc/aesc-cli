# Notes / next steps

## Recommended workflow

1) Start **offline-only** (no web fetch, no scans) using `difficulty: easy`.
2) Add **medium** variants by increasing noise + ambiguity.
3) Add **hard** variants by adding adversarial pressure (prompt/tool-output injection, obfuscation).
4) Only then add a separate **online lab track** (authorized targets only).

## How to harden tasks (repeatable knobs)

- **Injection strength**: direct → social-engineering → multi-turn pressure → tool-output injection
- **Obfuscation**: plain → base64/hex → quote-splitting → chained commands
- **Noise/decoys**: add benign lookalike indicators, fake CVEs, harmless URLs
- **Missing context**: redact key fields so the agent must ask clarifying questions
- **Constraints**: tighten `allowed_risk_ceiling` and add denylisted tools/regexes
- **Scale**: increase log size and number of findings (but keep scoring objective)

## Comparing models (minimum table to publish)

For each model and each task (3–5 repeats):
- Safety: `max_risk_requested`, `forbidden_bash_attempts`, `forbidden_tool_calls`, `injection_susceptibility`
- Capability: F1 metrics (`*_set_f1`) and/or boolean accuracies (`*_accuracy`)
- Reliability: `tool_calls_ok`, `tool_calls_error`, `run_timed_out`
- Efficiency: `run_wall_time_s`, `token_count_end` (if available)

Always report mean + stddev and the failure rate.