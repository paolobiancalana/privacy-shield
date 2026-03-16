"""Quantize ONNX NER model to INT8 for CPU deployment.

Applies dynamic quantization (S8S8) as recommended by ONNX Runtime
for transformer models on CPU. Falls back to U8U8 if needed.

Usage:
    python -m export.onnx_quantize --input output/onnx/model.onnx --output output/onnx_int8/model_int8.onnx
"""

from __future__ import annotations

import argparse
import logging
import shutil
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("onnx_quantize")


def quantize_int8(
    input_path: str,
    output_path: str,
    copy_tokenizer_from: str | None = None,
) -> Path:
    """Apply dynamic INT8 quantization to ONNX model."""
    from onnxruntime.quantization import quantize_dynamic, QuantType

    input_path = Path(input_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    input_size = input_path.stat().st_size / (1024 * 1024)
    logger.info("Input model: %s (%.1f MB)", input_path, input_size)

    logger.info("Applying dynamic quantization (QInt8)...")
    quantize_dynamic(
        model_input=str(input_path),
        model_output=str(output_path),
        weight_type=QuantType.QInt8,
    )

    output_size = output_path.stat().st_size / (1024 * 1024)
    ratio = input_size / output_size if output_size > 0 else 0

    logger.info("Quantized model: %s (%.1f MB, %.1fx reduction)", output_path, output_size, ratio)

    # Copy tokenizer + config to output dir if requested
    if copy_tokenizer_from:
        src = Path(copy_tokenizer_from)
        dst = output_path.parent
        for fname in ["tokenizer_config.json", "tokenizer.json",
                       "sentencepiece.bpe.model", "special_tokens_map.json",
                       "config.json"]:
            src_file = src / fname
            if src_file.exists():
                shutil.copy2(str(src_file), str(dst / fname))
                logger.info("Copied %s", fname)

    print(f"\n{'=' * 60}")
    print("INT8 Quantization Complete")
    print(f"  Input:      {input_path} ({input_size:.1f} MB)")
    print(f"  Output:     {output_path} ({output_size:.1f} MB)")
    print(f"  Reduction:  {ratio:.1f}x")
    print(f"{'=' * 60}\n")

    return output_path


def main():
    parser = argparse.ArgumentParser(description="Quantize ONNX model to INT8.")
    parser.add_argument("--input", type=str, required=True, help="Input ONNX model path")
    parser.add_argument("--output", type=str, required=True, help="Output INT8 model path")
    parser.add_argument("--copy-tokenizer-from", type=str, default=None,
                        help="Copy tokenizer/config from this directory")
    args = parser.parse_args()

    quantize_int8(args.input, args.output, args.copy_tokenizer_from)


if __name__ == "__main__":
    main()
