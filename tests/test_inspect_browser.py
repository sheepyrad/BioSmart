"""Exercise Candidate inspection in the browser.

The server stays on localhost. FakeScorer stands in for a GPU Scorer.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any
from urllib import request as urlrequest

import pytest

REPO = Path(__file__).resolve().parents[1]
BIOSMART_SRC = REPO / "biosmart" / "src"


def _pdb() -> str:
    lines = []
    for serial, name, x in ((1, "N", 10.0), (2, "CA", 11.0), (3, "C", 12.0), (4, "O", 13.0)):
        lines.append(
            f"ATOM  {serial:5d} {name:>4s} ALA A  10    {x:8.3f}   6.000  -6.000  1.00  0.00           {name[0]}"
        )
    lines.append("END")
    return "\n".join(lines) + "\n"


def _stop(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is not None:
        return
    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def _shot(page: object, name: str) -> None:
    folder = os.environ.get("BIOSMART_INSPECT_SHOTS", "").strip()
    if not folder:
        return
    destination = Path(folder)
    destination.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(destination / name), full_page=True)  # type: ignore[attr-defined]


def _post(port: int, payload: dict[str, Any]) -> str:
    request = urlrequest.Request(
        f"http://127.0.0.1:{port}/api/v1/runs",
        data=json.dumps(payload).encode(),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urlrequest.urlopen(request, timeout=30) as response:
        created = json.loads(response.read())
    return str(created["run_id"])


def test_browser_pages_filters_searches_and_offers_export(tmp_path: Path) -> None:
    playwright_sync = pytest.importorskip("playwright.sync_api")
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    (inputs / "ns5.pdb").write_text(_pdb())
    env = os.environ.copy()
    env["PYTHONPATH"] = str(BIOSMART_SRC)
    env["BIOSMART_RUNS_ROOT"] = str(tmp_path / "runs")
    env["BIOSMART_REGISTRY"] = str(tmp_path / "registry.sqlite")
    env["BIOSMART_INPUTS"] = str(inputs)
    env["BIOSMART_LIBRARIES_ROOT"] = str(tmp_path / "libraries")
    env["BIOSMART_SKIP_DOCTOR"] = "1"
    env["CUDA_VISIBLE_DEVICES"] = ""
    env.pop("BIOSMART_FAKE_SCORER_POSE", None)
    proc = subprocess.Popen(
        [sys.executable, "-m", "biosmart", "serve", "--port", "0"],
        cwd=REPO,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    stdout: list[str] = []
    stderr: list[str] = []

    def _drain(pipe: object, sink: list[str]) -> None:
        if pipe is None:
            return
        for line in pipe:  # type: ignore[union-attr]
            sink.append(line)

    threading.Thread(target=_drain, args=(proc.stdout, stdout), daemon=True).start()
    threading.Thread(target=_drain, args=(proc.stderr, stderr), daemon=True).start()
    port: int | None = None
    deadline = time.monotonic() + 15
    try:
        while time.monotonic() < deadline:
            for line in stdout:
                if line.startswith("http://127.0.0.1:"):
                    port = int(line.strip().rsplit(":", 1)[1])
                    break
            if port is not None or proc.poll() is not None:
                break
            time.sleep(0.05)
        if port is None:
            raise AssertionError(f"server did not listen; stderr={''.join(stderr)}")
        assert proc.pid is not None
        run_id = _post(
            port,
            {
                "scorer": "fake",
                "seed": 0,
                "budget": {"iterations": 2, "candidates_per_iteration": 30},
                "target": {"name": "ns5", "structure": "ns5.pdb"},
                "pocket": {"residues": ["A:10"]},
                "library": {"id": "fixture-library"},
            },
        )
        from playwright.sync_api import expect

        with playwright_sync.sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                channel="chrome",
                headless=os.environ.get("BIOSMART_BROWSER_HEADED") != "1",
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            page.goto(f"http://127.0.0.1:{port}/", wait_until="domcontentloaded")
            expect(page.get_by_text("Stop pauses the running Run.")).to_be_visible()
            inspect = page.locator(f"[data-run-id='{run_id}'] [data-action='inspect']")
            expect(inspect).to_be_visible(timeout=30000)
            inspect.click()
            expect(page.locator("#pose-caption")).to_contain_text("Candidate 000001", timeout=20000)
            expect(page.locator("#pose-caption")).to_contain_text("has no stored pose")
            expect(page.locator("#pose-caption")).to_contain_text("Pocket")
            expect(page.locator("#pose-caption")).to_contain_text("A:10")
            expect(page.locator("#candidate-rows")).to_contain_text("000001")
            expect(page.locator("#candidate-rows")).to_contain_text("CCO")
            expect(page.locator("#page-status")).to_have_text("Page 1")
            expect(page.get_by_role("columnheader", name="Filter reason")).to_be_visible()
            expect(page.get_by_role("columnheader", name="Score")).to_be_visible()
            _shot(page, "01-page.png")
            ink = page.evaluate(
                """() => {
                  const canvas = document.getElementById("pose-stage");
                  const context = canvas.getContext("2d");
                  const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data;
                  let count = 0;
                  for (let index = 3; index < pixels.length; index += 16) {
                    if (pixels[index] > 0) count += 1;
                  }
                  return count;
                }"""
            )
            assert ink > 20
            page.locator("#page-next").click()
            expect(page.locator("#page-status")).to_have_text("Page 2")
            expect(page.locator("#candidate-rows")).to_contain_text("000026")
            expect(page.locator("#candidate-rows")).not_to_contain_text("000001")
            _shot(page, "02-next-page.png")
            page.locator("#page-prev").click()
            expect(page.locator("#page-status")).to_have_text("Page 1")
            page.get_by_role("button", name="Failed", exact=True).click()
            expect(page.locator("#candidate-rows")).to_contain_text("No Candidates on this page.")
            _shot(page, "03-failed-filter.png")
            page.get_by_role("button", name="Scored", exact=True).click()
            expect(page.locator("#candidate-rows")).to_contain_text("CCO")
            page.wait_for_function(
                """() => {
                  const plate = document.getElementById("parallel-plate");
                  return plate && plate.querySelector("canvas") && window.echarts;
                }"""
            )
            page.evaluate(
                """() => {
                  const chart = window.echarts.getInstanceByDom(document.getElementById("parallel-plate"));
                  chart.dispatchAction({ type: "axisAreaSelect", parallelAxisId: "logp", intervals: [[1, 3]] });
                }"""
            )
            expect(page.locator("#candidate-rows")).to_contain_text("c1ccccc1", timeout=10000)
            expect(page.locator("#candidate-rows")).not_to_contain_text("CCO")
            _shot(page, "04-parallel-filter.png")
            page.locator("#clear-brush").click()
            expect(page.locator("#candidate-rows")).to_contain_text("CCO")
            page.locator("#candidate-query").fill("c1ccccc1")
            page.locator("#search-run").click()
            expect(page.locator("#page-status")).to_have_text("Search")
            expect(page.locator("#candidate-rows")).to_contain_text("c1ccccc1")
            expect(page.locator("#candidate-rows")).not_to_contain_text("CCO")
            _shot(page, "05-search.png")
            page.get_by_role("button", name="000004").click()
            expect(page.locator("#pose-caption")).to_contain_text("000004")
            expect(page.locator("#pose-caption")).to_contain_text("has no stored pose")
            expect(page.locator("#pose-caption")).to_contain_text("A:10")
            _shot(page, "06-pose.png")
            expect(page.locator("#export-sdf")).to_be_enabled()
            expect(page.locator("#export-csv")).to_be_enabled()
            expect(page.locator("#archive-run")).to_be_enabled()
            page.locator("#export-sdf").click()
            expect(page.locator("#inspect-status")).to_have_text("SDF exported.")
            page.locator("#export-csv").click()
            expect(page.locator("#inspect-status")).to_have_text("CSV exported.")
            page.locator("#archive-run").click()
            expect(page.locator("#inspect-status")).to_have_text("Run archived.")
            _shot(page, "07-archive.png")
            assert str(tmp_path) not in page.locator("#candidates").inner_text()
            browser.close()
    finally:
        _stop(proc)
