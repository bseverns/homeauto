# Turing Pi 2 compose slices (modular + mean)

These files are **role slices** — small, composable chunks you can run on any node.
Run only what you need; scale out when the hardware shows up.

## Layout

```
infra/turingpi2/
  compose/
    core.yml        # CORE services (HA + MQTT + Node-RED + proxy)
    audio.yml       # Snapserver + Mopidy + librespot + vinyl ingest
    assistant.yml   # LLM + RAG stack
  data/             # bind-mounts live here (created on demand)
```

## How to run (from repo root)

### CORE

```bash
docker compose -f infra/turingpi2/compose/core.yml up -d
```

### Audio slice

```bash
docker compose -f infra/turingpi2/compose/audio.yml up -d
```

### Assistant slice

```bash
docker compose -f infra/turingpi2/compose/assistant.yml up -d
# one-shot ingest run
# docker compose -f infra/turingpi2/compose/assistant.yml run --rm assistant-ingest
```

## Combine slices

Docker Compose accepts multiple `-f` flags. Keep CORE on the CORE host, then add slices
as needed:

```bash
docker compose \
  -f infra/turingpi2/compose/core.yml \
  -f infra/turingpi2/compose/audio.yml \
  up -d
```

## Environment notes

- Use `.env` at repo root. This keeps env shared across slices.
- `CORE_*` is the new naming; `ORIN_*` still works as a compatibility fallback.
- For audio, the FIFO defaults live under `infra/turingpi2/data/snapcast/fifo/` unless
  you point `MOPIDY_FIFO` or `LIBRESPOT_FIFO` somewhere else.

## Intent (teach the future)

This is a **role-first** deployment. Hardware is interchangeable; roles are not.
Keep CORE boring. Let experiments explode on their own node.
