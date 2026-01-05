# Field Card — Jetson Orin Home/Studio Core

## Purpose
Keep the Jetson Orin stack as the loud, reliable conductor for DNS, automation, and audio routing.
Give you a fast, punk-rock map from “fresh box” to “the house is talking.”

## Quickstart (3 steps max)
1. `cp .env.example .env` → fill ORIN_IP + DNS + FIFO paths.
2. `./scripts/bootstrap-volumes.sh` → create bind mounts + named pipes.
3. `docker compose up -d` → light the stack.

## Day‑1 baseline health check (make sure the heart beats)
Run these right after you boot the stack. If these fail, stop and fix before you build fancy on top.

- `docker compose ps` → confirms the containers are actually up, not just “started once.”
- `curl -s http://$ORIN_IP:8123` → Home Assistant should answer (even a login page is a win).
- `curl -s http://$ORIN_IP:1780` → Snapweb should respond; if not, Snapserver is asleep.
- `dig @${ORIN_IP} example.com` → DNS sanity check (Pi-hole + Unbound working together).

## Primary endpoints/ports

| Endpoint | Port | Protocol | Notes |
|---|---|---|---|
| Home Assistant | 8123 | HTTP | Core UI + API control surface. |
| Node-RED | 1880 | HTTP | Flow editor + integrations glue. |
| MQTT (Mosquitto) | 1883 | TCP | Event bus for automations. |
| MQTT (WebSockets) | 9001 | WS | Browser-friendly MQTT. |
| Snapweb | 1780 | HTTP | Snapcast group/stream routing UI. |
| Snapserver stream | 1704 | TCP | Snapcast audio stream ingress. |
| Pi-hole admin | 80 | HTTP | `http://$ORIN_IP/admin`. |
| Unbound | 5335 | TCP/UDP | DNS upstream for Pi-hole. |
| OctoFarm | 4000 | HTTP | Printer fleet dashboard (points at the Mac Mini A1347 printer host). |
| Portainer | 9000 / 9443 | HTTP/HTTPS | Container UI. |

## Topology in 6 lines (text mode for field ops)
- **ORIN** = the conductor (DNS + automation + audio brain).
- **MAC‑MINI A1347** = main printer host (OctoPrint + USB lifeline).
- **OctoFarm** lives on ORIN, points at the Mac Mini + any OctoPi/Klipper nodes.
- **OctoPi/Klipper** = printer‑specific edges (only where needed).
- **Snapclients** = per‑room audio endpoints.
- **Router** hands out ORIN as DNS so everything resolves locally.

## Printer host reality check (aka: where the plastic actually melts)
The **Mac Mini A1347** is the main printer server now. That means:
- **OctoPrint lives on the Mac Mini**, not on a Jetson edge.
- **OctoFarm on ORIN talks to the Mac Mini** (and any OctoPi/Klipper sidecars).
- If prints stall, start troubleshooting on the Mac Mini first — it’s the heartbeat for the printer fleet.

This isn’t a theoretical diagram thing; it’s the real wiring. Keep it honest so future-you doesn’t spelunk in the wrong box at 2 a.m.

## Printer field kit — bootstrapping OctoFarm + OctoPrint like you mean it
This is the practical, punchy starter kit to get the **Mac Mini A1347 + OctoFarm + OctoPrint** workflow alive.
Treat it like a checklist you can riff on, not a rigid ritual.

### 1) Mac Mini A1347: the printer host brain
**Intent:** put OctoPrint where the USB lives, and keep it boring on purpose.

- **Install OctoPrint** on the Mac Mini (native app, container, or system service — pick the method you actually maintain).
- **Name the host** something obvious (`macmini-printers`) and stick it in your DNS.
- **Connect printers by USB** to the Mac Mini (or via dedicated USB hubs so cables don’t wiggle loose).
- **Lock in the base URL** for OctoPrint (e.g. `http://macmini-printers.local:5000`).

If you’re unsure what method to install, choose the one you can update without dread. “Future-me will actually patch this” beats “fancy but abandoned.”

### 2) OctoFarm on ORIN: the control tower
**Intent:** OctoFarm is the fleet dashboard — it should point to the Mac Mini’s OctoPrint instances first.

- On ORIN, open OctoFarm at `http://$ORIN_IP:4000`.
- Add each OctoPrint instance from the Mac Mini:
  - **Name:** something human (`mk3s-left`, `ender3-neo`, `voron-2p4`).
  - **URL:** `http://macmini-printers.local:5000` (or the real port for that printer).
  - **API Key:** generate in OctoPrint (`Settings → API`) and paste into OctoFarm.

If you also run OctoPi/Klipper nodes, add them after the Mac Mini hosts so your “main printer host” stays the center of gravity.

### 3) MQTT wiring (so automations can read the room)
**Intent:** make printer states visible to HA + Node-RED without babysitting dashboards.

- Confirm OctoFarm (or OctoPrint) is publishing MQTT:
  - Topic pattern: `octoprint/+/state`
  - Broker: ORIN’s Mosquitto (`mqtt://$ORIN_IP:1883`)
- Import the Node-RED flow in [`flows/printer-truth-table.json`](../flows/printer-truth-table.json).
- Check the HA automation stub in the main README section “Printer truth table”.

If MQTT feels dead, start at the broker (`docker logs -f mosquitto`), not at HA. The signal chain goes: **printer → OctoPrint → OctoFarm → MQTT → Node-RED/HA**.

### 4) Quick smoke tests (2 minutes, tops)
- Visit OctoPrint on the Mac Mini: verify each printer shows **Operational**.
- Visit OctoFarm: confirm each printer appears with live status.
- Tail MQTT: `mosquitto_sub -h $ORIN_IP -t "octoprint/+/state" -v` and watch traffic.

If any step fails, fix it in that order. This keeps you from debugging the fancy layer before the power line exists.

### Printer failure ladder (debug in the right order)
1. **Cable + local OctoPrint UI:** the printer must appear in OctoPrint on the Mac Mini.
2. **OctoFarm sees it:** the printer must show up on `http://$ORIN_IP:4000`.
3. **MQTT emits:** `mosquitto_sub -h $ORIN_IP -t "octoprint/+/state" -v` should spit states.
4. **Node-RED updates:** the dashboard table should change without manual refresh.
5. **HA automations fire:** the “finished” effects should trigger on `studio/printers/finished`.

## Golden commands (fast muscle memory)
- `docker logs -f <service>` → watch the service breathe in real time.
- `docker compose restart <service>` → bounce one piece without nuking the stack.
- `mosquitto_sub -h $ORIN_IP -t "#" -v` → see all MQTT traffic (warning: noisy).
- `tailscale status` → confirm remote access routes and tags.

## Common failures + fixes (top 3)
1. **Snapcast audio is silent** → Re-run `./scripts/bootstrap-volumes.sh` and verify `MOPIDY_FIFO` + `LIBRESPOT_FIFO` paths exist.
2. **DNS breaks for clients** → Confirm Pi-hole is listening on LAN + tailnet only, and Unbound is `127.0.0.1#5335`.
3. **MQTT automations feel dead** → Check `docker logs -f mosquitto` and confirm topics in `flows/*.json` match your HA/Node-RED configs.

## Backups + restore intent (future‑you will thank you)
- **Back up `config/`, `flows/`, and `data/`** — that’s your automation brain and audio state.
- **Back up OctoPrint configs + printer profiles** on the Mac Mini (that’s your print muscle memory).
- **Restore order:** ORIN stack → Mac Mini OctoPrint → re‑link OctoFarm to printers.

## When not to use this system
- You don’t want a single “conductor” host owning DNS + audio + automation in one box.
- You need a cloud-managed stack with zero local maintenance or SSH access.

## Change‑log ritual (keep the map honest)
- Update this card when **host roles change** (like moving printer duty to the Mac Mini).
- Update the **ports table** any time services move or new ones appear.
- Update the **printer field kit** when OctoPrint deployment changes (native app vs container vs service).
