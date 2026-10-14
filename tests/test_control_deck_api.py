import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.control_deck.api import ControlDeckData, build_server


SCHEMA = ROOT / "coordination" / "world-state.schema.json"
FIXTURE = ROOT / "tests" / "fixtures" / "control-deck" / "world-state.json"


def valid_state() -> dict:
    state = json.loads(FIXTURE.read_text(encoding="utf-8"))
    state["generated_at"] = "2026-10-13T12:00:00+00:00"
    state["observations"] = [
        {
            "id": "observation:safe",
            "source": {
                "kind": "fixture",
                "name": "safe-source",
                "domain": "studio",
                "semantic": "health",
                "state_kind": "state",
            },
            "observed_at": "2026-10-13T12:00:00+00:00",
            "freshness": {"status": "fresh", "age_seconds": 0, "limit_seconds": 60},
            "sensitivity": "public",
            "confidence": 1.0,
            "value": {"secret": "must-not-leak"},
        }
    ]
    state["machines"][0]["docs_ref"] = "/private/arbitrary/path.md"
    state["machines"][0]["evidence"] = ["observation:safe"]
    return state


class ControlDeckDataTests(unittest.TestCase):
    def make_data(self, source: Path, now: str = "2026-10-13T12:30:00+00:00") -> ControlDeckData:
        return ControlDeckData(
            source_path=source,
            schema_path=SCHEMA,
            fallback_path=FIXTURE,
            stale_after_seconds=3600,
            now=lambda: datetime.fromisoformat(now),
        )

    def test_valid_world_state_is_validated_and_sanitized(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "world-state.json"
            source.write_text(json.dumps(valid_state()), encoding="utf-8")
            data = self.make_data(source)

            world = data.world_state()

        self.assertEqual(world["source"]["mode"], "authoritative")
        self.assertEqual(world["source"]["freshness"], "current")
        self.assertNotIn("observations", world)
        self.assertNotIn("docs_ref", world["machines"][0])
        self.assertNotIn("secret", json.dumps(world))
        self.assertEqual(world["evidence_index"][0]["id"], "observation:safe")
        self.assertNotIn("value", world["evidence_index"][0])

    def test_private_evidence_metadata_is_not_exposed(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "world-state.json"
            state = valid_state()
            state["observations"][0]["sensitivity"] = "private"
            state["observations"][0]["source"]["name"] = "/private/arbitrary/path.json"
            source.write_text(json.dumps(state), encoding="utf-8")

            world = self.make_data(source).world_state()

        self.assertEqual(world["evidence_index"], [])
        self.assertNotIn("/private/arbitrary/path.json", json.dumps(world))

    def test_contract_extensions_are_not_exposed(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "world-state.json"
            state = valid_state()
            state["contract"]["credential"] = "must-not-leak"
            source.write_text(json.dumps(state), encoding="utf-8")

            world = self.make_data(source).world_state()

        self.assertEqual(set(world["contract"]), {"name", "schema_version", "authority"})
        self.assertNotIn("must-not-leak", json.dumps(world))

    def test_non_finite_numbers_use_fixture(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "world-state.json"
            state = valid_state()
            state["observations"][0]["confidence"] = float("nan")
            source.write_text(json.dumps(state), encoding="utf-8")

            world = self.make_data(source).world_state()

        self.assertEqual(world["source"]["mode"], "fixture")
        self.assertNotIn("NaN", json.dumps(world, allow_nan=False))

    def test_invalid_datetime_uses_fixture(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "world-state.json"
            state = valid_state()
            state["generated_at"] = "definitely-not-a-date"
            source.write_text(json.dumps(state), encoding="utf-8")

            world = self.make_data(source).world_state()

        self.assertEqual(world["source"]["mode"], "fixture")
        self.assertEqual(world["source"]["problem"], "invalid_source")

    def test_invalid_world_state_uses_sanitized_fixture(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "world-state.json"
            source.write_text('{"contract": {}}', encoding="utf-8")
            data = self.make_data(source)

            health = data.health()
            world = data.world_state()

        self.assertEqual(health["status"], "degraded")
        self.assertEqual(world["source"]["mode"], "fixture")
        self.assertEqual(world["opportunities"], [])
        self.assertNotIn(str(source), json.dumps(world))

    def test_missing_world_state_uses_fixture_with_explicit_unknowns(self):
        data = self.make_data(Path("/definitely/missing/world-state.json"))

        machines = data.machines()["items"]

        self.assertEqual(machines[0]["readiness"], "unavailable")
        self.assertEqual(machines[0]["freshness"], "unavailable")
        self.assertEqual(machines[0]["runtime"], "no telemetry")

    def test_stale_source_is_served_as_stale_not_offline(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "world-state.json"
            state = valid_state()
            state["generated_at"] = "2026-10-13T10:00:00+00:00"
            source.write_text(json.dumps(state), encoding="utf-8")
            data = self.make_data(source)

            world = data.world_state()

        self.assertEqual(world["source"]["mode"], "authoritative")
        self.assertEqual(world["source"]["freshness"], "stale")
        self.assertNotEqual(world["machines"][0]["lifecycle"], "offline")

    def test_empty_opportunity_set_is_explicit(self):
        data = self.make_data(Path("/definitely/missing/world-state.json"))
        response = data.opportunities()
        self.assertEqual(response, {"count": 0, "items": [], "source": response["source"]})


class ControlDeckHttpTests(unittest.TestCase):
    def test_server_rejects_non_loopback_bind(self):
        data = ControlDeckData(SCHEMA, SCHEMA, FIXTURE)
        with self.assertRaises(ValueError):
            build_server("0.0.0.0", 0, data)

    def test_required_routes_are_get_only(self):
        data = ControlDeckData(
            source_path=Path("/definitely/missing/world-state.json"),
            schema_path=SCHEMA,
            fallback_path=FIXTURE,
        )
        server = build_server("127.0.0.1", 0, data)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            for route in ("health", "world-state", "opportunities", "machines"):
                with urllib.request.urlopen(f"{base}/api/v1/{route}") as response:
                    payload = json.load(response)
                self.assertIsInstance(payload, dict)

            request = urllib.request.Request(f"{base}/api/v1/world-state", method="POST", data=b"{}")
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(request)
            self.assertEqual(error.exception.code, 405)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_unknown_api_route_is_not_spa_fallback(self):
        data = ControlDeckData(
            source_path=Path("/definitely/missing/world-state.json"),
            schema_path=SCHEMA,
            fallback_path=FIXTURE,
        )
        with tempfile.TemporaryDirectory() as temporary:
            static_dir = Path(temporary)
            (static_dir / "index.html").write_text("<main>control deck</main>", encoding="utf-8")
            server = build_server("127.0.0.1", 0, data, static_dir=static_dir)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with self.assertRaises(urllib.error.HTTPError) as error:
                    urllib.request.urlopen(
                        f"http://127.0.0.1:{server.server_port}/api/not-a-route"
                    )
                self.assertEqual(error.exception.code, 404)
                self.assertEqual(json.load(error.exception), {"error": "not_found"})
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
