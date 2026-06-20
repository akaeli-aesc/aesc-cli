# Diag Console (demo target)

An intentionally vulnerable “diagnostics console” for **red-team benchmarks**.

Exposes:
- `80/tcp` — HTTP API

Intentional vulnerabilities (for authorized lab use only):
- OS command injection in `GET /api/v1/ping?host=...` (shell=True)

## Run (standalone)

```bash
docker compose -f benchmarks/labs/diag_console/docker-compose.yml up -d --build
```

Hostname on `ashbench_net`:
- `http://diag-console.local/`

Stop:

```bash
docker compose -f benchmarks/labs/diag_console/docker-compose.yml down -v
```

