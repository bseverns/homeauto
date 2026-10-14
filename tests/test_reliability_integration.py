import copy
import importlib.machinery
import importlib.util
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

import jsonschema


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "integration"

LAB_LOADER = importlib.machinery.SourceFileLoader(
    "reliability_lab_console", str(ROOT / "scripts" / "lab-console")
)
LAB_SPEC = importlib.util.spec_from_loader(LAB_LOADER.name, LAB_LOADER)
lab_console = importlib.util.module_from_spec(LAB_SPEC)
LAB_LOADER.exec_module(lab_console)

WORLD_SPEC = importlib.util.spec_from_file_location(
    "reliability_world_state", ROOT / "scripts" / "world_state.py"
)
world_state = importlib.util.module_from_spec(WORLD_SPEC)
WORLD_SPEC.loader.exec_module(world_state)

from services.control_deck.api import ControlDeckData


class ReliabilityPathIntegrationTests(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self.benlab_path = FIXTURES / "benlab-actions.json"
        self.schedule_path = FIXTURES / "schedule-capacity.json"
        self.benlab = json.loads(self.benlab_path.read_text(encoding="utf-8"))
        self.schedule = json.loads(self.schedule_path.read_text(encoding="utf-8"))
        self.empty_registry = {"schema_version": "1.0.0", "machines": []}

    def snapshot(self, benlab_path=None, schedule_path=None):
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary) / "sources.json"
            config.write_text(json.dumps({
                "sources": {
                    "benlab_actions": {"path": str(benlab_path or self.benlab_path)},
                    "schedule_capacity": {"path": str(schedule_path or self.schedule_path)},
                }
            }), encoding="utf-8")
            with (
                mock.patch.object(lab_console, "load_directives", return_value=([], [])),
                mock.patch.object(lab_console, "load_routine_receipts", return_value=([], [])),
            ):
                snapshot = lab_console.build_snapshot(config)
        snapshot["generated_at"] = "2026-10-13T15:00:00+00:00"
        return snapshot

    @staticmethod
    def raw(snapshot):
        return {
            "contract": {"name": "homeauto-raw-telemetry", "schema_version": "1.0.0"},
            "collected_at": "2026-10-13T15:00:00+00:00",
            "sources": [
                {
                    "source": {"kind": "system", "name": "collector-host"},
                    "observed_at": "2026-10-13T15:00:00+00:00",
                    "freshness_seconds": 120,
                    "sensitivity": "internal",
                    "confidence": 1.0,
                    "payload": {"disk_used_percent": 20.0, "load_1m": 0.1},
                },
                {
                    "source": {"kind": "coordination", "name": "operator-snapshot"},
                    "observed_at": "2026-10-13T15:00:00+00:00",
                    "freshness_seconds": 900,
                    "sensitivity": "private",
                    "confidence": 1.0,
                    "payload": snapshot,
                },
            ],
            "errors": [],
        }

    def test_fixture_proves_benlab_to_schedule_to_api_projection(self):
        for document, schema_name in (
            (self.benlab, "benlab-actions-1.2.0.schema.json"),
            (self.schedule, "schedule-capacity-1.0.0.schema.json"),
        ):
            schema = json.loads((ROOT / "coordination" / "upstream-schemas" / schema_name).read_text())
            jsonschema.Draft202012Validator(
                schema, format_checker=jsonschema.FormatChecker()
            ).validate(document)

        snapshot = self.snapshot()
        raw = self.raw(snapshot)
        jsonschema.Draft202012Validator(json.loads(
            (ROOT / "coordination" / "raw-telemetry.schema.json").read_text()
        ), format_checker=jsonschema.FormatChecker()).validate(raw)
        state = world_state.interpret(raw, studio_registry=self.empty_registry)
        jsonschema.Draft202012Validator(json.loads(
            (ROOT / "coordination" / "world-state.schema.json").read_text()
        ), format_checker=jsonschema.FormatChecker()).validate(state)

        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "world-state.json"
            source.write_text(json.dumps(state), encoding="utf-8")
            projection = ControlDeckData(
                source_path=source,
                schema_path=ROOT / "coordination" / "world-state.schema.json",
                fallback_path=ROOT / "tests" / "fixtures" / "control-deck" / "world-state.json",
                now=lambda: datetime.fromisoformat("2026-10-13T15:00:00+00:00"),
            ).world_state()

        opportunity = projection["opportunities"][0]
        self.assertEqual(opportunity["action_id"], "benlab-action:0123456789abcdef:1")
        self.assertEqual(opportunity["state"], "available")
        self.assertEqual(opportunity["capacity"]["authority"], "schedule-assessment")
        self.assertEqual(projection["source"]["mode"], "authoritative")
        self.assertNotIn("source_path", json.dumps(projection))

    def test_negative_source_and_join_states_fail_closed(self):
        snapshot = self.snapshot()

        stale = copy.deepcopy(snapshot)
        stale["schedule"]["capacity"]["freshness"]["status"] = "stale"
        stale_state = world_state.interpret(self.raw(stale), studio_registry=self.empty_registry)
        self.assertEqual(stale_state["opportunities"][0]["state"], "capacity_stale")

        mismatched = copy.deepcopy(snapshot)
        mismatched["schedule"]["capacity"]["results"][0]["action_id"] = "benlab-action:fedcba9876543210:1"
        mismatch_state = world_state.interpret(self.raw(mismatched), studio_registry=self.empty_registry)
        self.assertEqual(mismatch_state["opportunities"][0]["state"], "insufficient_information")

        no_results = copy.deepcopy(snapshot)
        no_results["schedule"]["capacity"]["results"] = []
        no_result_state = world_state.interpret(self.raw(no_results), studio_registry=self.empty_registry)
        self.assertEqual(no_result_state["opportunities"][0]["state"], "insufficient_information")

        registry = {
            "schema_version": "1.0.0",
            "machines": [{
                "id": "studio-machine:fixture", "label": "Fixture machine",
                "docs_ref": "fixture.md", "scope": "studio", "lifecycle": "operational",
                "capabilities": ["fdm-print"], "dashboard": True,
                "contributes_affordances": True,
            }],
        }
        no_telemetry = world_state.interpret(self.raw(snapshot), studio_registry=registry)["machines"][0]
        self.assertEqual(no_telemetry["runtime"], "no telemetry")
        self.assertEqual(no_telemetry["readiness"], "unknown")
        self.assertNotEqual(no_telemetry["lifecycle"], "offline")

    def test_missing_or_invalid_upstream_sources_are_not_available(self):
        missing = self.snapshot(
            benlab_path=Path("/definitely/missing/BenLab/actions.json"),
            schedule_path=Path("/definitely/missing/schedule-assessment/capacity.json"),
        )
        self.assertIsNone(missing["benlab"])
        self.assertIsNone(missing["schedule"]["capacity"])
        self.assertTrue(any("Missing source" in warning for warning in missing["warnings"]))
        self.assertEqual(
            world_state.interpret(self.raw(missing), studio_registry=self.empty_registry)["opportunities"],
            [],
        )

        with tempfile.TemporaryDirectory() as temporary:
            outdated = Path(temporary) / "benlab.json"
            payload = copy.deepcopy(self.benlab)
            payload["contract"]["schema_version"] = "9.0.0"
            outdated.write_text(json.dumps(payload), encoding="utf-8")
            invalid = self.snapshot(benlab_path=outdated)
        self.assertIsNone(invalid["benlab"])
        self.assertTrue(any("unsupported BenLab action contract" in warning for warning in invalid["warnings"]))


if __name__ == "__main__":
    unittest.main()
