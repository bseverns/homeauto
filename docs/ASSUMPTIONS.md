# Assumptions (so future-us can yell at present-us)

This repo is moving toward **role-based deployment**. When the source code didn’t make something explicit, I made the smallest, reversible guess and wrote it down here.

If any of these are wrong for your setup, tweak the doc + compose slices — that’s the point.

## Current assumptions

- **CORE is the old ORIN.** We treat `ORIN_*` variables as legacy aliases for the new `CORE_*` naming. The default compose slices use `CORE_*` first, then fall back to `ORIN_*`. Update your `.env` when you’re ready, but you’re not forced to migrate on day one.
- **The “assistant” stack is the existing LLM + RAG bundle.** The new Turing Pi slices reference Qdrant + llama.cpp + assistant API/ingest from `services/assistant/*` so you can offload them to a different node. If you don’t run the assistant, the slice can stay down.
- **Audio services use host networking** because ALSA + FIFO routing is fragile in bridged networks. We kept host networking in the Turing Pi slices to match the current topology.
- **Data lives under `infra/turingpi2/data/`** for the new slices. It keeps the Turing Pi deployment self-contained and avoids polluting the root `data/` directory when you’re testing.

If you add a new role (or change a dependency boundary), add a bullet here.
