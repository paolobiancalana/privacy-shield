# Privacy Shield — PII Detection Engine

NER-based PII detection for Italian business documents. Uses XLM-RoBERTa-base with token classification and deterministic span fusion post-processing.

## Architecture

- **Model**: XLM-RoBERTa-base (278M params), fine-tuned for 10 PII types
- **Inference**: ONNX Runtime INT8 (265MB, ~13ms/doc on CPU)
- **Post-processing**: `span_fusion.py` — deterministic trim + merge
- **Regex engine**: CF, IBAN, email, phone, P.IVA, PEC, SDI
- **Deploy**: FastAPI on 2vCPU/4GB VPS

## PII Types

| Code | Type | Source |
|------|------|--------|
| pe | Persona | NER |
| org | Organizzazione | NER |
| loc | Località | NER |
| ind | Indirizzo | NER |
| med | Medico | NER |
| leg | Legale | NER |
| rel | Relazione | NER |
| fin | Finanziario | NER |
| pro | Professione | NER |
| dt | Data nascita discorsiva | NER |
| cf | Codice Fiscale | Regex |
| ib | IBAN | Regex |
| em | Email | Regex |
| tel | Telefono | Regex |

## Metrics (v2, 2026-03-16)

| Metric | Value |
|--------|-------|
| Exact F1 (with fusion) | 88.5% |
| Partial F1 | 93.2% |
| FP rate (hard negatives) | 1.4% |
| Latency (ONNX INT8 CPU) | 12.8ms mean |

## Project Structure

```
dataset/           # Data pipeline (download, convert, clean, format)
training/          # Training config and scripts
inference/         # NER engine + span fusion
eval/              # Evaluation, benchmarks, e2e tests
export/            # ONNX export + INT8 quantization
scripts/           # Colab setup, dry run
tests/             # Unit tests + fixtures
```
