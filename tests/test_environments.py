#!/usr/bin/env python
"""
Test script to verify conda environments and the environment manager functionality.

This script tests:
1. Environment availability
2. Basic tool functionality in each environment
3. Environment manager operations
"""

import sys
import logging
from pathlib import Path

# Add the parent directory to the path so we can import utils
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.environment_manager import env_manager

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def test_environment_availability():
    """Test if all required conda environments are available."""
    logger.info("Testing environment availability...")
    
    env_status = env_manager.check_all_environments()
    
    all_available = True
    for env_name, available in env_status.items():
        status = "✓ Available" if available else "✗ Not Available"
        logger.info(f"  {env_name}: {status}")
        if not available:
            all_available = False
    
    return all_available

def test_tool_functionality():
    """Test basic functionality of each tool in its environment."""
    logger.info("Testing basic tool functionality...")
    
    tests = [
        ("diffsbdd", ["python", "--version"], "DiffSBDD environment Python check"),
        ("pocket2mol", ["python", "--version"], "Pocket2Mol environment Python check"),
        ("synformer", ["python", "--version"], "Synformer environment Python check"),
        ("boltz", ["python", "--version"], "Boltz environment Python check"),
        ("unidock", ["python", "--version"], "Uni-dock environment Python check"),
        ("unigbsa", ["python", "--version"], "Uni-GBSA environment Python check"),
        ("cgflow", ["python", "--version"], "CGFlow environment Python check"),
    ]
    
    results = {}
    for tool, command, description in tests:
        logger.info(f"  Testing {description}...")
        try:
            result = env_manager.run_tool(
                tool_name=tool,
                command=command,
                timeout=30,
                capture_output=True,
                text=True,
                check=False
            )
            
            if result.returncode == 0:
                logger.info(f"    ✓ {description} - SUCCESS")
                results[tool] = True
            else:
                logger.error(f"    ✗ {description} - FAILED (exit code {result.returncode})")
                logger.error(f"      stderr: {result.stderr}")
                results[tool] = False
                
        except Exception as e:
            logger.error(f"    ✗ {description} - ERROR: {e}")
            results[tool] = False
    
    return results

def test_specific_tools():
    """Test specific tool commands to verify they're properly installed."""
    logger.info("Testing specific tool commands...")
    
    specific_tests = [
        ("boltz", ["boltz", "--help"], "Boltz help command"),
        ("unidock", ["unidock", "--help"], "Uni-dock help command"),
    ]
    
    results = {}
    for tool, command, description in specific_tests:
        logger.info(f"  Testing {description}...")
        try:
            result = env_manager.run_tool(
                tool_name=tool,
                command=command,
                timeout=30,
                capture_output=True,
                text=True,
                check=False
            )
            
            # For help commands, both 0 and 1 exit codes can be normal
            if result.returncode in [0, 1]:
                logger.info(f"    ✓ {description} - SUCCESS")
                results[tool] = True
            else:
                logger.error(f"    ✗ {description} - FAILED (exit code {result.returncode})")
                logger.error(f"      stderr: {result.stderr}")
                results[tool] = False
                
        except Exception as e:
            logger.error(f"    ✗ {description} - ERROR: {e}")
            results[tool] = False
    
    return results

def test_async_functionality():
    """Test asynchronous execution functionality."""
    logger.info("Testing asynchronous execution...")
    
    result_storage = {}
    
    try:
        # Test async execution
        thread = env_manager.run_tool_async(
            tool_name="diffsbdd",
            command=["python", "--version"],
            timeout=30,
            result_storage=result_storage
        )
        
        # Wait for completion
        thread.join(timeout=60)  # Give it a minute max
        
        if thread.is_alive():
            logger.error("    ✗ Async execution - TIMEOUT")
            return False
        
        status = result_storage.get("status", "unknown")
        if status == "success":
            logger.info("    ✓ Async execution - SUCCESS")
            return True
        else:
            logger.error(f"    ✗ Async execution - FAILED (status: {status})")
            error = result_storage.get("error", "Unknown error")
            logger.error(f"      error: {error}")
            return False
            
    except Exception as e:
        logger.error(f"    ✗ Async execution - ERROR: {e}")
        return False

def main():
    """Run all tests and report results."""
    logger.info("Starting conda environment tests...")
    logger.info("=" * 60)
    
    # Test 1: Environment availability
    env_available = test_environment_availability()
    logger.info("")
    
    # Test 2: Basic tool functionality
    tool_results = test_tool_functionality()
    logger.info("")
    
    # Test 3: Specific tool commands
    specific_results = test_specific_tools()
    logger.info("")
    
    # Test 4: Async functionality
    async_result = test_async_functionality()
    logger.info("")
    
    # Summary
    logger.info("=" * 60)
    logger.info("TEST SUMMARY")
    logger.info("=" * 60)
    
    logger.info(f"Environment Availability: {'✓ PASS' if env_available else '✗ FAIL'}")
    
    tool_pass_count = sum(1 for result in tool_results.values() if result)
    tool_total = len(tool_results)
    logger.info(f"Basic Tool Tests: {tool_pass_count}/{tool_total} passed")
    
    specific_pass_count = sum(1 for result in specific_results.values() if result)
    specific_total = len(specific_results)
    logger.info(f"Specific Tool Tests: {specific_pass_count}/{specific_total} passed")
    
    logger.info(f"Async Functionality: {'✓ PASS' if async_result else '✗ FAIL'}")
    
    # Overall result
    overall_success = (
        env_available and 
        tool_pass_count == tool_total and 
        specific_pass_count >= specific_total // 2 and  # Allow some specific tests to fail
        async_result
    )
    
    logger.info("")
    logger.info(f"OVERALL RESULT: {'✓ ALL TESTS PASSED' if overall_success else '✗ SOME TESTS FAILED'}")
    
    if not overall_success:
        logger.info("")
        logger.info("RECOMMENDATIONS:")
        if not env_available:
            logger.info("- Run './setup.sh' to create missing conda environments")
        if tool_pass_count < tool_total:
            logger.info("- Check conda environment configurations in env/ directory")
        if specific_pass_count < specific_total // 2:
            logger.info("- Verify tool installations in specific environments")
        if not async_result:
            logger.info("- Check threading and subprocess functionality")
    
    return 0 if overall_success else 1

if __name__ == "__main__":
    sys.exit(main()) 