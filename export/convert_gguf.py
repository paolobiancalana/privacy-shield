#!/usr/bin/env python3
"""
convert_gguf.py - Convert merged HF model to GGUF format and quantize.

# DEPRECATED: The NER approach uses a standard HuggingFace model (SavedModel/ONNX),
# not GGUF. This file is kept for backward compatibility and to document the
# generative (llama.cpp) approach.

Converts a HuggingFace model to GGUF FP16, then quantizes to multiple
targets (Q4_K_M, Q5_K_M, Q8_0). Optionally runs a smoke test against
a local llama-server instance.

Usage:
    python convert_gguf.py
    python convert_gguf.py --merged-dir output/merged --output-dir output
    python convert_gguf.py --skip-smoke-test
    python convert_gguf.py --quantizations Q4_K_M,Q8_0
"""

import argparse
import json
import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("convert_gguf")

SMOKE_TEST_INPUTS = [
    "Il dottor Bianchi di Milano ha diagnosticato diabete tipo 2.",
    "Marco Rossi abita in Via Garibaldi 42, 20100 Milano.",
    "La pizza margherita è buonissima.",  # hard negative
    "Mio fratello lavora al tribunale di Roma.",
    "Sono nato il quindici marzo del sessantadue.",
]

SMOKE_TEST_SYSTEM_PROMPT = (
    "Sei un modello di rilevamento PII. Analizza il testo e restituisci un array JSON "
    "di entità PII trovate. Ogni entità ha i campi: entity_type, value, confidence. "
    "Se non ci sono PII, restituisci un array vuoto []."
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert merged HF model to GGUF and quantize."
    )
    parser.add_argument(
        "--merged-dir",
        type=str,
        default="output/merged",
        help="Path to the merged HuggingFace model (default: output/merged)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="output",
        help="Path to save GGUF files (default: output)",
    )
    parser.add_argument(
        "--llama-cpp-dir",
        type=str,
        default="/content/llama.cpp",
        help="Path to llama.cpp installation (default: /content/llama.cpp)",
    )
    parser.add_argument(
        "--skip-smoke-test",
        action="store_true",
        help="Skip the smoke test after conversion",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=11434,
        help="Port for llama-server during smoke test (default: 11434)",
    )
    parser.add_argument(
        "--quantizations",
        type=str,
        default="Q4_K_M,Q5_K_M,Q8_0",
        help="Comma-separated quantization targets (default: Q4_K_M,Q5_K_M,Q8_0)",
    )
    return parser.parse_args()


def find_llama_cpp(llama_cpp_dir: str) -> str:
    """
    Locate llama.cpp installation. Search order:
    1. Explicit --llama-cpp-dir argument
    2. /content/llama.cpp (Colab default)
    3. PATH lookup for convert_hf_to_gguf.py
    """
    # Check explicit argument first (user override takes precedence)
    if os.path.isdir(llama_cpp_dir) and os.path.isfile(
        os.path.join(llama_cpp_dir, "convert_hf_to_gguf.py")
    ):
        logger.info("Found llama.cpp at: %s", llama_cpp_dir)
        return llama_cpp_dir

    # Check Colab default
    colab_path = "/content/llama.cpp"
    if os.path.isdir(colab_path) and os.path.isfile(
        os.path.join(colab_path, "convert_hf_to_gguf.py")
    ):
        logger.info("Found llama.cpp at Colab default: %s", colab_path)
        return llama_cpp_dir

    # Check PATH
    try:
        result = subprocess.run(
            ["which", "llama-quantize"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            quantize_bin = result.stdout.strip()
            # Navigate up from bin to llama.cpp root
            llama_root = str(Path(quantize_bin).parent.parent.parent)
            if os.path.isfile(os.path.join(llama_root, "convert_hf_to_gguf.py")):
                logger.info("Found llama.cpp via PATH: %s", llama_root)
                return llama_root
    except FileNotFoundError:
        pass

    logger.error(
        "llama.cpp not found. Searched:\n"
        "  1. /content/llama.cpp (Colab)\n"
        "  2. %s (--llama-cpp-dir)\n"
        "  3. PATH (llama-quantize)\n"
        "Install llama.cpp or provide --llama-cpp-dir.",
        llama_cpp_dir,
    )
    sys.exit(1)


def find_quantize_binary(llama_cpp: str) -> str:
    """Find the llama-quantize binary, checking common locations."""
    candidates = [
        os.path.join(llama_cpp, "build", "bin", "llama-quantize"),
        os.path.join(llama_cpp, "build", "bin", "quantize"),
        os.path.join(llama_cpp, "llama-quantize"),
        os.path.join(llama_cpp, "quantize"),
    ]
    for candidate in candidates:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate

    logger.error(
        "llama-quantize binary not found. Checked:\n%s\n"
        "Build llama.cpp first: cd %s && mkdir -p build && cd build && cmake .. && make -j",
        "\n".join(f"  - {c}" for c in candidates),
        llama_cpp,
    )
    sys.exit(1)


def find_server_binary(llama_cpp: str) -> str:
    """Find the llama-server binary for smoke testing."""
    candidates = [
        os.path.join(llama_cpp, "build", "bin", "llama-server"),
        os.path.join(llama_cpp, "build", "bin", "server"),
        os.path.join(llama_cpp, "llama-server"),
    ]
    for candidate in candidates:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate

    # Check PATH
    try:
        result = subprocess.run(
            ["which", "llama-server"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except FileNotFoundError:
        pass

    return ""


def run_command(cmd: list[str], description: str) -> subprocess.CompletedProcess:
    """Run a shell command with logging and error handling."""
    logger.info("Running: %s", description)
    logger.info("Command: %s", " ".join(cmd))

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        logger.error("Command failed (exit code %d):", result.returncode)
        if result.stdout:
            logger.error("STDOUT:\n%s", result.stdout[-2000:])
        if result.stderr:
            logger.error("STDERR:\n%s", result.stderr[-2000:])
        sys.exit(1)

    if result.stdout:
        # Log last few lines of output
        lines = result.stdout.strip().split("\n")
        for line in lines[-5:]:
            logger.info("  %s", line)

    return result


def get_file_size_mb(path: str) -> float:
    """Get file size in MB."""
    return os.path.getsize(path) / (1024 * 1024)


def convert_hf_to_gguf(llama_cpp: str, merged_dir: str, output_dir: str) -> str:
    """Convert HuggingFace model to GGUF FP16."""
    fp16_path = os.path.join(output_dir, "snap-pii-fp16.gguf")
    convert_script = os.path.join(llama_cpp, "convert_hf_to_gguf.py")

    if not os.path.isfile(convert_script):
        logger.error("Conversion script not found: %s", convert_script)
        sys.exit(1)

    run_command(
        [
            sys.executable,
            convert_script,
            merged_dir,
            "--outfile",
            fp16_path,
            "--outtype",
            "f16",
        ],
        "Convert HF model to GGUF FP16",
    )

    if not os.path.isfile(fp16_path):
        logger.error("FP16 GGUF not created at: %s", fp16_path)
        sys.exit(1)

    logger.info("FP16 GGUF: %s (%.1f MB)", fp16_path, get_file_size_mb(fp16_path))
    return fp16_path


def quantize_model(
    quantize_bin: str, fp16_path: str, output_dir: str, quant_type: str
) -> str:
    """Quantize GGUF model to a specific type."""
    quant_name = quant_type.lower()
    output_path = os.path.join(output_dir, f"snap-pii-{quant_name}.gguf")

    run_command(
        [quantize_bin, fp16_path, output_path, quant_type],
        f"Quantize to {quant_type}",
    )

    if not os.path.isfile(output_path):
        logger.error("Quantized GGUF not created at: %s", output_path)
        sys.exit(1)

    return output_path


def wait_for_server(port: int, timeout: int = 60) -> bool:
    """Poll the llama-server health endpoint until ready."""
    import urllib.error
    import urllib.request

    url = f"http://localhost:{port}/health"
    start = time.time()
    logger.info("Waiting for llama-server on port %d...", port)

    while time.time() - start < timeout:
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    logger.info("Server ready (%.1fs)", time.time() - start)
                    return True
        except (urllib.error.URLError, ConnectionError, OSError):
            pass
        time.sleep(1)

    logger.error("Server failed to start within %ds", timeout)
    return False


def send_chat_request(port: int, system_prompt: str, user_message: str) -> dict:
    """Send a chat completion request to the llama-server."""
    import urllib.error
    import urllib.request

    url = f"http://localhost:{port}/v1/chat/completions"
    payload = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "temperature": 0.0,
        "max_tokens": 512,
    }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as e:
        return {"error": str(e)}


def validate_json_response(content: str) -> tuple[bool, str]:
    """Check if the response content is a valid JSON array."""
    content = content.strip()

    # Try to extract JSON from the content (model may wrap it in markdown)
    if "```" in content:
        lines = content.split("\n")
        json_lines = []
        in_block = False
        for line in lines:
            if line.strip().startswith("```"):
                in_block = not in_block
                continue
            if in_block:
                json_lines.append(line)
        if json_lines:
            content = "\n".join(json_lines).strip()

    try:
        parsed = json.loads(content)
        if isinstance(parsed, list):
            return True, content
        return False, f"Expected JSON array, got {type(parsed).__name__}"
    except json.JSONDecodeError as e:
        return False, f"Invalid JSON: {e}"


def run_smoke_test(
    llama_cpp: str, model_path: str, port: int, output_dir: str
) -> bool:
    """Start llama-server, run test queries, verify JSON output."""
    server_bin = find_server_binary(llama_cpp)
    if not server_bin:
        logger.warning("llama-server binary not found. Skipping smoke test.")
        return False

    logger.info("Starting smoke test with model: %s", model_path)
    logger.info("Server binary: %s", server_bin)

    # Start server
    server_proc = subprocess.Popen(
        [
            server_bin,
            "--model",
            model_path,
            "--port",
            str(port),
            "--ctx-size",
            "512",
            "--n-gpu-layers",
            "999",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    results = []
    all_passed = True

    try:
        if not wait_for_server(port):
            logger.error("Server did not become ready. Aborting smoke test.")
            return False

        for i, test_input in enumerate(SMOKE_TEST_INPUTS):
            logger.info("Test %d/%d: %s", i + 1, len(SMOKE_TEST_INPUTS), test_input[:60])

            response = send_chat_request(port, SMOKE_TEST_SYSTEM_PROMPT, test_input)

            if "error" in response:
                logger.error("  Request failed: %s", response["error"])
                results.append(
                    {
                        "input": test_input,
                        "passed": False,
                        "error": response["error"],
                        "raw_response": None,
                    }
                )
                all_passed = False
                continue

            # Extract content from chat completion response
            try:
                content = response["choices"][0]["message"]["content"]
            except (KeyError, IndexError):
                logger.error("  Unexpected response structure: %s", json.dumps(response)[:200])
                results.append(
                    {
                        "input": test_input,
                        "passed": False,
                        "error": "Unexpected response structure",
                        "raw_response": response,
                    }
                )
                all_passed = False
                continue

            is_valid, detail = validate_json_response(content)

            results.append(
                {
                    "input": test_input,
                    "passed": is_valid,
                    "output": content,
                    "parsed_json": detail if is_valid else None,
                    "error": None if is_valid else detail,
                }
            )

            if is_valid:
                logger.info("  PASS - Valid JSON array")
            else:
                logger.warning("  FAIL - %s", detail)
                all_passed = False

    finally:
        # Terminate server
        logger.info("Stopping llama-server...")
        server_proc.terminate()
        try:
            server_proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            logger.warning("Server did not stop gracefully, sending SIGKILL.")
            server_proc.kill()
            server_proc.wait(timeout=5)

    # Save results
    results_path = os.path.join(output_dir, "smoke_test_results.json")
    summary = {
        "model": model_path,
        "total_tests": len(results),
        "passed": sum(1 for r in results if r["passed"]),
        "failed": sum(1 for r in results if not r["passed"]),
        "all_passed": all_passed,
        "results": results,
    }

    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    logger.info("Smoke test results saved to: %s", results_path)
    return all_passed


def main() -> None:
    args = parse_args()

    merged_dir = os.path.abspath(args.merged_dir)
    output_dir = os.path.abspath(args.output_dir)
    quant_types = [q.strip() for q in args.quantizations.split(",") if q.strip()]

    # --- Validate merged model directory ---
    if not os.path.isdir(merged_dir):
        logger.error("Merged model directory not found: %s", merged_dir)
        sys.exit(1)

    os.makedirs(output_dir, exist_ok=True)

    logger.info("Merged model dir   : %s", merged_dir)
    logger.info("Output dir         : %s", output_dir)
    logger.info("Quantizations      : %s", ", ".join(quant_types))

    # --- Find llama.cpp ---
    llama_cpp = find_llama_cpp(args.llama_cpp_dir)
    quantize_bin = find_quantize_binary(llama_cpp)
    logger.info("Quantize binary    : %s", quantize_bin)

    # --- Step 1: Convert HF to GGUF FP16 ---
    t_start = time.time()
    fp16_path = convert_hf_to_gguf(llama_cpp, merged_dir, output_dir)
    t_convert = time.time() - t_start

    # --- Step 2: Quantize ---
    gguf_files = {"fp16": fp16_path}
    t_quant_start = time.time()

    for quant_type in quant_types:
        output_path = quantize_model(quantize_bin, fp16_path, output_dir, quant_type)
        gguf_files[quant_type] = output_path

    t_quant = time.time() - t_quant_start

    # --- Print file sizes ---
    print()
    print("=" * 60)
    print("  GGUF Conversion Complete")
    print("=" * 60)
    print(f"  Conversion time  : {t_convert:.1f}s")
    print(f"  Quantization time: {t_quant:.1f}s")
    print()
    print("  Files:")
    for label, path in gguf_files.items():
        size_mb = get_file_size_mb(path)
        print(f"    {label:12s} : {os.path.basename(path):30s} ({size_mb:.1f} MB)")
    print("=" * 60)
    print()

    # --- Step 3: Smoke test ---
    if args.skip_smoke_test:
        logger.info("Smoke test skipped (--skip-smoke-test).")
    else:
        q4_path = gguf_files.get("Q4_K_M")
        if q4_path is None:
            # Use the first quantized model available
            non_fp16 = {k: v for k, v in gguf_files.items() if k != "fp16"}
            if non_fp16:
                first_key = next(iter(non_fp16))
                q4_path = non_fp16[first_key]
                logger.info("Q4_K_M not available, using %s for smoke test.", first_key)
            else:
                logger.info("No quantized model available for smoke test, using FP16.")
                q4_path = fp16_path

        logger.info("Running smoke test with: %s", os.path.basename(q4_path))
        passed = run_smoke_test(llama_cpp, q4_path, args.port, output_dir)

        if passed:
            logger.info("Smoke test: ALL PASSED")
        else:
            logger.warning("Smoke test: SOME TESTS FAILED (see smoke_test_results.json)")

    logger.info("GGUF export pipeline complete.")


if __name__ == "__main__":
    main()
