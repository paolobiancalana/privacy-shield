# Session Log — 2026-03-15/16

## What We Built (in order)

### Day 1 (2026-03-15): NER Model Training
1. Implemented full NER pipeline: bio_converter → ner_formatter → ner_train → inference → ner_evaluate
2. Discovered mDeBERTa-v3-base has NaN instability in both bf16 and fp32
3. Switched to XLM-RoBERTa-base — stable, same performance
4. Trained on 25K mixed dataset (wikineural + ai4privacy + multinerd + synthetic)
5. Results: F1 exact 76.1%, partial 93.5%
6. Implemented span_fusion post-processing → F1 exact 87.4% (+11pp free improvement)
7. Hardened span_fusion: apostrophes, possessives, abbreviations, parentheses — 16 unit tests
8. Generated boundary-hard synthetic pack (1000 examples)
9. Retrained v2 with boundary pack → F1 exact 88.5%, partial 93.2%
10. ONNX INT8 export: 265MB, 12.8ms mean latency on CPU

### Day 2 (2026-03-16): Production Deployment
11. Rebuilt Hetzner VPS (Ubuntu 24.04, clean install)
12. Production server setup: users (deploy/pii), swap 2GB, firewall, fail2ban
13. Deployed ONNX model + FastAPI service
14. Benchmarked on VPS: 83ms mean, 685MB RAM stable
15. Security audit: SSH hardening, port lockdown, Swagger disabled
16. Installed Nginx + Let's Encrypt (auto-renewal)
17. Implemented mTLS (private CA, client certificate required)
18. Created landing page on privacyshield.pro
19. DNS configured: privacyshield.pro + api.privacyshield.pro
20. Red team test: 11/11 PASS (only fixed Nginx version disclosure)
21. Installed Redis (hardened: password, zero persistence, localhost)
22. Generated encryption keys (KEK, admin key)
23. Integrated mature microservice (hexagonal architecture, vault, crypto, API keys)
24. Deployed full microservice: tokenize + rehydrate + flush working end-to-end
25. Verified Redis flush: PII data correctly deleted, zero residual
26. Added mTLS support to SNAP Framework HttpPrivacyShieldAdapter
27. Created architecture, deployment, and platform plan documents

## Key Decisions Made

| Decision | Rationale |
|----------|-----------|
| XLM-RoBERTa over mDeBERTa | mDeBERTa has NaN in all precisions |
| ONNX INT8 over PyTorch | 4x smaller, no PyTorch dependency on VPS |
| mTLS over API-key-only | Zero-trust: even with stolen API key, can't connect without cert |
| Nginx reverse proxy over direct exposure | TLS termination, rate limiting, security headers |
| Redis zero persistence | PII tokens are ephemeral by design, no data at rest |
| span_fusion as post-processing | +11pp F1 with zero retraining cost |
| Single VPS over Kubernetes | 2vCPU/4GB is sufficient, K8s would waste resources |
| Privacy Shield as standalone SaaS | Not tied to SNAP — serves any client via API |

## Production Endpoints

| URL | Purpose | Auth |
|-----|---------|------|
| https://privacyshield.pro | Landing page | Public |
| https://api.privacyshield.pro/api/v1/tokenize | PII tokenization | mTLS + API key |
| https://api.privacyshield.pro/api/v1/rehydrate | Token restoration | mTLS + API key |
| https://api.privacyshield.pro/api/v1/flush | Delete tokens | mTLS + API key |
| https://api.privacyshield.pro/health | Service health | Public (via mTLS Nginx) |

## Active Credentials

| Credential | Location | Purpose |
|-----------|----------|---------|
| Admin API key | /opt/pii/.env on VPS | Admin endpoint auth |
| KEK (base64) | /opt/pii/.env on VPS | Master encryption key |
| Redis password | /opt/pii/.redis_pass on VPS | Redis auth |
| Termopoint API key | `ps_live_0ca00f62c9db29f594070680a3448c92` | First org key |
| CA cert + key | /etc/nginx/certs/ on VPS | mTLS CA |
| SNAP client cert | /etc/nginx/certs/snap-client.* | SNAP mTLS auth |

## Files on Google Drive

| Path | Content |
|------|---------|
| privacy-shield-ner/model_v2 | Best NER model (XLM-R, 10 epochs, 25K mixed) |
| privacy-shield-ner/model_xlm_wikineural | Wikineural-only model (F1 94.6%) |
| privacy-shield-ner/onnx_fp32 | ONNX fp32 model |
| privacy-shield-ner/onnx_int8 | ONNX INT8 model (deployed) |
| privacy-shield-ner/data_mix_v2 | Training data splits |

## Next Steps

1. **Admin CLI** — script for org/key management (immediate)
2. **Platform API** — user auth, self-service key management (Sprint 2)
3. **Dashboard** — usage, keys, settings on privacyshield.pro (Sprint 3)
4. **Stripe billing** — plans, metering, invoices (Sprint 4)
5. **Real document testing** — 50-100 Termopoint documents annotated
6. **Model improvement** — more training data for fin type (€ patterns), ind boundaries
