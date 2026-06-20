from __future__ import annotations

import re
from urllib.parse import urlsplit

import requests
from flask import Flask, Response, jsonify, request

app = Flask(__name__)


@app.get("/")
def index() -> Response:
    body = """<!doctype html>
<html>
  <head><meta charset="utf-8"><title>Webhook Hub</title></head>
  <body>
    <h1>Webhook Hub (staging)</h1>
    <p>Destination preview (for support triage):</p>
    <form method="GET" action="/api/v1/preview">
      <label>URL <input name="url" size="60" placeholder="http://example.local/..." /></label>
      <button type="submit">Preview</button>
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
    return jsonify({"service": "webhook-hub", "version": "1.7.0", "status": "ok"})


@app.get("/api/v1/preview")
def preview() -> Response:
    url = request.args.get("url", "").strip()
    if not url:
        return jsonify({"error": "missing_url"}), 400

    # Minimal parsing/validation (INTENTIONAL: does not restrict internal hosts).
    try:
        parsed = urlsplit(url)
    except Exception:
        return jsonify({"error": "invalid_url"}), 400

    if parsed.scheme not in ("http", "https"):
        return jsonify({"error": "unsupported_scheme"}), 400

    # Prevent extremely large responses (still SSRF).
    max_bytes = 8 * 1024
    try:
        r = requests.get(
            url,
            timeout=3,
            allow_redirects=True,
            headers={"User-Agent": "WebhookHub/1.7 preview"},
        )
        content = r.content[:max_bytes]
    except requests.RequestException as e:
        return jsonify({"error": "fetch_failed", "detail": re.sub(r"\s+", " ", str(e))[:200]}), 502

    return Response(
        content,
        status=r.status_code,
        mimetype=(r.headers.get("content-type") or "text/plain").split(";", 1)[0],
    )


def main() -> None:
    app.run(host="0.0.0.0", port=80, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()

