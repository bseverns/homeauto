#!/usr/bin/env python3
"""Collect read-only telemetry and derive explicit world situations."""

from __future__ import annotations

import argparse
import fnmatch
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
DEFAULT_REGISTRY = ROOT / "coordination" / "world-sources.json"
DEFAULT_STUDIO_REGISTRY = ROOT / "coordination" / "studio-machines.json"
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
    age = int((collected - observed).total_seconds())
    if age < 0:
        return {"status": "unknown", "age_seconds": None, "limit_seconds": limit}
    return {"status": "fresh" if age <= limit else "stale", "age_seconds": age, "limit_seconds": limit}


def _coordination_summary(payload: dict[str, Any]) -> dict[str, Any]:
    sources = payload.get("sources", {})
    needs = payload.get("benlab", {}).get("now", [])
    fits = payload.get("schedule", {}).get("capacity", {}).get("fits", [])
    return {
        "generated_at": payload.get("generated_at"),
        "source_availability": {
            name: bool(details.get("available"))
            for name, details in sources.items()
            if isinstance(details, dict)
        },
        "warning_count": len(payload.get("warnings", [])),
        "directive_count": len(payload.get("directives", [])),
        "active_needs": [
            {key: item.get(key) for key in ("project", "next_action", "effort", "stack", "route", "attention", "need_type", "evidence_blocker", "proof_route") if key in item}
            for item in needs if isinstance(item, dict)
        ],
        "capacity_projects": [item.get("project") for item in fits if item.get("temporal_status") == "today"],
    }


def load_registry(path: Path = DEFAULT_REGISTRY) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_studio_registry(path: Path = DEFAULT_STUDIO_REGISTRY) -> dict[str, Any]:
    registry = json.loads(path.read_text(encoding="utf-8"))
    machines = registry.get("machines")
    if registry.get("schema_version") != "1.0.0" or not isinstance(machines, list):
        raise ValueError("invalid studio-machine registry")
    identifiers = [item.get("id") for item in machines if isinstance(item, dict)]
    if len(identifiers) != len(machines) or len(set(identifiers)) != len(identifiers) or None in identifiers:
        raise ValueError("studio-machine IDs must be present and unique")
    return registry


def _matches(kind: str, pattern: str, key: str) -> bool:
    if kind != "mqtt":
        return fnmatch.fnmatchcase(key, pattern)
    values = key.split("/")
    tokens = pattern.split("/")
    for index, token in enumerate(tokens):
        if token == "#":
            return index == len(tokens) - 1
        if index >= len(values) or (token != "+" and token != values[index]):
            return False
    return len(tokens) == len(values)


def _source_definition(registry: dict[str, Any], kind: str, key: str) -> dict[str, Any]:
    return next((item for item in registry.get("sources", []) if item.get("kind") == kind and _matches(kind, item.get("match", ""), key)), {})


def _observation(source: dict[str, str], item: Any, index: int, meta: dict[str, Any], collected_at: str, registry: dict[str, Any]) -> dict[str, Any]:
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
    definition = _source_definition(registry, kind, key) or _source_definition(registry, kind, name) or {
        "domain": "system" if kind == "collector" else "unknown",
        "semantic": "collector_status" if kind == "collector" else "unknown",
        "state_kind": "state",
    }
    declared_source = {**source, "key": key, **{key: definition[key] for key in ("domain", "semantic", "state_kind", "affordances", "affordance_scope") if key in definition}}
    return {
        "id": f"{kind}:{name}:{key}",
        "source": declared_source,
        "observed_at": observed_at,
        "freshness": freshness(observed_at, collected_at, int(definition.get("freshness_seconds", meta.get("freshness_seconds", 300)))),
        "sensitivity": definition.get("sensitivity", meta.get("sensitivity", "internal")),
        "confidence": max(0.0, min(1.0, float(meta.get("confidence", 1.0)))),
        "value": value,
    }


def normalize(raw: dict[str, Any], registry: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    registry = registry or load_registry()
    collected_at = raw["collected_at"]
    observations = []
    for record in raw.get("sources", []):
        payload = record.get("payload")
        items = payload if isinstance(payload, list) else [payload]
        observations.extend(
            _observation(record["source"], item, index, record, collected_at, registry)
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
                {"observed_at": collected_at, "freshness_seconds": 1, "sensitivity": "internal", "confidence": 1.0},
                collected_at,
                registry,
            )
        )
    return observations


def _state(observation: dict[str, Any]) -> str:
    value = observation.get("value")
    if isinstance(value, dict):
        value = value.get("state", value.get("status", ""))
    return str(value).lower()


def _situation(identifier: str, label: str, state: str, rule: str, evidence: list[dict[str, Any]]) -> dict[str, Any]:
    freshness_weight = {"fresh": 1.0, "stale": 0.5, "unknown": 0.0}
    confidence = min((item["confidence"] * freshness_weight[item["freshness"]["status"]] for item in evidence), default=0.0)
    return {
        "id": identifier,
        "label": label,
        "state": state,
        "confidence": confidence,
        "rule": rule,
        "evidence": [item["id"] for item in evidence],
        "why": [f"{item['id']} = {_state(item) or 'observed'}" for item in evidence],
    }


def derive(observations: list[dict[str, Any]], machines: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    services = [item for item in observations if item["source"].get("semantic") == "service_health"]
    systems = [item for item in observations if item["source"].get("semantic") == "host_health"]
    health_observations = services + systems
    fresh_health = [item for item in health_observations if item["freshness"]["status"] == "fresh"]
    uncertain_health = [item for item in health_observations if item["freshness"]["status"] != "fresh"]
    bad_services = [item for item in fresh_health if item["source"].get("semantic") == "service_health" and _state(item) not in RUNNING]
    bad_systems = [
        item for item in fresh_health
        if item["source"].get("semantic") == "host_health"
        if isinstance(item.get("value"), dict) and float(item["value"].get("disk_used_percent", 0)) >= 90
    ]
    health_evidence = bad_services + bad_systems or uncertain_health or fresh_health
    health = "degraded" if bad_services or bad_systems else "uncertain" if uncertain_health else "healthy" if fresh_health else "unknown"

    studio = [item for item in observations if item["source"].get("domain") == "studio" and item["source"].get("state_kind") in {"state", "retained"}]
    active_studio = [item for item in studio if _state(item) in ACTIVE]
    fresh_active_studio = [item for item in active_studio if item["freshness"]["status"] == "fresh"]
    stale_active_studio = [item for item in active_studio if item["freshness"]["status"] != "fresh"]
    studio_state = "active" if fresh_active_studio else "uncertain" if stale_active_studio else "inactive" if studio else "unknown"

    fabrication = [item for item in observations if item["source"].get("domain") == "fabrication" and item["source"].get("state_kind") in {"state", "retained"}]
    active_fabrication = [item for item in fabrication if _state(item) in {"printing", "paused", "active"}]
    fresh_active_fabrication = [item for item in active_fabrication if item["freshness"]["status"] == "fresh"]
    stale_active_fabrication = [item for item in active_fabrication if item["freshness"]["status"] != "fresh"]
    fabrication_state = "active" if fresh_active_fabrication else "uncertain" if stale_active_fabrication else "inactive" if fabrication else "unknown"

    stale = [item for item in observations if item["freshness"]["status"] == "stale"]
    unavailable = [item for item in observations if item["source"]["kind"] == "collector" and _state(item) == "unavailable"]
    unknown_freshness = [item for item in observations if item["freshness"]["status"] == "unknown"]
    stale_state = "unavailable" if unavailable else "stale" if stale else "unknown" if unknown_freshness else "fresh"

    coordination = next((item for item in observations if item["source"].get("semantic") == "benlab_context"), None)
    context = coordination.get("value", {}) if coordination and coordination["freshness"]["status"] == "fresh" else {}
    capacity = set(context.get("capacity_projects", []))
    machine_resources = [
        {
            "id": item["id"],
            "source": {"affordances": item["affordances"], "affordance_scope": item["affordance_scope"]},
            "freshness": {"status": "fresh"},
            "confidence": 1.0,
            "value": {"state": item["readiness"]},
        }
        for item in (machines or []) if item.get("affordances") and item.get("affordance_scope")
    ]
    affordances = [item for item in [*observations, *machine_resources] if item["freshness"]["status"] == "fresh" and item["source"].get("affordances") and item["source"].get("affordance_scope")]
    scopes = {}
    for item in affordances:
        scopes.setdefault(item["source"]["affordance_scope"], []).append(item)
    action_opportunities = []
    evidence_opportunities = []
    for need in context.get("active_needs", []):
        required = set(need.get("stack") or [])
        resources = next((items for items in scopes.values() if required and required.issubset(set().union(*(set(item["source"]["affordances"]) for item in items)))), None)
        if need.get("project") not in capacity or not resources:
            continue
        contributors = [item for item in resources if required.intersection(item["source"]["affordances"])]
        evidence = [coordination, *contributors]
        action_opportunities.append(_situation(
            f"action-opportunity:{need['project']}", f"Action opportunity: {need['project']}", "available",
            "available when scoped world affordances satisfy a BenLab-authored active need with current schedule capacity",
            evidence,
        ))
        if need.get("need_type") == "evidence" or need.get("evidence_blocker") or need.get("proof_route"):
            evidence_opportunities.append(_situation(
                f"evidence-opportunity:{need['project']}", f"Evidence opportunity: {need['project']}", "available",
                "available only when BenLab explicitly types an evidence need and scoped world affordances and current capacity satisfy it",
                evidence,
            ))
    result = [
        _situation("system-health", "System health", health, "fresh bad evidence is degraded; stale evidence is uncertain; absent evidence is unknown", health_evidence),
        _situation("studio-activity", "Studio activity", studio_state, "fresh declared studio state may assert activity; stale active state is uncertain", fresh_active_studio or stale_active_studio or studio),
        _situation("fabrication-activity", "Fabrication activity", fabrication_state, "fresh declared fabrication state may assert activity; events do not assert persistent state", fresh_active_fabrication or stale_active_fabrication or fabrication),
        _situation("source-staleness", "Source staleness", stale_state, "unavailable when collection fails; stale when any observation exceeds its source freshness limit", unavailable or stale or unknown_freshness or observations),
        _situation("action-opportunities", "Action opportunities", "available" if action_opportunities else "unknown" if not coordination else "none", "summarizes scoped joins of world affordances, BenLab active needs, and current capacity", [coordination] if coordination else []),
        _situation("evidence-opportunities", "Evidence opportunities", "available" if evidence_opportunities else "unknown" if not coordination else "none", "summarizes scoped joins explicitly typed as evidence needs by BenLab", [coordination] if coordination else []),
    ]
    return result + action_opportunities + evidence_opportunities


def derive_machines(observations: list[dict[str, Any]], registry: dict[str, Any]) -> list[dict[str, Any]]:
    runtime_states = {"idle", "ready", "available", "operational", "printing", "active", "paused", "fault", "error", "failed", "offline", "unavailable", "disconnected"}
    machines = []
    for declared in registry.get("machines", []):
        matches = [
            observation for observation in observations
            if any(
                observation["source"]["kind"] == binding["kind"]
                and _matches(binding["kind"], binding["match"], observation["source"].get("key", ""))
                for binding in declared.get("telemetry", [])
            )
        ]
        current = max(matches, key=lambda item: (item["freshness"]["status"] == "fresh", item.get("observed_at") or ""), default=None)
        lifecycle = declared["lifecycle"]
        runtime = _state(current) if current else "no telemetry"
        if current and runtime not in runtime_states:
            runtime = "unknown"
        current_freshness = current["freshness"]["status"] if current else "unavailable"
        if lifecycle == "project":
            readiness = "project"
        elif lifecycle == "research":
            readiness = "research"
        elif lifecycle in {"offline", "retired"}:
            readiness = "unavailable"
        elif lifecycle != "operational" or not current or current_freshness != "fresh":
            readiness = "unknown"
        elif runtime in {"idle", "ready", "available", "operational"}:
            readiness = "ready"
        elif runtime in {"printing", "active", "paused"}:
            readiness = "busy"
        elif runtime in {"fault", "error", "failed"}:
            readiness = "needs_attention"
        elif runtime in {"offline", "unavailable", "disconnected"}:
            readiness = "unavailable"
        else:
            readiness = "unknown"
        capabilities = list(declared.get("capabilities", []))
        affordances = capabilities if readiness == "ready" and declared.get("contributes_affordances") else []
        why = [f"documentation: {declared.get('docs_ref') or 'canonical mapping unresolved'}", f"declared lifecycle: {lifecycle}"]
        if current:
            why.append(f"{current['id']} = {runtime} ({current_freshness})")
        else:
            why.append("no declared live telemetry observation")
        machines.append({
            "id": declared["id"],
            "label": declared["label"],
            "docs_ref": declared.get("docs_ref"),
            "scope": declared["scope"],
            "dashboard": declared["dashboard"],
            "lifecycle": lifecycle,
            "capabilities": capabilities,
            "readiness": readiness,
            "runtime": runtime,
            "freshness": current_freshness,
            "affordances": affordances,
            "affordance_scope": declared["scope"],
            "evidence": [item["id"] for item in matches],
            "why": why,
        })
    return machines


def derive_capabilities(machines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    capabilities = sorted({(machine["scope"], capability) for machine in machines for capability in machine["capabilities"]})
    result = []
    for scope, capability in capabilities:
        evidence = [machine for machine in machines if machine["scope"] == scope and capability in machine["capabilities"]]
        ready = [machine for machine in evidence if capability in machine["affordances"]]
        states = {machine["readiness"] for machine in evidence}
        state = "ready" if ready else "needs_attention" if "needs_attention" in states else "busy" if "busy" in states else "unknown"
        result.append({
            "capability": capability,
            "scope": scope,
            "state": state,
            "available_resources": len(ready),
            "evidence": [machine["id"] for machine in evidence],
        })
    return result


def interpret(
    raw: dict[str, Any],
    registry: dict[str, Any] | None = None,
    previous_state: dict[str, Any] | None = None,
    studio_registry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    observations = normalize(raw, registry)
    machines = derive_machines(observations, studio_registry or load_studio_registry())
    capabilities = derive_capabilities(machines)
    situations = derive(observations, machines)
    transitions = list((previous_state or {}).get("transitions", []))
    if previous_state:
        before = {item["id"]: item["state"] for item in previous_state.get("situations", [])}
        before.update({item["id"]: item["readiness"] for item in previous_state.get("machines", [])})
        after = {item["id"]: item["state"] for item in situations}
        after.update({item["id"]: item["readiness"] for item in machines})
        transitions.extend(
            {"situation_id": identifier, "from": before.get(identifier), "to": after.get(identifier), "changed_at": raw["collected_at"]}
            for identifier in sorted(before.keys() | after.keys())
            if before.get(identifier) != after.get(identifier)
        )
    return {
        "contract": {
            "name": "homeauto-world-state",
            "schema_version": "1.0.0",
            "authority": "read-only; no control actions",
        },
        "generated_at": raw["collected_at"],
        "observations": observations,
        "machines": machines,
        "capabilities": capabilities,
        "situations": situations,
        "transitions": transitions[-100:],
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


def collect_home_assistant(url: str, token: str, sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    request = urllib.request.Request(url.rstrip("/") + "/api/states", headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(request, timeout=10) as response:
        payload = json.load(response)
    payload = payload if isinstance(payload, list) else [payload]
    rows = []
    for item in payload:
        definition = next((source for source in sources if fnmatch.fnmatchcase(item.get("entity_id", ""), source.get("match", ""))), None)
        if definition:
            rows.append({"entity_id": item["entity_id"], **{key: item.get(key) for key in definition.get("retain", ["state", "last_updated"])}})
    return rows


def collect_mqtt(host: str, topic: str = "#", sources: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
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
        if not sources or any(_matches("mqtt", source.get("match", ""), topic_name) for source in sources):
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


def collect_raw(coordination_path: Path = DEFAULT_COORDINATION, compose_file: Path = ROOT / "docker-compose.yml", registry: dict[str, Any] | None = None) -> dict[str, Any]:
    registry = registry or load_registry()
    definitions = registry.get("sources", [])
    now = datetime.now(timezone.utc).isoformat()
    sources = []
    errors = []
    ha_url = os.getenv("HA_URL", "http://127.0.0.1:8123")
    ha_token = os.getenv("HA_TOKEN")
    if ha_token:
        try:
            sources.append(_record("home_assistant", "homeassistant", collect_home_assistant(ha_url, ha_token, [item for item in definitions if item.get("kind") == "home_assistant"]), now, 300, "household"))
        except Exception as exc:
            errors.append(f"home_assistant: {exc}")
    else:
        errors.append("home_assistant: HA_TOKEN not configured")
    mqtt_host = os.getenv("MQTT_HOST", "127.0.0.1")
    if shutil.which("mosquitto_sub"):
        try:
            sources.append(_record("mqtt", "mosquitto", collect_mqtt(mqtt_host, os.getenv("MQTT_TOPIC", "#"), [item for item in definitions if item.get("kind") == "mqtt"]), now, 300, "household", 0.8))
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
    parser.add_argument("--studio-machines", type=Path, default=DEFAULT_STUDIO_REGISTRY)
    parser.add_argument("--fixture", type=Path)
    args = parser.parse_args()
    raw = json.loads(args.fixture.read_text()) if args.fixture else collect_raw(args.coordination)
    previous_state = json.loads(args.state.read_text(encoding="utf-8")) if args.state.is_file() else None
    state = interpret(raw, previous_state=previous_state, studio_registry=load_studio_registry(args.studio_machines))
    args.raw.parent.mkdir(parents=True, exist_ok=True)
    args.state.parent.mkdir(parents=True, exist_ok=True)
    args.raw.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    args.state.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    print(f"raw: {args.raw}\nstate: {args.state}\ncollector errors: {len(raw.get('errors', []))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
