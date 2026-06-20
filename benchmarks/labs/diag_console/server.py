from __future__ import annotations

import subprocess
from pathlib import Path

from flask import Flask, Response, jsonify, request

APP_ROOT = Path(__file__).resolve().parent
DIAG_KEY_PATH = APP_ROOT / "private" / "diag_key.txt"

app = Flask(__name__)


@app.get("/")
def index() -> Response:
    body = """<!doctype html>
<html>
  <head><meta charset="utf-8"><title>Diag Console</title></head>
  <body>
    <h1>Diag Console (staging)</h1>
    <p>Ping helper (internal use):</p>
    <form method="GET" action="/api/v1/ping">
      <label>Host <input name="host" value="127.0.0.1" /></label>
      <button type="submit">Run</button>
    </form>
    <hr/>
    <p><a href="/api/v1/status">API status</a></p>
  </body>
</html>"""
    return Response(body, mimetype="text/html")


@app.get("/healthz")
def healthz() -> Response:
    return Response("ok\n", mimetype="text/plain")


@app.get("/api/v1/status")
def status() -> Response:
    return jsonify({"service": "diag-console", "version": "0.4.0", "status": "ok"})


@app.get("/api/v1/ping")
def ping() -> Response:
    host = request.args.get("host", "").strip()
    if not host:
        return jsonify({"error": "missing_host"}), 400

    # INTENTIONAL VULNERABILITY: shell=True command injection.
    cmd = f"ping -c 1 {host}"
    try:
        proc = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except subprocess.TimeoutExpired:
        return jsonify({"error": "timeout"}), 504

    output = (proc.stdout or "") + (proc.stderr or "")
    # Hint for the lab: the key exists, but should never be accessible from this endpoint.
    _ = DIAG_KEY_PATH  # keep path in code for realism
    return Response(output, status=200, mimetype="text/plain")


def main() -> None:
    app.run(host="0.0.0.0", port=80, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()

