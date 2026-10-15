"""Interactive, loopback-free Phase C0 simulation harness."""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .core import EvidenceProvider, FakeExecutor, PolicyError, SimulationService, TestIdentityProvider


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATABASE = ROOT / "coordination" / "state" / "phase-c0-simulation.sqlite3"
CREDENTIAL_ENV = "HOMEAUTO_C0_TEST_CREDENTIAL"


def _request(number: int, expected: str, desired: str, now: datetime) -> dict[str, str]:
    suffix = uuid.uuid4().hex
    return {
        "request_id": f"simulation-{number}-{suffix}",
        "action_id": "indicator.set",
        "target_id": "fixture:indicator-01",
        "desired_state": desired,
        "expected_prior_state": expected,
        "requested_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=2)).isoformat(),
        "idempotency_key": f"simulation-idem-{number}-{suffix}",
    }


def _observation(state: str, version: int, now: datetime) -> dict[str, object]:
    return {
        "evidence_id": "simulated-observation:indicator-01",
        "version": f"v{version}",
        "target_id": "fixture:indicator-01",
        "state": state,
        "observed_at": now.isoformat(),
        "fresh_until": (now + timedelta(seconds=30)).isoformat(),
        "source_mode": "simulated_authoritative",
        "contradictory": False,
    }


def demo(args: argparse.Namespace) -> int:
    credential = os.environ.get(CREDENTIAL_ENV)
    if not credential:
        raise PolicyError(f"set {CREDENTIAL_ENV} to an opaque test credential")
    clock = lambda: datetime.now(timezone.utc)
    initial = clock()
    observations = EvidenceProvider(_observation("off", 1, initial))
    service = SimulationService(
        args.database,
        TestIdentityProvider({credential: "phase-c0-test-operator"}),
        observations,
        FakeExecutor(args.behavior, args.delay_seconds),
        enabled=args.enable_simulation,
        kill_switch=args.kill_switch,
        now=clock,
    )

    receipts = []
    for number, (expected, desired) in enumerate((("off", "on"), ("on", "off")), start=1):
        now = clock()
        payload = _request(number, expected, desired, now)
        preview = service.preview(payload, credential)
        print(json.dumps({"preview": preview}, indent=2))
        token = service.approve(payload, credential)
        receipt = service.execute(payload, token, credential)
        receipts.append(receipt)
        print(json.dumps({"receipt": receipt}, indent=2))
        if receipt["outcome"] != "verified":
            print("Simulation stopped before reversal because the prior result was not verified.")
            return 2
        observations.set(_observation(desired, number + 1, clock()))

    print(json.dumps({"simulation": True, "completed": True, "receipts": len(receipts)}))
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase C0 simulated execution harness")
    parser.add_argument("command", choices=("demo",))
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--enable-simulation", action="store_true")
    parser.add_argument("--kill-switch", action="store_true")
    parser.add_argument("--behavior", choices=sorted(FakeExecutor.BEHAVIORS), default="success")
    parser.add_argument("--delay-seconds", type=float, default=0.0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        return demo(args)
    except (EOFError, KeyboardInterrupt, PolicyError) as error:
        print(f"rejected: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
