"""
Record synthetic visits of the demo site with the real snippet, via Playwright.

The snippet POSTs to /storyteller/events exactly as it would in production; we
intercept those requests and write each visit to fixtures/<name>.json in the
same shape the service buffers.

Usage: python examples/record_fixtures.py [--fast]
"""
from __future__ import annotations

import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "examples" / "demo-site"
OUT = ROOT / "fixtures"
FAST = "--fast" in sys.argv
SCALE = 0.15 if FAST else 1.0


def wait(page: Page, seconds: float) -> None:
    page.wait_for_timeout(int(seconds * 1000 * SCALE))


class Collector:
    """Serves the demo site and the two snippet-facing routes on a real local port, so that
    keepalive requests sent at page unload are delivered (Playwright's route interception drops them)."""

    def __init__(self) -> None:
        self.chunks: list[dict] = []
        self.lock = threading.Lock()
        col = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):  # quiet
                pass

            def _send(self, code, body=b"", ctype="application/json"):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if body:
                    self.wfile.write(body)

            def do_GET(self):
                path = self.path.split("?", 1)[0]
                if path == "/storyteller/recording":
                    return self._send(200, b'{"enabled": true}')
                file = SITE / path.lstrip("/")
                if file.is_file():
                    ctype = "text/html" if file.suffix == ".html" else "application/javascript"
                    return self._send(200, file.read_bytes(), ctype)
                self._send(404, b"not found", "text/plain")

            def do_POST(self):
                path = self.path.split("?", 1)[0]
                n = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(n) if n else b""
                if path == "/storyteller/events":
                    with col.lock:
                        col.chunks.append(json.loads(body or b"{}"))
                    return self._send(204)
                self._send(404)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def reset(self) -> None:
        with self.lock:
            self.chunks = []

    def recording(self) -> dict:
        with self.lock:
            chunks = list(self.chunks)
        events = [e for c in chunks for e in c["events"]]
        events.sort(key=lambda e: e["timestamp"])
        first = chunks[0]
        return {
            "visitorId": first["visitorId"],
            "visitId": first["visitId"],
            "userId": next((c.get("userId") for c in chunks if c.get("userId")), None),
            "events": events,
        }


PORT = 0


def hide_tab(page: Page, hidden: bool) -> None:
    page.evaluate(
        """(hidden) => {
          Object.defineProperty(document, 'visibilityState', {configurable: true, get: () => hidden ? 'hidden' : 'visible'});
          Object.defineProperty(document, 'hidden', {configurable: true, get: () => hidden});
          document.dispatchEvent(new Event('visibilitychange'));
        }""",
        hidden,
    )


def scenario_compare_abandon(page: Page) -> None:
    """Price-sensitive visitor compares plans, starts signup, stalls on company name, hits error, leaves."""
    page.goto(f"http://127.0.0.1:{PORT}/pricing.html", referer="https://www.google.com/")
    wait(page, 2)
    for _ in range(3):
        page.hover("#plan-pro")
        wait(page, 2.5)
        page.hover("#plan-team")
        wait(page, 2.5)
    page.hover("#plan-pro")
    wait(page, 1)
    page.click("#annual")
    wait(page, 2)
    page.click("#monthly")
    wait(page, 3)
    page.mouse.wheel(0, 600)
    wait(page, 2)
    page.mouse.wheel(0, -600)
    wait(page, 1)
    with page.expect_navigation():
        page.click("#plan-pro button")
    wait(page, 2)
    page.click("#email")
    page.keyboard.type("someone@example.com", delay=int(60 * SCALE))
    wait(page, 1)
    page.click("#password")
    page.keyboard.type("hunter2hunter2", delay=int(60 * SCALE))
    wait(page, 1)
    page.click("#company")
    wait(page, 9)  # stall: unsure what to enter
    hide_tab(page, True)
    wait(page, 12)
    hide_tab(page, False)
    wait(page, 2)
    page.click("#submit")  # company empty → validation error
    wait(page, 4)
    page.click("#submit")  # tries again, same error
    wait(page, 3)


def scenario_success_rage(page: Page) -> None:
    """Returning user reads docs, signs up successfully, then rage-clicks a dead button on the welcome dialog."""
    page.goto(f"http://127.0.0.1:{PORT}/docs.html")
    wait(page, 4)
    page.mouse.wheel(0, 300)
    wait(page, 2)
    with page.expect_navigation():
        page.click("text=Pricing")
    wait(page, 3)
    with page.expect_navigation():
        page.click("#plan-team button")
    wait(page, 1.5)
    page.evaluate("storyteller.identify('user_42', {plan_interest: 'team'})")
    page.click("#email")
    page.keyboard.type("ops@bigco.com", delay=int(50 * SCALE))
    page.click("#password")
    page.keyboard.type("correct-horse-battery", delay=int(50 * SCALE))
    page.click("#company")
    page.keyboard.type("BigCo", delay=int(50 * SCALE))
    wait(page, 1)
    page.click("#submit")
    wait(page, 3)  # spinner → welcome dialog
    for _ in range(4):
        page.click("#go", delay=20)
        wait(page, 0.25)
    wait(page, 2)


def scenario_bounce(page: Page) -> None:
    """Lands on pricing, looks for three seconds, leaves."""
    page.goto(f"http://127.0.0.1:{PORT}/pricing.html", referer="https://news.ycombinator.com/")
    wait(page, 3)


SCENARIOS = {
    "compare_abandon": scenario_compare_abandon,
    "success_rage": scenario_success_rage,
    "bounce": scenario_bounce,
}


def main() -> None:
    OUT.mkdir(exist_ok=True)
    global PORT
    col = Collector()
    PORT = col.port
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-proxy-server"])
        for name, fn in SCENARIOS.items():
            ctx = browser.new_context(viewport={"width": 1280, "height": 800})
            col.reset()
            page = ctx.new_page()
            t0 = time.time()
            fn(page)
            page.evaluate("storyteller.end()")
            page.wait_for_timeout(500)
            ctx.close()
            rec = col.recording()
            (OUT / f"{name}.json").write_text(json.dumps(rec))
            print(f"{name}: {len(rec['events'])} events in {time.time() - t0:.1f}s → fixtures/{name}.json")
        browser.close()


if __name__ == "__main__":
    main()
