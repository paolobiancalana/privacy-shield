# Privacy Shield — Deployment Guide

> Last updated: 2026-03-16

## Production Environment

| Component | Detail |
|-----------|--------|
| Host | OVHcloud VPS-1 (Gravelines, France) |
| Domain | privacyshield.pro (landing on Vercel), api.privacyshield.pro (API on OVH) |
| OS | Ubuntu 24.04 / 26.04 LTS |
| CPU | 2 vCore |
| RAM | 4 GB (model uses ~680MB, ~3GB available) |
| Disk | 40 GB SSD NVMe (model 265MB, ~36GB free) |
| Swap | 2 GB |

## Service Architecture

```
Internet → Nginx (80/443, TLS 1.3) → FastAPI (127.0.0.1:8000 via Docker) → ONNX Runtime + Redis
```

## Production Details

| Component | Detail |
|-----------|--------|
| Host IP | `162.19.78.180` |
| Primary User | `paolo` (SSH key authentication, NOPASSWD sudo, docker group) |
| System User | `ubuntu` (maintenance) |
| SSH Shortcut | `ssh privacyshield` o `ssh paolo@privacyshield` (configurato in `~/.ssh/config`) |
| Location | Gravelines (France) — OVHcloud SAS |
| Stack | Docker Compose (`privacy-shield` Python 3.12 container + `redis:7-alpine`) |
| Reverse Proxy | Nginx on host proxying `http://127.0.0.1:8000` |

## Directory Layout

```
/home/ubuntu/privacy-shield/
  ├── Dockerfile
  ├── docker-compose.yml
  ├── requirements-app.txt
  ├── .env                          # chmod 600, env variables
  ├── app/                          # FastAPI microservice
  └── .local/pii-model/             # ONNX INT8 model (265MB) + tokenizer
```

## Environment Variables (/opt/pii/.env)

| Variable | Description | Required |
|----------|-------------|----------|
| PRIVACY_SHIELD_KEK_BASE64 | AES-256 master key (base64, 32 bytes) | Yes |
| ADMIN_API_KEY | Admin endpoint authentication | Yes |
| REDIS_URL | Redis connection with password | Yes |
| PII_MODEL_DIR | Path to ONNX model directory | Yes |
| TOKEN_TTL_SECONDS | Vault entry TTL (default: 60) | No |
| MAX_TOKENS_PER_ORG | Per-org quota (default: 10000) | No |
| HOST | Bind address (default: 127.0.0.1) | No |
| PORT | Bind port (default: 8000) | No |
| LOG_LEVEL | Logging level (default: INFO) | No |

## Systemd Service

```
/etc/systemd/system/pii.service

[Unit]
Description=Privacy Shield PII Tokenization Service
After=network.target redis-server.service
Requires=redis-server.service

[Service]
User=pii
WorkingDirectory=/home/deploy/privacy-shield
EnvironmentFile=/opt/pii/.env
ExecStart=/opt/pii/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
Restart=always
RestartSec=5
NoNewPrivileges=yes
PrivateTmp=yes
CPUQuota=200%
MemoryMax=2G
```

### Commands

```bash
# Status
sudo systemctl status pii

# Restart
sudo systemctl restart pii

# Logs (live)
sudo journalctl -u pii -f

# Logs (last 100 lines)
sudo journalctl -u pii --no-pager -n 100
```

## Nginx Configuration

```
/etc/nginx/sites-available/privacy-shield

- privacyshield.pro     → static landing page (/var/www/privacyshield/)
- api.privacyshield.pro → mTLS proxy to localhost:8000
```

### TLS Certificates

| File | Purpose | Location |
|------|---------|----------|
| Server cert | Let's Encrypt (auto-renewal) | /etc/letsencrypt/live/privacyshield.pro/ |
| CA cert | Private CA for mTLS | /etc/nginx/certs/ca.crt |
| CA key | CA private key (PROTECT) | /etc/nginx/certs/ca.key |
| Client cert | For SNAP server | /etc/nginx/certs/snap-client.crt |
| Client key | For SNAP server | /etc/nginx/certs/snap-client.key |

### Creating a New Client Certificate

```bash
cd /etc/nginx/certs
openssl genrsa -out newclient.key 2048
openssl req -new -sha256 -key newclient.key -out newclient.csr \
  -subj "/C=IT/O=Privacy Shield/CN=new-client-name"
openssl x509 -req -sha256 -days 365 -in newclient.csr \
  -CA ca.crt -CAkey ca.key -CAcreateserial -out newclient.crt
openssl verify -CAfile ca.crt newclient.crt
```

## Redis

```
/etc/redis/redis.conf

- Bind: 127.0.0.1 only
- Auth: requirepass (stored in /opt/pii/.redis_pass)
- Persistence: disabled (save "", appendonly no)
- Memory: maxmemory 100mb, allkeys-lru
- Dangerous commands: renamed/disabled (FLUSHALL, CONFIG, DEBUG)
```

## Firewall (UFW)

| Port | Service | From |
|------|---------|------|
| 22/tcp | SSH | Anywhere |
| 443/tcp | HTTPS (Nginx) | Anywhere |
| 8000 | FastAPI | 127.0.0.1 only |

## Deployment Procedure

```bash
# 1. SSH into server
ssh deploy@<OVH_VPS_IP>

# 2. Pull latest code
cd /home/deploy/privacy-shield
git pull origin main

# 3. Install new dependencies (if any)
sudo /opt/pii/venv/bin/pip install -r requirements-app.txt

# 4. Restart service
sudo systemctl restart pii

# 5. Verify
curl -s http://localhost:8000/health
sudo journalctl -u pii --no-pager -n 5
```

## Monitoring

| Check | Command | Expected |
|-------|---------|----------|
| Service up | `systemctl is-active pii` | active |
| Health | `curl localhost:8000/health` | {"status":"healthy"} |
| Redis | `redis-cli -a $PASS ping` | PONG |
| RAM | `free -h` | > 1GB available |
| Cert expiry | `certbot certificates` | > 30 days |
| fail2ban | `fail2ban-client status sshd` | active |

## Backup

### What to backup

| Item | Location | Method |
|------|----------|--------|
| .env (KEK, admin key) | /opt/pii/.env | Copy to secure location (NOT git) |
| CA key | /etc/nginx/certs/ca.key | Copy to secure location (NOT git) |
| Redis password | /opt/pii/.redis_pass | Copy to secure location |
| ONNX model | /opt/pii/model/ | Google Drive backup exists |

### What NOT to backup

- Redis data (ephemeral by design — PII tokens expire)
- Logs (contain no PII, rotated automatically)
