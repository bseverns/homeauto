# Field Card — Jetson Orin Home/Studio Core

## Purpose
Keep the Jetson Orin stack as the loud, reliable conductor for DNS, automation, and audio routing.
Give you a fast, punk-rock map from “fresh box” to “the house is talking.”

## Quickstart (3 steps max)
1. `cp .env.example .env` → fill ORIN_IP + DNS + FIFO paths.
2. `./scripts/bootstrap-volumes.sh` → create bind mounts + named pipes.
3. `docker compose up -d` → light the stack.

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
| OctoFarm | 4000 | HTTP | Printer fleet dashboard. |
| Portainer | 9000 / 9443 | HTTP/HTTPS | Container UI. |

## Common failures + fixes (top 3)
1. **Snapcast audio is silent** → Re-run `./scripts/bootstrap-volumes.sh` and verify `MOPIDY_FIFO` + `LIBRESPOT_FIFO` paths exist.
2. **DNS breaks for clients** → Confirm Pi-hole is listening on LAN + tailnet only, and Unbound is `127.0.0.1#5335`.
3. **MQTT automations feel dead** → Check `docker logs -f mosquitto` and confirm topics in `flows/*.json` match your HA/Node-RED configs.

## When not to use this system
- You don’t want a single “conductor” host owning DNS + audio + automation in one box.
- You need a cloud-managed stack with zero local maintenance or SSH access.
