# Assumptions (so future-us can yell at present-us)

This repo is moving toward **role-based deployment**. When the source code didn’t make something explicit, I made the smallest, reversible guess and wrote it down here.

If any of these are wrong for your setup, tweak the doc + compose slices — that’s the point.

## Current assumptions

- **CORE is the old ORIN.** We treat `ORIN_*` variables as legacy aliases for the new `CORE_*` naming. The default compose slices use `CORE_*` first, then fall back to `ORIN_*`. Update your `.env` when you’re ready, but you’re not forced to migrate on day one.
- **The available server hardware is a Jetson Orin and at least one Intel Mac mini with 16 GB RAM.** There is no Turing Pi in the current inventory.
- **The Orin is the default CORE host** and is also the preferred home for VISION or other GPU-accelerated work.
- **The Intel Mac mini is the default HISTORY and printer host.** It can also run CPU-friendly EXPERIMENTS or the assistant stack when isolation from CORE matters more than GPU acceleration.
- **The “assistant” stack is the existing LLM + RAG bundle.** The role slices reference Qdrant + llama.cpp + assistant API/ingest from `services/assistant/*` so it can run on either available host. If you don’t run the assistant, the slice can stay down.
- **Audio services use host networking** because ALSA + FIFO routing is fragile in bridged networks. The audio slice retains host networking to match the current topology.
- **Role-slice data lives under `infra/roles/data/`.** This keeps the modular deployment self-contained and avoids polluting the root `data/` directory when you’re testing.

If you add a new role (or change a dependency boundary), add a bullet here.
