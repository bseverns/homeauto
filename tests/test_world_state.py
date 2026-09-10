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
STUDIO_MACHINES = ROOT / "coordination" / "studio-machines.json"
STUDIO_MACHINE_SCHEMA = ROOT / "coordination" / "studio-machines.schema.json"


class WorldStateTests(unittest.TestCase):
    def setUp(self):
        self.raw = json.loads(
            (ROOT / "tests" / "fixtures" / "world-state" / "raw.json").read_text()
        )
        self.state = world_state.interpret(self.raw)

    def machine_registry(self, lifecycle="operational"):
        return {
            "schema_version": "1.0.0",
            "machines": [{
                "id": "studio-machine:test-printer",
                "label": "Test Printer",
                "docs_ref": "../machine-docs/personal-machines/test-printer/",
                "scope": "personal-studio",
                "lifecycle": lifecycle,
                "capabilities": ["fdm-print"],
                "telemetry": [{"kind": "mqtt", "match": "octoprint/test-printer/state"}],
                "dashboard": True,
                "contributes_affordances": True,
            }],
        }

    def machine_raw(self, state="idle", observed_at="2026-09-10T15:00:00+00:00"):
        raw = json.loads(json.dumps(self.raw))
        raw["sources"] = [{
            "source": {"kind": "mqtt", "name": "octoprint"},
            "observed_at": observed_at,
            "freshness_seconds": 300,
            "sensitivity": "internal",
            "confidence": 1.0,
            "payload": [{
                "topic": "octoprint/test-printer/state",
                "payload": {"state": state, "token": "must-not-render"},
            }],
        }]
        raw["errors"] = []
        return raw

    def test_curated_registry_selects_only_studio_machines(self):
        registry = json.loads(STUDIO_MACHINES.read_text())
        jsonschema.Draft202012Validator(json.loads(STUDIO_MACHINE_SCHEMA.read_text())).validate(registry)
        ids = {item["id"] for item in registry["machines"]}
        self.assertEqual(ids, {
            "studio-machine:bambu-p1s",
            "studio-machine:lulzbot-mini-2",
            "studio-machine:aquila-modified",
            "studio-machine:genmitsu-cubiko",
            "studio-machine:folgertech-i3-rebuild",
            "studio-machine:stratasys-mojo-retrofit",
            "studio-machine:uprint-open-control",
        })

    def test_documented_machine_without_telemetry_still_appears(self):
        registry = self.machine_registry(lifecycle="commissioning")
        registry["machines"][0].pop("telemetry")
        state = world_state.interpret(self.machine_raw(), studio_registry=registry)
        machine = state["machines"][0]
        self.assertEqual(machine["runtime"], "no telemetry")
        self.assertEqual(machine["freshness"], "unavailable")
        self.assertEqual(machine["readiness"], "unknown")
        self.assertEqual(machine["docs_ref"], "../machine-docs/personal-machines/test-printer/")
        self.assertNotIn("source_document", machine)

    def test_registration_without_telemetry_never_grants_affordances(self):
        registry = self.machine_registry()
        registry["machines"][0].pop("telemetry")
        machine = world_state.interpret(self.machine_raw(), studio_registry=registry)["machines"][0]
        self.assertEqual(machine["readiness"], "unknown")
        self.assertEqual(machine["affordances"], [])

    def test_dashboard_membership_is_preserved(self):
        registry = self.machine_registry()
        registry["machines"][0]["dashboard"] = False
        machine = world_state.interpret(self.machine_raw(), studio_registry=registry)["machines"][0]
        self.assertFalse(machine["dashboard"])

    def test_machine_readiness_is_fresh_lifecycle_gated_and_scoped(self):
        ready = world_state.interpret(self.machine_raw(), studio_registry=self.machine_registry())
        machine = ready["machines"][0]
        self.assertEqual(machine["readiness"], "ready")
        self.assertEqual(machine["affordances"], ["fdm-print"])
        self.assertEqual(machine["affordance_scope"], "personal-studio")

        stale = world_state.interpret(
            self.machine_raw(observed_at="2026-09-10T14:00:00+00:00"),
            studio_registry=self.machine_registry(),
        )
        self.assertEqual(stale["machines"][0]["readiness"], "unknown")
        self.assertEqual(stale["machines"][0]["affordances"], [])

        project = world_state.interpret(
            self.machine_raw(), studio_registry=self.machine_registry(lifecycle="project")
        )
        self.assertEqual(project["machines"][0]["readiness"], "project")
        self.assertEqual(project["machines"][0]["affordances"], [])

    def test_future_telemetry_cannot_establish_readiness(self):
        state = world_state.interpret(
            self.machine_raw(observed_at="2026-09-10T15:01:00+00:00"),
            studio_registry=self.machine_registry(),
        )
        machine = state["machines"][0]
        self.assertEqual(machine["freshness"], "unknown")
        self.assertEqual(machine["readiness"], "unknown")
        self.assertEqual(machine["affordances"], [])

    def test_unknown_runtime_value_is_not_copied_to_interpreted_state(self):
        state = world_state.interpret(
            self.machine_raw("<script>private detail</script>"),
            studio_registry=self.machine_registry(),
        )
        rendered = json.dumps(state["machines"])
        self.assertNotIn("private detail", rendered)
        self.assertEqual(state["machines"][0]["runtime"], "unknown")

    def test_registration_without_telemetry_grants_no_readiness_or_affordance(self):
        machine = world_state.derive_machines([], self.machine_registry())[0]
        self.assertEqual(machine["readiness"], "unknown")
        self.assertEqual(machine["runtime"], "no telemetry")
        self.assertEqual(machine["affordances"], [])

    def test_capability_summary_has_machine_evidence(self):
        state = world_state.interpret(self.machine_raw(), studio_registry=self.machine_registry())
        summary = state["capabilities"][0]
        self.assertEqual(summary["capability"], "fdm-print")
        self.assertEqual(summary["scope"], "personal-studio")
        self.assertEqual(summary["state"], "ready")
        self.assertEqual(summary["available_resources"], 1)
        self.assertEqual(summary["evidence"], ["studio-machine:test-printer"])

    def test_capability_summary_is_partitioned_by_scope(self):
        registry = self.machine_registry()
        other = json.loads(json.dumps(registry["machines"][0]))
        other.update({"id": "studio-machine:other-printer", "scope": "other-studio"})
        registry["machines"].append(other)
        summaries = world_state.interpret(self.machine_raw(), studio_registry=registry)["capabilities"]
        self.assertEqual(
            [(item["scope"], item["available_resources"], item["evidence"]) for item in summaries],
            [
                ("other-studio", 1, ["studio-machine:other-printer"]),
                ("personal-studio", 1, ["studio-machine:test-printer"]),
            ],
        )

    def test_machine_state_omits_private_payload_and_keeps_authority(self):
        state = world_state.interpret(self.machine_raw(), studio_registry=self.machine_registry())
        rendered = json.dumps({"machines": state["machines"], "capabilities": state["capabilities"]})
        self.assertNotIn("must-not-render", rendered)
        self.assertNotIn("token", rendered)
        self.assertEqual(state["contract"]["authority"], "read-only; no control actions")
        self.assertTrue(any("does not create, approve, or dispatch directives" in item for item in state["boundaries"]))

    def test_machine_transitions_share_existing_bounded_history(self):
        registry = self.machine_registry()
        previous = world_state.interpret(self.machine_raw("idle"), studio_registry=registry)
        previous["transitions"] = [
            {"situation_id": f"old:{index}", "from": "a", "to": "b", "changed_at": self.raw["collected_at"]}
            for index in range(100)
        ]
        current = world_state.interpret(
            self.machine_raw("printing"), previous_state=previous, studio_registry=registry
        )
        self.assertEqual(len(current["transitions"]), 100)
        self.assertEqual(current["transitions"][-1]["situation_id"], "studio-machine:test-printer")
        self.assertEqual(current["transitions"][-1]["from"], "ready")
        self.assertEqual(current["transitions"][-1]["to"], "busy")

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
