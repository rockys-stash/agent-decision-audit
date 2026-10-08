"""Browser tests for the Casefile console against a small demo deployment and the committed results.

Run with ``uv run pytest -m ui`` after ``npm --prefix web run build``. Set
``AGENTAUDIT_SCREENSHOTS=1`` to (re)write the screenshots in ``docs/screenshots``.
"""

from __future__ import annotations

import json
import os
import socket
import threading
import time
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
SHOTS = ROOT / "docs" / "screenshots"
pytestmark = pytest.mark.ui

playwright_api = pytest.importorskip("playwright.sync_api")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _get(url: str) -> Any:
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.loads(r.read())


@pytest.fixture(scope="module")
def base_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    if not (ROOT / "web" / "dist" / "index.html").exists():
        pytest.skip("frontend not built (npm --prefix web run build)")
    import uvicorn

    from agentaudit.api.app import create_app
    from agentaudit.api.demo import build_demo

    mp = pytest.MonkeyPatch()
    mp.setenv("AGENTAUDIT_VAR", str(tmp_path_factory.mktemp("var")))
    for k in (
        "AGENTAUDIT_DB",
        "AGENTAUDIT_WITNESS",
        "AGENTAUDIT_SIGNING_KEY",
        "AGENTAUDIT_API_TOKEN",
    ):
        mp.delenv(k, raising=False)
    build_demo(ROOT, seed=0, n_claims=200)
    app = create_app(ROOT)
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            urllib.request.urlopen(f"{url}/api/health", timeout=1)
            break
        except OSError:
            time.sleep(0.1)
    yield url
    server.should_exit = True
    thread.join(timeout=5)
    mp.undo()


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with playwright_api.sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture(scope="module")
def flagged_case(base_url: str) -> dict[str, Any]:
    """A decision with a detector finding on a step (prefer a currency case: more steps to show)."""
    items = _get(f"{base_url}/api/cases?flagged=true&limit=500")["items"]
    fx = [c for c in items if c["simulation_truth"]["violation"] == "stale_rate"]
    case = (fx or items)[0]
    detail = _get(f"{base_url}/api/cases/{case['decision_id']}")
    return {"id": case["decision_id"], "step": detail["findings"][0]["step"]}


VIEWPORTS = {"desktop": {"width": 1440, "height": 900}, "mobile": {"width": 390, "height": 844}}

PAGES = [
    ("cases", "/cases", "Case files"),
    ("violations", "/violations", "Findings by check"),
    ("integrity", "/integrity", "Tamper lab"),
    ("e1", "/experiments?exp=e1_reconstruction&level=2", "Which decision types resist auditing"),
    ("e2", "/experiments?exp=e2_audit_delay", "Reconstruction as the audit happens later"),
    ("e3", "/experiments?exp=e3_violations", "Recall by violation type"),
    ("e4", "/experiments?exp=e4_tamper", "Which integrity layer catches which attack"),
    ("e5", "/experiments?exp=e5_overhead", "Cost of instrumentation"),
    ("method", "/method", "Limits of the evidence"),
]


def _open(
    browser: Any, base_url: str, viewport: str, path: str, marker: str, scheme: str = "light"
) -> Any:
    ctx = browser.new_context(viewport=VIEWPORTS[viewport], color_scheme=scheme)
    page = ctx.new_page()
    errors: list[str] = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(base_url + path)
    page.get_by_text(marker, exact=False).first.wait_for(timeout=30000)
    page.wait_for_load_state("networkidle")
    page.errors = errors
    return page


def _assert_clean(page: Any) -> None:
    assert page.locator("h1").count() == 1
    assert not page.locator(".skeleton").count(), "loading skeleton still visible"
    assert not page.locator("[role=alert]").count(), "error state rendered"
    overflow = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
    assert overflow <= 1, f"page scrolls horizontally by {overflow}px"
    assert not page.errors, page.errors


@pytest.mark.parametrize("viewport", list(VIEWPORTS))
@pytest.mark.parametrize(("name", "path", "marker"), PAGES)
def test_page_renders_real_data(
    browser: Any, base_url: str, viewport: str, name: str, path: str, marker: str
) -> None:
    page = _open(browser, base_url, viewport, path, marker)
    _assert_clean(page)
    if os.environ.get("AGENTAUDIT_SCREENSHOTS"):
        SHOTS.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(SHOTS / f"{name}-{viewport}.png"), full_page=viewport == "mobile")
    page.context.close()


@pytest.mark.parametrize("viewport", list(VIEWPORTS))
def test_replay_steps_like_a_debugger(
    browser: Any, base_url: str, flagged_case: dict[str, Any], viewport: str
) -> None:
    cid = flagged_case["id"]
    page = _open(browser, base_url, viewport, f"/cases/{cid}?level=4", "Reproduced")
    _assert_clean(page)
    assert page.get_by_text("Simulation ground truth.").count() == 1
    # v jumps to the step with a finding; n/p step forward and back.
    page.keyboard.press("v")
    page.locator(".finding").first.wait_for()
    assert f"step={flagged_case['step']}" in page.url
    page.keyboard.press("n")
    assert f"step={flagged_case['step'] + 1}" in page.url
    page.keyboard.press("p")
    assert f"step={flagged_case['step']}" in page.url
    if os.environ.get("AGENTAUDIT_SCREENSHOTS"):
        page.screenshot(path=str(SHOTS / f"replay-{viewport}.png"), full_page=viewport == "mobile")
    # A lower level: fewer steps kept, and the replay can no longer reproduce the decision.
    page.get_by_role("group", name="Instrumentation level").get_by_role("button", name="L0").click()
    page.get_by_text("not in the record at L0").wait_for()
    assert page.get_by_text("Reproduced", exact=True).count() == 0
    page.context.close()


def test_divergence_and_reference_code(
    browser: Any, base_url: str, flagged_case: dict[str, Any]
) -> None:
    cid = flagged_case["id"]
    page = _open(
        browser, base_url, "desktop", f"/cases/{cid}?level=4&code=approved", "Diverged", "dark"
    )
    _assert_clean(page)
    page.keyboard.press("f")
    page.get_by_text("Replay differs").wait_for()
    if os.environ.get("AGENTAUDIT_SCREENSHOTS"):
        page.screenshot(path=str(SHOTS / "replay-reference-dark.png"))
    page.context.close()


def test_tamper_lab_detects_without_touching_the_log(browser: Any, base_url: str) -> None:
    page = _open(browser, base_url, "desktop", "/integrity", "Tamper lab")
    head = page.locator("dd", has_text="seq").first.inner_text()
    page.get_by_label("Attack").select_option("rewrite_with_key")
    page.get_by_role("button", name="Run attack").click()
    page.get_by_text("Which integrity layers notice?").wait_for()
    assert (
        page.get_by_text("Accepted as valid").count() >= 2
    )  # sequence numbers; hash chain or checkpoints
    assert page.get_by_text("Tampering detected").count() >= 1  # the external anchor
    page.get_by_role("button", name="Verify again").click()
    page.locator(".panel-head .mark", has_text="Intact").wait_for()
    assert page.locator("dd", has_text="seq").first.inner_text() == head
    if os.environ.get("AGENTAUDIT_SCREENSHOTS"):
        page.screenshot(path=str(SHOTS / "tamper-lab-desktop.png"))
    page.context.close()


def test_filters_and_not_found(browser: Any, base_url: str) -> None:
    page = _open(browser, base_url, "desktop", "/cases?decided_by=human", "Case files")
    page.locator("tbody tr").first.wait_for()
    assert page.locator("tbody td", has_text="Agent").count() == 0
    page.goto(f"{base_url}/cases?search=NOMATCH")
    page.get_by_text("No decisions match these filters").wait_for()
    page.goto(f"{base_url}/no/such/page")
    page.get_by_role("heading", name="Page not found").first.wait_for()
    page.goto(f"{base_url}/cases/claims-agent:CLM-99999")
    page.get_by_text("unknown decision").wait_for()
    page.get_by_role("button", name="Retry").wait_for()
    page.context.close()


AXE = ROOT / "web" / "node_modules" / "axe-core" / "axe.min.js"


@pytest.mark.parametrize("scheme", ["light", "dark"])
@pytest.mark.parametrize("viewport", list(VIEWPORTS))
def test_no_wcag_violations(
    browser: Any, base_url: str, flagged_case: dict[str, Any], viewport: str, scheme: str
) -> None:
    """axe-core audit (WCAG 2.1 A/AA + best practices) of every view in both themes."""
    if not AXE.exists():
        pytest.skip("axe-core not installed (npm --prefix web ci)")
    ctx = browser.new_context(viewport=VIEWPORTS[viewport], color_scheme=scheme, bypass_csp=True)
    page = ctx.new_page()
    found: dict[str, list[str]] = {}
    views = [
        *PAGES,
        (
            "replay",
            f"/cases/{flagged_case['id']}?level=2&step={flagged_case['step']}",
            "Audit questions at L2",
        ),
    ]
    for _, path, marker in views:
        page.goto(base_url + path)
        page.get_by_text(marker, exact=False).first.wait_for(timeout=30000)
        page.wait_for_load_state("networkidle")
        page.add_script_tag(path=str(AXE))
        violations = page.evaluate(
            """async () => (await axe.run(document, {runOnly: ['wcag2a', 'wcag2aa', 'wcag21aa',
               'best-practice']})).violations.map(v => v.id + ': ' + v.nodes.map(n => n.target.join(' ')).join(', '))"""
        )
        if violations:
            found[path] = violations
    ctx.close()
    assert not found, found
