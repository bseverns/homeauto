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
