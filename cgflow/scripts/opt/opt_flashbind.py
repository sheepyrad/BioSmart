import argparse
import datetime
import os
import sys
from pathlib import Path

# Add src directory to Python path
script_dir = Path(__file__).parent.parent.parent
src_dir = script_dir / "src"
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from omegaconf import DictConfig, OmegaConf

from synthflow.config import Config, init_empty


def parse_args() -> DictConfig:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=str, help="Path to the configuration file.")

    # Common optimization overrides
    parser.add_argument("--result_dir", type=str, help="Directory to save results.")
    parser.add_argument("--env_dir", type=str, help="Directory containing environment data.")
    parser.add_argument("--max_atoms", type=int, help="Maximum atoms for generation.")
    parser.add_argument("--subsampling_ratio", type=float, help="Action-space subsampling ratio.")
    parser.add_argument("--num_steps", type=int, help="Number of optimization steps.")
    parser.add_argument("--num_sampling_per_step", type=int, help="Samples per optimization step.")
    parser.add_argument("--temperature", type=int, nargs="+", help="One value for constant or two values for uniform.")
    parser.add_argument("--seed", type=int, help="Random seed.")

    # Pocket context for generation
    parser.add_argument("--protein_path", type=str, help="Protein structure path for pocket setup.")
    parser.add_argument("--center", type=float, nargs=3, help="Pocket center x y z.")
    parser.add_argument("--ref_ligand_path", type=str, help="Reference ligand path if center is not provided.")
    parser.add_argument("--size", type=float, nargs=3, help="Pocket box size x y z.")

    # Pose model used by generator
    parser.add_argument("--pose_model", type=str, help="Pose prediction checkpoint for CGFlow.")
    parser.add_argument("--pose_steps", type=int, help="Number of pose prediction steps.")

    # FlashBind/FABind+ specific overrides
    parser.add_argument("--flashbind_root", type=str, help="Path to vendored FlashBind root (e.g. cgflow/src/FlashBind).")
    parser.add_argument("--flashbind_protein_id", type=str, help="Protein ID used to build sample IDs.")
    parser.add_argument("--flashbind_pdb_dir", type=str, help="Directory containing receptor PDB files for FABind/FlashBind.")
    parser.add_argument("--flashbind_protein_repr", type=str, help="Path to FlashBind protein representations.")
    parser.add_argument("--flashbind_ligand_repr", type=str, help="Path to FlashBind ligand representations.")
    parser.add_argument("--flashbind_prots_json", type=str, help="Path to prots.json (prot_id -> sequence) for ESM3 generation.")
    parser.add_argument("--flashbind_fabind_checkpoint", type=str, help="FABind+ regression checkpoint path.")
    parser.add_argument("--flashbind_binary_checkpoints", nargs="+", type=str, help="FlashBind binary task checkpoint(s).")
    parser.add_argument("--flashbind_value_checkpoints", nargs="+", type=str, help="FlashBind value task checkpoint(s).")
    parser.add_argument("--flashbind_fabind_conda_env", type=str, help="Conda env for FABind+ scripts.")
    parser.add_argument("--flashbind_flashbind_conda_env", type=str, help="Conda env for FlashBind predict.py.")
    parser.add_argument("--flashbind_fabind_num_threads", type=int, help="Threads for FABind molecule preprocessing.")
    parser.add_argument("--flashbind_fabind_batch_size", type=int, help="FABind inference batch size.")
    parser.add_argument("--flashbind_fabind_post_optim", action="store_true", help="Enable FABind post optimization.")
    parser.add_argument("--flashbind_devices", type=int, help="FlashBind predict devices.")
    parser.add_argument("--flashbind_accelerator", type=str, help="FlashBind accelerator (gpu/cpu/tpu).")
    parser.add_argument("--flashbind_num_workers", type=int, help="FlashBind dataloader workers.")
    parser.add_argument("--flashbind_distance_threshold", type=float, help="FlashBind distance threshold.")
    parser.add_argument("--flashbind_repr_n_jobs", type=int, help="n_jobs for TorchDrug repr generation.")
    parser.add_argument("--flashbind_auto_generate_protein_repr", action="store_true", help="Auto-generate protein repr if missing.")
    parser.add_argument("--flashbind_auto_generate_ligand_repr", action="store_true", help="Auto-generate ligand repr each oracle batch.")
    parser.add_argument("--flashbind_reward_cache_path", type=str, help="SMILES-level reward cache path.")

    args = parser.parse_args()

    param: DictConfig = OmegaConf.load(args.config)
    for key in vars(args):
        if key == "config":
            continue
        value = getattr(args, key)
        if value is None:
            continue
        if key.startswith("flashbind_"):
            nested_key = key.replace("flashbind_", "")
            if "flashbind" not in param:
                param["flashbind"] = {}
            param["flashbind"][nested_key] = value
        else:
            param[key] = value
    return param


if __name__ == "__main__":
    from tasks.flashbind import FlashBindMOOTrainer

    param = parse_args()
    config = init_empty(Config())

    config.desc = "Multi objective optimization for FABind+ docking with FlashBind scoring"
    # Default objective uses combined FlashBind score:
    # normalized_affinity * binary_probability * lilly_mask.
    config.task.moo.objectives = ["flashbind"]
    config.print_every = 10
    config.checkpoint_every = 100
    config.store_all_checkpoints = True
    config.num_workers_retrosynthesis = 4

    now = datetime.datetime.now().strftime("%y%m%d_%H%M%S")
    config.log_dir = os.path.join(param.result_dir, now)
    config.overwrite_existing_exp = True
    config.start_at_step = 0

    # Generative environment
    config.env_dir = param.env_dir
    config.algo.action_subsampling.sampling_ratio = param.subsampling_ratio
    config.algo.max_nodes = param.max_atoms

    # Docking context required by BaseDockingTask.
    config.task.docking.protein_path = str(Path(param.protein_path).resolve())
    config.task.docking.center = tuple(param.center) if param.center is not None else None
    if param.size is not None:
        config.task.docking.size = tuple(param.size)
    config.task.docking.ff_opt = "none"
    config.task.docking.ref_ligand_path = (
        str(Path(param.ref_ligand_path).resolve()) if param.ref_ligand_path else None
    )

    # FlashBind/FABind+ section
    fb_param = param.flashbind
    config.task.flashbind.root = str(Path(fb_param.root).resolve())
    config.task.flashbind.protein_id = str(fb_param.protein_id)
    config.task.flashbind.pdb_dir = str(Path(fb_param.pdb_dir).resolve())
    config.task.flashbind.protein_repr = str(Path(fb_param.protein_repr).resolve())
    config.task.flashbind.ligand_repr = str(Path(fb_param.ligand_repr).resolve())
    if OmegaConf.select(param, "flashbind.prots_json", default=None) is not None:
        config.task.flashbind.prots_json = str(Path(fb_param.prots_json).resolve())
    config.task.flashbind.fabind_checkpoint = str(Path(fb_param.fabind_checkpoint).resolve())
    config.task.flashbind.binary_checkpoints = [str(Path(p).resolve()) for p in fb_param.binary_checkpoints]
    config.task.flashbind.value_checkpoints = [str(Path(p).resolve()) for p in fb_param.value_checkpoints]
    if OmegaConf.select(param, "flashbind.fabind_conda_env", default=None) is not None:
        config.task.flashbind.fabind_conda_env = fb_param.fabind_conda_env
    if OmegaConf.select(param, "flashbind.flashbind_conda_env", default=None) is not None:
        config.task.flashbind.flashbind_conda_env = fb_param.flashbind_conda_env
    if OmegaConf.select(param, "flashbind.fabind_num_threads", default=None) is not None:
        config.task.flashbind.fabind_num_threads = fb_param.fabind_num_threads
    if OmegaConf.select(param, "flashbind.fabind_batch_size", default=None) is not None:
        config.task.flashbind.fabind_batch_size = fb_param.fabind_batch_size
    if OmegaConf.select(param, "flashbind.devices", default=None) is not None:
        config.task.flashbind.devices = fb_param.devices
    if OmegaConf.select(param, "flashbind.accelerator", default=None) is not None:
        config.task.flashbind.accelerator = fb_param.accelerator
    if OmegaConf.select(param, "flashbind.num_workers", default=None) is not None:
        config.task.flashbind.num_workers = fb_param.num_workers
    if OmegaConf.select(param, "flashbind.distance_threshold", default=None) is not None:
        config.task.flashbind.distance_threshold = fb_param.distance_threshold
    if OmegaConf.select(param, "flashbind.repr_n_jobs", default=None) is not None:
        config.task.flashbind.repr_n_jobs = fb_param.repr_n_jobs
    if OmegaConf.select(param, "flashbind.reward_cache_path", default=None) is not None:
        config.task.flashbind.reward_cache_path = str(Path(fb_param.reward_cache_path).resolve())

    # Preserve explicit CLI flag behavior for post optimization.
    config.task.flashbind.fabind_post_optim = bool(
        OmegaConf.select(param, "flashbind.fabind_post_optim", default=config.task.flashbind.fabind_post_optim)
    )
    config.task.flashbind.auto_generate_protein_repr = bool(
        OmegaConf.select(
            param,
            "flashbind.auto_generate_protein_repr",
            default=config.task.flashbind.auto_generate_protein_repr,
        )
    )
    config.task.flashbind.auto_generate_ligand_repr = bool(
        OmegaConf.select(
            param,
            "flashbind.auto_generate_ligand_repr",
            default=config.task.flashbind.auto_generate_ligand_repr,
        )
    )

    # Optimization settings
    config.num_training_steps = param.num_steps
    config.algo.num_from_policy = param.num_sampling_per_step
    config.seed = param.seed

    if len(param.temperature) == 1:
        config.cond.temperature.sample_dist = "constant"
    elif len(param.temperature) == 2:
        config.cond.temperature.sample_dist = "uniform"
    else:
        raise ValueError("Temperature should be one value (constant) or two values (uniform).")
    config.cond.temperature.dist_params = param.temperature

    config.cgflow.ckpt_path = param.pose_model
    config.cgflow.num_inference_steps = param.pose_steps

    config.algo.sampling_tau = param.sampling_tau
    config.algo.train_random_action_prob = param.random_action_prob
    config.replay.use = True
    config.replay.warmup = config.algo.num_from_policy * param.replay_warmup_step
    config.replay.capacity = param.replay_capacity
    config.replay.num_from_replay = config.algo.num_from_policy

    trainer = FlashBindMOOTrainer(config)
    trainer.run()
