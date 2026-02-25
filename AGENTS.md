# AGENTS.md

## Cursor Cloud specific instructions

### Overview

LogsAi is an AI-powered log analysis platform connecting Graylog with LLMs via MCP. The main services are:

| Service | Port | Description |
|---------|------|-------------|
| Graylog (+ MongoDB + OpenSearch) | 9000 | Log management platform with MCP endpoint |
| logs-ai-yandex (FastAPI) | 8000 (local) / 3020 (Docker) | Chat UI for querying logs via Yandex GPT |

### Starting services

1. **Graylog stack**: `docker compose up -d` (from repo root). Requires `vm.max_map_count=262144` — run `sudo sysctl -w vm.max_map_count=262144` before starting. Wait ~15s for Graylog to become healthy; verify with `curl -s http://127.0.0.1:9000/api/system/lbstatus` (should return `ALIVE`).

2. **logs-ai-yandex** (dev mode): `cd logs-ai-yandex && uvicorn app:app --reload --host 0.0.0.0 --port 8000`. The app loads `.env` from the repo root automatically. Health check: `curl http://127.0.0.1:8000/api/health`.

3. **Seeding demo logs**: First create a GELF UDP input in Graylog (`System > Inputs > GELF UDP > port 12201`), or via API:
   ```
   curl -u admin:admin -X POST http://127.0.0.1:9000/api/system/inputs \
     -H 'Content-Type: application/json' -H 'X-Requested-By: cli' \
     -d '{"title":"GELF UDP","type":"org.graylog2.inputs.gelf.udp.GELFUDPInput","configuration":{"bind_address":"0.0.0.0","port":12201,"recv_buffer_size":262144},"global":true}'
   ```
   Then: `php php/graylog_seed.php random --count=50 --sleep-ms=100`

### Gotchas

- The Docker socket may need permission fix after Docker install: `sudo chmod 666 /var/run/docker.sock`.
- OpenSearch requires `vm.max_map_count=262144`; without it the container crashes silently.
- The Graylog default admin password is `admin` (SHA-256 hash is pre-set in `.env.example`).
- `uvicorn` and other pip-installed scripts install to `~/.local/bin` — ensure it's on PATH.
- The Logs AI chat endpoint (`/api/chat`) requires `YANDEX_API_KEY` and `YANDEX_CATALOG_ID` in `.env` to function. Without these, the chat returns an error, but the rest of the app (UI, health, status endpoints) works fine.
- For full AI chat functionality, MCP must be enabled in Graylog: `System > Configurations > MCP > Enable`. Additionally, `GRAYLOG_MCP_AUTH` must be set with a valid API token (see `mcp/README.md`).
- Standard commands for lint/test/build/run are documented in `README.md`, `logs-ai-yandex/README.md`, and `QUICKSTART.md`.
