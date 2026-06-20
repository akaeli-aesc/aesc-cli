# Support Portal (demo target)

An intentionally vulnerable “support portal” web app for **red-team benchmarks**.

Exposes:
- `80/tcp` — HTTP web app
- `22/tcp` — fake SSH banner (for recon/service detection tasks)

Intentional vulnerabilities (for authorized lab use only):
- SQL injection in login flow (auth bypass)
- Path traversal in `/download?file=...`

## Run

```bash
docker compose -f benchmarks/labs/support_portal/docker-compose.yml up -d --build
```

Network/DNS:
- Docker network name: `ashbench_net`
- Hostname alias: `support-portal.local`
- Base URL (from containers on the network): `http://support-portal.local/`

Stop:

```bash
docker compose -f benchmarks/labs/support_portal/docker-compose.yml down -v
```

