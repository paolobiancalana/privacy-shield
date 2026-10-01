# AGENTS.md — Guidelines for AI Coding Agents

> **Privacy Shield** — Italian GDPR-Sovereign PII Tokenization & Vault Service.
> All agents working on this repository must read and strictly adhere to these instructions.

---

## 1. Architecture & Compliance Principles

1. **Sovereign EU Infrastructure**:
   - **Production VPS**: OVHcloud Gravelines (France) at `162.19.78.180`.
   - **No US Cloud Act Exposure**: Under no circumstances should backend PII processing or Redis vaulting be moved to US-controlled clouds (AWS, GCP, Railway, Azure US).
2. **Zero-PII Persistence Rule**:
   - Redis operates purely in-memory: `save ""` and `appendonly no`.
   - Ephemeral vault tokens expire after `TOKEN_TTL_SECONDS` (default: 60s).
   - Plaintext PII is **never logged** (`TokenInfo.original` is excluded from all logs).
3. **Hexagonal Architecture**:
   - `app/domain/`: Pure business entities, ports, and algorithms (zero external framework dependencies).
   - `app/application/`: Use cases orchestrating domain ports.
   - `app/infrastructure/`: Adapters (Redis, ONNX Runtime, FastAPI, Supabase).
   - Never import infrastructure code into domain or application layers.

---

## 2. Server Infrastructure & SSH Access

| Setting | Value |
|---|---|
| **Host IP** | `162.19.78.180` |
| **SSH Host Alias** | `privacyshield` (e.g. `ssh privacyshield`) |
| **SSH User** | `paolo` (sudo NOPASSWD, docker group) |
| **Key** | `~/.ssh/id_ed25519` (Ed25519 cryptographic key) |
| **Remote Directory** | `/home/ubuntu/privacy-shield` (symlink at `/home/paolo/privacy-shield`) |
| **Containers** | Docker Compose: `privacy-shield` (FastAPI:8000) + `redis` (Redis 7) |
| **Web Proxy** | Nginx on host (`80` / `443` -> `127.0.0.1:8000`) |

---

## 3. Continuous Integration (CI)

### Backend Testing (Python 3.12+)
Before deploying or committing backend changes, run:
```bash
# 1. Unit & domain tests
python -m pytest tests_app/ -q --tb=short

# 2. Cryptography test (AES-256-GCM round-trip)
python -m pytest tests_app/infrastructure/test_aes_crypto.py

# 3. Detection tests (Regex + Span Fusion)
python -m pytest tests_app/domain/test_span_fusion.py tests_app/infrastructure/test_regex_detection.py
```

### Frontend Testing (Next.js)
```bash
cd platform/web
npm run lint
npm run build
```

---

## 4. Continuous Deployment (CD) Workflows

Agents can execute CD through two primary methods:

### Method A: Direct Agent CD (Fast / Pair Programming)
When an agent makes code edits locally and needs to deploy them immediately to the production VPS:

```bash
# Step 1: Sync modified application files to VPS
rsync -avz --exclude='__pycache__' --exclude='.git' \
  ./app/ paolo@privacyshield:~/privacy-shield/app/

# Step 2: Rebuild & restart Docker container
ssh paolo@privacyshield "cd ~/privacy-shield && docker compose up -d --build"

# Step 3: Verify container health
ssh paolo@privacyshield "curl -sf http://127.0.0.1:8000/health"

# Step 4: Run smoke test
curl -s https://api.privacyshield.pro/health
```

### Method B: Git-Based Automated CD (GitHub Actions)
When pushing to `origin/main`:
1. `.github/workflows/ci.yml` runs automated tests in an ephemeral Redis container.
2. If tests pass, GitHub Actions connects via SSH to `162.19.78.180`.
3. Runs:
   ```bash
   cd ~/privacy-shield
   git pull origin main
   docker compose up -d --build
   ```
4. Executes automatic smoke test and rolls back (`git checkout HEAD~1`) if health check fails.

---

## 5. Security & Hardening Rules (DO NOT MODIFY)

1. **SSH Hardening**:
   - `PasswordAuthentication no` and `KbdInteractiveAuthentication no` are enforced in `/etc/ssh/sshd_config.d/00-security-hardening.conf`.
   - **NEVER** re-enable password authentication. Access is strictly key-based.
2. **Brute Force Protection**:
   - `fail2ban` is actively monitoring `sshd` with 24-hour ban for repeat offenders.
   - UFW firewall enforces rate-limiting on port 22 (`LIMIT IN Anywhere`).
   - Ports open to the internet: **only 80, 443, and 22**. Port 8000 and 6379 must remain local-only (`127.0.0.1`).
3. **Secrets Management**:
   - `PRIVACY_SHIELD_KEK_BASE64` is the AES master key. **NEVER** log it, commit it, or expose it in error messages.
   - Remote `.env` file at `~/privacy-shield/.env` has permissions `600`.
4. **Model Preservation**:
   - The ONNX model weights (`.local/pii-model/model_int8.onnx`, 265 MB) are pre-quantized and mounted inside the container.
   - Do not delete or commit `.local/pii-model` to Git (it is listed in `.gitignore`).

---

## 6. Useful Production Commands

```bash
# View live application logs
ssh paolo@privacyshield "docker compose -f ~/privacy-shield/docker-compose.yml logs -f privacy-shield"

# Check fail2ban status and banned IPs
ssh paolo@privacyshield "sudo fail2ban-client status sshd"

# Check UFW firewall status
ssh paolo@privacyshield "sudo ufw status verbose"

# View memory and system resources
ssh paolo@privacyshield "free -h && df -h / && docker stats --no-stream"
```
