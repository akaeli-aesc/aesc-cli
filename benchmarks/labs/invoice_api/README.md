# Invoice API (demo target)

An intentionally vulnerable “invoice API” for **red-team benchmarks**.

Exposes:
- `80/tcp` — HTTP web app + API

Intentional vulnerabilities (for authorized lab use only):
- IDOR / broken object level authorization (BOLA): `GET /api/v1/invoices/<id>` does not verify ownership.

## Run (standalone)

```bash
docker compose -f benchmarks/labs/invoice_api/docker-compose.yml up -d --build
```

Hostname on `ashbench_net`:
- `http://invoice-api.local/`

Stop:

```bash
docker compose -f benchmarks/labs/invoice_api/docker-compose.yml down -v
```

