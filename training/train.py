"""Main training script for Privacy Shield SLM fine-tuning.

# DEPRECATED: Use training/ner_train.py for the NER token classification
# approach. This file is kept for backward compatibility and to document
# the generative (Unsloth + SFTTrainer + LoRA) approach.

Usage (from the ``training/`` project root):

    python -m training.train
    python -m training.train --config configs/my_run.yaml
    python -m training.train --lora-rank 16 --num-train-epochs 3
    python -m training.train --resume-from output/adapter/checkpoint-400
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import fields as dc_fields
from pathlib import Path

import unsloth  # Must be imported FIRST to patch trl/transformers/peft
from unsloth import FastLanguageModel

import torch
from datasets import Dataset
from transformers import EarlyStoppingCallback  # kept for optional use
from trl import SFTTrainer, SFTConfig

from training.config import TrainingConfig, load_config, save_config


# ── Helpers ──────────────────────────────────────────────────────────────


def _build_arg_parser() -> argparse.ArgumentParser:
    """Build an argument parser with ``--config``, ``--resume-from``,
    and one flag for every ``TrainingConfig`` field."""

    parser = argparse.ArgumentParser(
        description="Fine-tune Privacy Shield SLM with Unsloth + TRL",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to a YAML config file (fields override defaults)",
    )
    parser.add_argument(
        "--resume-from",
        type=str,
        default=None,
        help="Path to a checkpoint directory to resume training from",
    )

    # Dynamically add one CLI flag per TrainingConfig field so users can
    # override any hyperparameter from the command line.
    for f in dc_fields(TrainingConfig):
        flag = f"--{f.name.replace('_', '-')}"
        if f.type == "bool" or f.type is bool:
            parser.add_argument(flag, type=_str_to_bool, default=None)
        elif f.type == "list[str]":
            parser.add_argument(flag, type=str, nargs="+", default=None)
        elif f.type == "float" or f.type is float:
            parser.add_argument(flag, type=float, default=None)
        elif f.type == "int" or f.type is int:
            parser.add_argument(flag, type=int, default=None)
        else:
            parser.add_argument(flag, type=str, default=None)

    return parser


def _str_to_bool(v: str) -> bool:
    if v.lower() in ("true", "1", "yes"):
        return True
    if v.lower() in ("false", "0", "no"):
        return False
    raise argparse.ArgumentTypeError(f"Boolean value expected, got '{v}'")


def _apply_cli_overrides(config: TrainingConfig, args: argparse.Namespace) -> TrainingConfig:
    """Mutate *config* in-place with any non-None CLI overrides."""
    for f in dc_fields(TrainingConfig):
        cli_value = getattr(args, f.name, None)
        if cli_value is not None:
            setattr(config, f.name, cli_value)
    return config


def _load_jsonl(path: str) -> Dataset:
    """Load a chat-formatted JSONL file into a HuggingFace ``Dataset``.

    Each line must be a JSON object with a ``"messages"`` key whose value
    is a list of ``{"role": ..., "content": ...}`` dicts.
    """
    records: list[dict] = []
    file_path = Path(path)
    if not file_path.is_file():
        raise FileNotFoundError(f"Dataset file not found: {file_path.resolve()}")

    with open(file_path, "r", encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{lineno}: invalid JSON — {exc}") from exc
            if "messages" not in obj:
                raise ValueError(f"{path}:{lineno}: missing 'messages' key")
            records.append(obj)

    print(f"[data] Loaded {len(records)} examples from {path}")
    return Dataset.from_list(records)


def _format_duration(seconds: float) -> str:
    """Human-readable duration string."""
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    parts: list[str] = []
    if h:
        parts.append(f"{h}h")
    if m:
        parts.append(f"{m}m")
    parts.append(f"{s}s")
    return " ".join(parts)


# ── Main ─────────────────────────────────────────────────────────────────


def main() -> None:
    parser = _build_arg_parser()
    args = parser.parse_args()

    # 1. Load config: YAML defaults -> dataclass -> CLI overrides
    config = load_config(args.config)
    config = _apply_cli_overrides(config, args)

    print("=" * 60)
    print("  Privacy Shield SLM — LoRA Fine-Tuning")
    print("=" * 60)
    print(f"  Model           : {config.model_id}")
    print(f"  LoRA rank       : {config.lora_rank}")
    print(f"  LoRA alpha      : {config.lora_alpha}")
    print(f"  Effective batch : {config.per_device_train_batch_size * config.gradient_accumulation_steps}")
    print(f"  Learning rate   : {config.learning_rate}")
    print(f"  Epochs          : {config.num_train_epochs}")
    print(f"  Max seq length  : {config.max_seq_length}")
    print(f"  Precision       : {'bf16' if config.bf16 else 'fp16' if config.fp16 else 'fp32'}")
    print(f"  Output          : {config.output_dir}")
    if args.resume_from:
        print(f"  Resume from     : {args.resume_from}")
    print("=" * 60)

    # 2. Load base model via Unsloth (Phase 1 fresh load, or Phase 2 adapter load)
    print("\n[model] Loading base model...")
    dtype = torch.bfloat16 if config.bf16 else (torch.float16 if config.fp16 else torch.float32)

    if args.resume_from and Path(args.resume_from).is_dir():
        # Phase 2: load the saved adapter as the base with a fresh optimizer.
        # Do NOT use resume_from_checkpoint — that restores Phase 1 optimizer state.
        print(f"[model] Loading adapter from {args.resume_from} for continued training...")
        model, tokenizer = FastLanguageModel.from_pretrained(
            model_name=args.resume_from,
            max_seq_length=config.max_seq_length,
            dtype=None,
            load_in_4bit=True,
        )
        # Re-apply LoRA on top of the loaded adapter for continued training
        print("[model] Re-applying LoRA adapter for Phase 2...")
        model = FastLanguageModel.get_peft_model(
            model,
            r=config.lora_rank,
            lora_alpha=config.lora_alpha,
            lora_dropout=config.lora_dropout,
            target_modules=config.lora_target_modules,
            use_gradient_checkpointing="unsloth" if config.gradient_checkpointing else False,
        )
    else:
        # Phase 1: load base model fresh
        if args.resume_from:
            print(f"[train] WARNING: checkpoint path '{args.resume_from}' not found, starting from scratch")
        model, tokenizer = FastLanguageModel.from_pretrained(
            model_name=config.model_id,
            max_seq_length=config.max_seq_length,
            dtype=None,
            load_in_4bit=True,
        )
        # 3. Apply LoRA via Unsloth
        print("[model] Applying LoRA adapter...")
        model = FastLanguageModel.get_peft_model(
            model,
            r=config.lora_rank,
            lora_alpha=config.lora_alpha,
            lora_dropout=config.lora_dropout,
            target_modules=config.lora_target_modules,
            use_gradient_checkpointing="unsloth" if config.gradient_checkpointing else False,
        )

    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in model.parameters())
    print(f"[model] Trainable parameters: {trainable:,} / {total:,} ({100 * trainable / total:.2f}%)")

    # 4. Load datasets and format as text using chat template (Unsloth pattern).
    # Unsloth's tokenizer has EOS_TOKEN set — we use it for formatting.
    print("\n[data] Loading datasets...")
    train_dataset = _load_jsonl(config.train_file)
    val_dataset = _load_jsonl(config.val_file)

    EOS_TOKEN = tokenizer.eos_token

    def formatting_func(examples):
        """Format chat messages into text strings with EOS token appended."""
        texts = []
        for messages in examples["messages"]:
            text = tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=False,
            )
            texts.append(text + EOS_TOKEN)
        return {"text": texts}

    print("[data] Formatting datasets with chat template...")
    train_dataset = train_dataset.map(formatting_func, batched=True,
                                       remove_columns=train_dataset.column_names)
    val_dataset = val_dataset.map(formatting_func, batched=True,
                                   remove_columns=val_dataset.column_names)

    # 5. Trainer setup — following Unsloth notebook pattern exactly
    output_dir = Path(config.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=train_dataset,
        eval_dataset=val_dataset,
        dataset_text_field="text",
        max_seq_length=config.max_seq_length,
        packing=False,
        args=SFTConfig(
            output_dir=str(output_dir),
            # Schedule
            num_train_epochs=config.num_train_epochs,
            max_steps=config.max_steps,
            learning_rate=config.learning_rate,
            lr_scheduler_type=config.lr_scheduler_type,
            warmup_steps=config.warmup_steps,
            # Batching
            per_device_train_batch_size=config.per_device_train_batch_size,
            gradient_accumulation_steps=config.gradient_accumulation_steps,
            # Precision
            bf16=config.bf16,
            fp16=config.fp16,
            # Eval & checkpoints
            eval_strategy="steps",
            eval_steps=config.eval_steps,
            save_strategy="steps",
            save_steps=config.save_steps,
            save_total_limit=3,
            load_best_model_at_end=True,
            metric_for_best_model=config.metric_for_best_model,
            greater_is_better=False,
            # Logging
            logging_steps=config.logging_steps,
            logging_first_step=True,
            report_to=config.report_to,
            # Misc
            seed=config.seed,
            optim="adamw_8bit",
            weight_decay=0.01,
        ),
    )

    # 10. Train (never pass resume_from_checkpoint — Phase 2 model is pre-loaded above)
    print("\n[train] Starting training...")
    start_time = time.time()

    train_result = trainer.train()
    elapsed = time.time() - start_time

    # 11. Save best adapter
    print(f"\n[save] Saving adapter to {config.output_dir} ...")
    trainer.save_model(str(output_dir))
    tokenizer.save_pretrained(str(output_dir))

    # Save config alongside adapter for reproducibility
    save_config(config, str(output_dir / "training_config.yaml"))

    # 12. Training summary
    metrics = train_result.metrics
    print("\n" + "=" * 60)
    print("  Training Complete")
    print("=" * 60)
    print(f"  Total time       : {_format_duration(elapsed)}")
    print(f"  Total steps      : {metrics.get('train_steps', 'N/A')}")
    print(f"  Final train loss : {metrics.get('train_loss', 'N/A')}")

    # Run final eval to get eval loss
    print("\n[eval] Running final evaluation...")
    eval_metrics = trainer.evaluate()
    print(f"  Final eval loss  : {eval_metrics.get('eval_loss', 'N/A')}")
    print(f"  Eval runtime     : {eval_metrics.get('eval_runtime', 0):.1f}s")
    print("=" * 60)
    print(f"\n  Adapter saved to: {output_dir.resolve()}")
    print(f"  Config saved to : {(output_dir / 'training_config.yaml').resolve()}")
    print()


if __name__ == "__main__":
    main()
