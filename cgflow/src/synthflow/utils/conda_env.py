"""Utility functions for running commands in specific conda environments."""

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional


def huggingface_cache_environ(cache_root: str | Path) -> dict[str, str]:
    """
    Environment variables so Hugging Face libraries use one root on a large disk.

    Sets HF_HOME plus common overrides (hub, datasets, transformers) under that root.
    """
    root = Path(cache_root).resolve()
    return {
        "HF_HOME": str(root),
        "HF_HUB_CACHE": str(root / "hub"),
        "HF_DATASETS_CACHE": str(root / "datasets"),
        "TRANSFORMERS_CACHE": str(root / "transformers"),
    }


def run_in_conda_env(
    cmd: list[str],
    conda_env: str,
    cwd: Optional[Path] = None,
    check: bool = True,
    capture_output: bool = True,
    text: bool = True,
    shell: bool = False,
    env: Optional[dict[str, str]] = None,
) -> subprocess.CompletedProcess:
    """
    Run a command in a specific conda environment.

    Parameters
    ----------
    cmd : list[str]
        Command to run (as a list of arguments)
    conda_env : str
        Name of the conda environment to activate
    cwd : Optional[Path]
        Working directory for the command
    check : bool
        Whether to raise CalledProcessError on non-zero exit
    capture_output : bool
        Whether to capture stdout and stderr
    text : bool
        Whether to return output as text (not bytes)
    shell : bool
        Whether to use shell execution

    Returns
    -------
    subprocess.CompletedProcess
        Result of the subprocess execution

    Raises
    ------
    subprocess.CalledProcessError
        If check=True and command returns non-zero exit code
    """
    # Find conda installation
    conda_base = _find_conda_base()
    if conda_base is None:
        raise RuntimeError("Conda not found. Please ensure conda is installed and in PATH.")

    # Create command to activate conda env and run command
    # Use conda run to execute command in the environment
    conda_run_cmd = [
        str(conda_base / "bin" / "conda"),
        "run",
        "-n",
        conda_env,
        "--no-capture-output",
    ] + cmd

    # Merge with current environment if env is provided
    if env is not None:
        full_env = os.environ.copy()
        full_env.update(env)
    else:
        full_env = os.environ.copy()
    _enable_ijit_compat_for_fabind(conda_env, full_env)
    
    return subprocess.run(
        conda_run_cmd,
        cwd=cwd,
        check=check,
        capture_output=capture_output,
        text=text,
        shell=shell,
        env=full_env,
    )


def run_python_in_conda_env(
    python_script: str | Path,
    conda_env: str,
    args: Optional[list[str]] = None,
    cwd: Optional[Path] = None,
    check: bool = True,
    capture_output: bool = True,
    text: bool = True,
) -> subprocess.CompletedProcess:
    """
    Run a Python script in a specific conda environment.

    Parameters
    ----------
    python_script : str | Path
        Path to Python script to run
    conda_env : str
        Name of the conda environment to activate
    args : Optional[list[str]]
        Additional arguments to pass to the script
    cwd : Optional[Path]
        Working directory for the command
    check : bool
        Whether to raise CalledProcessError on non-zero exit
    capture_output : bool
        Whether to capture stdout and stderr
    text : bool
        Whether to return output as text (not bytes)

    Returns
    -------
    subprocess.CompletedProcess
        Result of the subprocess execution

    Raises
    ------
    subprocess.CalledProcessError
        If check=True and command returns non-zero exit code
    """
    # Find conda installation
    conda_base = _find_conda_base()
    if conda_base is None:
        raise RuntimeError("Conda not found. Please ensure conda is installed and in PATH.")

    python_cmd = [
        str(conda_base / "bin" / "conda"),
        "run",
        "-n",
        conda_env,
        "--no-capture-output",
        "python",
        str(python_script),
    ]

    if args:
        python_cmd.extend(args)

    full_env = os.environ.copy()
    _enable_ijit_compat_for_fabind(conda_env, full_env)
    return subprocess.run(
        python_cmd,
        cwd=cwd,
        check=check,
        capture_output=capture_output,
        text=text,
        env=full_env,
    )


def _find_conda_base() -> Optional[Path]:
    """Find conda base installation directory."""
    import os

    # Check CONDA_PREFIX (if already in a conda env)
    conda_prefix = os.environ.get("CONDA_PREFIX")
    if conda_prefix:
        # Go up to base: CONDA_PREFIX is usually <base>/envs/<env_name>
        conda_base = Path(conda_prefix).parent.parent
        if (conda_base / "bin" / "conda").exists():
            return conda_base

    # Check CONDA_EXE (direct path to conda executable)
    conda_exe = os.environ.get("CONDA_EXE")
    if conda_exe:
        conda_base = Path(conda_exe).parent.parent
        if (conda_base / "bin" / "conda").exists():
            return conda_base

    # Try common conda locations
    home = Path.home()
    common_paths = [
        home / "anaconda3",
        home / "miniconda3",
        home / "conda",
        Path("/opt/conda"),
        Path("/usr/local/anaconda3"),
        Path("/usr/local/miniconda3"),
    ]

    for path in common_paths:
        if (path / "bin" / "conda").exists():
            return path

    # Try to find conda in PATH
    import shutil

    conda_path = shutil.which("conda")
    if conda_path:
        conda_base = Path(conda_path).parent.parent
        if (conda_base / "bin" / "conda").exists():
            return conda_base

    return None


def _enable_ijit_compat_for_fabind(conda_env: str, env: dict[str, str]) -> None:
    """
    Work around missing iJIT symbols in some FABind torch environments.

    Some Linux installs of older torch builds expect iJIT symbols that are not
    present in newer OpenMP/runtime stacks. Preloading this tiny shim keeps torch
    importable and does not affect FABind inference behavior.
    """
    if conda_env != "fabind":
        return
    stub_path = _ensure_ijit_stub()
    if stub_path is None:
        return
    existing = env.get("LD_PRELOAD", "").strip()
    if existing:
        env["LD_PRELOAD"] = f"{stub_path}:{existing}"
    else:
        env["LD_PRELOAD"] = stub_path


def _ensure_ijit_stub() -> Optional[str]:
    cache_dir = Path.home() / ".cache" / "synthflow"
    cache_dir.mkdir(parents=True, exist_ok=True)
    so_path = cache_dir / "libittnotify_stub.so"
    if so_path.exists():
        return str(so_path)

    c_src = """
unsigned int iJIT_GetNewMethodID(void) {
    static unsigned int i = 1U;
    return i++;
}
int iJIT_NotifyEvent(int event_type, void* event_data) {
    (void)event_type;
    (void)event_data;
    return 0;
}
int iJIT_IsProfilingActive(void) {
    return 0;
}
"""
    with tempfile.NamedTemporaryFile("w", suffix=".c", delete=False) as f:
        f.write(c_src)
        c_path = Path(f.name)
    try:
        subprocess.run(
            ["gcc", "-shared", "-fPIC", "-o", str(so_path), str(c_path)],
            check=True,
            capture_output=True,
            text=True,
        )
        return str(so_path) if so_path.exists() else None
    except Exception:
        return None
    finally:
        try:
            c_path.unlink(missing_ok=True)
        except Exception:
            pass







