#!/usr/bin/env python3
"""
Block 0 - Verify model architecture and LoRA target discovery.

Loads the base model, enumerates all nn.Linear layers as LoRA candidates,
applies a test PEFT config, and saves an architecture report to JSON.
"""

import argparse
import json
import os
import sys

import torch
import torch.nn as nn
from transformers import AutoConfig, AutoModelForCausalLM
from peft import LoraConfig, get_peft_model, TaskType


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify model architecture and discover LoRA targets"
    )
    parser.add_argument(
        "--model-id",
        type=str,
        default="Qwen/Qwen2.5-0.5B-Instruct",
        help="HuggingFace model identifier (default: Qwen/Qwen2.5-0.5B-Instruct)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="output",
        help="Directory to save the architecture report (default: output)",
    )
    return parser.parse_args()


def discover_linear_modules(model: nn.Module) -> list[str]:
    """Walk named_modules and collect names of all nn.Linear layers."""
    linear_modules: list[str] = []
    for name, module in model.named_modules():
        if isinstance(module, nn.Linear):
            linear_modules.append(name)
    return linear_modules


def derive_lora_targets(linear_modules: list[str]) -> list[str]:
    """
    Derive unique short target names from fully-qualified linear module paths.
    Strips numeric prefixes (e.g. 'model.layers.0.self_attn.q_proj' -> 'q_proj')
    and deduplicates, preserving discovery order.
    """
    seen: set[str] = set()
    targets: list[str] = []
    for fqn in linear_modules:
        short_name = fqn.split(".")[-1]
        if short_name not in seen:
            seen.add(short_name)
            targets.append(short_name)
    return targets


def count_parameters(model: nn.Module) -> tuple[int, int]:
    """Return (total_params, trainable_params)."""
    total = sum(p.numel() for p in model.parameters())
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    return total, trainable


def main() -> None:
    args = parse_args()
    model_id: str = args.model_id
    output_dir: str = args.output_dir

    # ---- Step 1: Load config ----
    print(f"Loading config for {model_id}...")
    try:
        config = AutoConfig.from_pretrained(model_id)
    except Exception as e:
        print(f"ERROR: Failed to load model config: {e}", file=sys.stderr)
        sys.exit(1)

    model_type = getattr(config, "model_type", "unknown")
    print(f"  model_type: {model_type}")

    # ---- Step 2: Load model ----
    print(f"Loading model {model_id} (bfloat16)...")
    try:
        model = AutoModelForCausalLM.from_pretrained(
            model_id,
            torch_dtype=torch.bfloat16,
        )
    except Exception as e:
        print(f"ERROR: Failed to load model: {e}", file=sys.stderr)
        sys.exit(1)

    total_params, _ = count_parameters(model)
    print(f"  Total parameters: {total_params:,}")

    # ---- Step 3: Discover linear modules ----
    print("Discovering nn.Linear layers (LoRA candidates)...")
    linear_modules = discover_linear_modules(model)
    lora_targets = derive_lora_targets(linear_modules)

    print(f"  Found {len(linear_modules)} nn.Linear layers")
    print(f"  Unique LoRA target names: {lora_targets}")

    # ---- Step 4: Apply PEFT LoRA ----
    print("Applying LoRA (rank=16, alpha=16)...")
    try:
        lora_config = LoraConfig(
            task_type=TaskType.CAUSAL_LM,
            r=16,
            lora_alpha=16,
            lora_dropout=0.0,
            target_modules=lora_targets,
        )
        peft_model = get_peft_model(model, lora_config)
    except Exception as e:
        print(f"ERROR: Failed to apply LoRA: {e}", file=sys.stderr)
        sys.exit(1)

    total_after, trainable_after = count_parameters(peft_model)
    trainable_pct = (trainable_after / total_after * 100) if total_after > 0 else 0.0

    print(f"  Trainable parameters: {trainable_after:,} / {total_after:,} ({trainable_pct:.2f}%)")

    # ---- Step 5: Save report ----
    os.makedirs(output_dir, exist_ok=True)
    report_path = os.path.join(output_dir, "architecture_report.json")

    report = {
        "model_type": model_type,
        "total_params": total_after,
        "trainable_params": trainable_after,
        "trainable_pct": round(trainable_pct, 4),
        "linear_modules": linear_modules,
        "lora_target_modules": lora_targets,
    }

    try:
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2)
        print(f"\nReport saved to {report_path}")
    except Exception as e:
        print(f"ERROR: Failed to save report: {e}", file=sys.stderr)
        sys.exit(1)

    print("\nDone.")


if __name__ == "__main__":
    main()
