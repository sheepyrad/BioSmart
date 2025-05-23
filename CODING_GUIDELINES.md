# Coding Guidelines

## Directory Structure Rules

### External Dependencies (`src/`)
The `src/` directory contains external packages that are essential dependencies of our pipeline:
- DiffSBDD (Diffusion-based generative model)
- Synformer (Retrosynthesis analysis)
- VFU (Virtual Flow Unity for docking)
- LUDe_v2 (For Decoy Generation)

⚠️ **IMPORTANT**: Never modify any files in the `src/` directory. These are external dependencies that:
- Are maintained by their respective teams
- Require specific versioning for reproducibility
- May be updated through proper dependency management
- Are essential for pipeline stability

If you need to modify functionality from these packages:
1. Create wrapper functions in the `utils/` directory
2. Use inheritance or composition patterns

### Utility Functions (`utils/`)
The `utils/` directory is where all custom code should be placed:
- Create new utility modules here
- Modify existing utility functions
- Add wrapper functions for external package functionality

## Code Style

### Python Version
- Use Python 3.10+ features

### Imports
Follow this import order:
```python
# 1. Standard library imports
import os
import sys
from pathlib import Path

# 2. Third-party packages
import numpy as np
import pandas as pd
from rdkit import Chem

# 3. Local imports
from utils.ligand_generation import run_ligand_generation
from utils.medchem_filter import filter_by_pass_count
```

### Formatting
- Indentation: 4 spaces (no tabs)
- Line length: 120 characters maximum
- Use trailing commas in multi-line structures
- Add two blank lines before class definitions
- Add one blank line before function definitions

### Naming Conventions
```python
# Constants
MAX_ATTEMPTS = 3
DEFAULT_TIMEOUT = 300

# Functions and variables
def calculate_rmsd(structure_a, structure_b):
    atomic_positions = get_coordinates(structure_a)

# Classes
class MoleculeGenerator:
    def __init__(self):
        self.initialized = False
```

### Type Hints
Use type hints for better code documentation:
```python
from typing import List, Dict, Optional, Union

def process_molecules(
    smiles_list: List[str],
    max_attempts: int = 3,
    timeout: Optional[float] = None
) -> Dict[str, float]:
    """Process a list of SMILES strings."""
    pass
```

### Documentation
Use docstrings for all functions and classes:
```python
def run_docking(
    molecule: str,
    receptor: str,
    center: tuple[float, float, float]
) -> tuple[float, str]:
    """
    Run molecular docking simulation.

    Args:
        molecule: SMILES string of the ligand
        receptor: Path to the receptor PDB file
        center: Docking box center coordinates (x, y, z)

    Returns:
        tuple: (docking_score, pose_path)
            - docking_score (float): Best docking score
            - pose_path (str): Path to the best pose structure

    Raises:
        ValueError: If molecule or receptor file is invalid
        RuntimeError: If docking fails
    """
    pass
```

### Error Handling
```python
try:
    result = process_molecule(smiles)
except ValueError as e:
    logger.error(f"Invalid molecule format: {e}")
    return None
except RuntimeError as e:
    logger.error(f"Processing failed: {e}")
    return None
except Exception as e:
    logger.critical(f"Unexpected error: {e}")
    raise
```

### Logging
Use the Python logging module with appropriate levels:
```python
import logging

logger = logging.getLogger(__name__)

def process_compound(compound_id: str) -> None:
    logger.debug(f"Starting processing of {compound_id}")
    logger.info(f"Generated molecule for {compound_id}")
    logger.warning(f"Unusual property detected in {compound_id}")
    logger.error(f"Failed to process {compound_id}")
```

## Testing

### Unit Tests
- Write tests for all new functionality
- Use pytest as the testing framework
- Place tests in a `unit_tests/` directory
- Name test files with `test_` prefix

```python
# tests/test_molecule_generation.py
def test_molecule_generation():
    generator = MoleculeGenerator()
    mol = generator.generate()
    assert mol is not None
    assert Chem.MolToSmiles(mol) != ""
```

### Integration Tests
- Test interactions between components
- Use realistic but simplified inputs
- Mock external services when appropriate

## Version Control

### Git Practices
- Use feature branches for new development
- Write descriptive commit messages
- Keep commits focused and atomic
- Rebase feature branches on main before merging

### Commit Message Format
```
[component] Brief description of change

Detailed explanation of what changed and why.
Include any important context or related issues.

Fixes #123
```

## Pipeline Development

### Adding New Features
1. Create new utility modules in `utils/`
2. Update `utils/__init__.py` to expose new functionality
3. Add appropriate logging and error handling
4. Update documentation and tests
5. Add entry in CHANGELOG.md

### Modifying Existing Features
1. Ensure changes don't break existing functionality
2. Update affected tests
3. Document changes in CHANGELOG.md
4. Update relevant documentation

## Performance Considerations

### Memory Management
- Use generators for large datasets
- Clean up temporary files
- Release resources properly
- Monitor memory usage in long-running processes

### Parallel Processing
- Use threading for I/O-bound operations
- Implement proper resource locking
- Handle process termination gracefully

## Security

### Data Protection
- Never commit sensitive data (API keys, credentials)
- Use environment variables for configuration
- Validate all input data
- Sanitize file paths

### Code Security
- Keep dependencies updated
- Review security advisories- Implement proper input validation
- Use secure file operations 