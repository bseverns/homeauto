"""Loopback-only, read-only API for the Homeauto Control Deck."""

from __future__ import annotations

import ipaddress
import json
import mimetypes
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

import jsonschema


DEFAULT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE = DEFAULT_ROOT / "coordination" / "state" / "world-state.json"
DEFAULT_SCHEMA = DEFAULT_ROOT / "coordination" / "world-state.schema.json"
DEFAULT_FIXTURE = DEFAULT_ROOT / "tests" / "fixtures" / "control-deck" / "world-state.json"

ACTION_FIELDS = (
    "action_id",
    "project",
    "attention_state",
    "queue",
    "queue_position",
    "current_commitment",
    "may_request_time_now",
    "next_action",
    "effort",
    "energy_fit",
    "required_stack",
    "route",
    "status",
)
CAPACITY_FIELDS = (
    "fit_status",
    "effort",
    "energy_fit",
    "reason",
    "source_freshness",
    "confidence",
    "warnings",
    "capacity_block_id",
    "capacity_start",
    "capacity_end",
    "authority",
)
MACHINE_FIELDS = (
    "id",
    "label",
    "scope",
    "dashboard",
    "lifecycle",
    "capabilities",
    "readiness",
    "runtime",
    "freshness",
    "affordances",
    "affordance_scope",
    "evidence",
    "why",
)


def _pick(value: dict[str, Any] | None, fields: tuple[str, ...]) -> dict[str, Any] | None:
    if value is None:
        return None
    return {field: value[field] for field in fields if field in value}


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(
        path.read_text(encoding="utf-8"),
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f"invalid JSON constant: {value}")),
    )


class ControlDeckData:
    """Validate source-owned state, then return a bounded public projection."""

    def __init__(
        self,
        source_path: Path = DEFAULT_SOURCE,
        schema_path: Path = DEFAULT_SCHEMA,
        fallback_path: Path = DEFAULT_FIXTURE,
        stale_after_seconds: int = 21_600,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.source_path = Path(source_path)
        self.fallback_path = Path(fallback_path)
        self.stale_after_seconds = stale_after_seconds
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.schema = _load_json(Path(schema_path))
        self._validator = jsonschema.Draft202012Validator(
            self.schema, format_checker=jsonschema.FormatChecker()
        )
        fixture = _load_json(self.fallback_path)
        self._validator.validate(fixture)

    def _load(self) -> tuple[dict[str, Any], dict[str, Any]]:
        problem = None
        try:
            state = _load_json(self.source_path)
            self._validator.validate(state)
            if _parse_time(state.get("generated_at")) is None:
                raise ValueError("invalid generated_at")
            mode = "authoritative"
        except FileNotFoundError:
            problem = "missing_source"
            state = _load_json(self.fallback_path)
            mode = "fixture"
        except (OSError, ValueError, json.JSONDecodeError, jsonschema.ValidationError):
            problem = "invalid_source"
            state = _load_json(self.fallback_path)
            mode = "fixture"

        generated_at = _parse_time(state.get("generated_at"))
        if mode == "fixture" or generated_at is None:
            freshness = "unknown"
            age_seconds = None
        else:
            age_seconds = max(0, int((self.now() - generated_at).total_seconds()))
            freshness = "stale" if age_seconds > self.stale_after_seconds else "current"

        source = {
            "mode": mode,
            "freshness": freshness,
            "generated_at": state.get("generated_at"),
            "age_seconds": age_seconds,
            "stale_after_seconds": self.stale_after_seconds,
        }
        if problem:
            source["problem"] = problem
        return state, source

    @staticmethod
    def _opportunity(item: dict[str, Any]) -> dict[str, Any]:
        provenance = []
        for entry in item.get("provenance", []):
            contract = entry.get("contract") or {}
            provenance.append(
                {
                    "authority": entry.get("authority"),
                    "contract": _pick(contract, ("name", "schema_version", "authority")),
                    "source_ids": entry.get("source_ids", []),
                }
            )
        return {
            "opportunity_id": item.get("opportunity_id"),
            "action_id": item.get("action_id"),
            "project_id": item.get("project_id"),
            "state": item.get("state", "insufficient_information"),
            "action": _pick(item.get("action"), ACTION_FIELDS) or {},
            "capacity": _pick(item.get("capacity"), CAPACITY_FIELDS),
            "affordances": item.get("affordances", {}),
            "why": item.get("why", []),
            "provenance": provenance,
            "warnings": item.get("warnings", []),
        }

    @staticmethod
    def _machine(item: dict[str, Any]) -> dict[str, Any]:
        return _pick(item, MACHINE_FIELDS) or {}

    @staticmethod
    def _transition(item: dict[str, Any]) -> dict[str, Any]:
        return _pick(
            item,
            ("situation_id", "action_id", "from", "to", "changed_at", "cause", "source_ids"),
        ) or {}

    @staticmethod
    def _evidence(item: dict[str, Any]) -> dict[str, Any]:
        source = item.get("source", {})
        return {
            "id": item.get("id"),
            "source": _pick(source, ("kind", "name", "domain", "semantic", "state_kind")),
            "observed_at": item.get("observed_at"),
            "freshness": item.get("freshness"),
            "confidence": item.get("confidence"),
        }

    @staticmethod
    def _inputs(inputs: dict[str, Any]) -> dict[str, Any]:
        result = {}
        for name in ("benlab", "schedule", "world_state"):
            entry = inputs.get(name, {})
            contract = entry.get("contract") or {}
            result[name] = {
                "generated_at": entry.get("generated_at"),
                "contract": _pick(contract, ("name", "schema_version", "authority")),
            }
        return result

    def health(self) -> dict[str, Any]:
        _, source = self._load()
        return {
            "status": "ok" if source["mode"] == "authoritative" else "degraded",
            "service": "homeauto-control-deck",
            "read_only": True,
            "source": source,
        }

    def world_state(self) -> dict[str, Any]:
        state, source = self._load()
        opportunities = [self._opportunity(item) for item in state.get("opportunities", [])]
        machines = [self._machine(item) for item in state.get("machines", []) if item.get("dashboard", True)]
        return {
            "contract": _pick(state.get("contract"), ("name", "schema_version", "authority")) or {},
            "generated_at": state.get("generated_at"),
            "source": source,
            "inputs": self._inputs(state.get("inputs", {})),
            "opportunity_contract": state.get("opportunity_contract", {}),
            "opportunities": opportunities,
            "machines": machines,
            "capabilities": state.get("capabilities", []),
            "transitions": [self._transition(item) for item in state.get("transitions", [])],
            "evidence_index": [
                self._evidence(item)
                for item in state.get("observations", [])
                if item.get("sensitivity") == "public"
            ],
            "boundaries": state.get("boundaries", []),
        }

    def opportunities(self) -> dict[str, Any]:
        state, source = self._load()
        items = [self._opportunity(item) for item in state.get("opportunities", [])]
        return {"count": len(items), "items": items, "source": source}

    def machines(self) -> dict[str, Any]:
        state, source = self._load()
        items = [self._machine(item) for item in state.get("machines", []) if item.get("dashboard", True)]
        return {"count": len(items), "items": items, "source": source}


class _LoopbackServer(ThreadingHTTPServer):
    daemon_threads = True


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def build_server(
    host: str,
    port: int,
    data: ControlDeckData,
    static_dir: Path | None = None,
) -> ThreadingHTTPServer:
    if not _is_loopback(host):
        raise ValueError("Control Deck may bind only to a loopback address")
    root = Path(static_dir).resolve() if static_dir else None

    class Handler(BaseHTTPRequestHandler):
        def _send_json(self, status: int, payload: dict[str, Any], head: bool = False) -> None:
            body = json.dumps(payload, separators=(",", ":"), allow_nan=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            if not head:
                self.wfile.write(body)

        def _send_file(self, path: Path, head: bool = False) -> None:
            body = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            if not head:
                self.wfile.write(body)

        def _get(self, head: bool = False) -> None:
            path = urlsplit(self.path).path
            routes = {
                "/api/v1/health": data.health,
                "/api/v1/world-state": data.world_state,
                "/api/v1/opportunities": data.opportunities,
                "/api/v1/machines": data.machines,
            }
            if path in routes:
                self._send_json(200, routes[path](), head)
                return
            if root is not None:
                relative = "index.html" if path == "/" else path.lstrip("/")
                candidate = (root / relative).resolve()
                if candidate.is_relative_to(root) and candidate.is_file():
                    self._send_file(candidate, head)
                    return
                if "." not in Path(relative).name:
                    index = root / "index.html"
                    if index.is_file():
                        self._send_file(index, head)
                        return
            self._send_json(404, {"error": "not_found"}, head)

        def do_GET(self) -> None:
            self._get()

        def do_HEAD(self) -> None:
            self._get(head=True)

        def _read_only(self) -> None:
            self._send_json(405, {"error": "read_only"})

        do_POST = do_PUT = do_PATCH = do_DELETE = _read_only

        def log_message(self, format: str, *args: Any) -> None:
            return

    return _LoopbackServer((host, port), Handler)


def main() -> None:
    static_dir = DEFAULT_ROOT / "services" / "control_deck" / "web" / "dist"
    server = build_server(
        "127.0.0.1",
        8765,
        ControlDeckData(),
        static_dir if static_dir.is_dir() else None,
    )
    print(f"Control Deck listening on http://127.0.0.1:{server.server_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
