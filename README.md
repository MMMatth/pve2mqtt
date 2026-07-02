# pve2mqtt

Publishes Proxmox VE node metrics (CPU, RAM, uptime, load average, disk
usage, temperatures) to MQTT, with Home Assistant auto-discovery.

Run directly on the Proxmox host (not inside an LXC) — hardware sensors and
`pvesh` require host access.

## Install

```bash
git clone <this-repo-url>
cd pve2mqtt
sudo ./install.sh
```

Edit `/etc/pve2mqtt.conf` with your MQTT broker details, then test:

```bash
/usr/local/bin/pve2mqtt.py
tail -20 /var/log/pve2mqtt.log
```

A cron job (every minute) keeps it running. Sensors show up in Home
Assistant under **Settings → Devices → Proxmox `<node>`**.

## Files

- `pve2mqtt.py` — collects metrics and publishes to MQTT
- `pve2mqtt.conf.example` — config template
- `install.sh` / `uninstall.sh`

## Force re-publishing discovery

After changing the payload structure:

```bash
rm /var/lib/pve2mqtt/.discovery_<node-name>
/usr/local/bin/pve2mqtt.py
```
