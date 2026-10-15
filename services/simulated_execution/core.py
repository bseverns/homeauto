"""Closed Phase C0 simulated-action service.

The module intentionally has no network, shell, MQTT, or device adapter.
"""

from __future__ import annotations

import copy
import fcntl
import hashlib
import json
import secrets
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

import jsonschema


ROOT = Path(__file__).resolve().parents[2]
REQUEST_SCHEMA = ROOT / "coordination" / "simulated-action-request.schema.json"
TERMINAL_OUTCOMES = {"rejected", "verified", "contradicted", "timed_out_ambiguous"}


class PolicyError(ValueError):
    """A request failed closed before simulated dispatch."""


class SimulatedCrash(RuntimeError):
    """Deterministic crash injection used only by the Phase C0 tests."""


def _confirm_with_os(preview: dict[str, Any]) -> None:
    """Require macOS to verify user presence outside the invoking process."""
    try:
        from LocalAuthentication import (  # type: ignore[import-not-found]
            LAContext,
            LAPolicyDeviceOwnerAuthentication,
        )
    except ImportError as error:
        raise PolicyError("human confirmation requires macOS LocalAuthentication") from error

    context = LAContext.alloc().init()
    available, _ = context.canEvaluatePolicy_error_(
        LAPolicyDeviceOwnerAuthentication, None
    )
    if not available:
        raise PolicyError("OS user authentication is unavailable")

    completed = threading.Event()
    result: dict[str, Any] = {}

    def reply(success: bool, error: Any) -> None:
        result.update(success=bool(success), error=error)
        completed.set()

    reason = (
        f"Approve one simulated {preview['action_id']} attempt for "
        f"{preview['target_id']}: {preview['expected_prior_state']} → "
        f"{preview['desired_state']} (request {preview['request_id']})"
    )
    context.evaluatePolicy_localizedReason_reply_(
        LAPolicyDeviceOwnerAuthentication, reason, reply
    )
    if not completed.wait(30):
        context.invalidate()
        raise PolicyError("OS user authentication timed out")
    if not result.get("success"):
        raise PolicyError("human confirmation was not supplied")


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise PolicyError("timestamps must include a timezone")
    return value.astimezone(timezone.utc)


def _parse_time(value: str, label: str) -> datetime:
    try:
        return _utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except (AttributeError, TypeError, ValueError) as error:
        raise PolicyError(f"invalid {label}") from error


def _stamp(value: datetime) -> str:
    return _utc(value).isoformat()


def _canonical(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class TestIdentityProvider:
    """In-memory test identity boundary; credentials are never journaled."""

    __test__ = False

    def __init__(self, credentials: dict[str, str]) -> None:
        self._credentials = dict(credentials)
        self._revoked: set[str] = set()
        self._lock = threading.RLock()

    def authenticate(self, credential: str | None) -> str:
        with self._lock:
            if not credential or credential in self._revoked or credential not in self._credentials:
                raise PolicyError("authentication failed")
            return self._credentials[credential]

    def revoke(self, credential: str) -> None:
        with self._lock:
            self._revoked.add(credential)


class EvidenceProvider:
    """Mutable deterministic observation source for the simulation harness."""

    def __init__(self, initial: dict[str, Any] | None) -> None:
        self._value = copy.deepcopy(initial)
        self._lock = threading.RLock()

    def current(self) -> dict[str, Any] | None:
        with self._lock:
            return copy.deepcopy(self._value)

    def set(self, value: dict[str, Any] | None) -> None:
        with self._lock:
            self._value = copy.deepcopy(value)


class FakeExecutor:
    """The complete Phase C0 executor allowlist."""

    __slots__ = ("behavior", "delay_seconds", "calls", "_lock")

    BEHAVIORS = {
        "success",
        "rejection",
        "delay",
        "timeout",
        "missing_observation",
        "contradictory_observation",
    }

    def __init__(self, behavior: str, delay_seconds: float = 0.0) -> None:
        if behavior not in self.BEHAVIORS:
            raise ValueError("unknown fake-executor behavior")
        self.behavior = behavior
        self.delay_seconds = max(0.0, delay_seconds)
        self.calls = 0
        self._lock = threading.Lock()

    def dispatch(self, desired_state: str, timeout_seconds: float) -> dict[str, Any]:
        if desired_state not in {"on", "off"}:
            raise PolicyError("executor received a state outside its allowlist")
        with self._lock:
            self.calls += 1
        if self.behavior == "rejection":
            return {"accepted": False, "possible_dispatch": False, "observed_state": None}
        if self.behavior == "timeout" or self.delay_seconds >= timeout_seconds:
            return {"accepted": True, "possible_dispatch": True, "observed_state": None}
        if self.delay_seconds:
            time.sleep(self.delay_seconds)
        if self.behavior == "missing_observation":
            return {"accepted": True, "possible_dispatch": True, "observed_state": None}
        if self.behavior == "contradictory_observation":
            observed = "off" if desired_state == "on" else "on"
        else:
            observed = desired_state
        return {"accepted": True, "possible_dispatch": True, "observed_state": observed}


class SimulationService:
    """Preview, approve, and execute one exact simulated indicator operation."""

    def __init__(
        self,
        database: Path,
        identities: TestIdentityProvider,
        evidence: EvidenceProvider,
        executor: FakeExecutor,
        *,
        enabled: bool = False,
        kill_switch: bool = False,
        now: Callable[[], datetime] | None = None,
        approval_ttl_seconds: int = 30,
        execution_timeout_seconds: float = 2.0,
        retention_limit: int = 1000,
    ) -> None:
        if type(executor) is not FakeExecutor:
            raise PolicyError("executor must be the closed Phase C0 FakeExecutor")
        self.database = Path(database)
        self.identities = identities
        self.evidence = evidence
        self.executor = executor
        self.enabled = bool(enabled)
        self.kill_switch = bool(kill_switch)
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.approval_ttl_seconds = max(1, approval_ttl_seconds)
        self.execution_timeout_seconds = max(0.001, execution_timeout_seconds)
        self.retention_limit = max(1, retention_limit)
        self._policy_lock = threading.RLock()
        self._operation_lock = threading.Lock()
        self._validator = jsonschema.Draft202012Validator(
            json.loads(REQUEST_SCHEMA.read_text(encoding="utf-8")),
            format_checker=jsonschema.FormatChecker(),
        )
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self._owner_lock = (self.database.parent / f"{self.database.name}.lock").open("a+")
        try:
            fcntl.flock(self._owner_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            self._owner_lock.close()
            raise PolicyError("simulation journal is already owned by another service") from error
        try:
            self._initialize()
            self.recover()
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        owner_lock = getattr(self, "_owner_lock", None)
        if owner_lock and not owner_lock.closed:
            fcntl.flock(owner_lock, fcntl.LOCK_UN)
            owner_lock.close()

    def __del__(self) -> None:
        self.close()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database, timeout=1.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS commands (
                    request_id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    payload_hash TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    operator_id TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    dispatch_possible INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS approvals (
                    approval_id TEXT PRIMARY KEY,
                    token_hash TEXT NOT NULL UNIQUE,
                    request_id TEXT NOT NULL UNIQUE REFERENCES commands(request_id) ON DELETE CASCADE,
                    operator_id TEXT NOT NULL,
                    action_id TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    expected_prior_state TEXT NOT NULL,
                    desired_state TEXT NOT NULL,
                    evidence_id TEXT NOT NULL,
                    evidence_version TEXT NOT NULL,
                    issued_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    consumed_at TEXT
                );
                CREATE TABLE IF NOT EXISTS confirmed_previews (
                    token_hash TEXT PRIMARY KEY,
                    payload_hash TEXT NOT NULL,
                    operator_id TEXT NOT NULL,
                    evidence_id TEXT NOT NULL,
                    evidence_version TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    confirmed_at TEXT,
                    consumed_at TEXT
                );
                CREATE TABLE IF NOT EXISTS replay_tombstones (
                    request_id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    payload_hash TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_id TEXT NOT NULL REFERENCES commands(request_id) ON DELETE CASCADE,
                    sequence INTEGER NOT NULL,
                    state TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    detail_json TEXT NOT NULL,
                    UNIQUE(request_id, sequence)
                );
                CREATE TRIGGER IF NOT EXISTS audit_events_immutable
                BEFORE UPDATE ON audit_events
                BEGIN
                    SELECT RAISE(ABORT, 'audit events are immutable');
                END;
                CREATE TABLE IF NOT EXISTS inflight_targets (
                    target_id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL UNIQUE REFERENCES commands(request_id) ON DELETE CASCADE,
                    claimed_at TEXT NOT NULL
                );
                INSERT OR IGNORE INTO replay_tombstones(request_id, idempotency_key, payload_hash)
                SELECT request_id, idempotency_key, payload_hash FROM commands;
                """
            )

    def _validate_request(self, request: dict[str, Any]) -> None:
        errors = sorted(self._validator.iter_errors(request), key=lambda item: list(item.path))
        if errors:
            raise PolicyError(f"invalid request: {errors[0].message}")

    def _validate_policy(
        self, request: dict[str, Any], credential: str | None
    ) -> tuple[str, dict[str, Any], datetime]:
        self._validate_request(request)
        operator = self.identities.authenticate(credential)
        if not self.enabled:
            raise PolicyError("simulation execution is disabled")
        if self.kill_switch:
            raise PolicyError("kill switch is engaged")
        now = _utc(self.now())
        requested_at = _parse_time(request["requested_at"], "requested_at")
        expires_at = _parse_time(request["expires_at"], "expires_at")
        if expires_at <= now:
            raise PolicyError("request expired")
        if requested_at > now + timedelta(seconds=5) or expires_at <= requested_at:
            raise PolicyError("invalid request time window")
        if expires_at - requested_at > timedelta(minutes=5):
            raise PolicyError("request lifetime exceeds five minutes")
        observation = self.evidence.current()
        if observation is None:
            raise PolicyError("missing evidence")
        required = {
            "evidence_id",
            "version",
            "target_id",
            "state",
            "observed_at",
            "fresh_until",
            "source_mode",
            "contradictory",
        }
        if set(observation) != required:
            raise PolicyError("malformed evidence")
        if observation["source_mode"] != "simulated_authoritative":
            raise PolicyError("fixture or non-authoritative evidence is ineligible")
        if observation["contradictory"]:
            raise PolicyError("contradictory evidence")
        if observation["target_id"] != request["target_id"]:
            raise PolicyError("evidence target mismatch")
        if observation["state"] != request["expected_prior_state"]:
            raise PolicyError("precondition does not match observed state")
        observed_at = _parse_time(observation["observed_at"], "observed_at")
        fresh_until = _parse_time(observation["fresh_until"], "fresh_until")
        if observed_at > now + timedelta(seconds=5) or fresh_until <= now:
            raise PolicyError("stale evidence")
        if not isinstance(observation["evidence_id"], str) or not observation["evidence_id"]:
            raise PolicyError("malformed evidence identity")
        if not isinstance(observation["version"], str) or not observation["version"]:
            raise PolicyError("malformed evidence version")
        return operator, observation, now

    @staticmethod
    def _preview_document(
        request: dict[str, Any], operator: str, observation: dict[str, Any], expires_at: str
    ) -> dict[str, Any]:
        return {
            "eligible": True,
            "simulation": True,
            "operator_id": operator,
            "request_id": request["request_id"],
            "action_id": request["action_id"],
            "target_id": request["target_id"],
            "expected_prior_state": request["expected_prior_state"],
            "desired_state": request["desired_state"],
            "evidence_id": observation["evidence_id"],
            "evidence_version": observation["version"],
            "approval_expires_at": expires_at,
        }

    def preview(self, request: dict[str, Any], credential: str | None) -> dict[str, Any]:
        operator, observation, now = self._validate_policy(request, credential)
        approval_expires = min(
            _parse_time(request["expires_at"], "expires_at"),
            now + timedelta(seconds=self.approval_ttl_seconds),
        )
        confirmation_token = secrets.token_urlsafe(32)
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO confirmed_previews VALUES (?, ?, ?, ?, ?, ?, NULL, NULL)",
                (
                    _digest(confirmation_token),
                    _digest(_canonical(request)),
                    operator,
                    observation["evidence_id"],
                    observation["version"],
                    _stamp(approval_expires),
                ),
            )
        return self._preview_document(
            request, operator, observation, _stamp(approval_expires)
        )

    @staticmethod
    def _event(
        connection: sqlite3.Connection,
        request_id: str,
        state: str,
        recorded_at: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        sequence = connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM audit_events WHERE request_id=?",
            (request_id,),
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO audit_events(request_id, sequence, state, recorded_at, detail_json) "
            "VALUES (?, ?, ?, ?, ?)",
            (request_id, sequence, state, recorded_at, _canonical(detail or {})),
        )

    def approve(
        self,
        request: dict[str, Any],
        credential: str | None,
    ) -> str:
        operator, observation, now = self._validate_policy(request, credential)
        request_json = _canonical(request)
        payload_hash = _digest(request_json)
        with self._connect() as connection:
            preview = connection.execute(
                "SELECT * FROM confirmed_previews WHERE payload_hash=? AND operator_id=? "
                "AND evidence_id=? AND evidence_version=? ORDER BY rowid DESC LIMIT 1",
                (payload_hash, operator, observation["evidence_id"], observation["version"]),
            ).fetchone()
        if not preview:
            raise PolicyError("approval requires a confirmed preview")
        if preview["consumed_at"]:
            raise PolicyError("confirmed preview already consumed")
        if _parse_time(preview["expires_at"], "preview expiration") <= now:
            raise PolicyError("confirmed preview expired")
        public_preview = self._preview_document(
            request, operator, observation, preview["expires_at"]
        )
        _confirm_with_os(public_preview)
        operator, observation, now = self._validate_policy(request, credential)
        token = secrets.token_urlsafe(32)
        token_hash = _digest(token)
        approval_id = f"approval:{uuid.uuid4().hex}"
        expires_at = min(
            _parse_time(request["expires_at"], "expires_at"),
            now + timedelta(seconds=self.approval_ttl_seconds),
        )
        stamp = _stamp(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            preview = connection.execute(
                "SELECT * FROM confirmed_previews WHERE token_hash=?",
                (preview["token_hash"],),
            ).fetchone()
            if not preview:
                raise PolicyError("approval requires a confirmed preview")
            if preview["consumed_at"]:
                raise PolicyError("confirmed preview already consumed")
            if _parse_time(preview["expires_at"], "preview expiration") <= now:
                raise PolicyError("confirmed preview expired")
            preview_bindings = {
                "payload_hash": payload_hash,
                "operator_id": operator,
                "evidence_id": observation["evidence_id"],
                "evidence_version": observation["version"],
            }
            if any(preview[field] != value for field, value in preview_bindings.items()):
                raise PolicyError("confirmed preview binding changed")
            by_key = connection.execute(
                "SELECT request_id, payload_hash FROM replay_tombstones WHERE idempotency_key=?",
                (request["idempotency_key"],),
            ).fetchone()
            if by_key:
                if by_key["payload_hash"] != payload_hash:
                    raise PolicyError("idempotency key was already used with a different payload")
                raise PolicyError("request is already registered")
            if connection.execute(
                "SELECT 1 FROM replay_tombstones WHERE request_id=?", (request["request_id"],)
            ).fetchone():
                raise PolicyError("request ID is already registered")
            connection.execute(
                "INSERT INTO replay_tombstones VALUES (?, ?, ?)",
                (request["request_id"], request["idempotency_key"], payload_hash),
            )
            connection.execute(
                "INSERT INTO commands VALUES (?, ?, ?, ?, ?, 'pending', 0, ?, ?)",
                (
                    request["request_id"],
                    request["idempotency_key"],
                    payload_hash,
                    request_json,
                    operator,
                    stamp,
                    stamp,
                ),
            )
            self._event(connection, request["request_id"], "pending", stamp)
            connection.execute(
                "INSERT INTO approvals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)",
                (
                    approval_id,
                    token_hash,
                    request["request_id"],
                    operator,
                    request["action_id"],
                    request["target_id"],
                    request["expected_prior_state"],
                    request["desired_state"],
                    observation["evidence_id"],
                    observation["version"],
                    stamp,
                    _stamp(expires_at),
                ),
            )
            connection.execute(
                "UPDATE confirmed_previews SET confirmed_at=?, consumed_at=? WHERE token_hash=?",
                (stamp, stamp, preview["token_hash"]),
            )
        return token

    def _reject_authorized(self, request_id: str, reason: str) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT outcome FROM commands WHERE request_id=?", (request_id,)
            ).fetchone()
            if not row or row["outcome"] != "authorized":
                return
            stamp = _stamp(self.now())
            connection.execute(
                "UPDATE commands SET outcome='rejected', updated_at=? WHERE request_id=?",
                (stamp, request_id),
            )
            self._event(connection, request_id, "rejected", stamp, {"reason": reason})
            connection.execute("DELETE FROM inflight_targets WHERE request_id=?", (request_id,))

    def execute(
        self,
        request: dict[str, Any],
        approval_token: str,
        credential: str | None,
        *,
        crash_at: str | None = None,
    ) -> dict[str, Any]:
        if not self._operation_lock.acquire(blocking=False):
            raise PolicyError("target already in flight")
        try:
            with self._policy_lock, self.identities._lock, self.evidence._lock:
                return self._execute_exclusive(
                    request, approval_token, credential, crash_at=crash_at
                )
        finally:
            self._operation_lock.release()

    def _execute_exclusive(
        self,
        request: dict[str, Any],
        approval_token: str,
        credential: str | None,
        *,
        crash_at: str | None = None,
    ) -> dict[str, Any]:
        operator, observation, now = self._validate_policy(request, credential)
        if crash_at not in {None, "before_dispatch", "after_dispatch"}:
            raise PolicyError("unknown crash injection point")
        payload_hash = _digest(_canonical(request))
        token_hash = _digest(approval_token)
        stamp = _stamp(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            approval = connection.execute(
                "SELECT * FROM approvals WHERE token_hash=?", (token_hash,)
            ).fetchone()
            if not approval:
                raise PolicyError("approval not found")
            if approval["consumed_at"]:
                raise PolicyError("approval already consumed")
            if _parse_time(approval["expires_at"], "approval expiration") <= now:
                raise PolicyError("approval expired")
            command = connection.execute(
                "SELECT * FROM commands WHERE request_id=?", (request["request_id"],)
            ).fetchone()
            if not command or command["payload_hash"] != payload_hash:
                raise PolicyError("approval request binding mismatch")
            bindings = {
                "operator_id": operator,
                "action_id": request["action_id"],
                "target_id": request["target_id"],
                "expected_prior_state": request["expected_prior_state"],
                "desired_state": request["desired_state"],
                "evidence_id": observation["evidence_id"],
                "evidence_version": observation["version"],
            }
            if any(approval[field] != value for field, value in bindings.items()):
                raise PolicyError("approval binding or evidence changed")
            if connection.execute(
                "SELECT 1 FROM inflight_targets WHERE target_id=?", (request["target_id"],)
            ).fetchone():
                raise PolicyError("target already in flight")
            connection.execute(
                "INSERT INTO inflight_targets VALUES (?, ?, ?)",
                (request["target_id"], request["request_id"], stamp),
            )
            connection.execute(
                "UPDATE approvals SET consumed_at=? WHERE approval_id=?",
                (stamp, approval["approval_id"]),
            )
            connection.execute(
                "UPDATE commands SET outcome='authorized', updated_at=? WHERE request_id=?",
                (stamp, request["request_id"]),
            )
            self._event(connection, request["request_id"], "authorized", stamp)

        if crash_at == "before_dispatch":
            raise SimulatedCrash("crash before dispatch recording")

        try:
            with self._policy_lock:
                operator, observation, dispatch_now = self._validate_policy(request, credential)
                with self._connect() as connection:
                    connection.execute("BEGIN IMMEDIATE")
                    approval = connection.execute(
                        "SELECT * FROM approvals WHERE token_hash=?", (token_hash,)
                    ).fetchone()
                    command = connection.execute(
                        "SELECT outcome, payload_hash FROM commands WHERE request_id=?",
                        (request["request_id"],),
                    ).fetchone()
                    if not approval or not command or command["outcome"] != "authorized":
                        raise PolicyError("authorized command changed before dispatch")
                    if command["payload_hash"] != payload_hash:
                        raise PolicyError("approval request binding mismatch")
                    if _parse_time(approval["expires_at"], "approval expiration") <= dispatch_now:
                        raise PolicyError("approval expired")
                    bindings.update(
                        operator_id=operator,
                        evidence_id=observation["evidence_id"],
                        evidence_version=observation["version"],
                    )
                    if any(approval[field] != value for field, value in bindings.items()):
                        raise PolicyError("approval binding or evidence changed")
                    dispatch_stamp = _stamp(dispatch_now)
                    connection.execute(
                        "UPDATE commands SET outcome='dispatched', dispatch_possible=1, updated_at=? "
                        "WHERE request_id=?",
                        (dispatch_stamp, request["request_id"]),
                    )
                    self._event(connection, request["request_id"], "dispatched", dispatch_stamp)
        except PolicyError as error:
            self._reject_authorized(request["request_id"], str(error))
            raise

        if crash_at == "after_dispatch":
            raise SimulatedCrash("crash after dispatch recording")

        result = self.executor.dispatch(
            request["desired_state"], self.execution_timeout_seconds
        )
        if not result["accepted"]:
            outcome = "rejected"
            states = [("rejected", {"reason": "executor_rejected"})]
            dispatch_possible = 0
        elif result["observed_state"] is None:
            outcome = "timed_out_ambiguous"
            states = [(outcome, {"reason": "no_conclusive_simulated_readback"})]
            dispatch_possible = 1
        else:
            observed = result["observed_state"]
            states = [("observed", {"state": observed})]
            if observed == request["desired_state"]:
                outcome = "verified"
                states.append((outcome, {"verification_kind": "simulated_platform_readback"}))
            else:
                outcome = "contradicted"
                states.append((outcome, {"expected": request["desired_state"], "observed": observed}))
            dispatch_possible = 1

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for state, detail in states:
                self._event(connection, request["request_id"], state, _stamp(self.now()), detail)
            connection.execute(
                "UPDATE commands SET outcome=?, dispatch_possible=?, updated_at=? WHERE request_id=?",
                (outcome, dispatch_possible, _stamp(self.now()), request["request_id"]),
            )
            connection.execute(
                "DELETE FROM inflight_targets WHERE request_id=?", (request["request_id"],)
            )
        receipt = self.receipt(request["request_id"])
        self._prune()
        return receipt

    def _expire_pending(self, connection: sqlite3.Connection, now: datetime) -> None:
        stamp = _stamp(now)
        rows = connection.execute(
            "SELECT c.request_id FROM commands c JOIN approvals a ON a.request_id=c.request_id "
            "WHERE c.outcome='pending' AND a.expires_at<=?",
            (stamp,),
        ).fetchall()
        for row in rows:
            connection.execute(
                "UPDATE commands SET outcome='rejected', updated_at=? WHERE request_id=?",
                (stamp, row["request_id"]),
            )
            connection.execute(
                "UPDATE approvals SET consumed_at=COALESCE(consumed_at, ?) WHERE request_id=?",
                (stamp, row["request_id"]),
            )
            self._event(
                connection,
                row["request_id"],
                "rejected",
                stamp,
                {"reason": "approval_expired_before_dispatch"},
            )
        connection.execute(
            "DELETE FROM confirmed_previews WHERE consumed_at IS NOT NULL OR expires_at<=?",
            (stamp,),
        )

    def recover(self) -> list[str]:
        with self._operation_lock:
            return self._recover_exclusive()

    def _recover_exclusive(self) -> list[str]:
        recovered: list[str] = []
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._expire_pending(connection, _utc(self.now()))
            rows = connection.execute(
                "SELECT c.request_id, c.outcome FROM commands c "
                "JOIN inflight_targets i ON i.request_id=c.request_id"
            ).fetchall()
            for row in rows:
                if row["outcome"] == "dispatched":
                    outcome = "timed_out_ambiguous"
                    detail = {"reason": "recovered_after_possible_dispatch; no automatic retry"}
                else:
                    outcome = "rejected"
                    detail = {"reason": "recovered_before_dispatch"}
                stamp = _stamp(self.now())
                connection.execute(
                    "UPDATE commands SET outcome=?, updated_at=? WHERE request_id=?",
                    (outcome, stamp, row["request_id"]),
                )
                self._event(connection, row["request_id"], outcome, stamp, detail)
                connection.execute(
                    "DELETE FROM inflight_targets WHERE request_id=?", (row["request_id"],)
                )
                recovered.append(row["request_id"])
        self._prune()
        return recovered

    def _prune(self) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._expire_pending(connection, _utc(self.now()))
            stale = connection.execute(
                "SELECT request_id FROM commands WHERE outcome IN ('rejected','verified','contradicted','timed_out_ambiguous') "
                "ORDER BY updated_at DESC, rowid DESC LIMIT -1 OFFSET ?",
                (self.retention_limit,),
            ).fetchall()
            connection.executemany(
                "DELETE FROM commands WHERE request_id=?", [(row["request_id"],) for row in stale]
            )

    def receipt(self, request_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            command = connection.execute(
                "SELECT * FROM commands WHERE request_id=?", (request_id,)
            ).fetchone()
            if not command:
                raise KeyError(request_id)
            events = connection.execute(
                "SELECT sequence, state, recorded_at, detail_json FROM audit_events "
                "WHERE request_id=? ORDER BY sequence", (request_id,)
            ).fetchall()
        return {
            "request_id": command["request_id"],
            "idempotency_key": command["idempotency_key"],
            "operator_id": command["operator_id"],
            "request": json.loads(command["request_json"]),
            "outcome": command["outcome"],
            "dispatch_possible": bool(command["dispatch_possible"]),
            "simulation": True,
            "verification_kind": (
                "simulated_platform_readback" if command["outcome"] == "verified" else None
            ),
            "physically_verified": False,
            "events": [
                {
                    "sequence": row["sequence"],
                    "state": row["state"],
                    "recorded_at": row["recorded_at"],
                    "detail": json.loads(row["detail_json"]),
                }
                for row in events
            ],
        }

    def status(self) -> dict[str, Any]:
        with self._connect() as connection:
            command_count = connection.execute("SELECT COUNT(*) FROM commands").fetchone()[0]
            targets = [
                row[0]
                for row in connection.execute(
                    "SELECT target_id FROM inflight_targets ORDER BY target_id"
                ).fetchall()
            ]
        return {
            "simulation": True,
            "enabled": self.enabled,
            "kill_switch": self.kill_switch,
            "command_count": command_count,
            "inflight_targets": targets,
        }

    def set_kill_switch(self, engaged: bool) -> None:
        with self._policy_lock:
            self.kill_switch = bool(engaged)
