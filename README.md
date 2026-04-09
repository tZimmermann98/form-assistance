# Agentic.Munster

Open source platform that auto-generates MCP (Model Context Protocol) connectors from German municipal web forms.

City workers paste a form URL, a browser agent explores it and extracts a form graph, the city worker reviews and approves it, and it's published as an MCP tool that any AI assistant can use to help citizens fill out government forms.

## Quick Start

```bash
# Start PostgreSQL
docker compose -f docker-compose.dev.yml up -d db

# Python environment
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Run migrations
alembic upgrade head

# Seed reference data
python -m backend.app.services.seed

# Start backend
uvicorn backend.app.main:app --reload

# Start frontend (separate terminal)
cd frontend && npm install && npm run dev
```

Then open http://localhost:8000

## Architecture

See [CLAUDE.md](./CLAUDE.md) for the full architecture overview.

## License

MIT (TBD)
