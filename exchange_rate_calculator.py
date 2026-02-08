#!/usr/bin/env python3

"""Local server for the GitHub Pages build.

The production demo is served via GitHub Pages from `docs/`.
This Flask app exists only to run the same static build locally.

Routes:
- GET /                 -> docs/index.html
- GET /assets/...       -> docs/assets/...
- GET /data/...         -> docs/data/...

No user data is stored server-side.
"""

from __future__ import annotations

import os
from pathlib import Path

from flask import Flask, abort, send_from_directory


DOCS_DIR = Path(__file__).resolve().parent / "docs"

# Disable Flask's default /static mapping; we serve from docs/ instead.
app = Flask(__name__, static_folder=None)


@app.get("/")
def index() -> object:
    return send_from_directory(DOCS_DIR, "index.html")


@app.get("/<path:subpath>")
def docs_files(subpath: str) -> object:
    # Basic existence check to return 404 instead of a 500.
    if not (DOCS_DIR / subpath).exists():
        abort(404)
    return send_from_directory(DOCS_DIR, subpath)


if __name__ == "__main__":
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "5000"))
    debug = os.getenv("DEBUG", "").strip() in {"1", "true", "True", "yes", "YES"}
    app.run(host=host, port=port, debug=debug)
