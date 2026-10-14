# Control Deck

Phase A is a local, read-only view of deterministic coordination state. It binds only to `127.0.0.1`, validates `coordination/state/world-state.json`, and falls back to a sanitized fixture when that source is missing or invalid. Fixture-backed tests verify the data path, not a live deployment; fixture responses and the browser view identify themselves as fixture data.

## Run

```bash
cd services/control_deck/web
npm install
npm run build
cd ../../..
env -u VIRTUAL_ENV uv run --isolated --with-requirements requirements.txt \
  python -m services.control_deck.api
```

Open <http://127.0.0.1:8765>. Stop the server with `Ctrl-C`.

## Verify

```bash
env -u VIRTUAL_ENV uv run --isolated --with-requirements requirements-dev.txt \
  python -m unittest tests.test_control_deck_api -v
cd services/control_deck/web
npm test
npm run build
npx tsc --noEmit
npm audit --audit-level=low
```

The API exposes only:

- `GET /api/v1/health`
- `GET /api/v1/world-state`
- `GET /api/v1/opportunities`
- `GET /api/v1/machines`

Mutation methods return `405 read_only`. Private observation metadata, observation values, raw telemetry, credentials, and filesystem paths are not part of the API projection.