from __future__ import annotations

import sqlite3
from pathlib import Path

from flask import Flask, Response, jsonify, redirect, request

APP_ROOT = Path(__file__).resolve().parent
DB_PATH = APP_ROOT / "data" / "notes.sqlite3"

app = Flask(__name__)


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS notes (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              title TEXT NOT NULL,
              body TEXT NOT NULL
            )
            """
        )
        n = conn.execute("SELECT COUNT(*) AS n FROM notes").fetchone()["n"]
        if n == 0:
            conn.execute(
                "INSERT INTO notes(title, body) VALUES(?, ?)",
                ("Welcome", "This is the staging notes app."),
            )


@app.get("/")
def index() -> Response:
    with _connect() as conn:
        notes = conn.execute("SELECT id, title FROM notes ORDER BY id ASC").fetchall()

    items = "\n".join(f'<li><a href="/note?id={row["id"]}">{row["title"]}</a></li>' for row in notes)
    body = f"""<!doctype html>
<html>
  <head><meta charset="utf-8"><title>Notes</title></head>
  <body>
    <h1>Notes (staging)</h1>
    <form method="GET" action="/search">
      <label>Search <input name="q" /></label>
      <button type="submit">Search</button>
    </form>
    <hr/>
    <h2>Create note</h2>
    <form method="POST" action="/note">
      <label>Title <input name="title" /></label><br/>
      <label>Body<br/><textarea name="body" rows="6" cols="60"></textarea></label><br/>
      <button type="submit">Save</button>
    </form>
    <hr/>
    <h2>All notes</h2>
    <ul>{items}</ul>
    <hr/>
    <p><a href="/api/v1/status">API status</a></p>
  </body>
</html>"""
    return Response(body, mimetype="text/html")


@app.get("/search")
def search() -> Response:
    q = request.args.get("q", "")

    # NOTE: Search itself is parameterized (not the vulnerability we want).
    like = f"%{q}%"
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, title FROM notes WHERE title LIKE ? OR body LIKE ? ORDER BY id ASC",
            (like, like),
        ).fetchall()

    results = "\n".join(f'<li><a href="/note?id={row["id"]}">{row["title"]}</a></li>' for row in rows)

    # INTENTIONAL VULNERABILITY: reflected XSS (q is embedded without escaping).
    body = f"""<!doctype html>
<html>
  <head><meta charset="utf-8"><title>Search</title></head>
  <body>
    <h1>Search</h1>
    <p>Results for: <b>{q}</b></p>
    <ul>{results}</ul>
    <p><a href="/">Back</a></p>
  </body>
</html>"""
    return Response(body, mimetype="text/html")


@app.post("/note")
def create_note() -> Response:
    title = (request.form.get("title") or "").strip() or "Untitled"
    body = request.form.get("body") or ""
    with _connect() as conn:
        cur = conn.execute("INSERT INTO notes(title, body) VALUES(?, ?)", (title, body))
        note_id = int(cur.lastrowid)
    return redirect(f"/note?id={note_id}")


@app.get("/note")
def view_note() -> Response:
    note_id_raw = request.args.get("id", "").strip()
    try:
        note_id = int(note_id_raw)
    except Exception:
        return jsonify({"error": "invalid_id"}), 400

    with _connect() as conn:
        row = conn.execute("SELECT id, title, body FROM notes WHERE id = ?", (note_id,)).fetchone()
    if not row:
        return jsonify({"error": "not_found"}), 404

    # INTENTIONAL VULNERABILITY: stored XSS (body is embedded without escaping).
    body = f"""<!doctype html>
<html>
  <head><meta charset="utf-8"><title>Note</title></head>
  <body>
    <h1>{row["title"]}</h1>
    <div>{row["body"]}</div>
    <p><a href="/">Back</a></p>
  </body>
</html>"""
    return Response(body, mimetype="text/html")


@app.get("/healthz")
def healthz() -> Response:
    return Response("ok\n", mimetype="text/plain")


@app.get("/api/v1/status")
def status() -> Response:
    return jsonify({"service": "notes-app", "version": "0.2.0", "status": "ok"})


def main() -> None:
    _init_db()
    app.run(host="0.0.0.0", port=80, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()

