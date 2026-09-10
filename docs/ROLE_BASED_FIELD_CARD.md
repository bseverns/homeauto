# Orin + Mac mini field card

## Current hosts

- `orin-core`: CORE + VISION; automation, networking, audio, and GPU work.
- `macmini-history`: HISTORY + printer host; backups, storage, OctoPrint, and
  optional CPU experiments. Assumed to be Intel with 16 GB RAM.

## Start or update the Orin

```bash
make up-core
make up-audio       # optional
make logs-core
```

## Start the optional assistant

Run this on the chosen EXPERIMENTS host:

```bash
make up-assistant
```

Use `ASSISTANT_GPU_LAYERS=0` for a CPU-only Mac mini deployment. Tune the value for
the Orin when its GPU is available to the container.

## Health checks

```bash
curl -s http://$CORE_IP:8123 | head -n 5
mosquitto_sub -h "$CORE_IP" -t '$SYS/broker/uptime' -C 1
curl -s http://$CORE_IP:1880 | head -n 5
curl -s "$ASSISTANT_API_URL/health"
```

## Backups

```bash
make backup
make restore-check
```

Back up both `data/` and `infra/roles/data/`, plus the Mac mini's OctoPrint profiles
and printer configuration.

## Recovery order

1. Restore CORE on the Orin.
2. Restore OctoPrint and printer profiles on the Mac mini.
3. Restore HISTORY data and relink OctoFarm/automation endpoints.
4. Restore optional EXPERIMENTS last.

## Remember

- The current deployment does not depend on cluster hardware.
- Compose slices live in `infra/roles/compose/`.
- Reserve both host addresses in DHCP and local DNS.
- Keep CORE stable; experiments can move between the two available hosts.
