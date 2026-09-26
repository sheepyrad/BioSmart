"""Exercise the Run wizard in a browser.

The server stays on localhost. FakeScorer stands in where a GPU is not required.
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
BIOSMART_SRC = REPO / "biosmart" / "src"


def _atom(serial: int, atom_name: str, resname: str, chain: str, resseq: int) -> str:
    return (
        f"ATOM  {serial:5d} {atom_name:>4s} {resname:3s} {chain}{resseq:4d}"
        "      11.000   6.000  -6.000  1.00  0.00           N"
    )


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
    folder = os.environ.get("BIOSMART_WIZARD_SHOTS", "").strip()
    if not folder:
        return
    destination = Path(folder)
    destination.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(destination / name), full_page=True)  # type: ignore[attr-defined]


def test_wizard_browser_starts_and_stops_a_run(tmp_path: Path) -> None:
    playwright_sync = pytest.importorskip("playwright.sync_api")
    inputs = tmp_path / "inputs"
    libraries = tmp_path / "libraries"
    inputs.mkdir()
    library = libraries / "enamine-stock-old"
    library.mkdir(parents=True)
    created = datetime.now(timezone.utc) - timedelta(days=31)
    (library / "library.json").write_text(
        json.dumps(
            {
                "id": "enamine-stock-old",
                "source": "Enamine Stock",
                "created_at": created.isoformat(),
                "druglike": False,
                "path": str(library),
                "supplier_file": "stock.zip",
            }
        )
        + "\n"
    )
    pdb = "\n".join(
        [
            _atom(1, "N", "ALA", "A", 10),
            _atom(2, "CA", "ALA", "A", 10),
            _atom(3, "N", "GLY", "A", 11),
            "END",
            "",
        ]
    )
    (inputs / "ns5.pdb").write_text(pdb)
    ligand = tmp_path / "site.sdf"
    ligand.write_bytes(b"reference-ligand\n")

    env = os.environ.copy()
    env["PYTHONPATH"] = str(BIOSMART_SRC)
    env["BIOSMART_RUNS_ROOT"] = str(tmp_path / "runs")
    env["BIOSMART_REGISTRY"] = str(tmp_path / "registry.sqlite")
    env["BIOSMART_LIBRARIES_ROOT"] = str(libraries)
    env["BIOSMART_INPUTS"] = str(inputs)
    env["BIOSMART_LIGANDS"] = str(tmp_path / "ligands")
    env["BIOSMART_ALIGNMENTS"] = str(tmp_path / "alignments")
    env["BIOSMART_SKIP_DOCTOR"] = "1"
    env["BIOSMART_WIZARD_FAKE"] = "1"
    env["BIOSMART_FAKE_SCORER_BLOCK_ROUND"] = "2"
    env["CUDA_VISIBLE_DEVICES"] = ""
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

        from playwright.sync_api import expect

        with playwright_sync.sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                channel="chrome",
                headless=os.environ.get("BIOSMART_BROWSER_HEADED") != "1",
                slow_mo=200 if os.environ.get("BIOSMART_BROWSER_HEADED") == "1" else 0,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            page.goto(f"http://127.0.0.1:{port}/", wait_until="domcontentloaded")
            steps = [item.strip() for item in page.locator("#wizard-order li").all_text_contents()]
            assert steps == ["Target", "Pocket", "Preset", "Scorer", "Start"]
            page.locator("#wizard").scroll_into_view_if_needed()
            _shot(page, "01-target.png")
            page.get_by_role("button", name="Choose · ns5.pdb").click()
            page.get_by_role("button", name="Continue").click()
            expect(page.get_by_text("Boltz-2 asks for selected residues.")).to_be_visible()
            expect(page.get_by_text("FlashBind asks for a Reference ligand.")).to_be_visible()
            page.get_by_role("button", name="A:10 ALA").click()
            expect(page.get_by_role("button", name="A:10 ALA")).to_have_attribute("aria-pressed", "true")
            _shot(page, "02-residues.png")
            page.locator("#ligand-file").set_input_files(ligand)
            page.get_by_role("button", name="Upload Reference ligand").click()
            expect(page.get_by_text("Reference ligand: site.sdf")).to_be_visible()
            _shot(page, "03-reference-ligand.png")
            page.get_by_role("button", name="Selected residues").click()
            page.get_by_role("button", name="Continue").click()
            expect(page.get_by_role("button", name=re.compile(r"Quick"))).to_be_visible()
            expect(page.get_by_role("button", name=re.compile(r"Standard"))).to_be_visible()
            expect(page.get_by_role("button", name=re.compile(r"Thorough"))).to_be_visible()
            page.get_by_role("button", name="Continue").click()
            expect(page.get_by_role("button", name=re.compile(r"Boltz-2"))).to_be_visible()
            expect(page.get_by_role("button", name=re.compile(r"FlashBind"))).to_be_visible()
            expect(page.get_by_text("Pose provider FABind+.", exact=True)).to_be_visible()
            page.get_by_role("button", name=re.compile(r"FakeScorer")).click()
            page.get_by_role("button", name="Continue").click()
            page.get_by_text("Advanced").click()
            expect(page.get_by_text("Seed", exact=True)).to_be_visible()
            expect(page.get_by_text("Sequence", exact=True)).to_be_visible()
            expect(page.get_by_text("Alignment", exact=True)).to_be_visible()
            expect(page.locator("#start-reminder")).to_contain_text("older than 30 days")
            expect(page.locator("#start-reminder")).to_contain_text("Start remains available.")
            _shot(page, "04-start.png")
            page.get_by_role("button", name="Start", exact=True).click()
            expect(page.locator("#run-progress")).to_contain_text("Iteration 1 of 100", timeout=20000)
            expect(page.locator("#run-eta")).to_contain_text("ETA", timeout=20000)
            page.locator("#runs").scroll_into_view_if_needed()
            _shot(page, "05-progress.png")
            page.get_by_role("button", name="Start", exact=True).click()
            expect(page.locator("[data-status='queued']")).to_be_visible(timeout=20000)
            page.get_by_role("button", name="Cancel").click()
            expect(page.locator("[data-status='cancelled']")).to_be_visible()
            page.get_by_role("button", name="Stop").click()
            expect(page.locator("[data-status='paused']")).to_be_visible(timeout=20000)
            expect(page.locator("#run-progress")).to_have_text("Paused.")
            _shot(page, "06-paused.png")
            page.get_by_role("button", name="Resume").click()
            expect(page.locator("[data-status='running']")).to_be_visible(timeout=20000)
            _shot(page, "07-resumed.png")
            browser.close()
    finally:
        _stop(proc)
