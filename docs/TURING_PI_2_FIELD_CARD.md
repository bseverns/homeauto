# Turing Pi 2 Field Card (quick reference)

One page. No fluff. You’re on the floor with a serial cable.

## Boot & basics

```bash
# On the CORE node
make up-core
```

Optional slices:

```bash
make up-audio
make up-assistant
```

## Update the stack

```bash
git pull
make up-core
make up-audio
make up-assistant
```

## Logs (CORE)

```bash
make logs-core
# or raw compose:
# docker compose -f infra/turingpi2/compose/core.yml logs -f
```

## Restart just CORE services

```bash
make down-core
make up-core
```

## Health checks

```bash
curl -s http://$CORE_IP:8123 | head -n 5
mosquitto_sub -h $CORE_IP -t '$SYS/broker/uptime' -C 1
curl -s http://$CORE_IP:1880 | head -n 5
```

## Recoveries

- **Storage filled?** rotate logs, prune old backups in `ops/backup/out/`.
- **Docker wedged?** `sudo systemctl restart docker`.
- **Network weird?** check static IP reservations + hostname mapping.

## Backups (the boring, reliable stuff)

```bash
make backup
make restore-check
```

## “Don’t panic” commands

```bash
docker ps
journalctl -u docker --since "1 hour ago"
```

## Things you should remember (tattoo if needed)

- CORE is a **role**, not a specific piece of hardware.
- `ORIN_*` env vars still work, but **new docs use CORE_* going forward**.
- Everything in `infra/turingpi2/compose/` is a **slice**. Run only what you need.
