"""NER inference engine for Privacy Shield PII detection."""

# Lazy imports — NERInferenceEngine requires torch (training/eval only).
# server.py uses ONNX directly and only imports span_fusion from here.

__all__ = ["NERInferenceEngine"]


def __getattr__(name: str):
    if name == "NERInferenceEngine":
        from inference.inference import NERInferenceEngine
        return NERInferenceEngine
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
