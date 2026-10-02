#!/usr/bin/env bash
# Read-only post-apply / post-reboot acceptance gate.
set -euo pipefail
[[ $(findmnt -no FSTYPE /run) == tmpfs ]]
for path in /run/privacyshield-nginx/body /run/privacyshield-nginx/proxy; do
  [[ $(findmnt -T "$path" -no FSTYPE) == tmpfs ]]
done
[[ $(wc -l < /proc/swaps) -eq 1 ]]
[[ $(cat /proc/sys/kernel/core_pattern) == '|/bin/false' ]]
[[ $(cat /proc/sys/fs/suid_dumpable) == 0 ]]
[[ $(stat -c '%U:%G %a' /run/privacyshield-nginx/body) == 'www-data:www-data 700' ]]
nginx -t
config=$(nginx -T 2>/dev/null)
for directive in 'client_body_temp_path /run/privacyshield-nginx/body;' 'proxy_request_buffering off;' 'proxy_buffering off;' 'proxy_max_temp_file_size 0;'; do
  [[ $config == *"$directive"* ]]
done
! systemctl is-active --quiet apport.service
if [[ ${1:-} != --preflight ]]; then
  curl --fail --silent http://127.0.0.1:8000/health > /dev/null
fi
printf 'PASS: nginx temp in tmpfs, swap disabled, core handler disabled (API checked outside preflight)\n'
