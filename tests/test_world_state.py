import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("world_state", ROOT / "scripts" / "world_state.py")
world_state = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(world_state)


class WorldStateTests(unittest.TestCase):
    def setUp(self):
        self.raw = json.loads(
            (ROOT / "tests" / "fixtures" / "world-state" / "raw.json").read_text()
        )
        self.state = world_state.interpret(self.raw)

    def test_observations_have_provenance_freshness_sensitivity_and_confidence(self):
        self.assertGreater(len(self.state["observations"]), 0)
        for observation in self.state["observations"]:
            self.assertIn("source", observation)
            self.assertIn("observed_at", observation)
            self.assertIn(observation["freshness"]["status"], {"fresh", "stale", "unknown"})
            self.assertIn("sensitivity", observation)
            self.assertGreaterEqual(observation["confidence"], 0)
            self.assertLessEqual(observation["confidence"], 1)

    def test_rules_derive_health_activity_fabrication_staleness_and_opportunities(self):
        situations = {item["id"]: item for item in self.state["situations"]}
        self.assertEqual(situations["system-health"]["state"], "degraded")
        self.assertEqual(situations["studio-activity"]["state"], "active")
        self.assertEqual(situations["fabrication-activity"]["state"], "active")
        self.assertEqual(situations["source-staleness"]["state"], "stale")
        self.assertEqual(situations["evidence-opportunities"]["state"], "open")
        self.assertTrue(all(item["evidence"] for item in situations.values()))
        self.assertTrue(all(item["rule"] for item in situations.values()))

    def test_interpreted_state_does_not_embed_raw_telemetry(self):
        encoded = json.dumps(self.state)
        self.assertNotIn('"payload"', encoded)
        coordination = next(
            item for item in self.state["observations"]
            if item["source"]["kind"] == "coordination"
        )
        self.assertEqual(
            set(coordination["value"]),
            {"generated_at", "source_availability", "warning_count", "directive_count"},
        )
        evidence_ids = {item["id"] for item in self.state["observations"]}
        self.assertEqual(self.state["contract"]["authority"], "read-only; no control actions")
        for situation in self.state["situations"]:
            self.assertTrue(set(situation["evidence"]).issubset(evidence_ids))

    def test_dashboard_has_why_evidence_and_human_directive_boundary(self):
        dashboard = world_state.render_situations(self.state)
        self.assertIn("## World situations", dashboard)
        self.assertIn("Why?", dashboard)
        self.assertIn("mosquitto", dashboard)
        self.assertIn("does not create, approve, or dispatch directives", dashboard)

    def test_read_only_collector_combines_all_source_types(self):
        with tempfile.TemporaryDirectory() as tmp:
            coordination = Path(tmp) / "snapshot.json"
            coordination.write_text(
                json.dumps({"generated_at": "2026-09-10T15:00:00+00:00"}),
                encoding="utf-8",
            )
            environment = {"HA_URL": "http://ha", "HA_TOKEN": "secret", "MQTT_HOST": "mqtt"}
            with (
                mock.patch.dict(os.environ, environment, clear=True),
                mock.patch.object(world_state, "collect_home_assistant", return_value=[]),
                mock.patch.object(world_state, "collect_mqtt", return_value=[]),
                mock.patch.object(world_state, "collect_services", return_value=[{"name": "ha", "state": "running"}]),
                mock.patch.object(world_state.shutil, "which", return_value="/usr/bin/mosquitto_sub"),
            ):
                raw = world_state.collect_raw(coordination, Path("compose.yml"))

        self.assertEqual(
            {record["source"]["kind"] for record in raw["sources"]},
            {"home_assistant", "mqtt", "service", "system", "coordination"},
        )
        self.assertEqual(raw["contract"]["name"], "homeauto-raw-telemetry")
        self.assertNotIn("secret", json.dumps(raw))


if __name__ == "__main__":
    unittest.main()
