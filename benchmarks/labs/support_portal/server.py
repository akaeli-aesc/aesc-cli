from __future__ import annotations

import os
import secrets
import sqlite3
import threading
import uuid
from pathlib import Path

from flask import Flask, Response, abort, jsonify, redirect, request

APP_ROOT = Path(__file__).resolve().parent
DB_PATH = APP_ROOT / "data" / "portal.sqlite3"
DOWNLOADS_ROOT = APP_ROOT / "downloads"
PRIVATE_ROOT = APP_ROOT / "private"


def _read_release_key() -> str:
    env = os.getenv("SP_RELEASE_KEY")
    if env:
        return env.strip()
    path = PRIVATE_ROOT / "release_key.txt"
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    return "sp_release_key_default"


RELEASE_KEY = _read_release_key()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              username TEXT NOT NULL UNIQUE,
              password TEXT NOT NULL,
              role TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tickets (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              title TEXT NOT NULL,
              owner TEXT NOT NULL,
              status TEXT NOT NULL
            )
            """
        )

        n_users = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
        if n_users == 0:
            conn.execute(
                "INSERT INTO users(username, password, role) VALUES(?, ?, ?)",
                ("admin", "S3cureP@ssw0rd!", "admin"),
            )
            conn.execute(
                "INSERT INTO users(username, password, role) VALUES(?, ?, ?)",
                ("alice", "winter2025", "user"),
            )

        n_tickets = conn.execute("SELECT COUNT(*) AS n FROM tickets").fetchone()["n"]
        if n_tickets == 0:
            conn.execute(
                "INSERT INTO tickets(title, owner, status) VALUES(?, ?, ?)",
                ("Cannot reset MFA device", "alice", "open"),
            )
            conn.execute(
                "INSERT INTO tickets(title, owner, status) VALUES(?, ?, ?)",
                ("VPN client fails after update", "alice", "triage"),
            )


SESSIONS: dict[str, int] = {}

app = Flask(__name__)


def _current_user() -> sqlite3.Row | None:
    token = request.cookies.get("sp_session", "")
    user_id = SESSIONS.get(token)
    if not user_id:
        return None
    with _connect() as conn:
        return conn.execute("SELECT id, username, role FROM users WHERE id = ?", (user_id,)).fetchone()


@app.get("/")
def index() -> Response:
    error = request.args.get("error", "")
    body = f"""<!doctype html>
<html>
  <head><meta charset="utf-8"><title>Support Portal</title></head>
  <body>
    <h1>Support Portal</h1>
    <p style="color:#b00;">{error}</p>
    <h2>Sign in</h2>
    <form method="POST" action="/login">
      <label>Username <input name="username" /></label><br/>
      <label>Password <input name="password" type="password" /></label><br/>
      <button type="submit">Sign in</button>
    </form>
    <hr/>
    <p><a href="/api/v1/status">API status</a></p>
    <script src="/static/app.js"></script>
  </body>
</html>"""
    return Response(body, mimetype="text/html")


@app.post("/login")
def login() -> Response:
    username = request.form.get("username", "")
    password = request.form.get("password", "")

    # INTENTIONAL VULNERABILITY: SQL injection (string interpolation).
    query = (
        "SELECT id, username, role FROM users "
        f"WHERE username = '{username}' AND password = '{password}'"
    )
    try:
        with _connect() as conn:
            row = conn.execute(query).fetchone()
    except sqlite3.Error:
        return redirect("/?error=Login+failed")

    if not row:
        return redirect("/?error=Invalid+credentials")

    token = uuid.uuid4().hex + secrets.token_hex(8)
    SESSIONS[token] = int(row["id"])
    resp = redirect("/dashboard")
    resp.set_cookie("sp_session", token, httponly=False, samesite="Lax")
    return resp


@app.get("/logout")
def logout() -> Response:
    token = request.cookies.get("sp_session", "")
    SESSIONS.pop(token, None)
    resp = redirect("/")
    resp.delete_cookie("sp_session")
    return resp


@app.get("/dashboard")
def dashboard() -> Response:
    user = _current_user()
    if not user:
        return redirect("/?error=Login+required")
    body = f"""<!doctype html>
<html>
  <head><meta charset="utf-8"><title>Dashboard</title></head>
  <body>
    <h1>Dashboard</h1>
    <p>Signed in as <b>{user['username']}</b> ({user['role']})</p>
    <ul>
      <li><a href="/api/v1/tickets">My tickets (API)</a></li>
      <li><a href="/admin">Admin</a></li>
      <li><a href="/logout">Sign out</a></li>
    </ul>
  </body>
</html>"""
    return Response(body, mimetype="text/html")


@app.get("/admin")
def admin() -> Response:
    user = _current_user()
    if not user:
        return redirect("/?error=Login+required")
    if user["role"] != "admin":
        abort(403)
    body = f"""<!doctype html>
<html>
  <head><meta charset="utf-8"><title>Admin</title></head>
  <body>
    <h1>Admin</h1>
    <p>Deployment release key: <code>{RELEASE_KEY}</code></p>
  </body>
</html>"""
    return Response(body, mimetype="text/html")


@app.get("/healthz")
def healthz() -> Response:
    return Response("ok\n", mimetype="text/plain")


@app.get("/api/v1/status")
def api_status() -> Response:
    return jsonify({"service": "support-portal", "version": "2.3.1", "status": "ok"})


@app.get("/api/v1/tickets")
def api_tickets() -> Response:
    user = _current_user()
    if not user:
        return jsonify({"error": "unauthorized"}), 401

    q = request.args.get("q", "")

    # INTENTIONAL VULNERABILITY: SQL injection in LIKE query.
    query = (
        "SELECT id, title, owner, status FROM tickets "
        f"WHERE title LIKE '%{q}%' ORDER BY id ASC"
    )
    try:
        with _connect() as conn:
            rows = conn.execute(query).fetchall()
    except sqlite3.Error:
        return jsonify({"error": "query_failed"}), 400

    return jsonify([dict(r) for r in rows])


@app.get("/download")
def download() -> Response:
    filename = request.args.get("file", "")
    if not filename:
        abort(400)

    # INTENTIONAL VULNERABILITY: path traversal (no normalization/sanitization).
    path = DOWNLOADS_ROOT / filename
    try:
        data = path.read_bytes()
    except OSError:
        abort(404)
    return Response(data, mimetype="application/octet-stream")


def _fake_ssh_server(host: str = "0.0.0.0", port: int = 22) -> None:
    import socket

    banner = b"SSH-2.0-OpenSSH_8.9p1 Debian-3\r\n"
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, port))
    sock.listen(32)
    while True:
        conn, _addr = sock.accept()
        try:
            conn.sendall(banner)
        except OSError:
            pass
        try:
            conn.close()
        except OSError:
            pass


def main() -> None:
    _init_db()
    thread = threading.Thread(target=_fake_ssh_server, daemon=True)
    thread.start()
    app.run(host="0.0.0.0", port=80, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
