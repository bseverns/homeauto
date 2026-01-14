# Hardware profiles (role mapping cheat sheet)

This stack is role-first: **CORE, HISTORY, VISION, EXPERIMENTS** are jobs, not machines. You can swap hardware under them without rewriting the whole world.

Use this as a quick “what could run where” map. Mix and match as your bench and budget allow.

## Roles (what they do)

- **CORE** — the conductor. Home Assistant, MQTT, Node-RED, DNS, reverse proxy, Snapserver. The one box that has to be boring and always-on.
- **HISTORY** — long-term logging and storage (InfluxDB, Timescale, MariaDB, backups, camera archive).
- **VISION** — heavy video or ML workloads (Frigate, object detection, NVR stuff).
- **EXPERIMENTS** — optional side quests: LLMs, RAG, OCR, custom automations.

## Example hardware mappings

| Hardware | Suggested role(s) | Why this fits |
| --- | --- | --- |
| **Turing Pi 2 + CM4 nodes** | CORE + HISTORY + EXPERIMENTS (split) | Low power, clustered, flexible. CORE stays light; EXPERIMENTS can die without taking the house with it. |
| **Jetson Orin Nano** | CORE or VISION | Strong GPU. Great as CORE *or* as a VISION node with Frigate + detectors. |
| **Jetson Nano / Xavier NX** | VISION | Solid edge inference for cameras. |
| **x86 mini PC (NUC, Beelink, etc.)** | HISTORY + EXPERIMENTS | Fast storage + plenty of RAM for databases, LLMs, and indexing. |
| **Mac Mini A1347** | HISTORY (printer host + OctoPrint) | Already in the stack for printers; keep it doing one job well. |
| **Raspberry Pi 4 / CM4** | AUDIO clients, small service host | Cheap, replaceable. Good for snapclients, small APIs, or a single service. |

## Human rule of thumb

- Put **CORE** on the most stable box with the best networking.
- Put **VISION** on the hottest silicon.
- Put **HISTORY** where storage is fast and boring.
- Put **EXPERIMENTS** on anything you can afford to break.

When in doubt, keep CORE and split everything else.
