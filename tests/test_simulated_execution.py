import argparse
import contextlib
import copy
import io
import json
import os
import sqlite3
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import jsonschema
from referencing import Registry, Resource

from services.simulated_execution.core import (
    EvidenceProvider,
    FakeExecutor,
    PolicyError,
    SimulatedCrash,
    SimulationService,
    TestIdentityProvider,
)
from services.simulated_execution import core, harness


NOW = datetime(2026, 10, 14, 15, 0, tzinfo=timezone.utc)
ROOT = Path(__file__).resolve().parents[1]


def iso(value):
    return value.isoformat()


def request(number=1, **changes):
    value = {
        "request_id": f"request-{number:04d}",
        "action_id": "indicator.set",
        "target_id": "fixture:indicator-01",
        "desired_state": "on",
        "expected_prior_state": "off",
        "requested_at": iso(NOW),
        "expires_at": iso(NOW + timedelta(minutes=2)),
        "idempotency_key": f"idem-{number:04d}",
    }
    value.update(changes)
    return value


def evidence(state="off", **changes):
    value = {
        "evidence_id": "simulated-observation:indicator-01",
        "version": "v1",
        "target_id": "fixture:indicator-01",
        "state": state,
        "observed_at": iso(NOW),
        "fresh_until": iso(NOW + timedelta(seconds=30)),
        "source_mode": "simulated_authoritative",
        "contradictory": False,
    }
    value.update(changes)
    return value


def confirmed_approval(service, payload, credential="test-credential"):
    service.preview(payload, credential)
    with mock.patch.object(core, "_confirm_with_os") as confirmation:
        token = service.approve(payload, credential)
    confirmation.assert_called_once()
    return token


class SimulatedExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.db = Path(self.temporary.name) / "journal.sqlite3"
        self.clock = [NOW]
        self.identity = TestIdentityProvider({"test-credential": "operator-01"})
        self.observations = EvidenceProvider(evidence())
        self.executor = FakeExecutor("success")
        self.service = SimulationService(
            self.db,
            self.identity,
            self.observations,
            self.executor,
            enabled=True,
            now=lambda: self.clock[0],
            approval_ttl_seconds=20,
            retention_limit=100,
        )

    def approve(self, payload=None, credential="test-credential"):
        payload = payload or request()
        return confirmed_approval(self.service, payload, credential)

    def test_success_records_every_transition_without_claiming_physical_verification(self):
        payload = request()
        token = self.approve(payload)

        receipt = self.service.execute(payload, token, "test-credential")

        self.assertEqual(receipt["outcome"], "verified")
        self.assertTrue(receipt["simulation"])
        self.assertFalse(receipt["physically_verified"])
        self.assertEqual(receipt["verification_kind"], "simulated_platform_readback")
        self.assertEqual(receipt["operator_id"], "operator-01")
        self.assertNotIn("test-credential", str(receipt))
        schema = json.loads(
            (ROOT / "coordination" / "simulated-action-receipt.schema.json").read_text()
        )
        request_schema = json.loads(
            (ROOT / "coordination" / "simulated-action-request.schema.json").read_text()
        )
        jsonschema.Draft202012Validator(
            schema,
            format_checker=jsonschema.FormatChecker(),
            registry=Registry().with_resource(
                "simulated-action-request.schema.json",
                Resource.from_contents(request_schema),
            ),
        ).validate(receipt)
        self.assertEqual(
            [event["state"] for event in receipt["events"]],
            ["pending", "authorized", "dispatched", "observed", "verified"],
        )

    def test_anonymous_unauthorized_and_revoked_operators_cannot_execute(self):
        with self.assertRaisesRegex(PolicyError, "authentication"):
            self.service.preview(request(), None)
        with self.assertRaisesRegex(PolicyError, "authentication"):
            self.service.preview(request(), "wrong")

        payload = request()
        token = self.approve(payload)
        self.identity.revoke("test-credential")
        with self.assertRaisesRegex(PolicyError, "authentication"):
            self.service.execute(payload, token, "test-credential")
        self.assertEqual(self.executor.calls, 0)

    def test_schema_rejects_unknown_action_target_parameters_and_actor_claims(self):
        invalid = (
            {**request(1), "action_id": "shell.run"},
            {**request(2), "target_id": "https://device.invalid/api"},
            {**request(3), "desired_state": "toggle"},
            {**request(4), "command": "touch /tmp/nope"},
            {**request(5), "mqtt_topic": "devices/all/set"},
            {**request(6), "actor_id": "administrator"},
        )
        for payload in invalid:
            with self.subTest(payload=payload):
                with self.assertRaises(PolicyError):
                    self.service.preview(payload, "test-credential")
        self.assertEqual(self.executor.calls, 0)

    def test_missing_stale_fixture_and_contradictory_evidence_fail_closed(self):
        bad = (
            None,
            evidence(fresh_until=iso(NOW - timedelta(seconds=1))),
            evidence(source_mode="fixture_fallback"),
            evidence(contradictory=True),
        )
        for number, item in enumerate(bad, start=1):
            self.observations.set(item)
            with self.subTest(evidence=item):
                with self.assertRaises(PolicyError):
                    self.service.preview(request(number), "test-credential")
        self.assertEqual(self.executor.calls, 0)

    def test_expired_request_and_approval_or_reused_approval_are_rejected(self):
        with self.assertRaisesRegex(PolicyError, "expired"):
            self.service.preview(
                request(expires_at=iso(NOW - timedelta(seconds=1))), "test-credential"
            )

        payload = request()
        token = self.approve(payload)
        self.clock[0] += timedelta(seconds=21)
        with self.assertRaisesRegex(PolicyError, "approval expired"):
            self.service.execute(payload, token, "test-credential")
        self.assertEqual(self.executor.calls, 0)

        self.clock[0] = NOW
        other = request(2)
        other_token = self.approve(other)
        self.service.execute(other, other_token, "test-credential")
        with self.assertRaisesRegex(PolicyError, "already consumed"):
            self.service.execute(other, other_token, "test-credential")

    def test_changed_precondition_or_evidence_version_invalidates_approval(self):
        payload = request()
        token = self.approve(payload)
        self.observations.set(evidence(state="on", version="v2"))
        with self.assertRaisesRegex(PolicyError, "evidence changed|precondition"):
            self.service.execute(payload, token, "test-credential")
        self.assertEqual(self.executor.calls, 0)

    def test_idempotency_replay_and_same_key_different_payload_are_rejected(self):
        payload = request()
        token = self.approve(payload)
        self.service.execute(payload, token, "test-credential")
        with self.assertRaisesRegex(PolicyError, "already consumed"):
            self.service.execute(payload, token, "test-credential")

        changed = request(2, idempotency_key=payload["idempotency_key"], desired_state="off")
        with self.assertRaisesRegex(PolicyError, "idempotency key"):
            confirmed_approval(self.service, changed)

    def test_only_one_command_per_target_can_be_in_flight(self):
        slow_executor = FakeExecutor("delay", delay_seconds=0.15)
        database = Path(self.temporary.name) / "inflight.sqlite3"
        first = SimulationService(
            database, self.identity, self.observations, slow_executor,
            enabled=True, now=lambda: self.clock[0],
        )
        one = request(1)
        two = request(2)
        token_one = confirmed_approval(first, one)
        token_two = confirmed_approval(first, two)
        errors = []

        thread = threading.Thread(
            target=lambda: first.execute(one, token_one, "test-credential"), daemon=True
        )
        thread.start()
        for _ in range(100):
            if first.status()["inflight_targets"]:
                break
            time.sleep(0.005)
        try:
            with self.assertRaisesRegex(PolicyError, "already in flight"):
                first.execute(two, token_two, "test-credential")
        except Exception as error:  # pragma: no cover - preserves thread cleanup
            errors.append(error)
        thread.join(timeout=2)
        if errors:
            raise errors[0]
        self.assertFalse(thread.is_alive())

    def test_executor_rejection_timeout_and_post_observation_failures_are_durable(self):
        expected = {
            "rejection": "rejected",
            "timeout": "timed_out_ambiguous",
            "missing_observation": "timed_out_ambiguous",
            "contradictory_observation": "contradicted",
        }
        for number, (behavior, outcome) in enumerate(expected.items(), start=1):
            db = Path(self.temporary.name) / f"journal-{number}.sqlite3"
            service = SimulationService(
                db, self.identity, self.observations, FakeExecutor(behavior),
                enabled=True, now=lambda: self.clock[0],
            )
            payload = request(number)
            token = confirmed_approval(service, payload)
            receipt = service.execute(payload, token, "test-credential")
            self.assertEqual(receipt["outcome"], outcome)
            self.assertEqual(service.receipt(payload["request_id"])["outcome"], outcome)

    def test_crash_recovery_never_retries_possible_dispatch(self):
        before = request(1)
        before_token = self.approve(before)
        with self.assertRaises(SimulatedCrash):
            self.service.execute(before, before_token, "test-credential", crash_at="before_dispatch")
        self.service.recover()
        self.assertEqual(self.service.receipt(before["request_id"])["outcome"], "rejected")

        after = request(2)
        after_token = self.approve(after)
        with self.assertRaises(SimulatedCrash):
            self.service.execute(after, after_token, "test-credential", crash_at="after_dispatch")
        self.service.recover()
        self.assertEqual(
            self.service.receipt(after["request_id"])["outcome"], "timed_out_ambiguous"
        )
        self.assertEqual(self.executor.calls, 0)

    def test_audit_storage_failure_prevents_dispatch(self):
        blocker = Path(self.temporary.name) / "not-a-directory"
        blocker.write_text("blocked", encoding="utf-8")
        with self.assertRaises((OSError, sqlite3.Error)):
            SimulationService(
                blocker / "journal.sqlite3", self.identity, self.observations,
                self.executor, enabled=True, now=lambda: self.clock[0],
            )
        self.assertEqual(self.executor.calls, 0)

    def test_disabled_and_kill_switch_states_preserve_diagnostics(self):
        disabled = SimulationService(
            Path(self.temporary.name) / "disabled.sqlite3",
            self.identity, self.observations, self.executor,
            enabled=False, now=lambda: self.clock[0],
        )
        with self.assertRaisesRegex(PolicyError, "disabled"):
            disabled.preview(request(), "test-credential")
        self.assertFalse(disabled.status()["enabled"])

        payload = request()
        token = self.approve(payload)
        self.service.set_kill_switch(True)
        with self.assertRaisesRegex(PolicyError, "kill switch"):
            self.service.execute(payload, token, "test-credential")
        self.assertTrue(self.service.status()["kill_switch"])
        self.assertEqual(self.executor.calls, 0)

    def test_audit_events_cannot_be_updated_and_receipts_are_bounded(self):
        payload = request()
        token = self.approve(payload)
        self.service.execute(payload, token, "test-credential")
        with sqlite3.connect(self.db) as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("UPDATE audit_events SET state='rejected'")

        bounded = SimulationService(
            Path(self.temporary.name) / "bounded.sqlite3",
            self.identity, self.observations, FakeExecutor("success"),
            enabled=True, now=lambda: self.clock[0], retention_limit=2,
        )
        for number in range(1, 4):
            item = request(number)
            bounded.execute(item, confirmed_approval(bounded, item), "test-credential")
        self.assertEqual(bounded.status()["command_count"], 2)

    def test_approval_requires_a_confirmed_single_use_preview(self):
        payload = request()
        with self.assertRaisesRegex(PolicyError, "confirmed preview"):
            self.service.approve(payload, "test-credential")

        preview = self.service.preview(payload, "test-credential")
        self.assertNotIn("confirmation_token", preview)
        self.assertFalse(hasattr(self.service, "confirm_preview"))
        with mock.patch.object(core, "_confirm_with_os") as confirmation:
            token = self.service.approve(payload, "test-credential")
        confirmation.assert_called_once_with(preview)
        self.assertIsInstance(token, str)
        with self.assertRaisesRegex(PolicyError, "already consumed"):
            self.service.approve(payload, "test-credential")

    def test_os_confirmation_requires_native_user_presence(self):
        payload = request()
        self.service.preview(payload, "test-credential")
        context = mock.Mock()
        context.canEvaluatePolicy_error_.return_value = (True, None)
        context.evaluatePolicy_localizedReason_reply_.side_effect = (
            lambda policy, reason, reply: reply(True, None)
        )
        la_context = mock.Mock()
        la_context.alloc.return_value.init.return_value = context
        native_module = mock.Mock(
            LAContext=la_context,
            LAPolicyDeviceOwnerAuthentication=1,
        )
        with (
            mock.patch("builtins.input", return_value="EXECUTE") as programmatic_input,
            mock.patch.dict("sys.modules", {"LocalAuthentication": native_module}),
        ):
            self.service.approve(payload, "test-credential")
        programmatic_input.assert_not_called()
        context.evaluatePolicy_localizedReason_reply_.assert_called_once()

    def test_os_confirmation_fails_closed_when_unavailable_or_denied(self):
        preview = self.service.preview(request(), "test-credential")
        for available, approved, message in (
            (False, False, "unavailable"),
            (True, False, "not supplied"),
        ):
            with self.subTest(message=message):
                context = mock.Mock()
                context.canEvaluatePolicy_error_.return_value = (available, None)
                context.evaluatePolicy_localizedReason_reply_.side_effect = (
                    lambda policy, reason, reply: reply(approved, None)
                )
                la_context = mock.Mock()
                la_context.alloc.return_value.init.return_value = context
                native_module = mock.Mock(
                    LAContext=la_context,
                    LAPolicyDeviceOwnerAuthentication=1,
                )
                with (
                    mock.patch.dict("sys.modules", {"LocalAuthentication": native_module}),
                    self.assertRaisesRegex(PolicyError, message),
                ):
                    core._confirm_with_os(preview)

    def test_unauthenticated_attempt_cannot_consume_another_operators_approval(self):
        payload = request()
        token = self.approve(payload)
        with self.assertRaisesRegex(PolicyError, "authentication"):
            self.service.execute(payload, "invalid-token", None)
        self.assertEqual(self.service.receipt(payload["request_id"])["outcome"], "pending")
        self.assertEqual(
            self.service.execute(payload, token, "test-credential")["outcome"],
            "verified",
        )

    def test_policy_is_revalidated_immediately_before_dispatch(self):
        payload = request()
        token = self.approve(payload)
        moments = iter((NOW, NOW + timedelta(seconds=60), NOW + timedelta(seconds=60)))
        self.service.now = lambda: next(moments)
        with self.assertRaisesRegex(PolicyError, "approval expired|stale evidence"):
            self.service.execute(payload, token, "test-credential")
        self.assertEqual(self.executor.calls, 0)

    def test_evidence_change_is_serialized_with_dispatch(self):
        payload = request()
        token = self.approve(payload)
        trigger = threading.Event()
        attempted = threading.Event()
        changed = threading.Event()
        original_current = self.observations.current
        calls = 0

        def current():
            nonlocal calls
            value = original_current()
            calls += 1
            if calls == 2:
                trigger.set()
                self.assertTrue(attempted.wait(1))
                changed.wait(0.05)
            return value

        def change():
            trigger.wait()
            attempted.set()
            self.observations.set(evidence(version="v2"))
            changed.set()

        worker = threading.Thread(target=change, daemon=True)
        worker.start()
        original_dispatch = FakeExecutor.dispatch
        with (
            mock.patch.object(self.observations, "current", side_effect=current),
            mock.patch.object(
                FakeExecutor,
                "dispatch",
                autospec=True,
                side_effect=lambda executor, *args: (
                    self.assertFalse(changed.is_set()),
                    original_dispatch(executor, *args),
                )[1],
            ),
        ):
            self.assertEqual(
                self.service.execute(payload, token, "test-credential")["outcome"],
                "verified",
            )
        worker.join(timeout=1)
        self.assertTrue(changed.is_set())

    def test_credential_revocation_is_serialized_with_dispatch(self):
        payload = request()
        token = self.approve(payload)
        trigger = threading.Event()
        attempted = threading.Event()
        revoked = threading.Event()
        original_authenticate = self.identity.authenticate
        calls = 0

        def authenticate(credential):
            nonlocal calls
            operator = original_authenticate(credential)
            calls += 1
            if calls == 2:
                trigger.set()
                self.assertTrue(attempted.wait(1))
                revoked.wait(0.05)
            return operator

        def revoke():
            trigger.wait()
            attempted.set()
            self.identity.revoke("test-credential")
            revoked.set()

        worker = threading.Thread(target=revoke, daemon=True)
        worker.start()
        original_dispatch = FakeExecutor.dispatch
        with (
            mock.patch.object(self.identity, "authenticate", side_effect=authenticate),
            mock.patch.object(
                FakeExecutor,
                "dispatch",
                autospec=True,
                side_effect=lambda executor, *args: (
                    self.assertFalse(revoked.is_set()),
                    original_dispatch(executor, *args),
                )[1],
            ),
        ):
            self.assertEqual(
                self.service.execute(payload, token, "test-credential")["outcome"],
                "verified",
            )
        worker.join(timeout=1)
        self.assertTrue(revoked.is_set())

    def test_database_has_one_exclusive_service_owner(self):
        with self.assertRaisesRegex(PolicyError, "already owned"):
            SimulationService(
                self.db,
                self.identity,
                self.observations,
                FakeExecutor("success"),
                enabled=True,
                now=lambda: self.clock[0],
            )

    def test_recovery_waits_for_live_execution_and_cannot_relabel_it(self):
        service = SimulationService(
            Path(self.temporary.name) / "recovery-race.sqlite3",
            self.identity,
            self.observations,
            FakeExecutor("success", delay_seconds=0.05),
            enabled=True,
            now=lambda: self.clock[0],
        )
        payload = request()
        token = confirmed_approval(service, payload)
        worker = threading.Thread(
            target=lambda: service.execute(payload, token, "test-credential"), daemon=True
        )
        worker.start()
        for _ in range(100):
            if service.executor.calls:
                break
            time.sleep(0.001)
        self.assertEqual(service.recover(), [])
        worker.join(timeout=1)
        self.assertFalse(worker.is_alive())
        receipt = service.receipt(payload["request_id"])
        self.assertEqual(receipt["outcome"], "verified")
        self.assertNotIn("timed_out_ambiguous", [event["state"] for event in receipt["events"]])

    def test_kill_switch_change_is_serialized_with_dispatch(self):
        service = SimulationService(
            Path(self.temporary.name) / "kill-switch-race.sqlite3",
            self.identity,
            self.observations,
            FakeExecutor("success", delay_seconds=0.05),
            enabled=True,
            now=lambda: self.clock[0],
        )
        payload = request()
        token = confirmed_approval(service, payload)
        result = []
        worker = threading.Thread(
            target=lambda: result.append(service.execute(payload, token, "test-credential")),
            daemon=True,
        )
        worker.start()
        for _ in range(100):
            if service.executor.calls:
                break
            time.sleep(0.001)
        switch = threading.Thread(target=lambda: service.set_kill_switch(True), daemon=True)
        switch.start()
        time.sleep(0.005)
        self.assertFalse(service.kill_switch)
        worker.join(timeout=1)
        switch.join(timeout=1)
        self.assertEqual(result[0]["outcome"], "verified")
        self.assertTrue(service.kill_switch)

    def test_phase_c0_rejects_custom_or_subclassed_executors(self):
        class UnsafeExecutor(FakeExecutor):
            pass

        with self.assertRaisesRegex(PolicyError, "closed Phase C0 FakeExecutor"):
            SimulationService(
                Path(self.temporary.name) / "unsafe-executor.sqlite3",
                self.identity,
                self.observations,
                UnsafeExecutor("success"),
                enabled=True,
                now=lambda: self.clock[0],
            )

    def test_delay_cannot_bypass_the_configured_execution_timeout(self):
        service = SimulationService(
            Path(self.temporary.name) / "delay-timeout.sqlite3",
            self.identity,
            self.observations,
            FakeExecutor("success", delay_seconds=0.05),
            enabled=True,
            now=lambda: self.clock[0],
            execution_timeout_seconds=0.001,
        )
        payload = request()
        started = time.monotonic()
        receipt = service.execute(
            payload, confirmed_approval(service, payload), "test-credential"
        )
        self.assertEqual(receipt["outcome"], "timed_out_ambiguous")
        self.assertLess(time.monotonic() - started, 0.03)

    def test_pruning_retains_permanent_replay_tombstones(self):
        service = SimulationService(
            Path(self.temporary.name) / "tombstones.sqlite3",
            self.identity,
            self.observations,
            FakeExecutor("success"),
            enabled=True,
            now=lambda: self.clock[0],
            retention_limit=1,
        )
        first = request(1)
        second = request(2)
        service.execute(first, confirmed_approval(service, first), "test-credential")
        service.execute(second, confirmed_approval(service, second), "test-credential")
        self.assertEqual(service.receipt(second["request_id"])["outcome"], "verified")
        with self.assertRaisesRegex(PolicyError, "already"):
            confirmed_approval(service, first)

    def test_expired_pending_approvals_are_terminal_and_bounded(self):
        service = SimulationService(
            Path(self.temporary.name) / "expired-pending.sqlite3",
            self.identity,
            self.observations,
            FakeExecutor("success"),
            enabled=True,
            now=lambda: self.clock[0],
            approval_ttl_seconds=5,
            retention_limit=1,
        )
        for number in range(1, 4):
            confirmed_approval(service, request(number))
        self.clock[0] += timedelta(seconds=6)
        service.recover()
        self.assertLessEqual(service.status()["command_count"], 1)


class SimulationHarnessTests(unittest.TestCase):
    def test_harness_is_disabled_by_default_and_runs_a_confirmed_reversal(self):
        with tempfile.TemporaryDirectory() as temporary:
            disabled = argparse.Namespace(
                database=Path(temporary) / "disabled.sqlite3",
                enable_simulation=False,
                kill_switch=False,
                behavior="success",
                delay_seconds=0.0,
            )
            with mock.patch.dict(os.environ, {harness.CREDENTIAL_ENV: "opaque-test-value"}):
                with self.assertRaisesRegex(PolicyError, "disabled"):
                    harness.demo(disabled)

            enabled = argparse.Namespace(
                database=Path(temporary) / "enabled.sqlite3",
                enable_simulation=True,
                kill_switch=False,
                behavior="success",
                delay_seconds=0.0,
            )
            output = io.StringIO()
            with (
                mock.patch.dict(os.environ, {harness.CREDENTIAL_ENV: "opaque-test-value"}),
                mock.patch.object(core, "_confirm_with_os"),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(harness.demo(enabled), 0)

        rendered = output.getvalue()
        self.assertIn('"completed": true', rendered)
        self.assertIn('"receipts": 2', rendered)
        self.assertNotIn("confirmation_token", rendered)
        self.assertNotIn("opaque-test-value", rendered)


if __name__ == "__main__":
    unittest.main()
