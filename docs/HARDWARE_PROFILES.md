# Hardware profiles (role mapping cheat sheet)

This stack is role-first: **CORE, HISTORY, VISION, EXPERIMENTS** are jobs, not machines. You can swap hardware under them without rewriting the whole world.

Use this as the current deployment map. The repo assumes the Orin and at least one
16 GB Intel Mac mini are available; it does not assume a cluster chassis.

## Roles (what they do)

- **CORE** — the conductor. Home Assistant, MQTT, Node-RED, DNS, reverse proxy, Snapserver. The one box that has to be boring and always-on.
- **HISTORY** — long-term logging and storage (InfluxDB, Timescale, MariaDB, backups, camera archive).
- **VISION** — heavy video or ML workloads (Frigate, object detection, NVR stuff).
- **EXPERIMENTS** — optional side quests: LLMs, RAG, OCR, custom automations.

## Current hardware mapping

| Hardware | Suggested role(s) | Why this fits |
| --- | --- | --- |
| **Jetson Orin** | CORE + VISION | The always-on automation host and the best available target for camera inference or other GPU work. |
| **Intel Mac mini (16 GB)** | HISTORY + printer host + EXPERIMENTS | Suitable for databases, backups, OctoPrint, indexing, and CPU-friendly services that should be isolated from CORE. |

If more than one Mac mini is online, keep printer USB workloads on one and move
HISTORY/EXPERIMENTS to another. With one Mac mini, prioritize printer hosting and
backups before optional experiments.

## Human rule of thumb

- Put **CORE** on the most stable box with the best networking.
- Put **VISION** on the hottest silicon.
- Put **HISTORY** where storage is fast and boring.
- Put **EXPERIMENTS** on anything you can afford to break.

When in doubt, keep CORE and split everything else.
