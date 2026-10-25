"""Website and chat assistant robustness, checked in headless Chrome (tmp/web_robustness_check.mjs).

The pages are served from docs/ by a local HTTP server on a free port, and a temporary Chrome profile
is used, so nothing in the repository or the user's own browser is touched. The checks cover hostile
and unusual chat input, the page opened from disk, a blocked chart library, corrupted data files, a
320 px phone screen, every filter combination, and every governed answer word for word. Skips cleanly
when Node.js or Chrome/Edge is not installed.
"""
import functools
import http.server
import json
import os
import shutil
import socketserver
import subprocess
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
SCRIPT = ROOT / "tmp" / "web_robustness_check.mjs"
CHECKS = ["html_in_chat_is_text", "long_input", "non_latin_input", "rapid_sends", "whitespace_ignored",
          "governed_answer_unchanged", "analytics_no_typed_text", "no_uncaught_errors", "all_filter_combinations",
          "dashboard_from_disk", "chat_from_disk", "chart_library_blocked", "dashboard_json_corrupt",
          "dashboard_json_incomplete", "qa_json_corrupt", "qa_json_incomplete", "phone_320px"]


def _browser() -> str | None:
    candidates = [os.environ.get("CHROME_PATH", ""),
                  r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                  r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                  shutil.which("google-chrome") or "", shutil.which("chromium") or "", shutil.which("chromium-browser") or ""]
    return next((c for c in candidates if c and Path(c).exists()), None)


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    node, browser = shutil.which("node"), _browser()
    if not node or not browser:
        pytest.skip("Node.js and Chrome or Edge are needed for the browser checks")
    handler = functools.partial(_QuietHandler, directory=str(DOCS))
    with socketserver.ThreadingTCPServer(("127.0.0.1", 0), handler) as httpd:
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        out = tmp_path_factory.mktemp("web") / "results.json"
        base = f"http://127.0.0.1:{httpd.server_address[1]}"
        proc = subprocess.run([node, str(SCRIPT), browser, str(DOCS), base, str(out)],
                              capture_output=True, text=True, timeout=600)
        httpd.shutdown()
    if not out.exists():
        pytest.fail(f"browser check did not run: {proc.stdout[-500:]} {proc.stderr[-500:]}")
    return json.loads(out.read_text(encoding="utf-8"))


def test_browser_script_completed(results):
    errors = [r for r in results if r["check"] == "script_error"]
    assert not errors, errors


@pytest.mark.parametrize("check", CHECKS)
def test_web_robustness(results, check):
    rows = [r for r in results if r["check"] == check]
    assert rows, f"{check} did not run"
    failed = [r for r in rows if not r["ok"]]
    assert not failed, failed[:3]
