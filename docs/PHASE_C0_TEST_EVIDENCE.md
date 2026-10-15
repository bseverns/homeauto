# Phase C0 test evidence

## Expected RED — 2026-10-14

Command:

```bash
python3 -m unittest tests.test_simulated_execution -v
```

Result: exit 1. The new test module failed to import because `services.simulated_execution` did not yet exist:

```text
ModuleNotFoundError: No module named 'services.simulated_execution'
Ran 1 test in 0.000s
FAILED (errors=1)
```

This failure was captured before implementation.

## Candidate verification — 2026-10-15

### Repository snapshot

The candidate was built on the following repository commits. Supporting repositories were clean when their checks were run.

| Repository | Branch | Commit |
|---|---|---|
| homeauto | `phase-c0-simulated-execution` | `fd0d9d93b8e7559cfb725167575b841f44622ffe` |
| BenLab | `main` | `6a6aaf3c869020bab75146394a5f3c40cfd41f70` |
| schedule-assessment | `main` | `377f6a1799940ecc6c2a45b45a3482ca2ef8ea23` |
| machine-docs | `main` | `4748fbe4699cbc6961b1b5b959781d4d2f0b18d2` |
| systems-atlas | `main` | `ba9f78d042002de6a5db5009303cec442fe9250b` |
| studio-compute | `main` | `4754bd70c40aef6ca50d234462fa8abe58883e47` |

The `homeauto` candidate spans 13 intended Phase C0 paths: three schemas, two documents, three dependency files, the simulated-execution package, its harness, and two test modules. No untracked file is part of the candidate.

### homeauto verification

```bash
env -u VIRTUAL_ENV uv run --isolated --with-requirements requirements-dev.txt \
  python -m unittest discover -s tests -v
```

Result: exit 0; **108 tests passed**. The focused Phase C0 module passed **28 tests**.

The Phase C0 cases cover successful verified simulation, authenticated identity, strict request validation, stale/missing/fallback/contradictory evidence, expiration, approval replay, changed evidence binding, idempotency conflict, target concurrency, executor rejection, timeout, missing and contradictory readback, crash recovery, audit-storage failure, disabled and kill-switch behavior, append-only audit events, receipt-schema validation, default-deny harness behavior, confirmed inverse action, and absence of a Control Deck execution route.

Security-review regressions additionally prove that no preview confirmation capability is returned to a caller; ordinary Python input is not used; macOS LocalAuthentication is the only unmocked approval boundary and fails closed when unavailable, denied, or timed out; approval consumes the confirmed preview once; an unauthenticated attempt cannot consume another operator's approval; policy, kill-switch, credential-revocation, and evidence-version changes serialize through dispatch; recovery cannot relabel live execution; alternate or subclassed executors are rejected; delayed fake execution cannot bypass the configured timeout; replay tombstones survive receipt pruning; and expired pending approvals become terminal and bounded.

```bash
cd services/control_deck/web
npm test
npx tsc --noEmit
npm run build
npm audit --audit-level=low
```

Result: all commands exited 0; **4 frontend tests passed**, TypeScript passed, the production build completed, and npm reported **0 vulnerabilities**.

```bash
uvx --from 'pip-audit>=2,<3' pip-audit --requirement requirements-dev.lock
```

Result: exit 0; `No known vulnerabilities found`.

A Draft 2020-12 meta-schema check accepted all **8** coordination schemas. Python `compileall` passed. `git diff HEAD --check` passed. An AST import check found no network, HTTP, MQTT, shell, subprocess, or socket adapter import in `services/simulated_execution`. A Linux-targeted `uv pip install --dry-run --require-hashes` accepted the universal lock while excluding all Darwin-only PyObjC packages.

A native dependency probe imported `LocalAuthentication`, created `LAContext`, and confirmed that `LAPolicyDeviceOwnerAuthentication` is available on this host. Automated tests mock the OS callback and never claim that a mock proves human presence. A final foreground demonstration requires the operator—not this test process—to satisfy the OS-owned Touch ID/account-authentication prompt.

### Independent review history

- `deleg_e22a0467` found that reusable credentials could authorize directly and that failed anonymous execution could consume another operator's approval. Both paths received focused regressions and root-cause fixes.
- `deleg_609dc76a` found that caller-controlled preview confirmation remained programmatically satisfiable and that arbitrary executor injection had to stay closed. Confirmation moved into the service, the executor boundary was restricted to the exact built-in `FakeExecutor`, and regressions were added.
- `deleg_1b3197fc` was blocked by the provider safety filter and produced no technical verdict.
- `deleg_805d7053` reviewed the post-remediation candidate and reproduced two blockers: `/dev/tty` opened as `r+` could not operate on a real terminal, and any repaired text-on-PTY scheme would still let the PTY owner self-confirm. The text/TTY mechanism was deleted and replaced with OS-owned macOS LocalAuthentication. Its snapshot-change finding was also accepted; the candidate must be frozen and reviewed again before commit.
- `deleg_0488b3aa` ran two independent read-only reviews. The specification reviewer found no unmet requirement. The adversarial reviewer reproduced evidence-change and credential-revocation races and identified missing Darwin markers in the then-current lock. The service now holds the identity and evidence locks through dispatch, deterministic race regressions were added, and the lock was regenerated as universal with explicit Darwin markers. A resulting target-concurrency regression was reproduced and fixed by acquiring the nonblocking operation lock before policy validation.

This document does not claim final independent clearance until the stable post-remediation fingerprint is reviewed.

### Read-only authority repositories

All supporting repositories remained clean after their documented checks:

- BenLab: `arch -arm64 /usr/bin/make test` — exit 0; **141 tests passed** across 23 scripts.
- schedule-assessment: `python3 -m unittest discover -s tests -v` — exit 0; **22 tests passed**.
- machine-docs: `python3 -m unittest discover -s tests -v` — exit 0; **5 tests passed**.
- systems-atlas: `npm test` — exit 0; **34 Ruby tests / 136 assertions passed**, and diagram checks/rendering completed.
- studio-compute: `./scripts/check.sh` — exit 0; **8 Python tests passed**, preview sync passed, and every Mermaid source rendered.

No CI workflow was changed. No live endpoint, physical device, production credential, deployment, push, or merge was used.
