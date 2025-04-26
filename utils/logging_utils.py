"""
Utility functions for logging in the drug discovery pipeline.
"""

import logging
import sys
import threading
from pathlib import Path

# Get logger for this module
logger = logging.getLogger(__name__)

class ThreadSafeRotatingFileHandler(logging.FileHandler):
    """A file handler that is thread-safe and properly handles file descriptor issues"""
    def __init__(self, filename, mode='a', encoding=None, delay=False):
        super().__init__(filename, mode, encoding, delay)
        self._lock = threading.RLock()
        
    def emit(self, record):
        with self._lock:
            try:
                super().emit(record)
            except Exception:
                # If there's an error with the file descriptor, reopen the file
                try:
                    self.close()
                    self.stream = self._open()
                    super().emit(record)
                except Exception:
                    self.handleError(record)

def setup_logging(out_dir: Path) -> None:
    """
    Set up logging with both console and file output in the specified directory.
    
    Args:
        out_dir: Output directory path where logs will be stored
    """
    # Create logs directory
    logs_dir = out_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    
    # Configure the root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    
    # Create handlers
    console_handler = logging.StreamHandler(sys.stdout)
    file_handler = ThreadSafeRotatingFileHandler(
        str(logs_dir / "quick_pipeline.log"),
        mode="w"
    )
    
    # Set formatter
    formatter = logging.Formatter("[%(asctime)s] %(name)s - %(levelname)s - %(message)s")
    console_handler.setFormatter(formatter)
    file_handler.setFormatter(formatter)
    
    # Remove any existing handlers from both root and module logger
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    module_logger = logging.getLogger("pipeline_quick_multiround")
    for handler in module_logger.handlers[:]:
        module_logger.removeHandler(handler)
    
    # Add handlers to root logger
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)
    
    # Start logging
    logger.info("Starting quick pipeline...")
    logger.info(f"Logs will be saved to: {logs_dir}") 