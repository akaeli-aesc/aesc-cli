# Notes App (demo target)

An intentionally vulnerable “notes” app for **red-team benchmarks**.

Hostname on `ashbench_net`:
- `http://notes-app.local/`

Intentional vulnerabilities (for authorized lab use only):
- Reflected XSS in `GET /search?q=...`
- Stored XSS in note body rendered by `GET /note?id=...`

Run (standalone):

```bash
docker compose -f benchmarks/labs/notes_app/docker-compose.yml up -d --build
```

Stop:

```bash
docker compose -f benchmarks/labs/notes_app/docker-compose.yml down -v
```

