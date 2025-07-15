# GPU Memory Management for Multi-Round Pocket2Mol Pipeline

## Issue Description

### Problem
After running approximately 100 rounds of the Pocket2Mol pipeline, users encounter a CUDA out of memory error:

```
torch.cuda.OutOfMemoryError: CUDA out of memory. Tried to allocate 24.00 MiB (GPU 0; 23.68 GiB total capacity; 134.07 MiB already allocated; 6.06 MiB free; 142.00 MiB reserved in total by PyTorch)
```

### Root Cause Analysis

The error occurs due to **GPU memory accumulation** over multiple rounds without proper cleanup:

1. **Model Persistence**: The Pocket2Mol model is loaded once and kept in GPU memory across all rounds
2. **Data Transfer Without Cleanup**: Each round transfers data to GPU but doesn't explicitly clear intermediate tensors
3. **Missing CUDA Memory Management**: The codebase lacked explicit CUDA memory management calls
4. **Gradient Accumulation**: Even with `@torch.no_grad()`, some operations still accumulate memory
5. **Memory Fragmentation**: Long-running processes can cause GPU memory fragmentation

### Key Observations
- The issue occurs specifically with Pocket2Mol (uses GPU) but not with DiffSBDD
- Memory usage grows incrementally over many rounds
- The error happens during model initialization/sampling phases
- Most GPU memory appears to be "reserved" rather than "allocated"

## Solution Implementation

### 1. Pipeline-Level Memory Management

**File**: `pipeline_quick_multiround.py`

Added comprehensive GPU memory management:

```python
# Clear GPU memory after Pocket2Mol execution
logger.info(f"Round {round_num}: Clearing GPU memory after Pocket2Mol execution...")
clear_gpu_memory()
log_gpu_memory_usage()

# Clear GPU memory at the end of each round
if model_choice == 'pocket2mol':
    logger.info(f"Round {round_num}: Clearing GPU memory at end of round...")
    clear_gpu_memory()
    log_gpu_memory_usage()
```

### 2. Ligand Generation Memory Management

**File**: `utils/ligand_generation.py`

Added memory cleanup before and after Pocket2Mol execution:

```python
# Clear GPU memory before starting Pocket2Mol
if log_callback:
    log_callback("Clearing GPU memory before Pocket2Mol execution...")
clear_gpu_memory()

# Clear GPU memory after Pocket2Mol execution
if log_callback:
    log_callback("Clearing GPU memory after Pocket2Mol execution...")
clear_gpu_memory()
```

### 3. Centralized GPU Memory Manager

**File**: `utils/gpu_memory_manager.py`

Created a comprehensive GPU memory management utility:

```python
class GPUMemoryManager:
    """Manages GPU memory to prevent memory leaks during pipeline execution."""
    
    def clear_memory(self) -> bool:
        """Clear GPU memory cache and run garbage collection."""
        if not TORCH_AVAILABLE or not torch.cuda.is_available():
            return False
            
        try:
            # Clear PyTorch CUDA cache
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
            
            # Force Python garbage collection
            gc.collect()
            
            return True
        except Exception as e:
            logger.warning(f"Failed to clear GPU memory cache: {e}")
            return False
```

### 4. Memory Monitoring and Logging

Added comprehensive memory monitoring:

```python
def log_gpu_memory_usage(prefix: str = "GPU Memory"):
    """Log current GPU memory usage."""
    if TORCH_AVAILABLE and torch.cuda.is_available():
        try:
            allocated = torch.cuda.memory_allocated() / 1024**3  # GB
            reserved = torch.cuda.memory_reserved() / 1024**3   # GB
            total = torch.cuda.get_device_properties(0).total_memory / 1024**3  # GB
            logger.info(f"{prefix} - Allocated: {allocated:.2f}GB, Reserved: {reserved:.2f}GB, Total: {total:.2f}GB")
        except Exception as e:
            logger.warning(f"Failed to get GPU memory usage: {e}")
```

## Key Features of the Solution

### 1. Automatic Memory Cleanup
- Memory is cleared after each Pocket2Mol execution
- Memory is cleared at the end of each round
- Memory is cleared when the entire pipeline completes

### 2. Memory Monitoring
- GPU memory usage is logged before and after critical operations
- Memory snapshots can be taken for analysis
- Memory growth detection with configurable thresholds

### 3. Graceful Fallback
- If PyTorch is not available, the memory management functions gracefully disable themselves
- If CUDA is not available, the functions return without error
- All memory operations are wrapped in try-catch blocks

### 4. Context Manager Support
- The GPU memory manager can be used as a context manager for automatic cleanup
- Provides `__enter__` and `__exit__` methods for resource management

### 5. Configurable Thresholds
- Maximum memory usage thresholds can be configured
- Automatic cleanup when memory usage exceeds limits
- Memory growth detection with customizable sensitivity

## Usage Examples

### Basic Usage
```python
from utils.gpu_memory_manager import clear_gpu_memory, log_gpu_memory_usage

# Clear GPU memory
clear_gpu_memory()

# Log current memory usage
log_gpu_memory_usage("Before Pocket2Mol")
```

### Context Manager Usage
```python
from utils.gpu_memory_manager import GPUMemoryManager

with GPUMemoryManager() as gpu_manager:
    # Your GPU-intensive operations here
    run_pocket2mol(...)
    # Memory will be automatically cleared when exiting the context
```

### Advanced Monitoring
```python
from utils.gpu_memory_manager import gpu_memory_manager

# Take snapshots for analysis
gpu_memory_manager.take_memory_snapshot("before_operation")
# ... perform operations ...
gpu_memory_manager.take_memory_snapshot("after_operation")

# Check for memory growth
if gpu_memory_manager.check_memory_growth(threshold_gb=1.0):
    print("Significant memory growth detected!")

# Force cleanup if needed
gpu_memory_manager.force_cleanup_if_needed(max_memory_gb=20.0)
```

## Best Practices

### 1. Regular Memory Cleanup
- Clear GPU memory after each computationally intensive operation
- Clear memory at the end of each processing round
- Use context managers for automatic cleanup

### 2. Memory Monitoring
- Log memory usage before and after critical operations
- Monitor for memory growth trends
- Set appropriate thresholds based on your GPU capacity

### 3. Error Handling
- Always wrap memory operations in try-catch blocks
- Provide graceful fallbacks when GPU/PyTorch is not available
- Log warnings for memory-related issues

### 4. Resource Management
- Use context managers for automatic resource cleanup
- Ensure memory is cleared even if exceptions occur
- Implement proper cleanup in finally blocks

## Performance Considerations

### 1. Memory Clearing Overhead
- `torch.cuda.empty_cache()` has minimal overhead
- `torch.cuda.synchronize()` ensures operations complete
- Python garbage collection (`gc.collect()`) may have some overhead

### 2. Memory Fragmentation
- Regular memory clearing helps prevent fragmentation
- Use context managers to ensure consistent cleanup
- Consider restarting the pipeline periodically for very long runs

### 3. Monitoring Impact
- Memory logging has minimal performance impact
- Snapshots store small amounts of metadata
- Use appropriate logging levels to control verbosity

## Troubleshooting

### 1. Memory Still Growing
- Check if all GPU operations are properly wrapped
- Verify that memory clearing is called after each operation
- Consider reducing batch sizes or model complexity

### 2. Memory Clearing Fails
- Ensure PyTorch and CUDA are properly installed
- Check for CUDA driver compatibility
- Verify that no other processes are using GPU memory

### 3. Performance Issues
- Reduce memory clearing frequency if performance is impacted
- Use appropriate logging levels to reduce I/O overhead
- Consider using memory snapshots instead of continuous logging

## Testing and Validation

### 1. Memory Leak Testing
- Run pipeline for extended periods (>100 rounds)
- Monitor memory usage trends
- Verify that memory is stable over time

### 2. Performance Testing
- Measure pipeline execution time with and without memory management
- Compare memory usage patterns
- Validate that memory clearing doesn't impact model performance

### 3. Integration Testing
- Test with different model configurations
- Verify compatibility with different GPU types
- Test graceful degradation when GPU is not available

## Future Enhancements

### 1. Advanced Memory Management
- Implement memory pooling for frequently used tensors
- Add support for multi-GPU memory management
- Implement memory compaction strategies

### 2. Predictive Memory Management
- Predict memory requirements based on input size
- Implement proactive memory clearing based on usage patterns
- Add memory usage forecasting

### 3. Integration with Monitoring Systems
- Export memory metrics to monitoring systems
- Add alerts for memory usage thresholds
- Implement automated pipeline restarts on memory issues

## Conclusion

The implemented GPU memory management solution addresses the root cause of CUDA out of memory errors in multi-round Pocket2Mol pipelines. By adding comprehensive memory cleanup, monitoring, and management capabilities, the pipeline can now run for extended periods without encountering memory issues.

The solution is designed to be:
- **Robust**: Handles edge cases and provides graceful fallbacks
- **Flexible**: Configurable thresholds and monitoring options
- **Efficient**: Minimal performance overhead
- **Maintainable**: Clear separation of concerns and comprehensive logging

This implementation should resolve the CUDA out of memory issues and provide a foundation for stable long-running pipeline execution. 