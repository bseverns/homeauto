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
Each observation records its source, observation time, freshness, sensitivity, and
confidence. Every situation links to observation IDs and displays its fixed rule under
**Why?**. Stale activity is `UNCERTAIN`, absent evidence is `UNKNOWN`, and evidence
opportunities require a declared world affordance, a BenLab-owned evidence need, and
current schedule capacity.

Host and Docker Compose state are collected locally. Set `HA_URL` and `HA_TOKEN` to
enable the read-only Home Assistant `GET /api/states` collector. Set `MQTT_HOST`
(and optionally `MQTT_TOPIC`) to sample MQTT with `mosquitto_sub`; it never publishes.
Collector failures are recorded in raw `errors` and do not trigger control actions.

The structured state may be ingested by the local assistant only downstream. Neither
the collector nor the rule layer creates, confirms, dispatches, or executes a
directive; confirmation authority remains human.
