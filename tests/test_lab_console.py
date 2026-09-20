import importlib.machinery
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
LOADER = importlib.machinery.SourceFileLoader(
    "lab_console", str(ROOT / "scripts" / "lab-console")
)
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
lab_console = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(lab_console)


class LabConsoleTests(unittest.TestCase):
    def test_schedule_capacity_json_is_consumed_without_scheduling_authority(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "schedule_capacity.json"
            path.write_text(json.dumps({
                "contract": {
                    "name": "schedule-capacity", "schema_version": "1.0.0",
                    "authority": "read_only_capacity_evidence", "scheduling_authority": False,
                    "calendar_mutation_allowed": False,
                },
                "freshness": {"status": "fresh", "warnings": []},
                "results": [
                    {"action_id": "benlab:one", "project_id": "p/one.md", "project": "one", "queue": "now", "queue_position": 1, "action": "A", "effort": "30m", "energy_fit": "screen-only", "fit_status": "fits", "capacity_start": "2026-09-19T10:00:00-05:00", "capacity_end": "2026-09-19T11:00:00-05:00", "source_freshness": "fresh"},
                    {"project": "two", "action": "B", "fit_status": "capacity_unknown"},
                ],
            }))

            summary = lab_console.summarize_capacity(path)

            self.assertEqual(summary["result_count"], 2)
            self.assertEqual(summary["fit_count"], 1)
            self.assertEqual(summary["fits"][0]["project"], "one")
            self.assertEqual(summary["fits"][0]["action_id"], "benlab:one")
            self.assertEqual(summary["fits"][0]["queue_position"], 1)
            self.assertFalse(summary["contract"]["scheduling_authority"])

    def test_schedule_capacity_json_rejects_authority_or_freshness_violation(self):
        base = {
            "contract": {"name": "schedule-capacity", "schema_version": "1.0.0", "authority": "read_only_capacity_evidence", "scheduling_authority": False, "calendar_mutation_allowed": False},
            "freshness": {"status": "stale"},
            "results": [{"fit_status": "fits"}],
        }
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "schedule_capacity.json"
            path.write_text(json.dumps(base))
            with self.assertRaises(ValueError):
                lab_console.summarize_capacity(path)
            base["freshness"]["status"] = "fresh"
            base["contract"]["calendar_mutation_allowed"] = True
            path.write_text(json.dumps(base))
            with self.assertRaises(ValueError):
                lab_console.summarize_capacity(path)

    def test_routine_registry_has_operator_shortcuts(self):
        registry = lab_console.load_routines(ROOT / "coordination" / "routines.json")
        self.assertEqual(
            set(registry),
            {"daily", "weekly", "monthly", "refresh", "ask", "benlab-refresh", "analyst-scan", "analyst-readonly", "analyst-write", "capacity", "latest"},
        )
        for routine in registry.values():
            self.assertIsInstance(routine["command"], list)
            self.assertIn("read_only", routine)
            self.assertIn("requires_confirmation", routine)
            self.assertIn("expected_output", routine)

    def test_open_uses_native_viewer_for_known_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dashboard = root / "state" / "dashboard.md"
            dashboard.parent.mkdir()
            dashboard.write_text("dashboard")
            detail = root / "analyst-promotions.json"
            detail.write_text("{}")
            config = root / "sources.json"
            config.write_text(json.dumps({
                "sources": {
                    "analyst_promotions": {"path": str(detail)}
                },
                "outputs": {
                    "snapshot": str(root / "state" / "snapshot.json"),
                    "dashboard": str(dashboard),
                },
            }))

            with mock.patch.object(
                lab_console.subprocess, "run"
            ) as run:
                lab_console.open_target("dashboard", config)
                lab_console.open_target("analyst", config)

            self.assertEqual(
                run.call_args_list,
                [
                    mock.call(["open", str(dashboard)], check=True),
                    mock.call(["open", str(detail)], check=True),
                ],
            )

    def test_run_routine_uses_adapter_and_writes_completed_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adapter = root / "adapter"
            adapter.write_text("#!/bin/sh\nprintf 'artifact output\\n'\n", encoding="utf-8")
            adapter.chmod(0o755)
            registry_path = root / "routines.json"
            registry_path.write_text(json.dumps({"routines": [{
                "id": "sample",
                "label": "Sample",
                "description": "Test routine",
                "target": "test",
                "adapter": str(adapter),
                "cwd": ".",
                "command": ["ignored"],
                "read_only": True,
                "requires_confirmation": False,
                "expected_output": "text",
                "duration": "brief",
                "interaction": "none",
            }]}), encoding="utf-8")

            receipt = lab_console.run_routine(
                "sample", registry_path, root / "receipts", refresh_world_state=False
            )

            self.assertEqual(receipt["result"], "completed")
            self.assertTrue(receipt["started"])
            self.assertEqual(receipt["requested_by"], "human")
            self.assertEqual(Path(receipt["artifact"]).read_text(), "artifact output\n")
            stored = json.loads(next((root / "receipts").glob("*.json")).read_text())
            self.assertEqual(stored, receipt)

    def test_dashboard_lists_recent_routine_receipts(self):
        dashboard = lab_console.render_dashboard({
            "generated_at": "2026-09-10T00:00:00+00:00",
            "sources": {
                "benlab_actions": {
                    "available": True,
                    "configured_path": "/tmp/benlab-actions.json",
                }
            },
            "schedule": {},
            "directives": [],
            "routine_receipts": [{
                "routine": "weekly",
                "label": "Weekly Connect",
                "requested_at": "2026-09-09T00:00:00+00:00",
                "result": "completed",
                "target": "benlab",
            }],
            "world_state": {"situations": [{
                "label": "System health",
                "state": "healthy",
                "confidence": 1,
                "rule": "fresh evidence",
                "why": ["system = observed"],
            }]},
            "warnings": [],
            "boundaries": [],
        })
        self.assertIn("## Operator", dashboard)
        self.assertIn("`lab-console run daily`", dashboard)
        self.assertIn("## Recent activity", dashboard)
        self.assertIn("[BenLab details](file:///tmp/benlab-actions.json)", dashboard)
        self.assertIn("`lab-console run benlab-refresh`", dashboard)
        self.assertIn("Weekly Connect", dashboard)
        self.assertIn("#### Why? System health", dashboard)
        self.assertNotIn("<details", dashboard)

    def test_dashboard_cells_escape_html_and_markdown_tables(self):
        self.assertEqual(lab_console.cell("<script>|private</script>"), "&lt;script&gt;\\|private&lt;/script&gt;")
        self.assertEqual(
            lab_console.cell("![x](https://host/track) [link](https://host)"),
            "\\!\\[x\\]\\(https://host/track\\) \\[link\\]\\(https://host\\)",
        )
        self.assertEqual(lab_console.cell("safe\r# injected"), "safe # injected")

    def test_routine_input_is_not_environment_expanded(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adapter = root / "adapter"
            adapter.write_text("#!/bin/sh\nprintf '%s' \"$1\"\n", encoding="utf-8")
            adapter.chmod(0o755)
            registry_path = root / "routines.json"
            registry_path.write_text(json.dumps({"routines": [{
                "id": "sample", "label": "Sample", "description": "Test", "target": "test",
                "adapter": str(adapter), "cwd": ".", "command": ["{input}"], "read_only": True,
                "requires_confirmation": False, "expected_output": "text", "duration": "brief",
                "interaction": "none",
            }]}), encoding="utf-8")

            receipt = lab_console.run_routine(
                "sample", registry_path, root / "receipts",
                input_value="$HOME/material", refresh_world_state=False,
            )

            self.assertEqual(Path(receipt["artifact"]).read_text(), "$HOME/material")

    def test_analyst_arguments_and_model_are_passed_as_literal_argv(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adapter = root / "adapter"
            adapter.write_text(
                "#!/bin/sh\nprintf '%s\\n' \"$OLLAMA_CHAT_MODEL\" \"$@\"\n",
                encoding="utf-8",
            )
            adapter.chmod(0o755)
            registry_path = root / "routines.json"
            registry_path.write_text(json.dumps({"routines": [{
                "id": "analyst-readonly", "label": "Analyst", "description": "Test", "target": "test",
                "adapter": str(adapter), "cwd": ".", "command": ["{args}"], "read_only": True,
                "requires_confirmation": False, "expected_output": "text", "duration": "brief",
                "interaction": "none",
            }]}), encoding="utf-8")

            receipt = lab_console.run_routine(
                "analyst-readonly", registry_path, root / "receipts",
                arguments=["find", "$HOME; touch /tmp/nope", "--limit", "10"],
                environment={"OLLAMA_CHAT_MODEL": "gpt-oss:20b"},
                refresh_world_state=False,
            )

            self.assertEqual(
                Path(receipt["artifact"]).read_text().splitlines(),
                ["gpt-oss:20b", "find", "$HOME; touch /tmp/nope", "--limit", "10"],
            )

    def test_analyst_write_policy_matches_cli_side_effects(self):
        self.assertFalse(lab_console.analyst_requires_confirmation(["find", "query"]))
        self.assertFalse(lab_console.analyst_requires_confirmation(["scan", "--help"]))
        self.assertFalse(lab_console.analyst_requires_confirmation(["benlab-tend", "--context", "context.json"]))
        self.assertFalse(lab_console.analyst_requires_confirmation(["benlab-challenge", "--project", "project"]))
        self.assertFalse(lab_console.analyst_requires_confirmation(["benlab-connect", "--note", "note"]))
        self.assertFalse(lab_console.analyst_requires_confirmation(["migrate-cards", "--to-schema", "2", "--dry-run"]))
        self.assertTrue(lab_console.analyst_requires_confirmation(["scan", "--root", "/tmp/research"]))
        self.assertTrue(lab_console.analyst_requires_confirmation(["migrate-cards", "--to-schema", "2"]))
        self.assertTrue(lab_console.analyst_requires_confirmation(["migrate-candidate-markers", "--apply"]))
        with self.assertRaisesRegex(ValueError, "spell --apply in full"):
            lab_console.analyst_requires_confirmation(["migrate-candidate-markers", "--app"])
        with self.assertRaisesRegex(ValueError, "unknown Analyst command"):
            lab_console.analyst_requires_confirmation(["future-command"])

    def test_analyst_cli_keeps_run_specific_values_dynamic(self):
        args = lab_console.parse_args([
            "analyst", "--model", "gemma4:12b", "find", "Beneath the information", "--limit", "10",
        ])
        self.assertEqual(args.model, "gemma4:12b")
        self.assertEqual(args.arguments, ["find", "Beneath the information", "--limit", "10"])
        write_args = lab_console.parse_args(["analyst", "scan", "--root", "/tmp/research", "--yes"])
        self.assertTrue(write_args.yes)
        self.assertEqual(write_args.arguments, ["scan", "--root", "/tmp/research"])
        with self.assertRaises(SystemExit):
            lab_console.parse_args(["analyst", "--model", "bad model", "find", "query"])

    def test_failed_process_start_is_recorded_truthfully(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry_path = root / "routines.json"
            registry_path.write_text(json.dumps({"routines": [{
                "id": "sample", "label": "Sample", "description": "Test", "target": "test",
                "adapter": str(root / "missing"), "cwd": ".", "command": ["ignored"],
                "read_only": True, "requires_confirmation": False, "expected_output": "text",
                "duration": "brief", "interaction": "none",
            }]}), encoding="utf-8")

            seen = []

            def observe_dashboard_refresh(_config_path):
                stored = json.loads(next((root / "receipts").glob("*.json")).read_text())
                seen.append(stored["result"])

            with mock.patch.object(
                lab_console, "write_snapshot", side_effect=observe_dashboard_refresh
            ):
                receipt = lab_console.run_routine("sample", registry_path, root / "receipts")

            self.assertFalse(receipt["started"])
            self.assertEqual(receipt["result"], "failed")
            self.assertEqual(seen, ["failed"])

    def test_artifact_failure_preserves_truthful_execution_fields(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adapter = root / "adapter"
            adapter.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            adapter.chmod(0o755)
            (root / "routine-artifacts").write_text("blocks directory creation", encoding="utf-8")
            registry_path = root / "routines.json"
            registry_path.write_text(json.dumps({"routines": [{
                "id": "sample", "label": "Sample", "description": "Test", "target": "test",
                "adapter": str(adapter), "cwd": ".", "command": ["ignored"], "read_only": True,
                "requires_confirmation": False, "expected_output": "text", "duration": "brief",
                "interaction": "none",
            }]}), encoding="utf-8")

            receipt = lab_console.run_routine(
                "sample", registry_path, root / "receipts", refresh_world_state=False
            )

            self.assertTrue(receipt["started"])
            self.assertEqual(receipt["exit_code"], 0)
            self.assertEqual(receipt["result"], "failed")

    def test_refresh_failure_is_part_of_receipt_result(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adapter = root / "adapter"
            adapter.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            adapter.chmod(0o755)
            registry_path = root / "routines.json"
            registry_path.write_text(json.dumps({"routines": [{
                "id": "sample", "label": "Sample", "description": "Test", "target": "test",
                "adapter": str(adapter), "cwd": ".", "command": ["ignored"], "read_only": True,
                "requires_confirmation": False, "expected_output": "text", "duration": "brief",
                "interaction": "none",
            }]}), encoding="utf-8")
            refresh_seen = []

            def observe_dashboard_refresh(_config_path):
                stored = json.loads(next((root / "receipts").glob("*.json")).read_text())
                refresh_seen.append(stored["result"])

            with (
                mock.patch.object(
                    lab_console.subprocess, "run",
                    side_effect=[mock.Mock(returncode=0, stdout=""), mock.Mock(returncode=2)],
                ),
                mock.patch.object(lab_console, "write_snapshot", side_effect=observe_dashboard_refresh),
            ):
                receipt = lab_console.run_routine("sample", registry_path, root / "receipts")

            self.assertEqual(receipt["result"], "refresh-failed")
            self.assertEqual(receipt["refresh_exit_code"], 2)
            self.assertFalse(receipt["refreshed_world_state"])
            self.assertEqual(refresh_seen, ["refresh-failed"])

    def test_analyst_summary_omits_private_source_material(self):
        payload = {
            "contract_version": 2,
            "generated_at": "2026-09-10T00:00:00+00:00",
            "promotions": [
                {
                    "card_id": "card-example",
                    "created_unix": 1,
                    "working_title": "Useful candidate",
                    "source_path": "/private/library/source.pdf",
                    "evidence": ["private evidence body"],
                    "promotion_recommendation": {
                        "status": "retain_as_candidate",
                        "promotion_target": "concept_note",
                    },
                    "benlab_intake": {
                        "suggested_route": "concept_note",
                        "suggested_next_step": "Review it",
                    },
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "promotions.json"
            source.write_text(json.dumps(payload), encoding="utf-8")
            summary = lab_console.summarize_analyst(source)

        serialized = json.dumps(summary)
        self.assertNotIn("/private/library", serialized)
        self.assertNotIn("private evidence body", serialized)
        self.assertEqual(summary["recent_candidates"][0]["card_id"], "card-example")

    def test_new_directive_is_inert_and_requires_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = lab_console.create_directive(
                Path(tmp),
                "schedule-assessment",
                "Reassess available capacity",
                "assess_capacity",
                source_refs=["benlab-actions:homeauto"],
                constraints=["Do not create calendar events"],
            )
            payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(payload["status"], "draft")
        self.assertTrue(payload["requires_confirmation"])
        self.assertEqual(payload["authority"], "human")
        self.assertIsNone(payload["outcome"])

    def test_dashboard_states_governance_boundaries(self):
        dashboard = lab_console.render_dashboard(
            {
                "generated_at": "2026-09-10T00:00:00+00:00",
                "sources": {},
                "benlab": None,
                "analyst": None,
                "schedule": {"capacity": None, "freshness": None},
                "directives": [],
                "warnings": [],
                "world_state": {
                    "machines": [{
                        "id": "studio-machine:test-printer",
                        "label": "Test Printer",
                        "docs_ref": "../machine-docs/personal-machines/test-printer/",
                        "scope": "personal-studio",
                        "lifecycle": "operational",
                        "capabilities": ["fdm-print"],
                        "readiness": "ready",
                        "runtime": "idle",
                        "freshness": "fresh",
                        "affordances": ["fdm-print"],
                        "affordance_scope": "personal-studio",
                        "evidence": ["mqtt:octoprint:octoprint/test-printer/state"],
                        "why": ["fresh idle telemetry supports ready"],
                    }],
                    "capabilities": [{
                        "capability": "fdm-print",
                        "state": "ready",
                        "available_resources": 1,
                        "evidence": ["studio-machine:test-printer"],
                    }],
                    "transitions": [{
                        "situation_id": "studio-machine:test-printer",
                        "from": "unknown",
                        "to": "ready",
                        "changed_at": "2026-09-10T00:00:00+00:00",
                    }],
                    "situations": [
                        {
                            "id": "system-health",
                            "label": "System health",
                            "state": "healthy",
                            "confidence": 1.0,
                            "rule": "all observed services are running",
                            "evidence": ["service:homeassistant"],
                            "why": ["homeassistant is running"],
                        }
                    ],
                    "boundaries": [
                        "World state is read-only and does not create, approve, or dispatch directives."
                    ],
                },
                "boundaries": [
                    "Analyst candidates are not commitments.",
                    "Capacity fit is not a scheduled calendar event.",
                ],
            }
        )
        self.assertIn("Analyst candidates are not commitments", dashboard)
        self.assertIn("Capacity fit is not a scheduled calendar event", dashboard)
        self.assertIn("## World situations", dashboard)
        self.assertIn("## Studio capabilities", dashboard)
        self.assertIn("## Studio Machines", dashboard)
        self.assertIn("Test Printer", dashboard)
        self.assertIn("../machine-docs/personal-machines/test-printer/", dashboard)
        self.assertIn("unknown → ready", dashboard)
        self.assertIn("Why?", dashboard)


if __name__ == "__main__":
    unittest.main()
