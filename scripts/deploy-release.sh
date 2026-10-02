#!/usr/bin/env bash
set -euo pipefail
sha=${1:?exact tested commit required}
[[ "$sha" =~ ^[a-f0-9]{40}$ ]] || exit 2
source_dir=/home/paolo/privacy-shield
release=/home/paolo/privacy-shield-releases/$sha
exec 9>/home/paolo/privacy-shield-deploy.lock
flock -n 9 || exit 3
cd "$source_dir"
git fetch origin main
git cat-file -e "$sha^{commit}"
mkdir -p "$release/.local"
git archive "$sha" | tar -x -C "$release"
[[ -d "$release/.local/pii-model" ]] || cp -al "$source_dir/.local/pii-model" "$release/.local/pii-model"
[[ -e "$release/.env" ]] || ln -s "$source_dir/.env" "$release/.env"
printf 'services:\n  privacy-shield:\n    image: privacy-shield:%s\n' "$sha" > "$release/release-override.yml"
docker build -t "privacy-shield:$sha" "$release"
# Validate the actual image/model before interrupting traffic.
docker run --rm -i --network none --read-only --tmpfs /tmp --memory 1g --memory-swap 1g --ulimit core=0 -e HF_HUB_OFFLINE=1 --entrypoint python "privacy-shield:$sha" <<'PY'
import asyncio
from app.infrastructure.adapters.ner_detection import NerDetectionAdapter
tail = ' Il signor Mario Rossi abita a Roma.'
text = ('testo neutro ' * 1000)[:10000-len(tail)] + tail
result = asyncio.run(NerDetectionAdapter('/opt/pii/model').detect(text))
assert any('Mario Rossi' in span.text for span in result.spans), 'tail PII missed'
print('candidate NER accepted')
PY
old_dir=$(readlink -f /home/paolo/privacy-shield-current 2>/dev/null || true)
[[ -d "$old_dir" ]] || old_dir=$source_dir
old_image=$(docker inspect --format '{{.Image}}' privacy-shield-privacy-shield-1)
printf 'services:\n  privacy-shield:\n    image: %s\n' "$old_image" > "$release/rollback-override.yml"
snippet=/etc/nginx/snippets/privacyshield-pii-memory.conf
backup=$(mktemp)
sudo cp "$snippet" "$backup"
switched=0
restore() {
  result=$?
  trap - EXIT
  if [[ $result != 0 && $switched == 1 ]]; then
    docker compose -p privacy-shield -f "$old_dir/docker-compose.yml" -f "$release/rollback-override.yml" up -d --no-build || true
  fi
  sudo cp "$backup" "$snippet"
  sudo nginx -t && sudo systemctl reload nginx
  rm -f "$backup"
  exit "$result"
}
trap restore EXIT
printf '\nlocation ^~ /api/v1/ { return 503; }\n' | sudo tee -a "$snippet" >/dev/null
sudo nginx -t
sudo systemctl reload nginx
# Drain requests and their ephemeral tokens before replacing Redis/writers.
sleep 125
switched=1
docker compose -p privacy-shield -f "$release/docker-compose.yml" -f "$release/release-override.yml" up -d --no-build
ready=0
for attempt in $(seq 1 30); do
  if curl --max-time 20 -fsS http://127.0.0.1:8000/ready >/dev/null; then ready=1; break; fi
  sleep 3
done
[[ $ready == 1 ]]
printf '%s\n' "$sha" > "$release/RELEASE_SHA"
ln -sfn "$release" /home/paolo/privacy-shield-current
printf 'DEPLOYED %s\n' "$sha"
