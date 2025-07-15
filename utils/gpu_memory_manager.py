"""
GPU Memory Management Utility

This module provides centralized GPU memory management functionality
to prevent CUDA out of memory errors during long-running pipelines.
"""

import gc
import logging
import sys
import time
from typing import Optional, Dict, Any

# Get logger for this module
logger = logging.getLogger(__name__)

# Try to import torch for CUDA memory management
try:
    import torch
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False
    logger.warning("PyTorch not available - GPU memory management will be disabled")

class GPUMemoryManager:
    """Manages GPU memory to prevent memory leaks during pipeline execution."""
    
    def __init__(self, enable_logging: bool = True):
        """
        Initialize GPU memory manager.
        
        Args:
            enable_logging: Whether to enable detailed logging of memory operations
        """
        self.enable_logging = enable_logging
        self.memory_snapshots = []
        
    def clear_memory(self) -> bool:
        """
        Clear GPU memory cache and run garbage collection.
        
        Returns:
            True if memory was cleared successfully, False otherwise
        """
        if not TORCH_AVAILABLE or not torch.cuda.is_available():
            return False
            
        try:
            # Clear PyTorch CUDA cache
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
            
            # Force Python garbage collection
            gc.collect()
            
            if self.enable_logging:
                logger.debug("GPU memory cache cleared successfully")
            return True
            
        except Exception as e:
            if self.enable_logging:
                logger.warning(f"Failed to clear GPU memory cache: {e}")
            return False
    
    def get_memory_info(self) -> Dict[str, float]:
        """
        Get current GPU memory usage information.
        
        Returns:
            Dictionary containing memory usage information in GB
        """
        if not TORCH_AVAILABLE or not torch.cuda.is_available():
            return {"allocated": 0.0, "reserved": 0.0, "total": 0.0, "free": 0.0}
            
        try:
            allocated = torch.cuda.memory_allocated() / 1024**3  # GB
            reserved = torch.cuda.memory_reserved() / 1024**3   # GB
            total = torch.cuda.get_device_properties(0).total_memory / 1024**3  # GB
            free = total - allocated
            
            return {
                "allocated": allocated,
                "reserved": reserved,
                "total": total,
                "free": free
            }
            
        except Exception as e:
            if self.enable_logging:
                logger.warning(f"Failed to get GPU memory info: {e}")
            return {"allocated": 0.0, "reserved": 0.0, "total": 0.0, "free": 0.0}
    
    def log_memory_usage(self, prefix: str = "GPU Memory"):
        """
        Log current GPU memory usage.
        
        Args:
            prefix: Prefix string for the log message
        """
        if not self.enable_logging:
            return
            
        memory_info = self.get_memory_info()
        
        if memory_info["total"] > 0:
            logger.info(
                f"{prefix} - "
                f"Allocated: {memory_info['allocated']:.2f}GB, "
                f"Reserved: {memory_info['reserved']:.2f}GB, "
                f"Free: {memory_info['free']:.2f}GB, "
                f"Total: {memory_info['total']:.2f}GB"
            )
        else:
            logger.info(f"{prefix} - No GPU available or PyTorch not installed")
    
    def take_memory_snapshot(self, label: str):
        """
        Take a snapshot of current memory usage for later analysis.
        
        Args:
            label: Label for this snapshot
        """
        memory_info = self.get_memory_info()
        snapshot = {
            "label": label,
            "timestamp": time.time(),
            "memory_info": memory_info
        }
        self.memory_snapshots.append(snapshot)
        
        if self.enable_logging:
            logger.debug(f"Memory snapshot taken: {label}")
    
    def get_memory_snapshots(self) -> list:
        """
        Get all memory snapshots taken so far.
        
        Returns:
            List of memory snapshots
        """
        return self.memory_snapshots.copy()
    
    def clear_snapshots(self):
        """Clear all memory snapshots."""
        self.memory_snapshots.clear()
        if self.enable_logging:
            logger.debug("Memory snapshots cleared")
    
    def check_memory_growth(self, threshold_gb: float = 1.0) -> bool:
        """
        Check if memory usage has grown significantly since the last snapshot.
        
        Args:
            threshold_gb: Memory growth threshold in GB
            
        Returns:
            True if memory growth exceeds threshold, False otherwise
        """
        if len(self.memory_snapshots) < 2:
            return False
            
        current_memory = self.get_memory_info()
        last_snapshot = self.memory_snapshots[-1]
        
        growth = current_memory["allocated"] - last_snapshot["memory_info"]["allocated"]
        
        if growth > threshold_gb:
            if self.enable_logging:
                logger.warning(f"Memory growth detected: {growth:.2f}GB since last snapshot")
            return True
            
        return False
    
    def force_cleanup_if_needed(self, max_memory_gb: float = 20.0) -> bool:
        """
        Force cleanup if memory usage exceeds threshold.
        
        Args:
            max_memory_gb: Maximum allowed memory usage in GB
            
        Returns:
            True if cleanup was performed, False otherwise
        """
        memory_info = self.get_memory_info()
        
        if memory_info["allocated"] > max_memory_gb:
            if self.enable_logging:
                logger.warning(f"Memory usage ({memory_info['allocated']:.2f}GB) exceeds threshold ({max_memory_gb}GB), forcing cleanup")
            
            return self.clear_memory()
            
        return False
    
    def __enter__(self):
        """Context manager entry."""
        self.take_memory_snapshot("context_start")
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit with cleanup."""
        self.take_memory_snapshot("context_end")
        self.clear_memory()

# Global instance for easy access
gpu_memory_manager = GPUMemoryManager()

# Convenience functions
def clear_gpu_memory() -> bool:
    """Clear GPU memory cache."""
    return gpu_memory_manager.clear_memory()

def log_gpu_memory_usage(prefix: str = "GPU Memory"):
    """Log current GPU memory usage."""
    gpu_memory_manager.log_memory_usage(prefix)

def get_gpu_memory_info() -> Dict[str, float]:
    """Get current GPU memory usage information."""
    return gpu_memory_manager.get_memory_info()

def take_gpu_memory_snapshot(label: str):
    """Take a snapshot of current memory usage."""
    gpu_memory_manager.take_memory_snapshot(label)

def force_cleanup_if_needed(max_memory_gb: float = 20.0) -> bool:
    """Force cleanup if memory usage exceeds threshold."""
    return gpu_memory_manager.force_cleanup_if_needed(max_memory_gb) 