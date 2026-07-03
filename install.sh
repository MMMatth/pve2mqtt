#!/usr/bin/env bash
#
# install.sh - Installs pve2mqtt on a Proxmox VE node.
# Run as root, from the repo folder, directly on the PVE host.
#
set -euo pipefail
cd "$(dirname "$0")"

if [[ $EUID -ne 0 ]]; then
  echo "This script must be run as root." >&2
  exit 1
fi

echo "=== Installing pve2mqtt ==="

CRON_SCHEDULE="${CRON_SCHEDULE:-* * * * *}"

# --- Dependencies ---
apt-get update -qq
apt-get install -y -qq python3-pip lm-sensors >/dev/null
pip3 install --break-system-packages --root-user-action=ignore --quiet paho-mqtt
sensors-detect --auto >/dev/null 2>&1 || true

# --- HDD Temperature Kernel Module ---
echo "Configuring drivetemp module for HDD/SSD temperature monitoring..."
modprobe drivetemp || true
if [[ -f /etc/modules ]]; then
  if ! grep -q "^drivetemp" /etc/modules; then
    echo "drivetemp" >> /etc/modules
  fi
else
  echo "drivetemp" >> /etc/modules
fi

# --- Script ---
install -m 755 pve2mqtt.py /usr/local/bin/pve2mqtt.py

# --- Config (never overwrite an existing config) ---
if [[ -f /etc/pve2mqtt.conf ]]; then
  echo "/etc/pve2mqtt.conf already exists, leaving it untouched."
else
  install -m 600 pve2mqtt.conf.example /etc/pve2mqtt.conf
  sed -i "s/^PVE_NODE=.*/PVE_NODE=$(hostname -s)/" /etc/pve2mqtt.conf
  echo "/etc/pve2mqtt.conf created. EDIT IT before first run (MQTT_HOST, MQTT_USER, MQTT_PASS)."
fi

mkdir -p /var/lib/pve2mqtt

# --- Cron ---
CRON_LINE="${CRON_SCHEDULE} /usr/local/bin/pve2mqtt.py >> /var/log/pve2mqtt.log 2>&1"
EXISTING_CRON="$(crontab -l 2>/dev/null | grep -v 'pve2mqtt.py' || true)"
printf '%s\n%s\n' "${EXISTING_CRON}" "${CRON_LINE}" | grep -v '^$' | crontab -

echo
echo "=== Installation complete ==="
echo "1. Edit /etc/pve2mqtt.conf with your MQTT credentials"
echo "2. Test: /usr/local/bin/pve2mqtt.py && tail -20 /var/log/pve2mqtt.log"
echo "3. Check Home Assistant: Settings > Devices > 'Proxmox <your-node>'"
