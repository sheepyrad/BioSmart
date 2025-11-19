"""
Environment management utilities for running tools in specific conda environments.

This module provides a centralized way to execute commands in specific conda environments
using 'conda run', replacing the previous approach of manual environment activation.
"""

import subprocess
import logging
import os
import shlex
from pathlib import Path
from typing import List, Dict, Optional, Union, Tuple, Any, Callable
import threading
import time
import select
import sys
import shutil
import json

logger = logging.getLogger(__name__)

# Environment mapping for different tools
TOOL_ENVIRONMENTS = {
    "diffsbdd": "diffsbdd-env",
    "pocket2mol": "pocket2mol-env", 
    "cgflow": "cgflow-env",
    "synformer": "synformer-env",
    "boltz": "boltz-env",
    "unidock": "unidock-env",  # unidock command is in unidock-env
    "unidocktools": "unidock-env",  # unidocktools is in unidock-env
    "unigbsa": "unigbsa-env",
}

class EnvironmentManager:
    """Manages conda environment execution for different tools."""
    
    def __init__(self):
        self.environments = TOOL_ENVIRONMENTS.copy()
        # Resolve the conda/mamba executable once to avoid PATH issues when invoked from other environments
        self._runner_executable, self._runner_name = self._resolve_conda_executable()

    def _resolve_conda_executable(self) -> Tuple[Optional[str], str]:
        """Resolve the path to a conda-compatible runner (conda or mamba).

        Returns a tuple of (executable_path or None, runner_name: 'conda'|'mamba'|'unknown').
        """
        # Prefer explicit environment variables
        conda_exe = os.environ.get("CONDA_EXE")
        if conda_exe and os.path.isfile(conda_exe):
            return conda_exe, "conda"

        mamba_exe = os.environ.get("MAMBA_EXE")
        if mamba_exe and os.path.isfile(mamba_exe):
            return mamba_exe, "mamba"

        # Fallback to PATH lookups
        path_conda = shutil.which("conda")
        if path_conda:
            return path_conda, "conda"

        path_mamba = shutil.which("mamba")
        if path_mamba:
            return path_mamba, "mamba"

        return None, "unknown"

    def _build_conda_run_cmd(self, env_name: str, cmd_list: List[str]) -> List[str]:
        """Build the full command to run something inside an environment with the resolved runner."""
        runner = self._runner_executable or "conda"
        return [runner, "run", "-n", env_name] + cmd_list
    
    def _stream_output(self, process, log_callback, result_storage, timeout=None):
        """Stream subprocess output in real-time to log callback with timeout support."""
        stdout_lines = []
        stderr_lines = []
        
        def read_stdout():
            """Read stdout in a separate thread."""
            try:
                for line in iter(process.stdout.readline, ''):
                    if line:
                        line = line.rstrip('\n\r')
                        stdout_lines.append(line)
                        if log_callback:
                            log_callback(f"[STDOUT] {line}")
            except Exception as e:
                if log_callback:
                    log_callback(f"[ERROR] Error reading stdout: {e}")
        
        def read_stderr():
            """Read stderr in a separate thread."""
            try:
                for line in iter(process.stderr.readline, ''):
                    if line:
                        line = line.rstrip('\n\r')
                        stderr_lines.append(line)
                        if log_callback:
                            log_callback(f"[STDERR] {line}")
            except Exception as e:
                if log_callback:
                    log_callback(f"[ERROR] Error reading stderr: {e}")
        
        # Start reader threads
        stdout_thread = threading.Thread(target=read_stdout, daemon=True)
        stderr_thread = threading.Thread(target=read_stderr, daemon=True)
        
        stdout_thread.start()
        stderr_thread.start()
        
        # Wait for process to complete with timeout support
        try:
            if timeout:
                # Wait with timeout
                process.wait(timeout=timeout)
            else:
                # Wait indefinitely
                process.wait()
        except subprocess.TimeoutExpired:
            # Process timed out, terminate it
            if log_callback:
                log_callback(f"[TIMEOUT] Process timed out after {timeout} seconds, terminating...")
            process.terminate()
            try:
                process.wait(timeout=5)  # Give it 5 seconds to terminate gracefully
            except subprocess.TimeoutExpired:
                if log_callback:
                    log_callback("[TIMEOUT] Process didn't terminate gracefully, killing...")
                process.kill()
                process.wait()  # Wait for kill to complete
            raise  # Re-raise the TimeoutExpired exception
        
        # Wait for reader threads to finish
        stdout_thread.join(timeout=5)
        stderr_thread.join(timeout=5)
        
        # Store the collected output
        result_storage["stdout"] = '\n'.join(stdout_lines)
        result_storage["stderr"] = '\n'.join(stderr_lines)
        result_storage["returncode"] = process.returncode
    
    def run_in_env(
        self,
        env_name: str,
        command: Union[str, List[str]],
        cwd: Optional[Union[str, Path]] = None,
        timeout: Optional[int] = None,
        capture_output: bool = True,
        text: bool = True,
        check: bool = False,
        log_callback: Optional[Callable[[str], None]] = None,
        stream_output: bool = False
    ) -> subprocess.CompletedProcess:
        """
        Run a command in a specific conda environment using 'conda run'.
        
        Args:
            env_name: Name of the conda environment
            command: Command to run (string or list of strings)
            cwd: Working directory for the command
            timeout: Timeout in seconds
            capture_output: Whether to capture stdout/stderr
            text: Whether to return text output
            check: Whether to raise exception on non-zero exit
            log_callback: Optional logging callback function
            stream_output: Whether to stream output in real-time
            
        Returns:
            subprocess.CompletedProcess object
        """
        # Convert command to list if it's a string
        if isinstance(command, str):
            cmd_list = shlex.split(command)
        else:
            cmd_list = command
        
        # Construct the conda/mamba run command using resolved executable
        # Always use <runner> run -n <env_name> since we may be running from a different conda env (e.g., Streamlit frontend)
        conda_cmd = self._build_conda_run_cmd(env_name, cmd_list)
        
        if log_callback:
            log_callback(f"Running in {env_name}: {' '.join(cmd_list)}")
            if cwd:
                log_callback(f"Working directory: {cwd}")
        
        try:
            if stream_output and log_callback:
                # Use streaming approach for real-time output
                result_storage = {}
                
                with subprocess.Popen(
                    conda_cmd,
                    cwd=cwd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=text,
                    bufsize=1,  # Line buffered
                    universal_newlines=True
                ) as process:
                    try:
                        # Stream output in real-time
                        self._stream_output(process, log_callback, result_storage, timeout)
                        
                        # Create a CompletedProcess-like object
                        result = subprocess.CompletedProcess(
                            args=conda_cmd,
                            returncode=result_storage["returncode"],
                            stdout=result_storage["stdout"],
                            stderr=result_storage["stderr"]
                        )
                            
                    except Exception as e:
                        process.terminate()
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()
                        raise e
            else:
                # Use standard approach without streaming
                result = subprocess.run(
                    conda_cmd,
                    cwd=cwd,
                    timeout=timeout,
                    capture_output=capture_output,
                    text=text,
                    check=check
                )
            
            if log_callback and result.returncode == 0:
                log_callback(f"Command completed successfully in {env_name}")
            elif log_callback:
                log_callback(f"Command failed in {env_name} with exit code {result.returncode}")
                
            return result
            
        except subprocess.TimeoutExpired as e:
            if log_callback:
                log_callback(f"Command timed out after {timeout} seconds in {env_name}")
            raise
        except subprocess.CalledProcessError as e:
            if log_callback:
                log_callback(f"Command failed in {env_name}: {e}")
            raise
        except Exception as e:
            if log_callback:
                log_callback(f"Unexpected error running command in {env_name}: {e}")
            raise
    
    def run_tool(
        self,
        tool_name: str,
        command: Union[str, List[str]],
        cwd: Optional[Union[str, Path]] = None,
        timeout: Optional[int] = None,
        capture_output: bool = True,
        text: bool = True,
        check: bool = False,
        log_callback: Optional[Callable[[str], None]] = None,
        stream_output: bool = False
    ) -> subprocess.CompletedProcess:
        """
        Run a command for a specific tool in its designated environment.
        
        Args:
            tool_name: Name of the tool (e.g., 'diffsbdd', 'pocket2mol')
            command: Command to run
            cwd: Working directory
            timeout: Timeout in seconds
            capture_output: Whether to capture output
            text: Whether to return text output
            check: Whether to raise exception on failure
            log_callback: Optional logging callback
            stream_output: Whether to stream output in real-time
            
        Returns:
            subprocess.CompletedProcess object
        """
        if tool_name not in self.environments:
            raise ValueError(f"Unknown tool: {tool_name}. Available tools: {list(self.environments.keys())}")
        
        env_name = self.environments[tool_name]
        return self.run_in_env(
            env_name=env_name,
            command=command,
            cwd=cwd,
            timeout=timeout,
            capture_output=capture_output,
            text=text,
            check=check,
            log_callback=log_callback,
            stream_output=stream_output
        )
    
    def run_tool_async(
        self,
        tool_name: str,
        command: Union[str, List[str]],
        cwd: Optional[Union[str, Path]] = None,
        timeout: Optional[int] = None,
        log_callback: Optional[Callable[[str], None]] = None,
        result_storage: Optional[Dict[str, Any]] = None,
        stream_output: bool = True
    ) -> threading.Thread:
        """
        Run a tool command asynchronously in a separate thread.
        
        Args:
            tool_name: Name of the tool
            command: Command to run
            cwd: Working directory
            timeout: Timeout in seconds
            log_callback: Optional logging callback
            result_storage: Dictionary to store results
            stream_output: Whether to stream output in real-time (default True for async)
            
        Returns:
            Thread object running the command
        """
        if result_storage is None:
            result_storage = {}
        
        def run_async():
            try:
                result = self.run_tool(
                    tool_name=tool_name,
                    command=command,
                    cwd=cwd,
                    timeout=timeout,
                    capture_output=True,
                    text=True,
                    check=False,
                    log_callback=log_callback,
                    stream_output=stream_output
                )
                
                result_storage.update({
                    "status": "success" if result.returncode == 0 else "error",
                    "returncode": result.returncode,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "command": command,
                    "tool": tool_name
                })
                
            except subprocess.TimeoutExpired:
                result_storage.update({
                    "status": "timeout",
                    "error": f"Command timed out after {timeout} seconds",
                    "command": command,
                    "tool": tool_name
                })
            except Exception as e:
                result_storage.update({
                    "status": "error",
                    "error": str(e),
                    "command": command,
                    "tool": tool_name
                })
        
        thread = threading.Thread(target=run_async)
        thread.daemon = True
        thread.start()
        return thread
    
    def check_environment(self, env_name: str) -> bool:
        """
        Check if a conda environment exists and is accessible.
        
        Args:
            env_name: Name of the conda environment
            
        Returns:
            True if environment exists and is accessible, False otherwise
        """
        try:
            # Prefer using resolved runner to avoid PATH issues
            run_cmd = self._build_conda_run_cmd(env_name, ["python", "--version"])
            result = subprocess.run(
                run_cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            if result.returncode == 0:
                return True

            # Fallback: if python is not present in env, at least verify the env exists via `conda env list --json`
            list_cmd = [self._runner_executable or "conda", "env", "list", "--json"]
            list_result = subprocess.run(
                list_cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            if list_result.returncode == 0:
                try:
                    data = json.loads(list_result.stdout or "{}")
                    # The JSON payload contains either 'envs' (paths) or 'default_prefix'
                    env_paths: List[str] = data.get("envs", [])
                    # Determine if any env path ends with the env_name
                    for env_path in env_paths:
                        if env_path.endswith(os.path.sep + env_name) or os.path.basename(env_path) == env_name:
                            return True
                except Exception:
                    pass
            return False
        except Exception:
            return False
    
    def check_all_environments(self) -> Dict[str, bool]:
        """
        Check all tool environments for availability.
        
        Returns:
            Dictionary mapping environment names to availability status
        """
        status = {}
        for tool, env_name in self.environments.items():
            status[env_name] = self.check_environment(env_name)
            logger.info(f"Environment {env_name} ({'available' if status[env_name] else 'unavailable'})")
        return status
    
    def get_environment_for_tool(self, tool_name: str) -> str:
        """Get the environment name for a specific tool."""
        if tool_name not in self.environments:
            raise ValueError(f"Unknown tool: {tool_name}")
        return self.environments[tool_name]

# Global instance for easy access
env_manager = EnvironmentManager()

# Convenience functions for backward compatibility
def run_in_env(env_name: str, command: Union[str, List[str]], **kwargs) -> subprocess.CompletedProcess:
    """Convenience function to run command in specific environment."""
    return env_manager.run_in_env(env_name, command, **kwargs)

def run_tool(tool_name: str, command: Union[str, List[str]], **kwargs) -> subprocess.CompletedProcess:
    """Convenience function to run tool command."""
    return env_manager.run_tool(tool_name, command, **kwargs)

def run_tool_async(tool_name: str, command: Union[str, List[str]], **kwargs) -> threading.Thread:
    """Convenience function to run tool command asynchronously."""
    return env_manager.run_tool_async(tool_name, command, **kwargs) 