#!/bin/bash

###############################################
# Premium RTL-SDR Control Panel
###############################################

LOCKFILE="/tmp/sdr-control.lock"
STATUS_FILE="/tmp/sdr-current-mode"
LOG_FILE="/tmp/sdr-control.log"

log() {
  echo -e "$(date '+%H:%M:%S')  $1" | tee -a "$LOG_FILE"
}

# Single instance
if [ -f "$LOCKFILE" ]; then
  wmctrl -a "RTL-SDR Control Panel" 2>/dev/null && exit 0
  rm -f "$LOCKFILE"
fi
echo $$ > "$LOCKFILE"
trap "rm -f $LOCKFILE; exit" INT TERM EXIT

[[ -f $STATUS_FILE ]] || echo "None" > "$STATUS_FILE"
echo "=== SDR Control Log started $(date) ===" > "$LOG_FILE"

stop_all() {
  log "→ Stopping all SDR processes..."
  sudo systemctl stop readsb 2>/dev/null
  killall -9 sdrpp satdump satdump-ui AIS-catcher 2>/dev/null
  sleep 1.2
  echo "None" > "$STATUS_FILE"
  log "✓ All stopped. Dongle free."
}

open_status() {
  if ! pgrep -f "xterm.*SDR Status" >/dev/null; then
    xterm -T "SDR Status Terminal" -geometry 95x22+80+80 \
      -bg black -fg lightgreen -fa Monospace -fs 10 \
      -e "tail -f $LOG_FILE" &
  else
    wmctrl -a "SDR Status Terminal" 2>/dev/null
  fi
}

test_dongle() {
  open_status
  log "→ Running rtl_test (5 seconds)..."
  timeout 5 rtl_test -t 2>&1 | tee -a "$LOG_FILE"
  log "✓ rtl_test finished"
  zenity --info --title="Dongle Test" --text="rtl_test completed.\nCheck the Status Terminal for results." --width=350
}

while true; do
  CURRENT=$(cat "$STATUS_FILE" 2>/dev/null || echo "None")

  CHOICE=$(zenity --list \
    --title="RTL-SDR Control Panel" \
    --text="<span size='large'><b>Currently: $CURRENT</b></span>\n\nChoose an action:" \
    --column="ID" --column="Mode" --column="Description" \
    --hide-header \
    --width=640 --height=480 \
    "1" "🎧  General Radio" "SDR++  •  FM / AM / SSB / Airband" \
    "2" "✈️  Flight Tracking" "ADS-B Aircraft Map (tar1090)" \
    "3" "🛰️  Weather Satellites" "SatDump  •  Meteor LRPT" \
    "4" "🚢  AIS Ships" "Marine vessel tracking" \
    "5" "🔌  Test Dongle" "Run rtl_test verification" \
    "6" "📟  Status Terminal" "Live background log" \
    "7" "⏹️  Stop Everything" "Free the RTL-SDR dongle" \
    "8" "❌  Exit" "Close this panel")

  case $CHOICE in
    "1")
      stop_all
      echo "Radio (SDR++)" > "$STATUS_FILE"
      log "▶ Starting SDR++"
      open_status
      sdrpp &
      ;;
    "2")
      stop_all
      echo "Flight Tracking" > "$STATUS_FILE"
      log "▶ Starting Flight Tracker (readsb)"
      sudo mkdir -p /run/readsb
      sudo chmod 777 /run/readsb
      sudo systemctl daemon-reload
      sudo systemctl restart readsb
      READY=0
      for _ in {1..20}; do
        if systemctl is-active --quiet readsb &&
           curl -fsS --max-time 2 http://localhost/tar1090/data/aircraft.json >/dev/null; then
          READY=1
          break
        fi
        sleep 0.8
      done
      if [ "$READY" = "1" ]; then
        log "✓ readsb running"
        xdg-open http://localhost/tar1090/ &
      else
        log "✗ readsb/tar1090 data not ready"
        systemctl status readsb --no-pager -l >> "$LOG_FILE" 2>&1 || true
        zenity --error --text="Flight Tracker data is not ready. Check: systemctl status readsb"
      fi
      open_status
      ;;
    "3")
      stop_all
      echo "Weather (SatDump)" > "$STATUS_FILE"
      log "▶ Starting SatDump"
      open_status
      satdump-ui &
      ;;
    "4")
      stop_all
      echo "AIS (Ships)" > "$STATUS_FILE"
      log "▶ Starting AIS-catcher"
      open_status
      AIS-catcher -d 0 -v 10 2>&1 | tee -a "$LOG_FILE" &
      ;;
    "5")
      test_dongle
      ;;
    "6")
      open_status
      ;;
    "7")
      stop_all
      zenity --info --text="All processes stopped.\nDongle is free." --timeout=2
      ;;
    "8"|"")
      rm -f "$LOCKFILE"
      exit 0
      ;;
  esac
done
