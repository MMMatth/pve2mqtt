#!/usr/bin/env python3
"""
pve2mqtt.py - Publishes Proxmox VE node metrics to MQTT
(with Home Assistant MQTT Discovery).

Config file: /etc/pve2mqtt.conf (KEY=VALUE format)
"""
import json
import os
import socket
import subprocess
import sys

CONFIG_PATH = "/etc/pve2mqtt.conf"
STATE_DIR = "/var/lib/pve2mqtt"


def load_config(path):
    cfg = {}
    if not os.path.exists(path):
        print(f"Config file not found: {path}", file=sys.stderr)
        sys.exit(1)
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            cfg[k.strip()] = v.strip().strip('"')
    return cfg


def get_node_status(node):
    out = subprocess.check_output(
        ["pvesh", "get", f"/nodes/{node}/status", "--output-format", "json"]
    )
    return json.loads(out)


def get_hwmon_readings():
    """Read temperature and fan readings via lm-sensors (if installed).

    lm-sensors JSON keys carry the real measurement type as a prefix
    (e.g. "temp1_input" vs "fan1_input"), so that prefix - not the free-text
    label - is what decides whether a reading is a temperature or a fan
    speed. Any other kind of reading (voltages, etc.) is ignored.
    """
    temps = {}
    fans = {}
    try:
        out = subprocess.check_output(["sensors", "-j"], stderr=subprocess.DEVNULL)
        data = json.loads(out)
        for chip, readings in data.items():
            for label, values in readings.items():
                if not isinstance(values, dict):
                    continue
                for k, v in values.items():
                    if not isinstance(v, (int, float)) or not k.endswith("_input"):
                        continue
                    clean_label = f"{chip}_{label}".replace(" ", "_").replace(":", "").replace("-", "_").lower()
                    clean_label = "".join(c for c in clean_label if c.isalnum() or c == "_")
                    if k.startswith("temp"):
                        temps[clean_label] = round(v, 1)
                    elif k.startswith("fan"):
                        fans[clean_label] = round(v)
    except (FileNotFoundError, subprocess.CalledProcessError, json.JSONDecodeError):
        pass
    return temps, fans


def get_cpu_percent():
    """Compute CPU usage percent from /proc/stat deltas since the last run.

    Proxmox's own "cpu" field (from `pvesh get .../status`) is an instantaneous
    two-sample snapshot that has been observed to always read 0 on some PVE
    versions when invoked via the CLI instead of through pvestatd, so we
    measure usage ourselves between successive cron invocations.
    """
    os.makedirs(STATE_DIR, exist_ok=True)
    state_path = os.path.join(STATE_DIR, "cpu_stat")

    with open("/proc/stat") as f:
        values = [int(x) for x in f.readline().split()[1:]]
    idle = values[3] + values[4]  # idle + iowait
    total = sum(values)

    prev = None
    if os.path.exists(state_path):
        try:
            with open(state_path) as f:
                prev = tuple(int(x) for x in f.read().split())
        except (ValueError, OSError):
            prev = None

    with open(state_path, "w") as f:
        f.write(f"{idle} {total}")

    if prev is None or len(prev) != 2:
        return None
    prev_idle, prev_total = prev
    delta_idle = idle - prev_idle
    delta_total = total - prev_total
    if delta_total <= 0:
        return None
    return round((1 - delta_idle / delta_total) * 100, 1)


def get_disk_usage_root():
    try:
        out = subprocess.check_output(["df", "--output=pcent", "/"])
        pcent_line = out.decode().strip().splitlines()[-1]
        return int(pcent_line.strip().strip("%"))
    except Exception:
        return None


def build_payload(node):
    status = get_node_status(node)
    cpu_pct = get_cpu_percent()
    mem = status.get("memory", {})
    mem_total = mem.get("total", 0)
    mem_used = mem.get("used", 0)
    mem_pct = round(mem_used / mem_total * 100, 1) if mem_total else None
    uptime_s = status.get("uptime", 0)
    loadavg = status.get("loadavg", [None])[0]

    payload = {
        "cpu_percent": cpu_pct,
        "mem_percent": mem_pct,
        "mem_used_gb": round(mem_used / (1024**3), 2),
        "mem_total_gb": round(mem_total / (1024**3), 2),
        "uptime_hours": round(uptime_s / 3600, 1),
        "loadavg_1m": loadavg,
        "disk_pct_root": get_disk_usage_root(),
    }
    temps, fans = get_hwmon_readings()
    for k, v in temps.items():
        payload[f"temp_{k}"] = v
    for k, v in fans.items():
        payload[f"fan_{k}"] = v
    return payload


def mqtt_publish(cfg, topic, payload, retain=False):
    import paho.mqtt.publish as publish
    auth = None
    if cfg.get("MQTT_USER"):
        auth = {"username": cfg["MQTT_USER"], "password": cfg.get("MQTT_PASS", "")}
    publish.single(
        topic,
        payload=payload,
        retain=retain,
        hostname=cfg["MQTT_HOST"],
        port=int(cfg.get("MQTT_PORT", 1883)),
        auth=auth,
        client_id=f"pve2mqtt-{socket.gethostname()}",
    )


def publish_discovery(cfg, node, sensors):
    """Publish MQTT discovery config for each sensor (retained, one-shot)."""
    device = {
        "identifiers": [f"pve_{node}"],
        "name": f"Proxmox {node}",
        "manufacturer": "Proxmox",
        "model": "PVE Node",
    }
    state_topic = f"{cfg['MQTT_TOPIC_PREFIX']}/{node}/state"
    for key, unit, device_class, icon in sensors:
        obj_id = f"pve_{node}_{key}"
        config_topic = f"homeassistant/sensor/{obj_id}/config"
        config_payload = {
            "name": f"PVE {node} {key.replace('_', ' ')}",
            "state_topic": state_topic,
            "value_template": f"{{{{ value_json.{key} }}}}",
            "unique_id": obj_id,
            "device": device,
        }
        if unit:
            config_payload["unit_of_measurement"] = unit
        if device_class:
            config_payload["device_class"] = device_class
        if icon:
            config_payload["icon"] = icon
        mqtt_publish(cfg, config_topic, json.dumps(config_payload), retain=True)


def main():
    cfg = load_config(CONFIG_PATH)
    node = cfg.get("PVE_NODE") or socket.gethostname().split(".")[0]
    payload = build_payload(node)

    state_topic = f"{cfg['MQTT_TOPIC_PREFIX']}/{node}/state"
    mqtt_publish(cfg, state_topic, json.dumps(payload), retain=True)

    os.makedirs(STATE_DIR, exist_ok=True)
    marker = os.path.join(STATE_DIR, f".discovery_{node}")
    if cfg.get("HA_DISCOVERY", "true").lower() == "true" and not os.path.exists(marker):
        base_sensors = [
            ("cpu_percent", "%", None, None),
            ("mem_percent", "%", None, None),
            ("mem_used_gb", "GB", None, None),
            ("mem_total_gb", "GB", None, None),
            ("uptime_hours", "h", None, None),
            ("loadavg_1m", None, None, None),
            ("disk_pct_root", "%", None, None),
        ]
        temp_sensors = [
            (k, "°C", "temperature", None) for k in payload if k.startswith("temp_")
        ]
        fan_sensors = [
            (k, "RPM", None, "mdi:fan") for k in payload if k.startswith("fan_")
        ]
        publish_discovery(cfg, node, base_sensors + temp_sensors + fan_sensors)
        with open(marker, "w") as f:
            f.write("done\n")


if __name__ == "__main__":
    main()
