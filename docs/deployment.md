# Deployment Guide

## Prerequisites

- Docker and Docker Compose
- Git

## Quick Start

```bash
git clone https://github.com/agentic-ms/agentic.ms.git
cd agentic.ms

# Start all services
docker compose -f docker-compose.dev.yml up -d

# Run database migrations
docker compose -f docker-compose.dev.yml exec backend alembic upgrade head

# Seed reference data (optional)
docker compose -f docker-compose.dev.yml exec backend python -m backend.app.seed
```

The platform is available at:
- **Admin UI**: http://localhost:8000
- **MCP Server**: http://localhost:8001/mcp
- **Vite Dev Server**: http://localhost:5173 (development only)

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql+asyncpg://agentic:agentic_dev@localhost:5432/agentic_ms` | PostgreSQL connection string |
| `ENVIRONMENT` | `development` | `development` or `production` |
| `SETTINGS_ENCRYPTION_KEY` | _(empty)_ | Fernet key for encrypting API keys at rest. Generate with: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `EXPLORER_MODE` | `real` | `real` (Playwright + LLM) or `mock` (simulated with reference data) |
| `EXPLORER_HEADLESS` | `true` | Run Playwright in headless mode |
| `EXPLORER_TIMEOUT` | `30000` | Page navigation timeout in milliseconds |
| `MCP_SERVER_PORT` | `8001` | Port for the MCP server |
| `VITE_DEV_URL` | `http://localhost:5173` | Vite dev server URL (development only) |

## LLM Configuration

1. Navigate to http://localhost:8000/settings
2. Select your LLM provider (Anthropic, OpenAI, Google, or Custom)
3. Enter your API key
4. Choose a model (defaults provided per provider)
5. Click "Verbindung testen" to verify
6. Save

Supported providers:
- **Anthropic**: Best for exploration (native vision support). Uses `claude-sonnet-4-20250514` by default.
- **OpenAI**: Uses `gpt-4o` by default.
- **Google**: Uses `gemini-2.0-flash` via their OpenAI-compatible endpoint.
- **Custom**: Any OpenAI-compatible API (vLLM, Ollama, LiteLLM, etc.)

## Connecting AI Assistants

Navigate to http://localhost:8000/connect for per-platform instructions with copy-pasteable config snippets for Claude Desktop, Claude Code, Cursor, VS Code Copilot, and more.

## Security Architecture

- **Citizen PII never leaves the city's infrastructure.** The executor runs on-premise with no external API calls.
- **The explorer never handles PII.** It works with empty forms only. The LLM sees form structure, not citizen data.
- **Audit logs never contain PII.** Values are always logged as `[REDACTED]`.
- **Stateless execution.** All citizen data is discarded after the executor returns.
- **API keys encrypted at rest** using Fernet symmetric encryption (set `SETTINGS_ENCRYPTION_KEY`).
- **V1 rule: fill but don't submit.** The executor fills all fields but never clicks the final submit button.

## Monitoring

- **Dashboard** (http://localhost:8000): Shows all forms with status badges
- **Notifications**: Bell icon in the nav bar shows form changes and failures
- **Audit logs**: Returned with every form execution (no PII)
- **Change detection**: Automatic re-exploration triggered on executor failures

## Updating

```bash
git pull
docker compose -f docker-compose.dev.yml up -d --build
docker compose -f docker-compose.dev.yml exec backend alembic upgrade head
```
