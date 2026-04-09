# Agentic.Munster — Claude Code Development Prompt

What this is: A comprehensive prompt for Claude Code to scaffold and build the first working prototype of the Agentic.Munster platform.

## Project summary

Agentic.Munster is an open source platform that auto-generates MCP (Model Context Protocol) connectors from German municipal web forms. City workers paste a form URL, a browser agent explores it and extracts a form graph, the city worker reviews and approves it, and it's published as an MCP tool that any AI assistant can use to help citizens fill out government forms.

- Repo: github.com/agentic-ms/agentic.ms (org exists, basic structure present)
- License: Open source (MIT or similar TBD)
- Deployment target: Docker, on-premise at city IT provider (citeq), stateless, zero persistent citizen data

## Tech stack (fixed decisions — do not change)

| Component | Technology | Notes |
|-----------|-----------|-------|
| Backend | FastAPI (Python 3.12+) | Main application server |
| Frontend glue | Inertia.js v2 | Via fastapi-inertia package (`pip install fastapi-inertia`) |
| Frontend framework | React 19 + TypeScript | With Vite as bundler |
| Browser automation | Playwright (Python) | NOT Selenium. Playwright is faster, more reliable, better async |
| MCP server | Python MCP SDK | `pip install mcp` — following https://modelcontextprotocol.io/ standard |
| Database | PostgreSQL 16 | With JSONB for form graph storage |
| ORM | SQLAlchemy 2.0 + Alembic | Async with asyncpg |
| Container | Docker + docker-compose | Dev and production |
| CSS | Tailwind CSS 4 | Via Vite integration (`@tailwindcss/vite` plugin, no config file) |

## Architecture overview

The platform has 5 components. Build them as separate Python packages/modules within a monorepo:

```
agentic-ms/
├── docker-compose.yml
├── docker-compose.dev.yml
├── pyproject.toml                 # Root project config
├── alembic/                       # DB migrations
├── backend/                       # FastAPI application
│   ├── app/
│   │   ├── main.py                # FastAPI app factory
│   │   ├── config.py              # Settings via pydantic-settings
│   │   ├── database.py            # Async SQLAlchemy engine + session
│   │   ├── models/                # SQLAlchemy models
│   │   │   ├── form_graph.py
│   │   │   ├── exploration_job.py
│   │   │   └── user.py
│   │   ├── schemas/               # Pydantic schemas
│   │   │   ├── form_graph.py
│   │   │   └── exploration.py
│   │   ├── api/                   # REST API routes (for MCP server internal calls)
│   │   │   └── v1/
│   │   │       ├── forms.py
│   │   │       └── explorations.py
│   │   ├── pages/                 # Inertia page routes
│   │   │   ├── dashboard.py
│   │   │   ├── form_explorer.py
│   │   │   └── form_review.py
│   │   ├── services/              # Business logic
│   │   │   ├── exploration_service.py
│   │   │   ├── diff_service.py
│   │   │   └── mcp_publish_service.py
│   │   └── inertia_setup.py       # Inertia config + dependency
│   └── tests/
├── explorer/                      # Auto-Explorer module
│   ├── agent.py                   # Main exploration orchestrator
│   ├── extractors/
│   │   ├── field_extractor.py     # JS-based field extraction
│   │   ├── navigation_extractor.py
│   │   └── conditional_logic.py
│   ├── llm/
│   │   ├── client.py              # Claude API client (Sonnet 4.6)
│   │   └── prompts.py             # Exploration prompts
│   └── tests/
├── executor/                      # Deterministic form filler
│   ├── runner.py                  # Playwright-based form execution
│   ├── field_resolver.py          # Label-based field targeting
│   └── tests/
├── mcp_server/                    # MCP server component
│   ├── server.py                  # MCP server with dynamic tool registration
│   ├── tool_generator.py          # FormGraph → MCP tool definition
│   └── tests/
└── frontend/                      # React + Inertia.js
    ├── package.json
    ├── vite.config.ts
    ├── tsconfig.json
    └── src/
        ├── app.tsx                # Inertia app bootstrap
        ├── layouts/
        │   └── AdminLayout.tsx
        ├── pages/
        │   ├── Dashboard.tsx
        │   ├── FormExplorer.tsx
        │   └── FormReview.tsx
        └── components/
            ├── FormStepPreview.tsx
            ├── FieldCard.tsx
            ├── DiffViewer.tsx
            └── StatusBadge.tsx
```

## Data model

### FormGraph (the central data structure)

This is the most important model. Everything revolves around it.

```python
# backend/app/models/form_graph.py

import uuid
from datetime import datetime
from enum import Enum
from sqlalchemy import Column, String, DateTime, Integer, Enum as SAEnum, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB

class FormStatus(str, Enum):
    EXPLORING = "exploring"
    EXPLORATION_FAILED = "exploration_failed"
    REVIEW_PENDING = "review_pending"
    APPROVED = "approved"
    OUTDATED = "outdated"
    DEGRADED = "degraded"
    BROKEN = "broken"

class FormGraph(Base):
    __tablename__ = "form_graphs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    form_id = Column(String(100), nullable=True, comment="External ID like KFAS_CQ00171")
    title = Column(String(500), nullable=False)
    source_url = Column(Text, nullable=False)
    organization = Column(String(200), default="Stadt Munster")
    platform = Column(String(100), default="MACH formsolutions")

    status = Column(SAEnum(FormStatus), default=FormStatus.EXPLORING, nullable=False)

    # The actual form graph — stored as JSONB
    graph_data = Column(JSONB, nullable=True, comment="Full form graph: steps, fields, sections, conditional logic")

    # Generated MCP tool spec — stored as JSONB
    mcp_tool_spec = Column(JSONB, nullable=True, comment="Generated MCP tool definition")

    # Lifecycle
    explored_at = Column(DateTime, nullable=True)
    approved_at = Column(DateTime, nullable=True)
    approved_by = Column(String(200), nullable=True)
    version = Column(Integer, default=1)

    # Automation metadata
    automation_notes = Column(JSONB, nullable=True, comment="Platform quirks, login requirements, etc.")

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
```

### The graph_data JSONB structure

This is the schema for the graph_data column. It must follow this exact structure — the executor depends on it:

```json
{
  "steps": [
    {
      "step": 1,
      "id": "step_id_string",
      "title": "Step title in German",
      "description": "What this step is about",
      "sections": [
        {
          "section": "Section name",
          "group_rule": null,
          "fields": [
            {
              "label": "Exact label text from the form",
              "type": "text | email | select | checkbox | radio | date | textarea",
              "required": true,
              "format": "DD.MM.YYYY (if date)",
              "options": ["option1", "option2"],
              "help": "Help text if present",
              "conditional_logic": {
                "if_<value>": "What happens when this value is selected"
              }
            }
          ]
        }
      ],
      "navigation": {
        "next": "step_id_or_null",
        "back": "step_id_or_null"
      }
    }
  ],
  "outcome": {
    "type": "print_and_sign | digital_submission | download",
    "description": "What happens after the last step",
    "submission_mode": "offline | online"
  }
}
```

### Reference form graph

Use the Vollmacht form as the reference implementation and test fixture:
- Form: Vollmacht zur Abholung eines Ausweises / Passes (KFAS_CQ00171)
- URL: https://formulare.stadt-muenster.de (Buergerservice portal)
- Steps: 4 (Consent → Vollmachtgebende Person → Bevollmaechtigte Person → Bevollmaechtigung)
- Required fields: 19
- Platform: MACH formsolutions / Apache Wicket
- No CAPTCHA, no login, no eID — ideal V1 candidate
- Outcome: Print-and-sign PDF (not digital submission)

The full JSON is available in `reference-data/form-graph-vollmacht-ausweis.json`.

## Component specs

### 1. Backend (FastAPI + Inertia.js)

Setup with fastapi-inertia:

```python
# backend/app/inertia_setup.py
from fastapi import Depends
from typing import Annotated
from inertia import InertiaConfig, inertia_dependency_factory, Inertia
from fastapi.templating import Jinja2Templates

inertia_config = InertiaConfig(
    templates=Jinja2Templates(directory="backend/templates"),
    environment="development",  # or "production"
    version="1.0",
    use_flash_messages=True,
    use_flash_errors=True,
)

inertia_dependency = inertia_dependency_factory(inertia_config)
InertiaDep = Annotated[Inertia, Depends(inertia_dependency)]
```

Page routes (Inertia pattern — returns React component name + props):

```python
# backend/app/pages/dashboard.py
from fastapi import APIRouter, Depends
from app.inertia_setup import InertiaDep
from app.services.form_service import get_all_forms

router = APIRouter()

@router.get("/")
async def dashboard(inertia: InertiaDep):
    forms = await get_all_forms()
    return inertia.render("Dashboard", props={
        "forms": [form.to_dict() for form in forms],
    })

@router.get("/forms/{form_id}")
async def form_detail(form_id: str, inertia: InertiaDep):
    form = await get_form_by_id(form_id)
    return inertia.render("FormReview", props={
        "form": form.to_dict(),
        "graph": form.graph_data,
        "mcp_spec": form.mcp_tool_spec,
    })
```

API routes (for MCP server and internal calls):

```python
# backend/app/api/v1/forms.py
@router.get("/api/v1/forms/{form_id}/graph")
async def get_form_graph(form_id: str):
    """Returns the form graph — used by the executor."""
    ...

@router.post("/api/v1/forms/{form_id}/execute")
async def execute_form(form_id: str, field_values: dict):
    """Execute form fill — called by MCP server. PII in, result out, data discarded."""
    ...

@router.post("/api/v1/forms/{form_id}/re-explore")
async def trigger_re_exploration(form_id: str):
    """Trigger re-exploration for change detection."""
    ...
```

Inertia root template (`backend/templates/index.html`):

```html
<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    {% inertia_head %}
</head>
<body>
    {% inertia_body %}
</body>
</html>
```

### 2. Auto-Explorer

The explorer navigates a form URL using Playwright, extracts the complete field graph, and uses Claude Sonnet 4.6 for interpretation.

**CRITICAL: The explorer never handles citizen PII. It works on empty forms only.**

LLM: Claude Sonnet 4.6 via Anthropic API. A full exploration costs ~$0.10-0.50.

Technical constraints the explorer MUST respect:
1. **NEVER use or store element IDs** — they are session-scoped (Apache Wicket regenerates them per session). Target fields by label text, CSS selectors based on structure, or name attribute patterns.
2. **JavaScript extraction over DOM readers** — `page.evaluate()` with `document.querySelectorAll` is more reliable than Playwright's `page.get_by_*` for MACH formsolutions' server-side rendered markup.
3. **Label matching is fragile** — labels may contain asterisks (*) for required fields, trailing whitespace, or special characters. Always normalize: strip *, trim whitespace, collapse multiple spaces.
4. **Test all conditional branches** — for every radio button and checkbox, select each option, screenshot, and check if new fields appear.
5. **Group-required fields (Pflichtgruppe)** — some field groups require "at least one" but don't use HTML required.
6. **Date format: Always DD.MM.YYYY** for Munster forms.
7. **Screenshots between steps** — use `page.screenshot()` after each navigation click as ground truth.

### 3. Form Executor (deterministic, NO LLM)

**CRITICAL DESIGN DECISION:** The executor does NOT use any LLM. It is a pure deterministic Playwright script. This is a hard requirement because citizen PII flows through the executor, and PII must NEVER leave the city's on-premise infrastructure.

Key design:
- Label-based field targeting (NOT element IDs)
- Field resolver with 3 strategies: Playwright `get_by_label()`, JS `label[for]` resolution, parent container traversal
- Audit logs with `[REDACTED]` values — never log PII
- V1 hard rule: fill but do NOT click final submit

### 4. MCP Server (dynamic tool registration)

The MCP server reads all approved FormGraphs from the database and exposes each as an MCP tool. When a new form is approved, the server picks it up without restart.

Uses `mcp` Python package (`pip install mcp`).

### 5. Frontend (React + Inertia.js + TypeScript)

```typescript
// frontend/src/app.tsx
import { createInertiaApp } from '@inertiajs/react'
import { createRoot } from 'react-dom/client'

createInertiaApp({
  resolve: name => {
    const pages = import.meta.glob('./pages/**/*.tsx', { eager: true })
    return pages[`./pages/${name}.tsx`]
  },
  setup({ el, App, props }) {
    createRoot(el).render(<App {...props} />)
  },
})
```

Key pages: Dashboard.tsx, FormExplorer.tsx, FormReview.tsx

## PII and security architecture

### HARD RULES — non-negotiable:

1. **Citizen PII NEVER leaves the city's infrastructure.** The executor runs on-premise. No external API calls during execution. No LLM sees citizen data.
2. **The Auto-Explorer NEVER handles PII.** It works with empty forms only. The LLM only sees form structure: labels, field types, help texts.
3. **Audit logs NEVER contain PII.** Log which field was filled, on which step, at what time. NEVER log the value itself. Use `[REDACTED]`.
4. **Stateless execution.** After the executor returns a result, all citizen data is discarded. No database storage of field values.
5. **V1 hard rule: we fill, citizen submits.** The executor fills all fields but does NOT click the final submit button.

## Change detection system

Three triggers, one pipeline (re-explore → diff → notify):
1. **Manual trigger** — city worker clicks "Erneut pruefen" in Admin UI
2. **Execution failure** — executor can't find a field → retry once → if still fails, trigger re-exploration
3. **Scheduled health check** (Phase 2) — weekly cron re-explores all approved forms

Graph diff classification:
- **Cosmetic** — label text changed slightly. Status stays approved.
- **Structural** — new field added, type changed. Status → outdated. Notify city worker.
- **Breaking** — required field disappeared, step removed. Status → broken. MCP tool auto-disabled.

## Development priorities

### Phase 1: Skeleton (Week 1-2)
1. Docker-compose with PostgreSQL + FastAPI + Vite dev server
2. FastAPI app with Inertia.js setup
3. Database schema + Alembic migration for FormGraph model
4. Dashboard page showing form data
5. Seed the database with the Vollmacht form graph

### Phase 2: Explorer + Review (Week 3-5)
1. Auto-Explorer with Playwright + Claude Sonnet 4.6
2. FormExplorer page: URL input → trigger exploration → show progress
3. FormReview page: render form graph step-by-step, edit/approve
4. Test on 2-3 live Munster forms

### Phase 3: MCP + Executor (Week 6-8)
1. Deterministic executor (Playwright, no LLM)
2. MCP server with dynamic tool registration
3. Test end-to-end: approve form → MCP tool appears → Claude can call it
4. Change detection: execution failure → re-explore trigger

### Phase 4: Polish (Week 9-10)
1. Graph diff engine + notification system
2. Manual re-check trigger in Admin UI
3. Status management (degraded, outdated, broken)
4. Operator documentation for deployment

## What "done" looks like for the prototype

A city worker can:
1. Open the dashboard, see a list of forms
2. Paste a new form URL, trigger exploration
3. See the exploration progress in real-time
4. Review the extracted form graph step-by-step
5. Approve the form

An AI assistant can:
6. Discover the approved form as an MCP tool
7. See its required parameters
8. Call the tool with citizen data
9. Receive confirmation that the form was filled

The system correctly:
10. Fills the real form via Playwright (deterministic, no LLM)
11. Stops before final submit (human reviews)
12. Fails gracefully if a field changed, triggering re-check
13. Never sends citizen PII to any external service
