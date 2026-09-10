#!/usr/bin/env python3
"""Collect read-only telemetry and derive explicit world situations."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / "coordination" / "state"
DEFAULT_RAW = STATE_DIR / "world-telemetry.json"
DEFAULT_STATE = STATE_DIR / "world-state.json"
DEFAULT_COORDINATION = STATE_DIR / "snapshot.json"
BOUNDARY = "World state is read-only and does not create, approve, or dispatch directives."
ACTIVE = {"active", "detected", "home", "occupied", "on", "open", "printing", "paused"}
RUNNING = {"healthy", "running", "up"}


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def freshness(observed_at: str | None, collected_at: str, limit: int) -> dict[str, Any]:
    observed = parse_time(observed_at)
    collected = parse_time(collected_at)
    if not observed or not collected:
        return {"status": "unknown", "age_seconds": None, "limit_seconds": limit}
    age = max(0, int((collected - observed).total_seconds()))
    return {"status": "fresh" if age <= limit else "stale", "age_seconds": age, "limit_seconds": limit}


def _coordination_summary(payload: dict[str, Any]) -> dict[str, Any]:
    sources = payload.get("sources", {})
    return {
        "generated_at": payload.get("generated_at"),
        "source_availability": {
            name: bool(details.get("available"))
            for name, details in sources.items()
            if isinstance(details, dict)
        },
        "warning_count": len(payload.get("warnings", [])),
        "directive_count": len(payload.get("directives", [])),
    }


def _observation(source: dict[str, str], item: Any, index: int, meta: dict[str, Any], collected_at: str) -> dict[str, Any]:
    kind = source["kind"]
    name = source["name"]
    observed_at = meta.get("observed_at")
    key = str(index)
    value = item
    if isinstance(item, dict):
        key = str(item.get("entity_id") or item.get("topic") or item.get("name") or index)
        observed_at = item.get("last_updated") or item.get("observed_at") or observed_at
        if kind == "home_assistant":
            value = {"state": item.get("state")}
        elif kind == "mqtt":
            mqtt_payload = item.get("payload")
            value = mqtt_payload if isinstance(mqtt_payload, dict) else {"state": mqtt_payload}
        elif kind == "service":
            value = {"state": item.get("state")}
        elif kind == "coordination":
            value = _coordination_summary(item)
    return {
        "id": f"{kind}:{name}:{key}",
        "source": source,
        "observed_at": observed_at,
        "freshness": freshness(observed_at, collected_at, int(meta.get("freshness_seconds", 300))),
        "sensitivity": meta.get("sensitivity", "internal"),
        "confidence": max(0.0, min(1.0, float(meta.get("confidence", 1.0)))),
        "value": value,
    }


def normalize(raw: dict[str, Any]) -> list[dict[str, Any]]:
    collected_at = raw["collected_at"]
    observations = []
    for record in raw.get("sources", []):
        payload = record.get("payload")
        items = payload if isinstance(payload, list) else [payload]
        observations.extend(
            _observation(record["source"], item, index, record, collected_at)
            for index, item in enumerate(items)
            if item is not None
        )
    for index, error in enumerate(raw.get("errors", [])):
        source_name, _, detail = str(error).partition(":")
        observations.append(
            _observation(
                {"kind": "collector", "name": source_name or "unknown"},
                {"state": "unavailable", "detail": detail.strip()},
                index,
                {"observed_at": collected_at, "freshness_seconds": 0, "sensitivity": "internal", "confidence": 1.0},
                collected_at,
            )
        )
    return observations


def _state(observation: dict[str, Any]) -> str:
    value = observation.get("value")
    if isinstance(value, dict):
        value = value.get("state", value.get("status", ""))
    return str(value).lower()


def _situation(identifier: str, label: str, state: str, rule: str, evidence: list[dict[str, Any]]) -> dict[str, Any]:
    confidence = min((item["confidence"] for item in evidence), default=0.0)
    return {
        "id": identifier,
        "label": label,
        "state": state,
        "confidence": confidence,
        "rule": rule,
        "evidence": [item["id"] for item in evidence],
        "why": [f"{item['id']} = {_state(item) or 'observed'}" for item in evidence],
    }


def derive(observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    services = [item for item in observations if item["source"]["kind"] == "service"]
    systems = [item for item in observations if item["source"]["kind"] == "system"]
    bad_services = [item for item in services if _state(item) not in RUNNING]
    bad_systems = [
        item for item in systems
        if isinstance(item.get("value"), dict) and float(item["value"].get("disk_used_percent", 0)) >= 90
    ]
    health_evidence = bad_services + bad_systems or services + systems
    health = "degraded" if bad_services or bad_systems else "healthy" if health_evidence else "unknown"

    studio = [
        item for item in observations
        if "studio" in item["id"].lower()
    ]
    active_studio = [item for item in studio if _state(item) in ACTIVE]
    studio_state = "active" if active_studio else "inactive" if studio else "unknown"

    fabrication = [
        item for item in observations
        if any(word in item["id"].lower() for word in ("octoprint", "printer", "fabrication"))
    ]
    active_fabrication = [item for item in fabrication if _state(item) in {"printing", "paused", "active"}]
    fabrication_state = "active" if active_fabrication else "inactive" if fabrication else "unknown"

    stale = [item for item in observations if item["freshness"]["status"] == "stale"]
    unavailable = [item for item in observations if item["source"]["kind"] == "collector" and _state(item) == "unavailable"]
    unknown_freshness = [item for item in observations if item["freshness"]["status"] == "unknown"]
    stale_state = "unavailable" if unavailable else "stale" if stale else "unknown" if unknown_freshness else "fresh"

    opportunities = bad_services + bad_systems + stale + unavailable + active_fabrication
    return [
        _situation("system-health", "System health", health, "degraded when a service is not running or disk use is at least 90%", health_evidence),
        _situation("studio-activity", "Studio activity", studio_state, "active when a studio observation has an explicit active state", active_studio or studio),
        _situation("fabrication-activity", "Fabrication activity", fabrication_state, "active when printer telemetry reports printing, paused, or active", active_fabrication or fabrication),
        _situation("source-staleness", "Source staleness", stale_state, "unavailable when collection fails; stale when any observation exceeds its source freshness limit", unavailable or stale or unknown_freshness or observations),
        _situation("evidence-opportunities", "Evidence opportunities", "open" if opportunities else "none", "open for degraded health, stale or unavailable evidence, or an active fabrication run", opportunities),
    ]


def interpret(raw: dict[str, Any]) -> dict[str, Any]:
    observations = normalize(raw)
    return {
        "contract": {
            "name": "homeauto-world-state",
            "schema_version": "1.0.0",
            "authority": "read-only; no control actions",
        },
        "generated_at": raw["collected_at"],
        "observations": observations,
        "situations": derive(observations),
        "boundaries": [BOUNDARY, "The local LLM consumes structured state downstream and is not a state source."],
    }


def render_situations(state: dict[str, Any]) -> str:
    lines = ["## World situations", "", "| Situation | State | Confidence |", "| --- | --- | --- |"]
    for item in state.get("situations", []):
        lines.append(f"| {item['label']} | {item['state']} | {item['confidence']:.2f} |")
        lines.extend(["", f"<details><summary>Why? {item['label']}</summary>", "", f"Rule: {item['rule']}", ""])
        lines.extend(f"- {reason}" for reason in item.get("why", []))
        if not item.get("why"):
            lines.append("- No matching observations.")
        lines.extend(["", "</details>"])
    lines.extend(["", "### World-state boundaries", ""])
    lines.extend(f"- {boundary}" for boundary in state.get("boundaries", []))
    return "\n".join(lines) + "\n"


def _record(kind: str, name: str, payload: Any, observed_at: str, freshness_seconds: int, sensitivity: str, confidence: float = 1.0) -> dict[str, Any]:
    return {
        "source": {"kind": kind, "name": name},
        "observed_at": observed_at,
        "freshness_seconds": freshness_seconds,
        "sensitivity": sensitivity,
        "confidence": confidence,
        "payload": payload,
    }


def collect_home_assistant(url: str, token: str) -> list[dict[str, Any]]:
    request = urllib.request.Request(url.rstrip("/") + "/api/states", headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)


def collect_mqtt(host: str, topic: str = "#") -> list[dict[str, Any]]:
    command = ["mosquitto_sub", "-h", host, "-t", topic, "-W", "2", "-C", "100", "-F", "%t\t%p"]
    result = subprocess.run(command, capture_output=True, text=True, timeout=5, check=False)
    if result.returncode not in {0, 27}:
        raise RuntimeError(result.stderr.strip() or "mosquitto_sub failed")
    rows = []
    for line in result.stdout.splitlines():
        topic_name, separator, payload = line.partition("\t")
        if not separator:
            continue
        try:
            value = json.loads(payload)
        except json.JSONDecodeError:
            value = payload
        rows.append({"topic": topic_name, "payload": value, "state": value.get("state") if isinstance(value, dict) else value})
    return rows


def collect_services(compose_file: Path) -> list[dict[str, Any]]:
    result = subprocess.run(
        ["docker", "compose", "-f", str(compose_file), "ps", "--format", "json"],
        capture_output=True, text=True, timeout=15, check=True,
    )
    text = result.stdout.strip()
    rows = json.loads(text) if text.startswith("[") else [json.loads(line) for line in text.splitlines() if line]
    return [{"name": row.get("Service") or row.get("Name"), "state": row.get("State") or row.get("Status")} for row in rows]


def collect_raw(coordination_path: Path = DEFAULT_COORDINATION, compose_file: Path = ROOT / "docker-compose.yml") -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    sources = []
    errors = []
    ha_url = os.getenv("HA_URL", "http://127.0.0.1:8123")
    ha_token = os.getenv("HA_TOKEN")
    if ha_token:
        try:
            sources.append(_record("home_assistant", "homeassistant", collect_home_assistant(ha_url, ha_token), now, 300, "household"))
        except Exception as exc:
            errors.append(f"home_assistant: {exc}")
    else:
        errors.append("home_assistant: HA_TOKEN not configured")
    mqtt_host = os.getenv("MQTT_HOST", "127.0.0.1")
    if shutil.which("mosquitto_sub"):
        try:
            sources.append(_record("mqtt", "mosquitto", collect_mqtt(mqtt_host, os.getenv("MQTT_TOPIC", "#")), now, 300, "household", 0.8))
        except Exception as exc:
            errors.append(f"mqtt: {exc}")
    else:
        errors.append("mqtt: mosquitto_sub is not installed")
    try:
        sources.append(_record("service", "docker-compose", collect_services(compose_file), now, 120, "internal"))
    except Exception as exc:
        errors.append(f"service: {exc}")
    disk = shutil.disk_usage(ROOT)
    sources.append(_record("system", socket.gethostname(), {"disk_used_percent": round((disk.used / disk.total) * 100, 1), "load_1m": os.getloadavg()[0]}, now, 120, "internal"))
    if coordination_path.is_file():
        snapshot = json.loads(coordination_path.read_text(encoding="utf-8"))
        observed_at = snapshot.get("generated_at") or datetime.fromtimestamp(coordination_path.stat().st_mtime, timezone.utc).isoformat()
        sources.append(_record("coordination", "operator-snapshot", snapshot, observed_at, 900, "private"))
    else:
        errors.append(f"coordination: missing {coordination_path}")
    return {"contract": {"name": "homeauto-raw-telemetry", "schema_version": "1.0.0"}, "collected_at": now, "sources": sources, "errors": errors}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, default=DEFAULT_RAW)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--coordination", type=Path, default=DEFAULT_COORDINATION)
    parser.add_argument("--fixture", type=Path)
    args = parser.parse_args()
    raw = json.loads(args.fixture.read_text()) if args.fixture else collect_raw(args.coordination)
    state = interpret(raw)
    args.raw.parent.mkdir(parents=True, exist_ok=True)
    args.state.parent.mkdir(parents=True, exist_ok=True)
    args.raw.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    args.state.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    print(f"raw: {args.raw}\nstate: {args.state}\ncollector errors: {len(raw.get('errors', []))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
