"""Building-block library from Enamine Stock.

Seam: ``python -m biosmart library``. A library is the directory the policy
can load (``workflow.yaml``, ``blocks/``, ``bb_feature.pt``) plus
``library.json`` and ``supplier.smi``. Tests generate a tiny Stock zip.
They do not unpack the Stock file into git.

``EN300-BOROXINE`` (``B1OBOBO1``) scores 58.41 on the DeepDL extended model.
``b_druglike_filter.py`` drops scores below 60, so that id is the independent
check that the filter stayed off.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from rdkit import Chem

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "biosmart" / "src"

# One SMILES for every reactant pattern the unmodified workflow builder requires.
# Boroxine is extra: it is below the drug-like threshold.
STOCK_BLOCKS: tuple[tuple[str, str], ...] = (
    ("EN300-0001", "Nc1ccccc1"),
    ("EN300-0002", "CCO"),
    ("EN300-0003", "CC(=O)O"),
    ("EN300-0004", "CC=O"),
    ("EN300-0005", "CC(=O)OC"),
    ("EN300-0006", "CC(=O)NN"),
    ("EN300-0007", "CC(=O)C"),
    ("EN300-0008", "CCl"),
    ("EN300-0009", "CNN"),
    ("EN300-0010", "CN=[N+]=[N-]"),
    ("EN300-0011", "CC#N"),
    ("EN300-0012", "CC#C"),
    ("EN300-0013", "CS(=O)(=O)Cl"),
    ("EN300-0014", "CN"),
    ("EN300-0015", "CO"),
    ("EN300-0016", "CS"),
    ("EN300-0018", "COS(=O)(=O)C"),
    ("EN300-0019", "CC(Cl)C"),
    ("EN300-0020", "C1CO1"),
    ("EN300-0021", "Clc1ccccc1"),
    ("EN300-0022", "Oc1ccccc1"),
    ("EN300-0023", "OB(O)c1ccccc1"),
    ("EN300-0024", "C[N+](=O)[O-]"),
    ("EN300-0025", "N#CCC#N"),
    ("EN300-0026", "C=CC=O"),
    ("EN300-0027", "NCC(=O)OC"),
    ("EN300-0028", "Nc1ccccc1C(N)=O"),
    ("EN300-0029", "NCCC(=O)O"),
    ("EN300-0030", "Nc1ccccc1N"),
    ("EN300-0031", "COC(=O)c1ccccc1N"),
    ("EN300-BOROXINE", "B1OBOBO1"),
)


def write_stock_zip(path: Path, blocks: tuple[tuple[str, str], ...] = STOCK_BLOCKS) -> None:
    sdf_path = path.with_suffix(".sdf")
    writer = Chem.SDWriter(str(sdf_path))
    for catalog_id, smiles in blocks:
        mol = Chem.MolFromSmiles(smiles)
        assert mol is not None, smiles
        mol.SetProp("Catalog_ID", catalog_id)
        writer.write(mol)
    writer.close()
    with zipfile.ZipFile(path, "w") as archive:
        archive.write(sdf_path, arcname="Enamine_Building_Blocks_Stock.sdf")
    sdf_path.unlink()


def run_biosmart(*args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, "-m", "biosmart", *args],
        cwd=REPO,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def supplier_ids(library_dir: Path) -> set[str]:
    lines = (library_dir / "supplier.smi").read_text().splitlines()
    return {line.split()[1] for line in lines if line and not line.startswith("smiles")}


def test_stock_zip_builds_a_library_with_the_druglike_filter_off(tmp_path: Path) -> None:
    stock_zip = tmp_path / "stock.zip"
    write_stock_zip(stock_zip)
    libraries_root = tmp_path / "libraries"

    result = run_biosmart(
        "library",
        "build",
        str(stock_zip),
        "--source",
        "stock",
        "--libraries-root",
        str(libraries_root),
        "--cpu",
        "2",
    )
    assert result.returncode == 0, result.stderr

    built = list(libraries_root.glob("*/library.json"))
    assert len(built) == 1
    library_dir = built[0].parent
    meta = json.loads(built[0].read_text())
    assert meta["source"] == "Enamine Stock"
    assert meta["druglike"] is False
    assert (library_dir / "workflow.yaml").is_file()
    assert (library_dir / "bb_feature.pt").is_file()
    assert any((library_dir / "blocks").glob("*.smi"))
    assert "EN300-BOROXINE" in supplier_ids(library_dir)
    assert "EN300-0001" in supplier_ids(library_dir)


def test_catalog_source_is_not_the_stock_build(tmp_path: Path) -> None:
    libraries_root = tmp_path / "libraries"
    result = run_biosmart(
        "library",
        "build",
        str(tmp_path / "catalog.sdf"),
        "--source",
        "catalog",
        "--libraries-root",
        str(libraries_root),
    )
    assert result.returncode != 0
    assert not libraries_root.exists()


def _build(zip_path: Path, libraries_root: Path, *, druglike: bool = False) -> None:
    args = [
        "library",
        "build",
        str(zip_path),
        "--source",
        "stock",
        "--libraries-root",
        str(libraries_root),
        "--cpu",
        "2",
    ]
    if druglike:
        args.append("--druglike")
    result = run_biosmart(*args)
    assert result.returncode == 0, result.stderr


@pytest.fixture(scope="module")
def two_libraries(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, str, str]:
    root = tmp_path_factory.mktemp("libraries")
    libraries_root = root / "libraries"
    first_zip = root / "first.zip"
    second_zip = root / "second.zip"
    write_stock_zip(first_zip)
    write_stock_zip(
        second_zip,
        tuple((catalog_id.replace("EN300", "EN301"), smiles) for catalog_id, smiles in STOCK_BLOCKS),
    )
    _build(first_zip, libraries_root)
    _build(second_zip, libraries_root)
    metas = [json.loads(path.read_text()) for path in libraries_root.glob("*/library.json")]
    metas.sort(key=lambda meta: str(meta["created_at"]))
    assert len(metas) == 2
    return libraries_root, str(metas[0]["id"]), str(metas[1]["id"])


def test_second_library_coexists_and_newest_is_the_default(
    two_libraries: tuple[Path, str, str],
) -> None:
    libraries_root, first_id, second_id = two_libraries
    assert (libraries_root / first_id).is_dir()
    assert (libraries_root / second_id).is_dir()

    result = run_biosmart("library", "list", "--libraries-root", str(libraries_root))
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["default_id"] == second_id
    assert {item["id"] for item in payload["libraries"]} == {first_id, second_id}
    assert "EN301-0001" in supplier_ids(libraries_root / second_id)


def _start_run(tmp_path: Path, libraries_root: Path, library_id: str) -> subprocess.CompletedProcess[str]:
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(
        json.dumps(
            {
                "scorer": "fake",
                "seed": 7,
                "budget": {"iterations": 1, "candidates_per_iteration": 1},
                "target": {"name": "ns5-fixture"},
                "pocket": {"residues": ["A:42"]},
                "library": {"id": library_id},
            }
        )
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC)
    env["BIOSMART_RUNS_ROOT"] = str(tmp_path / "runs")
    env["BIOSMART_REGISTRY"] = str(tmp_path / "registry.sqlite")
    env["BIOSMART_LIBRARIES_ROOT"] = str(libraries_root)
    env["BIOSMART_SKIP_DOCTOR"] = "1"
    env["CUDA_VISIBLE_DEVICES"] = ""
    return subprocess.run(
        [sys.executable, "-m", "biosmart", "run", str(spec_path)],
        cwd=REPO,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
    )


def _events(run_folder: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in (run_folder / "events.jsonl").read_text().splitlines()
        if line.strip()
    ]


def test_run_records_the_default_library(two_libraries: tuple[Path, str, str], tmp_path: Path) -> None:
    libraries_root, _first_id, second_id = two_libraries
    listed = json.loads(
        run_biosmart("library", "list", "--libraries-root", str(libraries_root)).stdout
    )
    assert listed["default_id"] == second_id

    result = _start_run(tmp_path, libraries_root, second_id)
    assert result.returncode == 0, result.stderr
    run_folder = next(path for path in (tmp_path / "runs").iterdir() if path.is_dir())
    recorded = json.loads((run_folder / "library.json").read_text())
    assert recorded["id"] == second_id
    assert recorded["source"] == "Enamine Stock"
    assert recorded["druglike"] is False
    events = _events(run_folder)
    assert events[0]["type"] == "run.started"
    assert events[-1]["type"] == "run.finished"
    assert all(event["type"] != "warning" for event in events)


def test_old_library_reminds_and_does_not_refuse_start(
    two_libraries: tuple[Path, str, str],
    tmp_path: Path,
) -> None:
    libraries_root, first_id, _second_id = two_libraries
    library_dir = libraries_root / first_id
    assert library_dir.is_dir()
    meta_path = library_dir / "library.json"
    meta = json.loads(meta_path.read_text())
    created_at = datetime.fromisoformat(str(meta["created_at"]))
    meta["created_at"] = (created_at - timedelta(days=31)).isoformat()
    meta_path.write_text(json.dumps(meta, indent=2) + "\n")

    result = _start_run(tmp_path, libraries_root, first_id)
    assert result.returncode == 0, result.stderr
    run_folder = next(path for path in (tmp_path / "runs").iterdir() if path.is_dir())
    events = _events(run_folder)
    assert any(event["type"] == "run.started" for event in events)
    assert events[-1]["type"] == "run.finished"
    warnings = [event for event in events if event["type"] == "warning"]
    assert len(warnings) == 1
    assert "older" in str(warnings[0]["message"])
    recorded = json.loads((run_folder / "library.json").read_text())
    assert recorded["id"] == first_id
    assert recorded["source"] == "Enamine Stock"


def test_unset_libraries_root_still_warns_for_an_old_default_library(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    env = os.environ.copy()
    env.pop("BIOSMART_LIBRARIES_ROOT", None)
    env["HOME"] = str(home)
    env["PYTHONPATH"] = str(SRC)
    env["CUDA_VISIBLE_DEVICES"] = ""
    assert "BIOSMART_LIBRARIES_ROOT" not in env

    stock_zip = tmp_path / "stock.zip"
    write_stock_zip(stock_zip)
    built = subprocess.run(
        [
            sys.executable,
            "-m",
            "biosmart",
            "library",
            "build",
            str(stock_zip),
            "--source",
            "stock",
            "--cpu",
            "2",
        ],
        cwd=REPO,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=120,
    )
    assert built.returncode == 0, built.stderr
    meta_paths = list((home / "BioSmart" / "libraries").glob("*/library.json"))
    assert len(meta_paths) == 1
    meta = json.loads(meta_paths[0].read_text())
    created_at = datetime.fromisoformat(str(meta["created_at"]))
    meta["created_at"] = (created_at - timedelta(days=31)).isoformat()
    meta_paths[0].write_text(json.dumps(meta, indent=2) + "\n")

    spec_path = tmp_path / "spec.json"
    spec_path.write_text(
        json.dumps(
            {
                "scorer": "fake",
                "seed": 7,
                "budget": {"iterations": 1, "candidates_per_iteration": 1},
                "target": {"name": "ns5-fixture"},
                "pocket": {"residues": ["A:42"]},
                "library": {"id": meta["id"]},
            }
        )
    )
    run_env = dict(env)
    run_env["BIOSMART_RUNS_ROOT"] = str(tmp_path / "runs")
    run_env["BIOSMART_REGISTRY"] = str(tmp_path / "registry.sqlite")
    run_env["BIOSMART_SKIP_DOCTOR"] = "1"
    result = subprocess.run(
        [sys.executable, "-m", "biosmart", "run", str(spec_path)],
        cwd=REPO,
        env=run_env,
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    run_folder = next(path for path in (tmp_path / "runs").iterdir() if path.is_dir())
    events = _events(run_folder)
    assert any(event["type"] == "run.started" for event in events)
    assert events[-1]["type"] == "run.finished"
    warnings = [event for event in events if event["type"] == "warning"]
    assert len(warnings) == 1
    assert "older" in str(warnings[0]["message"])
    recorded = json.loads((run_folder / "library.json").read_text())
    assert recorded["id"] == meta["id"]
    assert recorded["source"] == "Enamine Stock"
    assert recorded["druglike"] is False


def test_druglike_filter_removes_the_block_below_the_threshold(tmp_path: Path) -> None:
    stock_zip = tmp_path / "stock.zip"
    write_stock_zip(stock_zip)
    libraries_root = tmp_path / "libraries"
    _build(stock_zip, libraries_root, druglike=True)

    built = list(libraries_root.glob("*/library.json"))
    assert len(built) == 1
    meta = json.loads(built[0].read_text())
    assert meta["druglike"] is True
    assert meta["source"] == "Enamine Stock"
    ids = supplier_ids(built[0].parent)
    assert "EN300-BOROXINE" not in ids
    assert "EN300-0001" in ids
    assert (built[0].parent / "workflow.yaml").is_file()
