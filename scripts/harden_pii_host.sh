#!/usr/bin/env bash
# Run as root on the OVH host. No application deployment or secret access.
set -euo pipefail
[[ $(id -u) == 0 ]] || { echo 'Run as root' >&2; exit 1; }
[[ $(findmnt -no FSTYPE /run) == tmpfs ]] || { echo '/run must be tmpfs' >&2; exit 1; }
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
site=/etc/nginx/sites-available/api.privacyshield.pro
[[ -f $site ]] || { echo 'Expected API site missing' >&2; exit 1; }
# Refuse swapoff if repatriating pages leaves less than 512MiB available.
available=$(awk '/MemAvailable:/ {print $2}' /proc/meminfo)
swap_used=$(awk '/SwapTotal:/ {t=$2} /SwapFree:/ {f=$2} END {print t-f}' /proc/meminfo)
(( available - swap_used > 524288 )) || { echo 'Insufficient RAM for swapoff' >&2; exit 1; }
install -d -m 0755 /etc/nginx/snippets
install -m 0644 "$script_dir/../infra/nginx-pii-memory.conf" /etc/nginx/snippets/privacyshield-pii-memory.conf
install -d -o www-data -g www-data -m 0700 /run/privacyshield-nginx /run/privacyshield-nginx/body /run/privacyshield-nginx/proxy
cat > /etc/tmpfiles.d/privacyshield-nginx.conf <<'CONF'
d /run/privacyshield-nginx 0700 www-data www-data -
d /run/privacyshield-nginx/body 0700 www-data www-data -
d /run/privacyshield-nginx/proxy 0700 www-data www-data -
CONF
if ! grep -q 'include /etc/nginx/snippets/privacyshield-pii-memory.conf;' "$site"; then
  cp -p "$site" "$site.before-pii-hardening"
  sed -i '/client_max_body_size/a\    include /etc/nginx/snippets/privacyshield-pii-memory.conf;' "$site"
fi
# Validate before applying network-facing changes.
nginx -t
swapoff -a
[[ -e /etc/fstab.before-pii-hardening ]] || cp -p /etc/fstab /etc/fstab.before-pii-hardening
awk '$1 !~ /^#/ && $3 == "swap" {print "# privacyshield: disabled swap " $0; next} {print}' /etc/fstab > /etc/fstab.pii-new
cat /etc/fstab.pii-new > /etc/fstab
rm /etc/fstab.pii-new
# Disable swap units on subsequent boots, including a generator outside fstab.
while read -r unit; do
  [[ -z $unit ]] || systemctl mask "$unit"
done < <(systemctl list-units --all --type=swap --no-legend | awk '{print $1}')
cat > /etc/sysctl.d/99-privacyshield-no-dumps.conf <<'CONF'
fs.suid_dumpable = 0
kernel.core_pattern = |/bin/false
CONF
mkdir -p /etc/systemd/coredump.conf.d /etc/systemd/system/nginx.service.d
cat > /etc/systemd/coredump.conf.d/privacyshield.conf <<'CONF'
[Coredump]
Storage=none
ProcessSizeMax=0
CONF
install -d -m 0755 /usr/local/lib/privacyshield
install -m 0755 "$script_dir/check_pii_host.sh" /usr/local/lib/privacyshield/check_pii_host.sh
cat > /etc/systemd/system/nginx.service.d/no-core.conf <<'CONF'
[Service]
LimitCORE=0
ExecStartPre=/usr/local/lib/privacyshield/check_pii_host.sh --preflight
CONF
if [[ -f /etc/default/apport ]]; then
  sed -i 's/^enabled=.*/enabled=0/' /etc/default/apport
  systemctl disable --now apport.service
fi
sysctl -p /etc/sysctl.d/99-privacyshield-no-dumps.conf
systemctl daemon-reload
systemctl restart nginx
"$script_dir/check_pii_host.sh"
