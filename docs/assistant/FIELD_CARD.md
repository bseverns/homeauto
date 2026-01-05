# Assistant Field Card (Orin)

Fast, no‑nonsense runtime notes for the local assistant stack.

---

## Ports

| Service | Port | Notes |
|---|---|---|
| Qdrant | `6333` | Vector DB API |
| Assistant API | `7070` | Query endpoint (`/query`) |
| llama.cpp server | `8080` | OpenAI‑style chat completions |

---

## Compose profile

This stack is gated behind the `assistant` profile so it won’t light up unless you ask for it.

```bash
docker compose --profile assistant up -d qdrant llama-server assistant-api
```

Index data on demand:

```bash
docker compose --profile assistant run --rm assistant-ingest
```

---

## Health checks

```bash
curl http://localhost:7070/health
curl http://localhost:6333/collections
```

---

## API quick test

```bash
curl -X POST http://localhost:7070/query \
  -H 'Content-Type: application/json' \
  -d '{"question": "What is the purpose of the Snapcast FIFO?", "top_k": 5}'
```

---

## Troubleshooting

- **Slow responses:** drop to a smaller GGUF model or lower context length.
- **No sources returned:** re‑run the ingest step or verify your `ASSISTANT_DATA_ROOTS` paths.
- **Weird answers:** check `assistant-api` logs to see which chunks were retrieved.

