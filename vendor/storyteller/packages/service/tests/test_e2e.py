"""End to end on a real stack: demo consumer (SQLite) + fake LLM + storyteller service + snippet via Playwright."""
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[3]
SITE = ROOT / "examples" / "demo-site"


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def wait_http(url, timeout=20):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if httpx.get(url, timeout=1).status_code < 500:
                return
        except Exception:
            time.sleep(0.2)
    raise RuntimeError(f"{url} not up")


@pytest.fixture(scope="module")
def stack(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("st")
    consumer_port, llm_port, svc_port = free_port(), free_port(), free_port()
    env = {**os.environ, "STORYTELLER_SECRET": "testsecret", "STORYTELLER_ADMIN_TOKEN": "admintoken", "PYTHONPATH": str(ROOT), "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"}
    db = tmp / "consumer.db"
    consumer_code = f"""
import sys; sys.path.insert(0, r'{ROOT / "packages" / "adapters" / "fastapi"}')
from fastapi import FastAPI
from storyteller_adapter import make_router
app = FastAPI(); app.include_router(make_router(db_path=r'{db}'))
"""
    (tmp / "consumer_app.py").write_text(consumer_code)
    cfg = {
        "site": {"key": "testkey", "brief_file": str(ROOT / "examples" / "brief.example.md")},
        "recording": {"default_enabled": True, "idle_timeout_minutes": 10},
        "llm": {"provider": "openai_compatible", "base_url": f"http://127.0.0.1:{llm_port}/v1", "model": "fake"},
        "consumer": {"base_url": f"http://127.0.0.1:{consumer_port}"},
        "service": {"prefix": "/storyteller", "buffer_dir": str(tmp / "data"), "finalize_every_seconds": 1},
    }
    import yaml

    (tmp / "storyteller.yaml").write_text(yaml.safe_dump(cfg))
    procs = [
        subprocess.Popen([sys.executable, "-m", "uvicorn", "consumer_app:app", "--port", str(consumer_port)], cwd=tmp, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL),
        subprocess.Popen([sys.executable, "-m", "uvicorn", "examples.fake_llm:app", "--port", str(llm_port)], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL),
    ]
    wait_http(f"http://127.0.0.1:{consumer_port}/internal/storyteller/recent")
    wait_http(f"http://127.0.0.1:{llm_port}/docs")
    procs.append(subprocess.Popen([sys.executable, "-m", "storyteller.cli", "serve", "--config", str(tmp / "storyteller.yaml"), "--port", str(svc_port)], cwd=tmp, env=env, stdout=subprocess.DEVNULL, stderr=open(tmp / "svc.log", "w")))
    wait_http(f"http://127.0.0.1:{svc_port}/storyteller/health")
    yield {"consumer": consumer_port, "svc": svc_port, "tmp": tmp}
    for p in procs:
        p.terminate()


def test_health_and_hooks(stack):
    h = httpx.get(f"http://127.0.0.1:{stack['svc']}/storyteller/health").json()
    assert h["ok"] and h["consumer"]["check"]["ok"], h
    assert h["recording_enabled"] is True


def test_kill_switch(stack):
    base = f"http://127.0.0.1:{stack['svc']}/storyteller"
    assert httpx.post(f"{base}/recording", json={"enabled": False}).status_code == 401  # needs admin token
    r = httpx.post(f"{base}/recording", json={"enabled": False}, headers={"Authorization": "Bearer admintoken"})
    assert r.json() == {"enabled": False}
    assert httpx.get(f"{base}/recording").json() == {"enabled": False}
    assert httpx.post(f"{base}/events", json={"siteKey": "testkey", "visitId": "x", "events": []}).status_code == 403
    httpx.post(f"{base}/recording", json={"enabled": True}, headers={"Authorization": "Bearer admintoken"})
    assert httpx.get(f"{base}/recording").json() == {"enabled": True}


def test_browser_visit_becomes_a_story_in_consumer_db(stack):
    from playwright.sync_api import sync_playwright

    import threading
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    # static demo site on its own port; snippet endpoint points at the service (cross-origin, so CORS is exercised)
    class H(SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(SITE), **k)

        def log_message(self, *a):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
    site_port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    svc = f"http://127.0.0.1:{stack['svc']}/storyteller"
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--no-proxy-server"])
        page = b.new_page()
        page.add_init_script(f"window.__ST_ENDPOINT = '{svc}'; window.__ST_KEY = 'testkey';")
        page.goto(f"http://127.0.0.1:{site_port}/signup.html")
        page.wait_for_function("window.storyteller && window.storyteller.ids().visitId")
        page.click("#email")
        page.keyboard.type("a@b.co")
        page.click("#company")
        page.wait_for_timeout(300)
        page.click("#submit")
        page.wait_for_timeout(1500)
        ids = page.evaluate("storyteller.ids()")
        page.evaluate("storyteller.end()")
        page.wait_for_timeout(800)
        b.close()
    httpd.shutdown()
    # finalizer runs every 1s; visit_end makes it finalize ~5s later
    deadline = time.time() + 25
    stories = []
    while time.time() < deadline:
        stories = [s for s in httpx.get(f"http://127.0.0.1:{stack['consumer']}/internal/storyteller/recent").json() if s["visit_id"] == ids["visitId"]]
        if stories:
            break
        time.sleep(1)
    assert stories, (stack["tmp"] / "svc.log").read_text()[-3000:]
    s = stories[0]
    assert s["schema_version"] == "1"
    assert "Company name is required" in s["timeline_text"]
    assert s["outcome"]["label"] == "abandoned_signup"
    assert s["history_available"] is False
    assert s["provenance"]["model"] == "fake-llm"
    # visitor memory now exists → a second visit would be "returning"
    v = httpx.get(f"http://127.0.0.1:{stack['consumer']}/internal/storyteller/visitors/{ids['visitorId']}")
    assert v.status_code == 401  # unsigned requests are rejected
    ui = httpx.get(f"http://127.0.0.1:{stack['consumer']}/internal/storyteller/ui")
    assert ui.status_code == 200 and "Storyteller" in ui.text


def test_second_visit_sees_history(stack):
    """Regenerate a story for a known visitor via the admin route: the read hook must return memory."""
    import hashlib, hmac
    rec = json.load(open(ROOT / "fixtures" / "success_rage.json"))
    svc = f"http://127.0.0.1:{stack['svc']}/storyteller"
    hdr = {"Authorization": "Bearer admintoken"}
    r1 = httpx.post(f"{svc}/visits/first/regenerate", json={"recording": rec}, headers=hdr, timeout=30).json()
    assert r1["delivered"] and r1["story"]["history_available"] is False
    # add a high-weight fact through the consumer's convenience route, then regenerate again
    vid = rec["visitorId"]
    httpx.post(f"http://127.0.0.1:{stack['consumer']}/internal/storyteller/visitors/{vid}/facts", json={"text": "This is my friend Sam", "weight": "high"})
    rec2 = {**rec, "visitId": "second-visit"}
    r2 = httpx.post(f"{svc}/visits/second/regenerate", json={"recording": rec2}, headers=hdr, timeout=30).json()
    s = r2["story"]
    assert s["history_available"] is True
    assert [t["visit_id"] for t in s["trajectory"]][-2:] == [rec["visitId"], "second-visit"]
    assert "returning visitor" in s["visitor_summary"]
    # and a correctly signed read returns the memory
    ts = str(int(time.time()))
    sig = "v1=" + hmac.new(b"testsecret", f"{ts}.".encode(), hashlib.sha256).hexdigest()
    v = httpx.get(f"http://127.0.0.1:{stack['consumer']}/internal/storyteller/visitors/{vid}", headers={"X-Storyteller-Timestamp": ts, "X-Storyteller-Signature": sig}).json()
    assert v["facts"][0]["text"] == "This is my friend Sam" and v["facts"][0]["weight"] == "high"
    assert len(v["trajectory"]) == 2
