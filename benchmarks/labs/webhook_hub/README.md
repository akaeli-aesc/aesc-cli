# Webhook Hub (demo target)

An intentionally vulnerable “webhook destination preview” service for **red-team benchmarks**.

Exposes:
- `80/tcp` — HTTP web app + API

Intentional vulnerabilities (for authorized lab use only):
- SSRF in `GET /api/v1/preview?url=...` (server fetches arbitrary URL)

Companion internal service:
- `metadata.local` (separate container) exposes a “release key” endpoint that should be internal-only.

## Run (standalone)

```bash
docker compose -f benchmarks/labs/webhook_hub/docker-compose.yml up -d --build
```

Hostnames on `ashbench_net`:
- `http://webhook-hub.local/`
- `http://metadata.local/`

Stop:

```bash
docker compose -f benchmarks/labs/webhook_hub/docker-compose.yml down -v
```

