import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import jsonschema


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

    def test_raw_and_interpreted_documents_validate_against_published_schemas(self):
        for document, schema_name in (
            (self.raw, "raw-telemetry.schema.json"),
            (self.state, "world-state.schema.json"),
        ):
            schema = json.loads((ROOT / "coordination" / schema_name).read_text())
            jsonschema.Draft202012Validator(schema).validate(document)

        failed = dict(self.raw, errors=["mqtt: unavailable"])
        jsonschema.Draft202012Validator(
            json.loads((ROOT / "coordination" / "world-state.schema.json").read_text())
        ).validate(world_state.interpret(failed))

    def test_stale_activity_is_uncertain_not_active(self):
        raw = json.loads(json.dumps(self.raw))
        raw["sources"][0]["payload"][0]["last_updated"] = "2026-09-10T14:00:00+00:00"
        situation = {item["id"]: item for item in world_state.interpret(raw)["situations"]}["studio-activity"]
        self.assertEqual(situation["state"], "uncertain")
        self.assertLess(situation["confidence"], 1.0)

    def test_system_health_is_three_valued_by_freshness(self):
        raw = json.loads(json.dumps(self.raw))
        raw["sources"][2]["observed_at"] = "2026-09-10T14:00:00+00:00"
        raw["sources"][3]["observed_at"] = "2026-09-10T14:00:00+00:00"
        health = {item["id"]: item for item in world_state.interpret(raw)["situations"]}["system-health"]
        self.assertEqual(health["state"], "uncertain")
        self.assertLess(health["confidence"], 1.0)

        raw["sources"] = [item for item in raw["sources"] if item["source"]["kind"] not in {"service", "system"}]
        health = {item["id"]: item for item in world_state.interpret(raw)["situations"]}["system-health"]
        self.assertEqual(health["state"], "unknown")

    def test_registry_declares_source_meaning_and_events_do_not_assert_state(self):
        registry = {
            "sources": [{
                "kind": "mqtt", "match": "octoprint/+/state", "domain": "fabrication",
                "semantic": "machine_activity", "state_kind": "event", "freshness_seconds": 120,
                "sensitivity": "household",
            }]
        }
        observation = next(item for item in world_state.interpret(self.raw, registry)["observations"] if item["source"]["kind"] == "mqtt")
        situation = {item["id"]: item for item in world_state.interpret(self.raw, registry)["situations"]}["fabrication-activity"]
        self.assertEqual(observation["source"]["semantic"], "machine_activity")
        self.assertEqual(observation["source"]["state_kind"], "event")
        self.assertEqual(situation["state"], "unknown")

    def test_home_assistant_collection_retains_only_allowlisted_fields(self):
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        response.read.return_value = json.dumps({
            "entity_id": "binary_sensor.studio_motion", "state": "on",
            "last_updated": "2026-09-10T14:59:30+00:00", "attributes": {"person": "private"},
        }).encode()
        source = {"match": "binary_sensor.studio_motion", "retain": ["state", "last_updated"]}
        with mock.patch.object(world_state.urllib.request, "urlopen", return_value=response):
            rows = world_state.collect_home_assistant("http://ha", "token", [source])
        self.assertEqual(rows, [{
            "entity_id": "binary_sensor.studio_motion", "state": "on",
            "last_updated": "2026-09-10T14:59:30+00:00",
        }])

    def test_evidence_opportunity_joins_affordance_need_and_capacity(self):
        raw = json.loads(json.dumps(self.raw))
        raw["sources"][4]["observed_at"] = raw["collected_at"]
        raw["sources"][4]["payload"].update({
            "benlab": {"now": [{
                "project": "homeauto", "next_action": "Save an ingest receipt", "effort": "30m",
                "stack": ["terminal", "repo"], "route": "repo_issue", "attention": "now",
                "need_type": "evidence",
            }]},
            "schedule": {"capacity": {"fits": [{"project": "homeauto", "temporal_status": "today"}]}},
        })
        registry = {"sources": [
            {
                "kind": "system", "match": "*", "domain": "system", "semantic": "host_health",
                "state_kind": "state", "freshness_seconds": 120, "sensitivity": "internal",
                "affordances": ["terminal", "repo"], "affordance_scope": "local-operator",
            },
            {
                "kind": "coordination", "match": "*", "domain": "coordination",
                "semantic": "benlab_context", "state_kind": "state",
                "freshness_seconds": 900, "sensitivity": "private",
            },
        ]}
        situations = {item["id"]: item for item in world_state.interpret(raw, registry)["situations"]}
        opportunity = situations["evidence-opportunity:homeauto"]
        self.assertEqual(opportunity["state"], "available")
        self.assertIn("BenLab", opportunity["rule"])
        self.assertIn("system:collector-host:0", opportunity["evidence"])

        raw["sources"][4]["observed_at"] = "2026-09-10T14:00:00+00:00"
        stale_situations = {item["id"]: item for item in world_state.interpret(raw, registry)["situations"]}
        self.assertNotIn("evidence-opportunity:homeauto", stale_situations)

    def test_active_needs_are_neutral_and_only_explicit_evidence_needs_get_evidence_opportunities(self):
        raw = json.loads(json.dumps(self.raw))
        raw["sources"][4]["observed_at"] = raw["collected_at"]
        raw["sources"][4]["payload"].update({
            "benlab": {"now": [{
                "project": "homeauto", "next_action": "Make a decision", "stack": ["terminal"],
                "route": "decision", "attention": "now",
            }]},
            "schedule": {"capacity": {"fits": [{"project": "homeauto", "temporal_status": "today"}]}},
        })
        state = world_state.interpret(raw)
        coordination = next(item for item in state["observations"] if item["source"]["kind"] == "coordination")
        situations = {item["id"]: item for item in state["situations"]}
        self.assertIn("active_needs", coordination["value"])
        self.assertNotIn("evidence_needs", coordination["value"])
        self.assertIn("action-opportunity:homeauto", situations)
        self.assertNotIn("evidence-opportunity:homeauto", situations)

    def test_affordances_compose_only_within_one_scope(self):
        raw = json.loads(json.dumps(self.raw))
        raw["sources"][4]["observed_at"] = raw["collected_at"]
        raw["sources"][4]["payload"].update({
            "benlab": {"now": [{
                "project": "live-rig", "next_action": "Capture evidence",
                "stack": ["camera", "hardware", "obsidian"], "attention": "now", "need_type": "evidence",
            }]},
            "schedule": {"capacity": {"fits": [{"project": "live-rig", "temporal_status": "today"}]}},
        })
        raw["sources"].extend([
            {"source": {"kind": "system", "name": "bench"}, "observed_at": raw["collected_at"], "freshness_seconds": 120, "sensitivity": "internal", "confidence": 1.0, "payload": {}},
            {"source": {"kind": "system", "name": "laptop"}, "observed_at": raw["collected_at"], "freshness_seconds": 120, "sensitivity": "internal", "confidence": 1.0, "payload": {}},
        ])
        registry = {"sources": [
            {"kind": "system", "match": "bench", "domain": "system", "semantic": "resource", "state_kind": "state", "freshness_seconds": 120, "sensitivity": "internal", "affordances": ["camera", "hardware"], "affordance_scope": "studio"},
            {"kind": "system", "match": "laptop", "domain": "system", "semantic": "resource", "state_kind": "state", "freshness_seconds": 120, "sensitivity": "internal", "affordances": ["obsidian"], "affordance_scope": "studio"},
            {"kind": "coordination", "match": "*", "domain": "coordination", "semantic": "benlab_context", "state_kind": "state", "freshness_seconds": 900, "sensitivity": "private"},
        ]}
        opportunity = {item["id"]: item for item in world_state.interpret(raw, registry)["situations"]}["evidence-opportunity:live-rig"]
        self.assertEqual(set(opportunity["evidence"]), {"coordination:operator-snapshot:0", "system:bench:0", "system:laptop:0"})

        registry["sources"][1]["affordance_scope"] = "home"
        situations = {item["id"] for item in world_state.interpret(raw, registry)["situations"]}
        self.assertNotIn("evidence-opportunity:live-rig", situations)

    def test_interpret_records_bounded_state_transitions(self):
        previous = self.state
        raw = json.loads(json.dumps(self.raw))
        raw["collected_at"] = "2026-09-10T15:01:00+00:00"
        raw["sources"][0]["payload"][0]["state"] = "off"
        raw["sources"][0]["payload"][0]["last_updated"] = raw["collected_at"]
        state = world_state.interpret(raw, previous_state=previous)
        transition = next(item for item in state["transitions"] if item["situation_id"] == "studio-activity")
        self.assertEqual((transition["from"], transition["to"]), ("active", "inactive"))
        self.assertEqual(transition["changed_at"], raw["collected_at"])

        previous["transitions"] = [{"situation_id": "old", "from": "a", "to": "b", "changed_at": str(index)} for index in range(100)]
        self.assertEqual(len(world_state.interpret(raw, previous_state=previous)["transitions"]), 100)

    def test_rules_derive_health_activity_fabrication_staleness_and_opportunities(self):
        situations = {item["id"]: item for item in self.state["situations"]}
        self.assertEqual(situations["system-health"]["state"], "degraded")
        self.assertEqual(situations["studio-activity"]["state"], "active")
        self.assertEqual(situations["fabrication-activity"]["state"], "active")
        self.assertEqual(situations["source-staleness"]["state"], "stale")
        self.assertEqual(situations["evidence-opportunities"]["state"], "none")
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
            {"generated_at", "source_availability", "warning_count", "directive_count", "active_needs", "capacity_projects"},
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
