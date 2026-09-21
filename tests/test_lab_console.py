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
    def test_benlab_1_2_contract_is_validated_and_preserves_authoritative_action_id(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "benlab-actions.json"
            payload = {
                "generated_at": "2026-09-20T00:00:00+00:00",
                "contract": {
                    "name": "benlab-actions", "schema_version": "1.2.0",
                    "action_identity_field": "action_id", "calendar_data": False,
                    "prose_inference_allowed": False,
                },
                "queues": {"now": ["one"], "next": [], "sleeping": [], "background": []},
                "actions": [{
                    "action_id": "benlab-action:0123456789abcdef:1",
                    "path": "vault/one.md", "project": "one", "status": "active",
                    "attention": "now", "attention_state": "now",
                    "next_action": "Do one thing",
                }],
                "sleeping": [],
            }
            path.write_text(json.dumps(payload))

            summary = lab_console.summarize_benlab(path)

            self.assertEqual(summary["contract"]["schema_version"], "1.2.0")
            self.assertEqual(summary["actions"][0]["action_id"], "benlab-action:0123456789abcdef:1")

            payload["actions"][0]["action_id"] = None
            path.write_text(json.dumps(payload))
            with self.assertRaisesRegex(ValueError, "does not conform to schema 1.2.0"):
                lab_console.summarize_benlab(path)

    def test_benlab_contract_is_versioned_and_preserves_action_semantics(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "benlab-actions.json"
            payload = {
                "contract": {
                    "name": "benlab-actions", "schema_version": "1.1.0",
                    "authority": "human-authored project attention metadata",
                    "prose_inference_allowed": False,
                },
                "generated_at": "2026-09-20T00:00:00+00:00",
                "actions": [{
                    "action_id": "benlab:one", "path": "vault/one.md", "project": "one",
                    "attention_state": "now", "attention_reason": "human activation",
                    "current_commitment": True, "may_request_time_now": True,
                    "next_action": "Do one thing", "next_action_effort": "30m",
                    "energy_fit": "screen-only", "next_action_stack": ["terminal", "repo"],
                    "next_action_route": "repo_issue", "evidence_status": "missing",
                    "evidence_blocker": True, "proof_mode": "source-repo proof",
                    "public_safe": True, "ready_for": ["review"], "status": "active",
                }],
                "queues": {"now": ["one"], "next": [], "background": []},
                "sleeping": [],
            }
            path.write_text(json.dumps(payload))

            summary = lab_console.summarize_benlab(path)

            action = summary["actions"][0]
            self.assertEqual(action["action_id"], "benlab:one")
            self.assertEqual(action["queue_position"], 1)
            self.assertEqual(action["evidence"]["status"], "missing")
            self.assertEqual(action["human_activation_reason"], "human activation")
            self.assertEqual(summary["artifact_sha256"], lab_console.sha256_file(path))

            payload["contract"]["schema_version"] = "9.0.0"
            path.write_text(json.dumps(payload))
            with self.assertRaisesRegex(ValueError, "unsupported BenLab action contract"):
                lab_console.summarize_benlab(path)

    def test_schedule_capacity_json_is_consumed_without_scheduling_authority(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "schedule_capacity.json"
            path.write_text(json.dumps({
                "contract": {
                    "name": "schedule-capacity", "schema_version": "1.0.0",
                    "authority": "read_only_capacity_evidence", "scheduling_authority": False,
                    "calendar_mutation_allowed": False, "prose_inference_allowed": False,
                    "generated_at": "2026-09-20T00:00:00+00:00",
                },
                "inputs": {"benlab_contract_name": "benlab-actions", "benlab_schema_version": "1.2.0", "benlab_artifact_sha256": "a" * 64},
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
            self.assertEqual(summary["results"][1]["fit_status"], "capacity_unknown")
            self.assertEqual(summary["inputs"]["benlab_artifact_sha256"], "a" * 64)
            self.assertEqual(summary["contract"]["generated_at"], "2026-09-20T00:00:00+00:00")
            self.assertEqual(summary["artifact_sha256"], lab_console.sha256_file(path))

    def test_benlab_actions_are_normalized_in_authoritative_queue_order(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "benlab-actions.json"
            path.write_text(json.dumps({
                "contract": {"name": "benlab-actions", "schema_version": "1.1.0", "authority": "human-authored project attention metadata", "prose_inference_allowed": False},
                "generated_at": "2026-09-20T00:00:00+00:00",
                "actions": [
                    {"project": "second", "path": "second.md", "attention_state": "next"},
                    {"project": "first", "path": "first.md", "attention_state": "now"},
                ],
                "queues": {"now": ["first"], "next": ["second"], "background": []},
                "sleeping": [],
            }))

            summary = lab_console.summarize_benlab(path)

        self.assertEqual([item["project"] for item in summary["actions"]], ["first", "second"])
        self.assertEqual([item["queue_position"] for item in summary["actions"]], [1, 1])

    def test_snapshot_rejects_schedule_bound_to_another_benlab_artifact(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            benlab_path = root / "benlab.json"
            benlab_path.write_text(json.dumps({
                "contract": {"name": "benlab-actions", "schema_version": "1.1.0", "authority": "human-authored project attention metadata", "prose_inference_allowed": False},
                "generated_at": "2026-09-20T00:00:00+00:00", "actions": [],
                "queues": {"now": [], "next": [], "background": []}, "sleeping": [],
            }))
            schedule_path = root / "schedule.json"
            schedule_path.write_text(json.dumps({
                "contract": {"name": "schedule-capacity", "schema_version": "1.0.0", "authority": "read_only_capacity_evidence", "scheduling_authority": False, "calendar_mutation_allowed": False, "prose_inference_allowed": False, "generated_at": "2026-09-20T00:00:00+00:00"},
                "inputs": {"benlab_contract_name": "benlab-actions", "benlab_schema_version": "1.1.0", "benlab_artifact_sha256": "b" * 64},
                "freshness": {"status": "fresh", "warnings": []}, "results": [],
            }))
            config = root / "sources.json"
            config.write_text(json.dumps({"sources": {
                "benlab_actions": {"path": str(benlab_path)},
                "schedule_capacity": {"path": str(schedule_path)},
            }}))

            snapshot = lab_console.build_snapshot(config)

        self.assertIsNone(snapshot["schedule"]["capacity"])
        self.assertTrue(any("does not match loaded BenLab artifact" in item for item in snapshot["warnings"]))

    def test_schedule_capacity_json_rejects_authority_or_freshness_violation(self):
        base = {
            "contract": {"name": "schedule-capacity", "schema_version": "1.0.0", "authority": "read_only_capacity_evidence", "scheduling_authority": False, "calendar_mutation_allowed": False, "prose_inference_allowed": False, "generated_at": "2026-09-20T00:00:00+00:00"},
            "inputs": {"benlab_contract_name": "benlab-actions", "benlab_schema_version": "1.1.0", "benlab_artifact_sha256": "a" * 64},
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
            base["contract"]["calendar_mutation_allowed"] = False
            base["inputs"]["benlab_artifact_sha256"] = "not-a-sha256"
            path.write_text(json.dumps(base))
            with self.assertRaisesRegex(ValueError, "invalid schedule capacity input"):
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
        self.assertIn("## Intentional routines", dashboard)
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

    def test_dashboard_leads_with_deterministic_opportunities_and_demotes_research(self):
        dashboard = lab_console.render_dashboard({
            "generated_at": "2026-09-20T00:00:00+00:00",
            "sources": {}, "benlab": None,
            "analyst": {"candidate_count": 1, "recommendation_counts": {}, "recent_candidates": []},
            "schedule": {"capacity": None, "freshness": None},
            "directives": [], "routine_receipts": [], "warnings": [], "boundaries": [],
            "world_state": {
                "opportunities": [
                    {
                        "opportunity_id": "opportunity:a", "action_id": "a", "state": "available",
                        "action": {"project": "Available project", "next_action": "Make proof", "effort": "30m", "energy_fit": "screen-only"},
                        "capacity": {"capacity_start": "10:00", "capacity_end": "10:30"},
                        "affordances": {"required": ["terminal"], "available": ["terminal"], "missing": []},
                        "why": [{"detail": "BenLab permits the action."}, {"detail": "Fresh terminal evidence exists."}],
                    },
                    {
                        "opportunity_id": "opportunity:b", "action_id": "b", "state": "missing_affordance",
                        "action": {"project": "Blocked project", "next_action": "Use bench"},
                        "capacity": None,
                        "affordances": {"required": ["bench"], "available": [], "missing": ["bench"]},
                        "why": [{"detail": "No fresh bench provider."}],
                    },
                ],
                "transitions": [{"situation_id": "opportunity:a", "from": "runtime_stale", "to": "available", "changed_at": "2026-09-20T00:00:00+00:00", "cause": "Fresh terminal evidence exists."}],
                "situations": [], "machines": [], "capabilities": [], "boundaries": [],
            },
        })

        headings = [
            dashboard.index("## Available now"),
            dashboard.index("## Recently changed"),
            dashboard.index("## Blocked / missing affordances"),
            dashboard.index("## Stale or uncertain evidence"),
            dashboard.index("## Intentional routines"),
            dashboard.index("## Research"),
        ]
        self.assertEqual(headings, sorted(headings))
        self.assertIn("Available project", dashboard)
        self.assertIn("Fresh terminal evidence exists", dashboard)
        self.assertIn("Blocked project", dashboard)
        self.assertIn("No action has been scheduled or dispatched", dashboard)

    def test_routine_receipt_can_bind_context_without_claiming_semantic_completion(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adapter = root / "adapter"
            adapter.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            adapter.chmod(0o755)
            registry = root / "routines.json"
            registry.write_text(json.dumps({"routines": [{
                "id": "sample", "label": "Sample", "description": "Test", "target": "test",
                "adapter": str(adapter), "cwd": ".", "command": ["ignored"], "read_only": True,
                "requires_confirmation": False, "expected_output": "text", "duration": "brief", "interaction": "none",
            }]}))

            receipt = lab_console.run_routine(
                "sample", registry, root / "receipts", refresh_world_state=False,
                action_id="benlab-action:0123456789abcdef:1",
                opportunity_id="opportunity:benlab-action:0123456789abcdef:1",
            )

        self.assertEqual(receipt["action_id"], "benlab-action:0123456789abcdef:1")
        self.assertEqual(
            receipt["opportunity_id"], "opportunity:benlab-action:0123456789abcdef:1"
        )
        self.assertFalse(receipt["canonical_source_changed"])
        self.assertFalse(receipt["semantic_completion"])


if __name__ == "__main__":
    unittest.main()
