#!/usr/bin/env python3
"""
merge_lora.py - Merge LoRA adapter back into the base model.

# DEPRECATED: The NER approach (training/ner_train.py) saves a standalone model
# directly — no LoRA merge needed. This file is kept for backward compatibility
# and to document the generative approach.

Loads the fine-tuned LoRA adapter and merges it into the base model,
producing a standalone HuggingFace model in safetensors format.

Usage:
    python merge_lora.py
    python merge_lora.py --adapter-dir output/adapter --output-dir output/merged
    python merge_lora.py --base-model Qwen/Qwen2.5-0.5B-Instruct
"""

import argparse
import logging
import os
import shutil
import sys
import time
from pathlib import Path

import torch

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("merge_lora")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Merge LoRA adapter into base model and save as HuggingFace safetensors."
    )
    parser.add_argument(
        "--adapter-dir",
        type=str,
        default="output/adapter",
        help="Path to the LoRA adapter directory (default: output/adapter)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="output/merged",
        help="Path to save the merged model (default: output/merged)",
    )
    parser.add_argument(
        "--base-model",
        type=str,
        default="Qwen/Qwen2.5-0.5B-Instruct",
        help="Base model ID or path (default: Qwen/Qwen2.5-0.5B-Instruct)",
    )
    return parser.parse_args()


def get_dir_size_mb(path: Path) -> float:
    """Calculate total size of a directory in MB."""
    total = 0
    for f in path.rglob("*"):
        if f.is_file():
            total += f.stat().st_size
    return total / (1024 * 1024)


def count_parameters(model: torch.nn.Module) -> int:
    """Count total parameters in the model."""
    return sum(p.numel() for p in model.parameters())


def load_with_unsloth(adapter_path: str):
    """Load model and tokenizer using Unsloth's FastLanguageModel."""
    from unsloth import FastLanguageModel

    logger.info("Loading model with Unsloth FastLanguageModel...")
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=adapter_path,
        max_seq_length=256,
        dtype=torch.bfloat16,
        load_in_4bit=True,
    )
    return model, tokenizer


def load_with_transformers(base_model_id: str, adapter_path: str):
    """Load model and tokenizer using standard transformers + peft."""
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    logger.info("Loading base model from: %s", base_model_id)
    base_model = AutoModelForCausalLM.from_pretrained(
        base_model_id,
        torch_dtype=torch.bfloat16,
    )

    logger.info("Loading LoRA adapter from: %s", adapter_path)
    model = PeftModel.from_pretrained(base_model, adapter_path)
    tokenizer = AutoTokenizer.from_pretrained(adapter_path)

    logger.info("Merging adapter weights into base model...")
    model = model.merge_and_unload()

    return model, tokenizer


def main() -> None:
    args = parse_args()

    adapter_path = os.path.abspath(args.adapter_dir)
    output_dir = os.path.abspath(args.output_dir)
    base_model_id = args.base_model

    # --- Validate adapter directory ---
    if not os.path.isdir(adapter_path):
        logger.error("Adapter directory not found: %s", adapter_path)
        sys.exit(1)

    logger.info("Adapter directory : %s", adapter_path)
    logger.info("Output directory   : %s", output_dir)
    logger.info("Base model         : %s", base_model_id)

    # --- Load model + adapter ---
    t_start = time.time()

    try:
        model, tokenizer = load_with_unsloth(adapter_path)
        logger.info("Loaded with Unsloth successfully.")
    except ImportError:
        logger.info("Unsloth not available, falling back to transformers + peft.")
        model, tokenizer = load_with_transformers(base_model_id, adapter_path)

    t_load = time.time() - t_start
    logger.info("Model loaded and merged in %.1fs", t_load)

    # --- Merge (guard against double-merge when Unsloth auto-merges) ---
    t_merge_start = time.time()

    from peft import PeftModel
    if isinstance(model, PeftModel):
        logger.info("Merging LoRA adapter into base model...")
        model = model.merge_and_unload()
    else:
        logger.info("Model already merged (Unsloth auto-merge), skipping merge_and_unload.")

    t_merge = time.time() - t_merge_start

    # --- Save merged model ---
    logger.info("Saving merged model to: %s", output_dir)
    os.makedirs(output_dir, exist_ok=True)

    model.save_pretrained(output_dir, safe_serialization=True)
    tokenizer.save_pretrained(output_dir)

    t_total = time.time() - t_start

    # --- Print summary ---
    total_params = count_parameters(model)
    output_size_mb = get_dir_size_mb(Path(output_dir))

    print()
    print("=" * 60)
    print("  LoRA Merge Complete")
    print("=" * 60)
    print(f"  Total parameters : {total_params:,}")
    print(f"  Merge time       : {t_merge:.1f}s")
    print(f"  Total time       : {t_total:.1f}s")
    print(f"  Output size      : {output_size_mb:.1f} MB")
    print(f"  Output directory : {output_dir}")
    print("=" * 60)
    print()

    # --- Verify output files ---
    output_files = list(Path(output_dir).glob("*.safetensors"))
    if not output_files:
        logger.warning("No .safetensors files found in output directory!")
    else:
        logger.info("Saved %d safetensors file(s):", len(output_files))
        for f in sorted(output_files):
            logger.info("  %s (%.1f MB)", f.name, f.stat().st_size / (1024 * 1024))

    config_file = Path(output_dir) / "config.json"
    if config_file.exists():
        logger.info("Model config saved: config.json")
    else:
        logger.warning("config.json not found in output directory.")

    tokenizer_files = list(Path(output_dir).glob("tokenizer*"))
    if tokenizer_files:
        logger.info("Tokenizer files: %s", ", ".join(f.name for f in sorted(tokenizer_files)))
    else:
        logger.warning("No tokenizer files found in output directory.")

    logger.info("Merge pipeline complete.")


if __name__ == "__main__":
    main()
