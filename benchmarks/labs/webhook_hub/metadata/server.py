from __future__ import annotations

from pathlib import Path

from flask import Flask, Response, jsonify

APP_ROOT = Path(__file__).resolve().parent
RELEASE_KEY_PATH = APP_ROOT / "private" / "release_key.txt"

app = Flask(__name__)


@app.get("/healthz")
def healthz() -> Response:
    return Response("ok\n", mimetype="text/plain")


@app.get("/latest/release-key")
def release_key() -> Response:
    value = RELEASE_KEY_PATH.read_text(encoding="utf-8").strip()
    return Response(value + "\n", mimetype="text/plain")


@app.get("/api/v1/status")
def status() -> Response:
    return jsonify({"service": "metadata", "status": "ok"})


def main() -> None:
    app.run(host="0.0.0.0", port=80, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()

