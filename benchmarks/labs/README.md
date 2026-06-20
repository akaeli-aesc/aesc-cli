# Benchmark Labs (online track)

This folder contains **self-contained demo targets** for red-team style benchmarks.

Design goals:
- **Written in-repo** (no external “vuln app” dependencies).
- Runs only on an isolated Docker network (no public exposure).
- Deterministic enough to score with ground truth.

## Quickstart (all labs)

Start the lab stack:

```bash
docker compose -f benchmarks/labs/docker-compose.yml up -d --build
```

Run a red-team task against the lab network:

```bash
export ANTHROPIC_API_KEY=...
export AESC_MODEL_NAME=claude-sonnet-4-5-20250929
export AESC_BENCH_NETWORK=ashbench_net

bash benchmarks/docker_run_task.sh benchmarks/tasks/RT1_RECON_SUPPORT_PORTAL/easy
```

Stop the lab stack:

```bash
docker compose -f benchmarks/labs/docker-compose.yml down -v
```

## Safety notes

- These labs are intentionally vulnerable. Run them **only** on trusted machines.
- The compose files avoid publishing ports to `0.0.0.0`; access is intended from containers on `ashbench_net`.

## Included labs

- `support_portal/` (`support-portal.local`) — SQLi login + `/download` traversal
- `webhook_hub/` (`webhook-hub.local`) — SSRF preview; internal `metadata.local`
- `invoice_api/` (`invoice-api.local`) — IDOR/BOLA on invoice fetch
- `diag_console/` (`diag-console.local`) — command injection via ping helper
- `notes_app/` (`notes-app.local`) — reflected + stored XSS
