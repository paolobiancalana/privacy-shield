"""Training configuration for Privacy Shield NER (token classification) fine-tuning.

Uses XLM-RoBERTa-base with full fine-tuning (no LoRA) and HuggingFace Trainer.

Usage:
    from training.ner_config import NERTrainingConfig
    config = NERTrainingConfig()
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class NERTrainingConfig:
    """Hyperparameters and paths for NER token classification fine-tuning."""

    # ── Model ────────────────────────────────────────────────────────────
    # mDeBERTa-v3-base has numerical instability (NaN) in both bf16 and fp32
    # due to disentangled attention. XLM-RoBERTa-base is stable, same size,
    # multilingual (incl. Italian), and proven for NER tasks.
    model_id: str = "xlm-roberta-base"
    max_seq_length: int = 512

    # ── Training ─────────────────────────────────────────────────────────
    learning_rate: float = 5e-5
    lr_scheduler_type: str = "linear"
    warmup_ratio: float = 0.1
    per_device_train_batch_size: int = 16
    per_device_eval_batch_size: int = 16
    gradient_accumulation_steps: int = 2  # effective batch = 32
    num_train_epochs: int = 10
    weight_decay: float = 0.01
    max_grad_norm: float = 1.0

    # ── Eval & saving ────────────────────────────────────────────────────
    eval_strategy: str = "epoch"
    save_strategy: str = "epoch"
    save_total_limit: int = 2
    logging_steps: int = 50
    metric_for_best_model: str = "eval_f1"  # seqeval entity-level F1
    greater_is_better: bool = True
    load_best_model_at_end: bool = True

    # ── Precision ────────────────────────────────────────────────────────
    bf16: bool = True
    fp16: bool = False

    # ── Memory ───────────────────────────────────────────────────────────
    eval_accumulation_steps: int = 10  # move logits to CPU during eval

    # ── Paths ────────────────────────────────────────────────────────────
    data_dir: str = "data/final_ner"
    output_dir: str = "output/ner"

    # ── Misc ─────────────────────────────────────────────────────────────
    seed: int = 42
    report_to: str = "none"
