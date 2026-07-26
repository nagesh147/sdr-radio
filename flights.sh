#!/bin/bash
set -euo pipefail

killall -9 sdrpp satdump satdump-ui 2>/dev/null || true

sudo mkdir -p /run/readsb
sudo chmod 777 /run/readsb
sudo systemctl daemon-reload
sudo systemctl restart readsb

for _ in {1..20}; do
  if systemctl is-active --quiet readsb &&
     curl -fsS --max-time 2 http://localhost/tar1090/data/aircraft.json >/dev/null; then
    xdg-open http://localhost/tar1090/
    exit 0
  fi
  sleep 0.8
done

echo "readsb started, but tar1090 aircraft data is not ready." >&2
systemctl status readsb --no-pager -l >&2 || true
exit 1
