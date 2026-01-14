# Turing Pi 2 Base Station (role-based stack)

You’re not deploying “an Orin.” You’re deploying **roles**. Hardware is just the stage.

This doc shows how to run the stack on a **Turing Pi 2** either as a **single-node base station** or as a **split-node cluster** where heavy stuff moves off CORE.

## Roles, plain-English

- **CORE** — the conductor. Home Assistant, MQTT, Node-RED, DNS, reverse proxy, Snapserver.
- **HISTORY** — long-term storage and analytics (databases, camera archives, time-series).
- **VISION** — video + ML compute (Frigate, detectors).
- **EXPERIMENTS** — optional labs: LLMs, RAG, weird automations, that one script you’ll forget you wrote.

Keep CORE stable; everything else is allowed to be spicy.

---

## Option A: single-node “simple” mode (all on CORE)

If you just want it to work, start here.

**What you run:** `infra/turingpi2/compose/core.yml` + optional audio + assistant slices.

```bash
# From repo root
cp .env.example .env
# Fill in CORE_* (or keep ORIN_* if you're not migrating yet)

make up-core
make up-audio   # optional: audio stack on the same host
make up-assistant  # optional: local LLM/RAG stack
```

You now have a CORE node that can carry everything by itself. This is the “baby but bulletproof” mode.

---

## Option B: split-node mode (CORE + workers)

The Turing Pi 2 shines when you offload heavy work to other nodes. The rule: **CORE stays in charge**, the rest can get weird.

**Example split:**

- **CORE** (Node 1): HA, MQTT, Node-RED, DNS, reverse proxy, Snapserver.
- **EXPERIMENTS** (Node 2): LLM/RAG assistant slice.
- **VISION** (Node 3): Frigate or camera ML.
- **HISTORY** (Node 4): databases + backups.

The only requirement is that every role can reach CORE on the LAN.

### Networking expectations

- Give every node **a static IP or DHCP reservation**.
- Set hostnames that match roles: `core`, `history`, `vision`, `experiments`.
- Example in `.env`:

```dotenv
CORE_HOSTNAME=tp2-core
CORE_IP=192.168.50.60
AUDIO_HOST=tp2-audio
AUDIO_IP=192.168.50.61
ASSISTANT_HOST=tp2-experiments
ASSISTANT_API_URL=http://192.168.50.62:7070
```

### Bring-up checklist (split mode)

1. **CORE node**:
   - `make up-core`
   - Optional: `make up-audio` if audio stays on CORE.
2. **Assistant node**:
   - Copy `.env` (or minimal vars) to that node.
   - Run `make up-assistant` from the repo clone there.
3. **VISION + HISTORY nodes**:
   - Not in this repo yet; treat them as future slices or external services.
4. **Verify**:
   - `curl http://$CORE_IP:8123` (Home Assistant)
   - `mosquitto_sub -h $CORE_IP -t '#' -v` (MQTT)
   - `curl http://$ASSISTANT_API_URL/health` (assistant API)

---

## Role-based conventions in this repo

- **CORE is the new name for ORIN.** All new docs use CORE terminology.
- Backwards compatibility remains: `ORIN_*` vars still work as fallback.
- Compose slices under `infra/turingpi2/compose/` are **modular** — run only what you need.

---

## TL;DR (if you only read one block)

```bash
cp .env.example .env
# Fill CORE_HOSTNAME + CORE_IP (or leave ORIN_* for now)

make up-core
# Optional extras
make up-audio
make up-assistant
```

You now have a role-based base station. Swap the silicon later without changing your mental model.
