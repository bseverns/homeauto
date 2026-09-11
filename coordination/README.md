# Lab coordination console

This directory makes `homeauto` a local operator surface for three neighboring
systems without replacing any of them:

```text
benlab-local-analyst -- candidates --> BenLab -- commitments --> schedule-assessment
          \________________________ read-only reports _______________________/
                                      |
                               homeauto console
                                      |
                           human-reviewed directives
```

## Authority boundaries

- **benlab-local-analyst** discovers and proposes. Its promotions remain candidates.
- **BenLab** owns significance, attention, and project commitments.
- **schedule-assessment** owns read-only capacity and freshness assessment. A fit is
  not a scheduled event.
- **homeauto** gathers summaries and records your explicit directives. It does not
  silently promote research, reprioritize BenLab, or mutate a calendar.

## Refresh the console

The default sibling paths live in [`sources.json`](./sources.json). From the repo
root, run:

```bash
make coordination-refresh
make coordination-status
```

This writes two ignored, local artifacts under `coordination/state/`:

- `dashboard.md`: a human-readable view of current attention, capacity fit, recent
  Analyst candidates, freshness warnings, and open directives.
- `snapshot.json`: the same information in a compact machine-readable contract.

The snapshot intentionally omits Analyst source paths and evidence bodies. It keeps
only the identifiers and short routing fields needed for orientation.

## Dictate an action

Create a draft directive:

```bash
python3 scripts/lab-console new-directive schedule-assessment \
  "Reassess capacity after the next calendar refresh" \
  --type assess_capacity \
  --source "benlab-actions:homeauto" \
  --constraint "Do not create calendar events"
```

Directives are JSON files in `coordination/directives/`. They are suitable for code
review and eventual adapters. New directives always require confirmation and do
nothing by themselves.

## Ask the local assistant

The assistant ingest services mount `/data/coordination`, so after a refresh and
ingest you can ask questions such as:

```bash
docker compose --profile assistant run --rm assistant-ingest
./scripts/ask "What is active now, what fits current capacity, and which reports are stale?"
```

Only the distilled console artifacts and directives are added through this path;
the assistant does not crawl the three neighboring repositories.

## Read-only world state

`make coordination-refresh` now writes two additional ignored artifacts:

- `coordination/state/world-telemetry.json` is the raw collector envelope.
- `coordination/state/world-state.json` contains normalized observations and the
  deterministic situations shown in `dashboard.md`.

The contracts are [`raw-telemetry.schema.json`](./raw-telemetry.schema.json) and
[`world-state.schema.json`](./world-state.schema.json); tests validate both with
`jsonschema` from `requirements-dev.txt`. Source meaning, freshness, sensitivity,
retained-state versus event semantics, Home Assistant field allowlists, and physical
world affordances are declared in [`world-sources.json`](./world-sources.json).
Unlisted Home Assistant entities are discarded before the raw artifact is written.

[`studio-machines.json`](./studio-machines.json) is the deliberately small membership
list for machines shown in the control deck; its contract is
[`studio-machines.schema.json`](./studio-machines.schema.json). Entries retain stable
pointers into the sibling `machine-docs` repository but never parse or copy those
documents at runtime. `machine-docs` remains authoritative for identity, installed
configuration, maintenance, safety, and project maturity. `homeauto` owns runtime
observations, deterministic readiness, scoped affordances, transitions, and display.

Registered machines remain visible without telemetry. Missing telemetry is reported as
`no telemetry`/`unavailable`, distinct from a fresh explicit `offline` observation.
Only an `operational` machine with fresh ready-state telemetry and
`contributes_affordances: true` can expose its declared capabilities as current
affordances. Project, research, commissioning, stale, and unknown machines cannot
masquerade as ready production resources. Capability summaries are derived from the
machine rows and retain machine IDs as evidence. Machine readiness changes share the
existing 100-entry bounded transition history; raw telemetry changes are not recorded.

## Operator routines

`routines.json` owns stable launcher IDs and declarative invocation metadata; called
scripts remain owned by BenLab, benlab-local-analyst, schedule-assessment, the
assistant, or homeauto. JSON reuses the existing coordination-registry parser and
avoids a new YAML runtime dependency. The adapter passes an argv list directly
without a shell, so user input remains one argument rather than executable syntax.

```sh
scripts/lab-console routines
scripts/lab-console run daily
scripts/lab-console run weekly
scripts/lab-console run monthly
scripts/lab-console run refresh
scripts/lab-console run benlab-refresh
scripts/lab-console run capacity
scripts/lab-console run analyst-scan --input /path/to/material --yes
scripts/lab-console run latest
scripts/lab-console open dashboard
scripts/lab-console open benlab
scripts/lab-console open analyst
scripts/lab-console open capacity
scripts/lab-console ask "What became possible today?"
```

Each invocation writes a receipt and, for non-guided output, a text artifact under
the ignored `coordination/state/` tree. Completed routines trigger the existing
coordination refresh; the dashboard includes the four cadence shortcuts, recent
receipts, and clickable local links to the three source-owned detail artifacts.
`open` uses the native macOS viewer and never executes source content. `read_only`
means the routine does not mutate source material or dispatch
control actions; derived reports, receipts, and refreshed state may still be written.
Daily and weekly are non-read-only because the existing guided BenLab script writes
canonical practice notes.

Each observation records its source, observation time, freshness, sensitivity, and
confidence. Every situation links to observation IDs and displays its fixed rule under
**Why?**. Health is `DEGRADED` from fresh bad evidence, `HEALTHY` from fresh all-good
evidence, `UNCERTAIN` from stale evidence, and `UNKNOWN` without evidence. BenLab
`now` items remain neutral `active_needs`; only explicitly typed evidence needs create
an evidence opportunity. Required affordances may compose across resources only when
all resources declare the same `affordance_scope`, and every contributor remains in the
evidence trail. The state carries at most 100 situation transitions for compact change
history.

Host and Docker Compose state are collected locally. Set `HA_URL` and `HA_TOKEN` to
enable the read-only Home Assistant `GET /api/states` collector. Set `MQTT_HOST`
(and optionally `MQTT_TOPIC`) to sample MQTT with `mosquitto_sub`; it never publishes.
Collector failures are recorded in raw `errors` and do not trigger control actions.

The structured state may be ingested by the local assistant only downstream. Neither
the collector nor the rule layer creates, confirms, dispatches, or executes a
directive; confirmation authority remains human.
