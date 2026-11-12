import importlib.machinery
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LAB_LOADER = importlib.machinery.SourceFileLoader("life_inbox_lab_console", str(ROOT / "scripts" / "lab-console"))
LAB_SPEC = importlib.util.spec_from_loader(LAB_LOADER.name, LAB_LOADER)
lab_console = importlib.util.module_from_spec(LAB_SPEC)
LAB_LOADER.exec_module(lab_console)
WORLD_SPEC = importlib.util.spec_from_file_location("life_inbox_world_state", ROOT / "scripts" / "world_state.py")
world_state = importlib.util.module_from_spec(WORLD_SPEC)
WORLD_SPEC.loader.exec_module(world_state)


FEED = {
    "contract": {
        "name": "life-inbox-homeauto-feed",
        "schema_version": "1.0.0",
        "authority": "human-approved personal actions",
        "prose_inference_allowed": False,
        "scheduling_authority": False,
        "execution_authority": False,
    },
    "generated_at": "2026-11-11T12:05:00-06:00",
    "actions": [{
        "action_id": "life-inbox:abc",
        "summary": "Replace the furnace filter",
        "captured_at": "2026-11-11T12:00:00-06:00",
        "deadline": None,
        "status": "approved",
    }],
}


class LifeInboxFeedTests(unittest.TestCase):
    def test_feed_is_validated_then_becomes_an_unavailable_personal_opportunity(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "homeauto-actions.json"
            path.write_text(json.dumps(FEED), encoding="utf-8")
            summary = lab_console.summarize_life_inbox(path)

        self.assertEqual("life-inbox:abc", summary["actions"][0]["action_id"])
        raw = {
            "contract": {"name": "homeauto-raw-telemetry", "schema_version": "1.0.0"},
            "collected_at": "2026-11-11T12:10:00-06:00",
            "sources": [{
                "source": {"kind": "coordination", "name": "operator-snapshot"},
                "observed_at": "2026-11-11T12:10:00-06:00",
                "freshness_seconds": 900,
                "sensitivity": "private",
                "confidence": 1.0,
                "payload": {"sources": {}, "benlab": None, "schedule": {"capacity": None}, "life_inbox": summary, "directives": [], "warnings": []},
            }],
            "errors": [],
        }
        state = world_state.interpret(raw, studio_registry={"schema_version": "1.0.0", "machines": []})
        opportunity = state["opportunities"][0]

        self.assertEqual("life-inbox:abc", opportunity["action_id"])
        self.assertEqual("insufficient_information", opportunity["state"])
        self.assertEqual("Life Inbox", opportunity["action"]["authority"])
        self.assertIsNone(opportunity["capacity"])
        self.assertIn("separate human authorization", opportunity["warnings"][0])

    def test_rejects_a_feed_that_claims_scheduling_authority(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "homeauto-actions.json"
            invalid = json.loads(json.dumps(FEED))
            invalid["contract"]["scheduling_authority"] = True
            path.write_text(json.dumps(invalid), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unsupported Life Inbox"):
                lab_console.summarize_life_inbox(path)


if __name__ == "__main__":
    unittest.main()
