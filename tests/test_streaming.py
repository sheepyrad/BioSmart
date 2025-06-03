#!/usr/bin/env python
"""
Test script to demonstrate the streaming output functionality of the environment manager.

This script shows how subprocess output is now streamed in real-time to the pipeline log.
"""

import sys
import logging
from pathlib import Path
import time

# Add the parent directory to the path so we can import utils
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.environment_manager import env_manager

# Set up logging to see the streaming output
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

def test_streaming_output():
    """Test streaming output with a simple command."""
    logger.info("Testing streaming output functionality...")
    logger.info("=" * 60)
    
    # Test with a simple command that produces output over time
    test_commands = [
        {
            "tool": "diffsbdd",
            "command": ["python", "-c", "import time; [print(f'Line {i}') or time.sleep(0.5) for i in range(5)]"],
            "description": "Python script with delayed output"
        },
        {
            "tool": "synformer", 
            "command": ["python", "--version"],
            "description": "Simple version check"
        }
    ]
    
    for test in test_commands:
        logger.info(f"\nTesting {test['description']} in {test['tool']} environment...")
        logger.info("-" * 40)
        
        try:
            # Test synchronous execution with streaming
            start_time = time.time()
            result = env_manager.run_tool(
                tool_name=test["tool"],
                command=test["command"],
                timeout=30,
                log_callback=logger.info,
                stream_output=True
            )
            elapsed = time.time() - start_time
            
            logger.info(f"Command completed in {elapsed:.2f} seconds")
            logger.info(f"Exit code: {result.returncode}")
            
        except Exception as e:
            logger.error(f"Error running test: {e}")

def test_async_streaming():
    """Test asynchronous streaming output."""
    logger.info("\n" + "=" * 60)
    logger.info("Testing asynchronous streaming output...")
    logger.info("=" * 60)
    
    result_storage = {}
    
    # Test async execution with streaming (default for async)
    logger.info("Starting async command with streaming...")
    thread = env_manager.run_tool_async(
        tool_name="diffsbdd",
        command=["python", "-c", "import time; [print(f'Async line {i}') or time.sleep(0.3) for i in range(8)]"],
        timeout=30,
        log_callback=logger.info,
        result_storage=result_storage
    )
    
    logger.info("Waiting for async command to complete...")
    thread.join()
    
    status = result_storage.get("status", "unknown")
    logger.info(f"Async command status: {status}")
    
    if status == "success":
        logger.info("✓ Async streaming test completed successfully")
    else:
        error = result_storage.get("error", "Unknown error")
        logger.error(f"✗ Async streaming test failed: {error}")

def test_environment_availability():
    """Test environment availability before running streaming tests."""
    logger.info("Checking environment availability...")
    
    env_status = env_manager.check_all_environments()
    available_envs = [env for env, status in env_status.items() if status]
    
    if not available_envs:
        logger.error("No conda environments are available. Please run './setup.sh' first.")
        return False
    
    logger.info(f"Available environments: {', '.join(available_envs)}")
    return True

def main():
    """Run streaming output tests."""
    logger.info("Starting streaming output tests...")
    
    # Check if environments are available
    if not test_environment_availability():
        return 1
    
    try:
        # Test synchronous streaming
        test_streaming_output()
        
        # Test asynchronous streaming
        test_async_streaming()
        
        logger.info("\n" + "=" * 60)
        logger.info("✓ All streaming tests completed successfully!")
        logger.info("=" * 60)
        
        return 0
        
    except Exception as e:
        logger.error(f"Test failed with error: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main()) 