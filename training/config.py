"""Training configuration for Privacy Shield SLM fine-tuning.

# DEPRECATED: Use training/ner_config.py (NERTrainingConfig) for the NER
# token classification approach. This file is kept for backward compatibility
# and to document the generative (Unsloth + LoRA) approach.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class TrainingConfig:
    """Hyperparameters and paths for LoRA fine-tuning with Unsloth + TRL."""

    # ── Model ────────────────────────────────────────────────────────────
    model_id: str = "Qwen/Qwen2.5-0.5B-Instruct"
    max_seq_length: int = 256

    # ── LoRA ─────────────────────────────────────────────────────────────
    lora_rank: int = 16
    lora_alpha: int = 16
    lora_dropout: float = 0.0
    # target_modules for Qwen2.5-0.5B-Instruct (standard attention + MLP only)
    lora_target_modules: list[str] = field(default_factory=lambda: [
        "q_proj", "k_proj", "v_proj", "o_proj",
        "gate_proj", "up_proj", "down_proj",
    ])

    # ── Training ─────────────────────────────────────────────────────────
    learning_rate: float = 2e-4
    lr_scheduler_type: str = "cosine"
    warmup_steps: int = 100
    per_device_train_batch_size: int = 4
    gradient_accumulation_steps: int = 8  # effective batch size = 32
    num_train_epochs: int = 3
    max_steps: int = -1  # -1 = use epochs

    # ── Eval & saving ────────────────────────────────────────────────────
    eval_steps: int = 100
    save_steps: int = 200
    logging_steps: int = 10

    # ── Early stopping ───────────────────────────────────────────────────
    early_stopping_patience: int = 5
    early_stopping_threshold: float = 0.001
    metric_for_best_model: str = "eval_loss"

    # ── Precision ────────────────────────────────────────────────────────
    bf16: bool = True
    fp16: bool = False

    # ── Paths ────────────────────────────────────────────────────────────
    train_file: str = "data/final/train.jsonl"
    val_file: str = "data/final/val.jsonl"
    output_dir: str = "output/adapter"

    # ── Misc ─────────────────────────────────────────────────────────────
    seed: int = 42
    gradient_checkpointing: bool = True
    dataloader_num_workers: int = 0
    report_to: str = "none"  # no wandb on Colab by default


def load_config(path: str | None = None) -> TrainingConfig:
    """Load training config from a YAML file, falling back to defaults.

    If *path* is ``None`` or the file does not exist, a default
    ``TrainingConfig`` is returned.  Only keys that match dataclass
    fields are applied; unknown keys are silently ignored so the YAML
    can carry extra metadata.
    """
    if path is None:
        return TrainingConfig()

    config_path = Path(path)
    if not config_path.is_file():
        print(f"[config] YAML not found at {config_path}, using defaults")
        return TrainingConfig()

    with open(config_path, "r", encoding="utf-8") as fh:
        raw: dict[str, Any] = yaml.safe_load(fh) or {}

    # Only keep keys that are actual TrainingConfig fields
    valid_keys = {f.name for f in TrainingConfig.__dataclass_fields__.values()}
    filtered = {k: v for k, v in raw.items() if k in valid_keys}

    return TrainingConfig(**filtered)


def save_config(config: TrainingConfig, path: str) -> None:
    """Persist a ``TrainingConfig`` to a YAML file."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        yaml.dump(asdict(config), fh, default_flow_style=False, sort_keys=False)
    print(f"[config] Saved to {out}")
