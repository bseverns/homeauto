# Role-based deployment: Orin + Intel Mac mini

The current server inventory is a **Jetson Orin** and at least one **Intel Mac mini
with 16 GB RAM**. There is no cluster backplane in this deployment. Services remain
organized by role so they can move between the two machines without changing their
network contracts.

## Current role assignment

| Host | Primary roles | Services |
| --- | --- | --- |
| Jetson Orin (`orin-core`) | CORE + VISION | Home Assistant, MQTT, Node-RED, DNS, reverse proxy, Snapserver, camera/ML workloads |
| Intel Mac mini (`macmini-history`) | HISTORY + printer host | Backups, databases, OctoPrint, archives |
| Either host | EXPERIMENTS | Local assistant, RAG, OCR, and temporary services |

Run GPU-dependent experiments on the Orin. Run ordinary x86 containers and
memory-heavy CPU services on the Mac mini when doing so will not interfere with
printing or backups.

If multiple Intel Mac minis are available, dedicate one to the printer USB workload
and use another for HISTORY and EXPERIMENTS.

## Prepare both hosts

Give each host a DHCP reservation or static address. Use the example names below or
replace them consistently in `.env` and local DNS:

```dotenv
CORE_HOSTNAME=orin-core
CORE_IP=192.168.50.50
HISTORY_HOST=macmini-history
HISTORY_IP=192.168.50.60
ASSISTANT_HOST=macmini-history
ASSISTANT_API_URL=http://192.168.50.60:7070
```

Docker Compose is required on both hosts. The Orin needs an ARM64-compatible Docker
environment; the Intel Mac mini needs an x86_64-compatible one. Verify third-party
images support the target architecture before moving a slice.

## Bring up the Orin

From a repo clone on the Orin:

```bash
cp .env.example .env
# Set CORE_IP, router/DNS values, and hardware-specific audio values.
make up-core
make up-audio  # optional; keep here when the Orin owns the audio devices
```

CORE is the stable control plane. Avoid putting experimental services here unless
they require the Orin GPU.

## Bring up the Mac mini

Copy the repo and a minimal `.env` to the Mac mini. Keep OctoPrint close to the
printer USB devices. Database and backup services are not yet defined as compose
slices in this repo, so HISTORY currently describes host ownership rather than a
Make target.

The assistant slice can run on the Mac mini as a CPU workload:

```bash
make up-assistant
```

Set `ASSISTANT_GPU_LAYERS=0` on a Mac configuration that does not expose a supported
GPU backend to the container. Use a model size that fits comfortably within 16 GB
alongside the host's other work.

To run the assistant with acceleration on the Orin instead, run the same target
there and tune `ASSISTANT_GPU_LAYERS` for the board.

## Verify the split

```bash
curl http://$CORE_IP:8123
mosquitto_sub -h "$CORE_IP" -t '$SYS/broker/uptime' -C 1
curl "$ASSISTANT_API_URL/health"
```

Also verify the Mac mini's OctoPrint UI and confirm that the Orin-hosted automation
services can reach it over the LAN.

## Repository conventions

- CORE, HISTORY, VISION, and EXPERIMENTS are roles, not product names.
- Active modular compose files live under `infra/roles/compose/`.
- Their bind-mounted state lives under `infra/roles/data/`.
- `CORE_*` is preferred. `ORIN_*` remains as a compatibility fallback.
- `make up-core`, `make up-audio`, and `make up-assistant` can be run independently
  on the host assigned to each slice.
