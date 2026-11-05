"""Frontend serving + security tests (server-side)."""
import os
import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
for sub in ("api", "agents", "analytics", "rag", "database", "ml"):
    sys.path.append(str(ROOT / "src" / sub))
os.environ.setdefault("JWT_SECRET", "test-secret-" + "x" * 40)

import main  # noqa: E402

FRONT = ROOT / "frontend"


@pytest.fixture(scope="module")
def client():
    with TestClient(main.app) as c:
        yield c


def test_index_is_served_with_security_headers(client):
    r = client.get("/")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    csp = r.headers["content-security-policy"]
    assert "script-src 'self'" in csp and "frame-ancestors 'none'" in csp and "unsafe-inline" not in csp
    assert r.headers["x-frame-options"] == "DENY" and r.headers["x-content-type-options"] == "nosniff"


def test_static_assets_are_served(client):
    js = client.get("/static/js/app.js")
    assert js.status_code == 200 and "javascript" in js.headers["content-type"]
    assert client.get("/static/css/styles.css").status_code == 200


def test_static_path_traversal_is_blocked(client):
    for p in ("/static/..%2f.env", "/static/../.env", "/static/%2e%2e/src/api/main.py"):
        assert client.get(p).status_code in (400, 404)


def test_api_responses_are_not_cached(client):
    assert client.get("/api/v1/health").headers["cache-control"] == "no-store"


def test_api_docs_still_work_without_frontend_csp(client):
    r = client.get("/docs")
    assert r.status_code == 200 and "content-security-policy" not in r.headers


def test_index_has_no_inline_scripts_or_styles():
    html = (FRONT / "index.html").read_text(encoding="utf-8")
    assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html)       # inline <script> nahi
    assert "<style" not in html and ' style="' not in html and "onclick=" not in html


def test_frontend_code_avoids_dangerous_apis():
    banned = ["innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function", "localStorage"]
    for f in FRONT.rglob("*.js"):
        text = re.sub(r"//.*", "", f.read_text(encoding="utf-8"))     # comments ignore karo, sirf code dekho
        for b in banned:
            assert b not in text, f"{f.name} uses {b}"


def test_frontend_has_no_external_urls():
    for f in list(FRONT.rglob("*.js")) + list(FRONT.rglob("*.css")) + [FRONT / "index.html"]:
        assert not re.search(r"https?://(?!www\.w3\.org)", f.read_text(encoding="utf-8")), f.name