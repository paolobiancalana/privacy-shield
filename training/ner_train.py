"""NER training script for Privacy Shield PII detection.

Uses mDeBERTa-v3-base with full fine-tuning (no LoRA) and standard
HuggingFace Trainer for token classification.

Usage:
    python -m training.ner_train
    python -m training.ner_train --data-dir data/final_ner --output-dir output/ner
"""

from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

import numpy as np
from datasets import load_from_disk
from transformers import (
    AutoModelForTokenClassification,
    AutoTokenizer,
    DataCollatorForTokenClassification,
    Trainer,
    TrainingArguments,
)

from dataset.entity_types import ID2LABEL, LABEL2ID, NUM_LABELS
from training.ner_config import NERTrainingConfig

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("ner_train")


def _compute_metrics(eval_pred):
    """Compute seqeval entity-level metrics.

    Decodes logits via argmax, reconstructs list[list[str]] label sequences
    (skipping -100 positions), and passes to seqeval for standard NER metrics.
    """
    import evaluate

    seqeval = evaluate.load("seqeval")

    logits, labels = eval_pred
    predictions = np.argmax(logits, axis=2)

    # Reconstruct string label sequences, skipping -100 positions
    true_labels: list[list[str]] = []
    pred_labels: list[list[str]] = []

    for pred_seq, label_seq in zip(predictions, labels):
        true_seq: list[str] = []
        pred_seq_str: list[str] = []

        for pred_id, label_id in zip(pred_seq, label_seq):
            if label_id == -100:
                continue
            true_seq.append(ID2LABEL.get(int(label_id), "O"))
            pred_seq_str.append(ID2LABEL.get(int(pred_id), "O"))

        true_labels.append(true_seq)
        pred_labels.append(pred_seq_str)

    results = seqeval.compute(
        predictions=pred_labels,
        references=true_labels,
        zero_division=0,
    )

    return {
        "precision": results["overall_precision"],
        "recall": results["overall_recall"],
        "f1": results["overall_f1"],
        "accuracy": results["overall_accuracy"],
    }


def _format_duration(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    parts: list[str] = []
    if h:
        parts.append(f"{h}h")
    if m:
        parts.append(f"{m}m")
    parts.append(f"{s}s")
    return " ".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Train NER token classification model for Privacy Shield."
    )
    parser.add_argument(
        "--data-dir", type=str, default=None,
        help="Directory with Arrow datasets (default: from config)",
    )
    parser.add_argument(
        "--output-dir", type=str, default=None,
        help="Output directory for model (default: from config)",
    )
    parser.add_argument(
        "--model-id", type=str, default=None,
        help="HuggingFace model ID (default: from config)",
    )
    parser.add_argument(
        "--num-train-epochs", type=int, default=None,
        help="Number of training epochs (default: from config)",
    )
    parser.add_argument(
        "--learning-rate", type=float, default=None,
        help="Learning rate (default: from config)",
    )
    args = parser.parse_args()

    config = NERTrainingConfig()

    # Apply CLI overrides
    if args.data_dir:
        config.data_dir = args.data_dir
    if args.output_dir:
        config.output_dir = args.output_dir
    if args.model_id:
        config.model_id = args.model_id
    if args.num_train_epochs:
        config.num_train_epochs = args.num_train_epochs
    if args.learning_rate:
        config.learning_rate = args.learning_rate

    print("=" * 60)
    print("  Privacy Shield — NER Token Classification Training")
    print("=" * 60)
    print(f"  Model           : {config.model_id}")
    print(f"  Effective batch : {config.per_device_train_batch_size * config.gradient_accumulation_steps}")
    print(f"  Learning rate   : {config.learning_rate}")
    print(f"  Epochs          : {config.num_train_epochs}")
    print(f"  Max seq length  : {config.max_seq_length}")
    print(f"  Num labels      : {NUM_LABELS}")
    precision = 'bf16' if config.bf16 else ('fp16' if config.fp16 else 'fp32')
    print(f"  Precision       : {precision}")
    print(f"  Data dir        : {config.data_dir}")
    print(f"  Output          : {config.output_dir}")
    print("=" * 60)

    # Load datasets
    data_dir = Path(config.data_dir)
    logger.info("Loading datasets from %s", data_dir)

    train_dataset = load_from_disk(str(data_dir / "train"))
    val_dataset = load_from_disk(str(data_dir / "val"))

    logger.info("Train: %d examples, Val: %d examples", len(train_dataset), len(val_dataset))

    # Load model and tokenizer
    logger.info("Loading model: %s", config.model_id)
    tokenizer = AutoTokenizer.from_pretrained(config.model_id)
    model = AutoModelForTokenClassification.from_pretrained(
        config.model_id,
        num_labels=NUM_LABELS,
        id2label=ID2LABEL,
        label2id=LABEL2ID,
    )

    total_params = sum(p.numel() for p in model.parameters())
    trainable_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
    logger.info("Total parameters: %s (all trainable)", f"{total_params:,}")

    # Data collator for dynamic padding
    data_collator = DataCollatorForTokenClassification(tokenizer=tokenizer)

    # Training arguments
    output_dir = Path(config.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    training_args = TrainingArguments(
        output_dir=str(output_dir),
        num_train_epochs=config.num_train_epochs,
        learning_rate=config.learning_rate,
        lr_scheduler_type=config.lr_scheduler_type,
        warmup_ratio=config.warmup_ratio,
        per_device_train_batch_size=config.per_device_train_batch_size,
        per_device_eval_batch_size=config.per_device_eval_batch_size,
        gradient_accumulation_steps=config.gradient_accumulation_steps,
        weight_decay=config.weight_decay,
        eval_strategy=config.eval_strategy,
        eval_steps=config.eval_steps,
        save_strategy="steps",
        save_steps=config.save_steps,
        save_total_limit=config.save_total_limit,
        logging_steps=config.logging_steps,
        logging_first_step=True,
        metric_for_best_model=config.metric_for_best_model,
        greater_is_better=config.greater_is_better,
        load_best_model_at_end=config.load_best_model_at_end,
        bf16=config.bf16,
        fp16=config.fp16,
        eval_accumulation_steps=10,  # move logits to CPU during eval to avoid OOM
        seed=config.seed,
        report_to=config.report_to,
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=val_dataset,
        data_collator=data_collator,
        processing_class=tokenizer,
        compute_metrics=_compute_metrics,
    )

    # Train
    logger.info("Starting training...")
    start_time = time.time()
    train_result = trainer.train()
    elapsed = time.time() - start_time

    # Save best model + tokenizer + config (id2label baked into config.json)
    logger.info("Saving model to %s", config.output_dir)
    trainer.save_model(str(output_dir))
    tokenizer.save_pretrained(str(output_dir))

    # Final evaluation
    logger.info("Running final evaluation...")
    eval_metrics = trainer.evaluate()

    # Summary
    metrics = train_result.metrics
    print("\n" + "=" * 60)
    print("  Training Complete")
    print("=" * 60)
    print(f"  Total time       : {_format_duration(elapsed)}")
    print(f"  Total steps      : {metrics.get('train_steps', 'N/A')}")
    print(f"  Final train loss : {metrics.get('train_loss', 'N/A')}")
    print(f"  Eval F1          : {eval_metrics.get('eval_f1', 'N/A')}")
    print(f"  Eval precision   : {eval_metrics.get('eval_precision', 'N/A')}")
    print(f"  Eval recall      : {eval_metrics.get('eval_recall', 'N/A')}")
    print(f"  Eval accuracy    : {eval_metrics.get('eval_accuracy', 'N/A')}")
    print("=" * 60)
    print(f"\n  Model saved to: {output_dir.resolve()}")
    print(f"  pipeline('token-classification') compatible (id2label in config.json)")
    print()


if __name__ == "__main__":
    main()
