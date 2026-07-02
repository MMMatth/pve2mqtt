#!/usr/bin/env bash
#
# uninstall.sh - Removes pve2mqtt from a Proxmox VE node.
#
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "This script must be run as root." >&2
  exit 1
fi

crontab -l 2>/dev/null | grep -v 'pve2mqtt.py' | crontab - || true
rm -f /usr/local/bin/pve2mqtt.py
rm -f /etc/pve2mqtt.conf
rm -rf /var/lib/pve2mqtt
rm -f /var/log/pve2mqtt.log

echo "pve2mqtt uninstalled. (remaining Home Assistant sensors can be removed manually)"
