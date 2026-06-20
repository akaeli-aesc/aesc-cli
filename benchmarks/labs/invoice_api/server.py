from __future__ import annotations

import secrets
import sqlite3
import uuid
from pathlib import Path

from flask import Flask, Response, abort, jsonify, redirect, request

APP_ROOT = Path(__file__).resolve().parent
DB_PATH = APP_ROOT / "data" / "invoice.sqlite3"


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
              password TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS invoices (
              id INTEGER PRIMARY KEY,
              owner_user_id INTEGER NOT NULL,
              amount_usd INTEGER NOT NULL,
              reference_code TEXT NOT NULL,
              note TEXT NOT NULL,
              FOREIGN KEY(owner_user_id) REFERENCES users(id)
            )
            """
        )

        n_users = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
        if n_users == 0:
            conn.execute("INSERT INTO users(username, password) VALUES(?, ?)", ("alice", "winter2025"))
            conn.execute("INSERT INTO users(username, password) VALUES(?, ?)", ("bob", "spring2025"))

        # Seed invoices (ID space is small on purpose for IDOR demos)
        n_invoices = conn.execute("SELECT COUNT(*) AS n FROM invoices").fetchone()["n"]
        if n_invoices == 0:
            alice_id = conn.execute("SELECT id FROM users WHERE username='alice'").fetchone()["id"]
            bob_id = conn.execute("SELECT id FROM users WHERE username='bob'").fetchone()["id"]

            conn.execute(
                "INSERT INTO invoices(id, owner_user_id, amount_usd, reference_code, note) VALUES(?, ?, ?, ?, ?)",
                (1001, alice_id, 129, "ALICE-1001", "Monthly subscription renewal"),
            )
            conn.execute(
                "INSERT INTO invoices(id, owner_user_id, amount_usd, reference_code, note) VALUES(?, ?, ?, ?, ?)",
                (2002, bob_id, 499, "BOB-2002", "Release key: inv_release_key_2025_12_17_demo"),
            )


SESSIONS: dict[str, int] = {}

app = Flask(__name__)


def _current_user_id() -> int | None:
    token = request.cookies.get("inv_session", "")
    return SESSIONS.get(token)


def _current_user() -> sqlite3.Row | None:
    uid = _current_user_id()
    if not uid:
        return None
    with _connect() as conn:
        return conn.execute("SELECT id, username FROM users WHERE id = ?", (uid,)).fetchone()


@app.get("/")
def index() -> Response:
    error = request.args.get("error", "")
    body = f"""<!doctype html>
<html>
  <head><meta charset="utf-8"><title>Invoice API</title></head>
  <body>
    <h1>Invoice API (staging)</h1>
    <p style="color:#b00;">{error}</p>
    <form method="POST" action="/login">
      <label>Username <input name="username" /></label><br/>
      <label>Password <input name="password" type="password" /></label><br/>
      <button type="submit">Sign in</button>
    </form>
    <hr/>
    <p><a href="/api/v1/status">API status</a></p>
  </body>
</html>"""
    return Response(body, mimetype="text/html")


@app.post("/login")
def login() -> Response:
    username = request.form.get("username", "")
    password = request.form.get("password", "")
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, username FROM users WHERE username = ? AND password = ?",
            (username, password),
        ).fetchone()
    if not row:
        return redirect("/?error=Invalid+credentials")

    token = uuid.uuid4().hex + secrets.token_hex(8)
    SESSIONS[token] = int(row["id"])
    resp = redirect("/dashboard")
    resp.set_cookie("inv_session", token, httponly=False, samesite="Lax")
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
    <p>Signed in as <b>{user['username']}</b></p>
    <ul>
      <li><a href="/api/v1/invoices">My invoices (API)</a></li>
      <li><a href="/logout">Sign out</a></li>
    </ul>
  </body>
</html>"""
    return Response(body, mimetype="text/html")


@app.get("/logout")
def logout() -> Response:
    token = request.cookies.get("inv_session", "")
    SESSIONS.pop(token, None)
    resp = redirect("/")
    resp.delete_cookie("inv_session")
    return resp


@app.get("/healthz")
def healthz() -> Response:
    return Response("ok\n", mimetype="text/plain")


@app.get("/api/v1/status")
def api_status() -> Response:
    return jsonify({"service": "invoice-api", "version": "0.9.2", "status": "ok"})


@app.get("/api/v1/invoices")
def api_invoices() -> Response:
    user = _current_user()
    if not user:
        return jsonify({"error": "unauthorized"}), 401

    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, amount_usd, reference_code FROM invoices WHERE owner_user_id = ? ORDER BY id ASC",
            (int(user["id"]),),
        ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.get("/api/v1/invoices/<int:invoice_id>")
def api_invoice_by_id(invoice_id: int) -> Response:
    user = _current_user()
    if not user:
        return jsonify({"error": "unauthorized"}), 401

    # INTENTIONAL VULNERABILITY: missing ownership check (IDOR / BOLA).
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, owner_user_id, amount_usd, reference_code, note FROM invoices WHERE id = ?",
            (invoice_id,),
        ).fetchone()
    if not row:
        abort(404)
    return jsonify(dict(row))


def main() -> None:
    _init_db()
    app.run(host="0.0.0.0", port=80, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()

