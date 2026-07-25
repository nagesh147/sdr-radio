#!/bin/bash
killall -9 sdrpp satdump satdump-ui 2>/dev/null
sudo mkdir -p /run/readsb
sudo chmod 777 /run/readsb
sudo systemctl restart readsb
sleep 3
xdg-open http://localhost/tar1090/
