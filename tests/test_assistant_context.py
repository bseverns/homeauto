import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "assistant_context", ROOT / "services" / "assistant" / "api" / "context.py"
)
assistant_context = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(assistant_context)


class AssistantContextTests(unittest.TestCase):
    def test_current_state_context_is_deterministic_and_excludes_raw_observations(self):
        state = {
            "contract": {"name": "homeauto-world-state", "schema_version": "1.1.0"},
            "generated_at": "2026-09-20T00:00:00+00:00",
            "opportunity_contract": {"name": "lab-opportunities", "schema_version": "1.0.0"},
            "inputs": {"benlab": {}, "schedule": {}, "world_state": {}},
            "opportunities": [{
                "opportunity_id": "opportunity:a", "state": "available",
                "action": {"project": "A", "next_action": "Do A"},
                "why": [{"detail": "Explicit deterministic reason"}],
            }],
            "machines": [{"id": "studio-machine:a", "readiness": "ready"}],
            "capabilities": [{"capability": "terminal", "state": "ready"}],
            "transitions": [{"situation_id": "opportunity:a", "from": "blocked", "to": "available"}],
            "boundaries": ["No control actions."],
            "observations": [{"sensitivity": "private", "value": {"secret": "must-not-leak"}}],
            "situations": [{"why": ["redundant projection"]}],
        }
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "world-state.json"
            path.write_text(json.dumps(state), encoding="utf-8")
            chunk = assistant_context.load_current_state(path)

        serialized = chunk["payload"]["text"]
        self.assertIn("Explicit deterministic reason", serialized)
        self.assertNotIn("must-not-leak", serialized)
        self.assertNotIn("observations", serialized)
        self.assertEqual(chunk["payload"]["source"], "homeauto-world-state:current")

    def test_vector_context_excludes_coordination_files_that_can_be_stale_or_private(self):
        chunks = [
            {"payload": {"source": "/data/coordination/state/world-state.json", "text": "old state"}},
            {"payload": {"source": "/data/docs/operator.md", "text": "operator docs"}},
        ]
        self.assertEqual(
            assistant_context.filter_retrieval_chunks(chunks),
            [chunks[1]],
        )


if __name__ == "__main__":
    unittest.main()
