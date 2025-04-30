import unittest
from unittest.mock import patch, MagicMock, call
import sys
import os
from pathlib import Path
import logging

# Add the project root to sys.path to allow importing utils
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Now import the function to test
from utils.redocking import redock_compound

# Disable logging for tests unless specifically needed
logging.disable(logging.CRITICAL)

class TestRedockCompound(unittest.TestCase):

    @patch('utils.redocking.shutil.copy2')
    @patch('utils.redocking.Path')
    @patch('utils.redocking.os.path.basename')
    @patch.dict(sys.modules, {'run_vf_unity': MagicMock()}) # Mock the module itself
    def test_redock_successful_with_receptor(self, mock_basename, mock_path, mock_copy2):
        """Test successful redocking when a receptor file is provided."""
        # --- Mock Setup ---
        # Mock Path objects and their methods
        mock_vfu_dir = MagicMock(spec=Path)
        mock_vfu_dir.exists.return_value = True
        mock_vfu_dir.resolve.return_value = '/fake/project/src/VFU'

        mock_input_dir = MagicMock(spec=Path)
        mock_input_dir.resolve.return_value = '/fake/project/input'

        mock_receptor_in_input = MagicMock(spec=Path)
        mock_receptor_in_input.exists.return_value = True
        mock_receptor_in_input.stat.return_value.st_mtime = 100 # Simulate file time

        mock_receptor_in_vfu_config = MagicMock(spec=Path)
        mock_receptor_in_vfu_config.exists.return_value = False # Force copy
        mock_receptor_in_vfu_config.stat.return_value.st_mtime = 50

        # Configure the Path mock to return specific instances based on __truediv__ calls
        def path_side_effect(*args, **kwargs):
            if args == (Path(__file__).parent.parent / "src" / "VFU",):
                 return mock_vfu_dir
            elif args == (Path(__file__).parent.parent / "input",):
                 return mock_input_dir
            elif args == (mock_input_dir, 'receptor.pdbqt'):
                 return mock_receptor_in_input
            elif args == (mock_vfu_dir / "config", 'receptor.pdbqt'):
                 return mock_receptor_in_vfu_config
            elif args == (mock_vfu_dir, "config"):
                 return mock_vfu_dir / "config" # Return a mock for chaining
            elif args == (mock_vfu_dir, "inputs"):
                 return mock_vfu_dir / "inputs"
            elif args == (mock_vfu_dir, "outputs"):
                 return mock_vfu_dir / "outputs"
            # Add more specific path constructions if needed
            return MagicMock() # Default mock for other Path uses

        mock_path.side_effect = path_side_effect
        mock_path.return_value = MagicMock(spec=Path) # Default return if not caught by side_effect

        # Mock os.path.basename
        mock_basename.return_value = 'receptor.pdbqt'

        # Mock the imported run_vf_unity.main function
        mock_vfu_main = sys.modules['run_vf_unity'].main
        mock_vfu_main.return_value = ({'pose': 1}, {'score': -8.5})

        # Mock the logger callback
        mock_log_callback = MagicMock()

        # --- Test Execution ---
        compound_id = 'test_mol'
        smiles = 'CCO'
        redock_params = ('qvina+nnscore2', 'nnscore2', 0, 0, 0, 20, 20, 20, 8, False, False)
        receptor_path = '/fake/project/input/receptor.pdbqt' # This path is only used for basename

        pose_out, score_out = redock_compound(
            compound_id, smiles, redock_params, receptor=receptor_path, log_callback=mock_log_callback
        )

        # --- Assertions ---
        self.assertEqual(pose_out, {'pose': 1})
        self.assertEqual(score_out, {'score': -8.5})
        mock_basename.assert_called_once_with(receptor_path)
        mock_receptor_in_input.exists.assert_called_once()
        # Check if copy was called because exists was False initially
        mock_copy2.assert_called_once_with(mock_receptor_in_input, mock_receptor_in_vfu_config)
        # Check if VFU main was called with correct args (including split program/score and absolute path)
        expected_receptor_vfu_path = str(mock_receptor_in_vfu_config.resolve())
        mock_vfu_main.assert_called_once_with(
            'qvina', 'nnscore2', 0, 0, 0, 20, 20, 20, 8, smiles, False, False, expected_receptor_vfu_path
        )
        # Check if path was added and removed from sys.path
        self.assertIn(call(f"Temporarily added {mock_vfu_dir.resolve()} to sys.path for VFU import."), mock_log_callback.call_args_list)
        self.assertIn(call(f"Removed {mock_vfu_dir.resolve()} from sys.path."), mock_log_callback.call_args_list)


    @patch('utils.redocking.Path')
    @patch.dict(sys.modules, {'run_vf_unity': MagicMock()})
    def test_redock_successful_no_receptor(self, mock_path):
        """Test successful redocking when no receptor file is provided."""
        # --- Mock Setup ---
        mock_vfu_dir = MagicMock(spec=Path)
        mock_vfu_dir.exists.return_value = True
        mock_vfu_dir.resolve.return_value = '/fake/project/src/VFU'

        mock_path.side_effect = lambda *args, **kwargs: mock_vfu_dir if args == (Path(__file__).parent.parent / "src" / "VFU",) else MagicMock()
        mock_path.return_value = MagicMock(spec=Path)

        mock_vfu_main = sys.modules['run_vf_unity'].main
        mock_vfu_main.return_value = ({'pose': 2}, {'score': -9.0})
        mock_log_callback = MagicMock()

        # --- Test Execution ---
        compound_id = 'test_mol_2'
        smiles = 'CCC'
        redock_params = ('qvina', 'vina', 1, 1, 1, 25, 25, 25, 16, False, False)

        pose_out, score_out = redock_compound(
            compound_id, smiles, redock_params, receptor=None, log_callback=mock_log_callback
        )

        # --- Assertions ---
        self.assertEqual(pose_out, {'pose': 2})
        self.assertEqual(score_out, {'score': -9.0})
        mock_vfu_main.assert_called_once_with(
            'qvina', 'vina', 1, 1, 1, 25, 25, 25, 16, smiles, False, False, None # Expect None for receptor path
        )
        # Check if path was added and removed from sys.path
        self.assertIn(call(f"Temporarily added {mock_vfu_dir.resolve()} to sys.path for VFU import."), mock_log_callback.call_args_list)
        self.assertIn(call(f"Removed {mock_vfu_dir.resolve()} from sys.path."), mock_log_callback.call_args_list)


    @patch('utils.redocking.Path')
    def test_vfu_dir_not_found(self, mock_path):
        """Test behavior when the VFU directory doesn't exist."""
        # --- Mock Setup ---
        mock_vfu_dir = MagicMock(spec=Path)
        mock_vfu_dir.exists.return_value = False # Simulate VFU dir not found
        mock_path.side_effect = lambda *args, **kwargs: mock_vfu_dir if args == (Path(__file__).parent.parent / "src" / "VFU",) else MagicMock()
        mock_log_callback = MagicMock()

        # --- Test Execution ---
        pose_out, score_out = redock_compound('c1', 'C', (None)*11, log_callback=mock_log_callback)

        # --- Assertions ---
        self.assertIsNone(pose_out)
        self.assertIsNone(score_out)
        mock_log_callback.assert_any_call(f"VFU directory not found at {mock_vfu_dir}. Please ensure it exists.")


    @patch('utils.redocking.shutil.copy2')
    @patch('utils.redocking.Path')
    @patch('utils.redocking.os.path.basename')
    def test_receptor_not_found_in_input(self, mock_basename, mock_path, mock_copy2):
        """Test behavior when the receptor file is not found in the input directory."""
        # --- Mock Setup ---
        mock_vfu_dir = MagicMock(spec=Path); mock_vfu_dir.exists.return_value = True
        mock_input_dir = MagicMock(spec=Path)
        mock_receptor_in_input = MagicMock(spec=Path)
        mock_receptor_in_input.exists.return_value = False # Simulate receptor not found

        def path_side_effect(*args, **kwargs):
            if args == (Path(__file__).parent.parent / "src" / "VFU",): return mock_vfu_dir
            elif args == (Path(__file__).parent.parent / "input",): return mock_input_dir
            elif args == (mock_input_dir, 'receptor.pdbqt'): return mock_receptor_in_input
            return MagicMock()

        mock_path.side_effect = path_side_effect
        mock_path.return_value = MagicMock(spec=Path)
        mock_basename.return_value = 'receptor.pdbqt'
        mock_log_callback = MagicMock()

        # --- Test Execution ---
        pose_out, score_out = redock_compound(
            'c1', 'C', (None)*11, receptor='/fake/receptor.pdbqt', log_callback=mock_log_callback
        )

        # --- Assertions ---
        self.assertIsNone(pose_out)
        self.assertIsNone(score_out)
        mock_receptor_in_input.exists.assert_called_once()
        mock_copy2.assert_not_called() # Copy should not be attempted
        mock_log_callback.assert_any_call(f"Receptor file 'receptor.pdbqt' not found in input directory at {mock_receptor_in_input}. Please place it there.")


    @patch('utils.redocking.shutil.copy2')
    @patch('utils.redocking.Path')
    @patch('utils.redocking.os.path.basename')
    def test_receptor_copy_error(self, mock_basename, mock_path, mock_copy2):
        """Test behavior when copying the receptor file fails."""
        # --- Mock Setup ---
        # Similar setup to test_redock_successful_with_receptor, but mock copy2 to raise error
        mock_vfu_dir = MagicMock(spec=Path); mock_vfu_dir.exists.return_value = True
        mock_input_dir = MagicMock(spec=Path)
        mock_receptor_in_input = MagicMock(spec=Path); mock_receptor_in_input.exists.return_value = True
        mock_receptor_in_input.stat.return_value.st_mtime = 100
        mock_receptor_in_vfu_config = MagicMock(spec=Path); mock_receptor_in_vfu_config.exists.return_value = False

        def path_side_effect(*args, **kwargs):
             if args == (Path(__file__).parent.parent / "src" / "VFU",): return mock_vfu_dir
             elif args == (Path(__file__).parent.parent / "input",): return mock_input_dir
             elif args == (mock_input_dir, 'receptor.pdbqt'): return mock_receptor_in_input
             elif args == (mock_vfu_dir / "config", 'receptor.pdbqt'): return mock_receptor_in_vfu_config
             elif args == (mock_vfu_dir, "config"): return mock_vfu_dir / "config"
             return MagicMock()

        mock_path.side_effect = path_side_effect
        mock_path.return_value = MagicMock(spec=Path)
        mock_basename.return_value = 'receptor.pdbqt'
        mock_copy2.side_effect = OSError("Disk full") # Simulate copy error
        mock_log_callback = MagicMock()

        # --- Test Execution ---
        pose_out, score_out = redock_compound(
            'c1', 'C', (None)*11, receptor='/fake/receptor.pdbqt', log_callback=mock_log_callback
        )

        # --- Assertions ---
        self.assertIsNone(pose_out)
        self.assertIsNone(score_out)
        mock_copy2.assert_called_once()
        mock_log_callback.assert_any_call("Error copying receptor file: Disk full")

    @patch('utils.redocking.Path')
    # Note: We don't mock sys.modules here to simulate import failure
    def test_vfu_import_error(self, mock_path):
        """Test behavior when importing run_vf_unity fails."""
        # --- Mock Setup ---
        mock_vfu_dir = MagicMock(spec=Path)
        mock_vfu_dir.exists.return_value = True
        mock_vfu_dir.resolve.return_value = '/fake/project/src/VFU_no_script' # Simulate path without the script

        mock_path.side_effect = lambda *args, **kwargs: mock_vfu_dir if args == (Path(__file__).parent.parent / "src" / "VFU",) else MagicMock()
        mock_path.return_value = MagicMock(spec=Path)
        mock_log_callback = MagicMock()

        # Temporarily remove the mock if it exists from previous tests
        if 'run_vf_unity' in sys.modules:
            del sys.modules['run_vf_unity']

        # --- Test Execution ---
        pose_out, score_out = redock_compound(
            'c1', 'C', (None)*11, receptor=None, log_callback=mock_log_callback
        )

        # --- Assertions ---
        self.assertIsNone(pose_out)
        self.assertIsNone(score_out)
        # Check log messages for import error
        self.assertTrue(any("Error importing VFU module" in str(call_args) for call_args in mock_log_callback.call_args_list))
        self.assertTrue(any("No module named 'run_vf_unity'" in str(call_args) for call_args in mock_log_callback.call_args_list))
        # Ensure path removal was still attempted/logged if path was added
        self.assertIn(call(f"Temporarily added {mock_vfu_dir.resolve()} to sys.path for VFU import."), mock_log_callback.call_args_list)
        self.assertIn(call(f"Removed {mock_vfu_dir.resolve()} from sys.path."), mock_log_callback.call_args_list)


    @patch('utils.redocking.Path')
    @patch.dict(sys.modules, {'run_vf_unity': MagicMock()})
    def test_vfu_execution_error(self, mock_path):
        """Test behavior when run_vf_unity.main raises an exception."""
        # --- Mock Setup ---
        mock_vfu_dir = MagicMock(spec=Path); mock_vfu_dir.exists.return_value = True
        mock_vfu_dir.resolve.return_value = '/fake/project/src/VFU'
        mock_path.side_effect = lambda *args, **kwargs: mock_vfu_dir if args == (Path(__file__).parent.parent / "src" / "VFU",) else MagicMock()
        mock_path.return_value = MagicMock(spec=Path)

        mock_vfu_main = sys.modules['run_vf_unity'].main
        mock_vfu_main.side_effect = ValueError("VFU internal error") # Simulate error during execution
        mock_log_callback = MagicMock()

        # --- Test Execution ---
        pose_out, score_out = redock_compound(
            'c1', 'C', (None)*11, receptor=None, log_callback=mock_log_callback
        )

        # --- Assertions ---
        self.assertIsNone(pose_out)
        self.assertIsNone(score_out)
        mock_vfu_main.assert_called_once()
        self.assertTrue(any("Error during direct VFU execution for c1: VFU internal error" in str(call_args) for call_args in mock_log_callback.call_args_list))
        # Ensure path removal was still attempted/logged
        self.assertIn(call(f"Removed {mock_vfu_dir.resolve()} from sys.path."), mock_log_callback.call_args_list)


if __name__ == '__main__':
    unittest.main() 