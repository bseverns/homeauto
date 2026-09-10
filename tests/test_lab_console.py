import importlib.machinery
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOADER = importlib.machinery.SourceFileLoader(
    "lab_console", str(ROOT / "scripts" / "lab-console")
)
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
lab_console = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(lab_console)


class LabConsoleTests(unittest.TestCase):
    def test_dashboard_cells_escape_html_and_markdown_tables(self):
        self.assertEqual(lab_console.cell("<script>|private</script>"), "&lt;script&gt;\\|private&lt;/script&gt;")

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
