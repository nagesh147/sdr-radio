#!/bin/bash
killall -9 rtl_fm play 2>/dev/null
sleep 0.2
for d in /sys/bus/usb/devices/*/idVendor; do
  if [ -f "$d" ] && grep -q 0bda "$d"; then
    dev=$(dirname "$d")
    echo 0 > "$dev/authorized" 2>/dev/null
    sleep 0.4
    echo 1 > "$dev/authorized" 2>/dev/null
    echo "Reset $dev"
  fi
done
# Also reload drivers
modprobe -r dvb_usb_rtl28xxu rtl2832 rtl2830 2>/dev/null
modprobe dvb_usb_rtl28xxu 2>/dev/null
sleep 0.5
