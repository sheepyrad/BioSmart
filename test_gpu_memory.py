#!/usr/bin/env python
"""
Test script to verify GPU memory management works with environment manager.
"""

import logging
import sys
from pathlib import Path

# Add utils to path
sys.path.insert(0, str(Path(__file__).parent / "utils"))

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

def test_gpu_memory_management():
    """Test GPU memory management functionality."""
    logger.info("Testing GPU memory management...")
    
    try:
        from utils.gpu_memory_manager import (
            gpu_memory_manager, 
            clear_gpu_memory, 
            log_gpu_memory_usage,
            is_gpu_available
        )
        
        # Test GPU availability check
        logger.info("Checking GPU availability...")
        gpu_available = is_gpu_available()
        logger.info(f"GPU available: {gpu_available}")
        
        # Test memory info retrieval
        logger.info("Getting memory info...")
        memory_info = gpu_memory_manager.get_memory_info()
        logger.info(f"Memory info: {memory_info}")
        
        # Test memory usage logging
        logger.info("Logging memory usage...")
        log_gpu_memory_usage("Test")
        
        # Test memory clearing
        logger.info("Clearing GPU memory...")
        clear_result = clear_gpu_memory()
        logger.info(f"Memory clear result: {clear_result}")
        
        # Test memory usage after clearing
        logger.info("Logging memory usage after clearing...")
        log_gpu_memory_usage("After Clear")
        
        logger.info("GPU memory management test completed successfully!")
        return True
        
    except Exception as e:
        logger.error(f"GPU memory management test failed: {e}", exc_info=True)
        return False

if __name__ == "__main__":
    success = test_gpu_memory_management()
    sys.exit(0 if success else 1) 