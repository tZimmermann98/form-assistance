# Architecture Overview

## Components

Agentic.Muenster consists of 5 components within a monorepo:

```
Admin Platform (FastAPI + Inertia.js + React)
    ├── Dashboard — form list with status management
    ├── Explorer UI — trigger and monitor form exploration
    ├── Review UI — step-by-step graph review and approval
    ├── Test Chat — built-in chat interface for testing
    ├── Settings — LLM provider configuration
    └── Connect Guide — MCP connection instructions

Auto-Explorer (Playwright + LLM)
    ├── Field Extractor — JavaScript-based field extraction
    ├── Conditional Logic — toggle options to detect dynamic fields
    └── LLM Interpreter — Claude/GPT interprets form structure

Form Executor (Playwright only, NO LLM)
    ├── Field Resolver — label-based field targeting
    └── Runner — deterministic form filling

MCP Server (Python MCP SDK)
    ├── Tool Generator — FormGraph → MCP tool definition
    └── Dynamic Registration — approved forms become MCP tools

PostgreSQL Database
    ├── form_graphs — central data model
    ├── exploration_jobs — exploration tracking
    ├── platform_settings — LLM config (encrypted)
    ├── form_graph_diffs — change detection results
    └── notifications — status change alerts
```

## Data Flow

### Exploration Flow (no PII)

```
City Worker → pastes URL → Explorer
    → Playwright opens empty form
    → JavaScript extracts fields (no element IDs)
    → LLM interprets structure (screenshots + field data)
    → Form graph stored in DB
    → City worker reviews and approves
```

### Execution Flow (PII contained on-premise)

```
AI Assistant → calls MCP tool with citizen data
    → MCP Server checks form status
    → Executor fills form via Playwright (NO LLM)
    → Screenshot taken before submit
    → Citizen data discarded
    → Result returned (screenshot + audit log)
    → Human reviews and clicks submit
```

### PII Boundary

```
┌──────────────────────────────────────────────┐
│            City Infrastructure               │
│                                              │
│  ┌──────────┐    ┌──────────┐               │
│  │ Executor │◄───│MCP Server│◄── AI Request │
│  │(Playwright│    │(Tool Hub)│    (with PII) │
│  │ NO LLM)  │    └──────────┘               │
│  └──────────┘                                │
│       │ PII discarded after execution        │
│       ▼                                      │
│  [Screenshot + Audit Log (no PII)]           │
└──────────────────────────────────────────────┘

┌──────────────────────────────────────────────┐
│            Cloud (External)                  │
│                                              │
│  ┌──────────┐    Only sees: empty forms,     │
│  │ LLM API  │    field labels, screenshots   │
│  │(Anthropic/│    of empty forms. NEVER       │
│  │ OpenAI)  │    citizen data.                │
│  └──────────┘                                │
└──────────────────────────────────────────────┘
```

## Form Lifecycle States

```
exploring ──► review_pending ──► approved ──► outdated ──► approved (v2)
    │              │                  │            │
    ▼              ▼                  ▼            ▼
exploration    (re-explore)      degraded      broken
  _failed                           │            │
                                    ▼            ▼
                              (re-explore)  MCP tool
                                            disabled
```

## Change Detection

Three triggers feed into one pipeline:

1. **Manual**: City worker clicks "Erneut pruefen"
2. **Execution failure**: Executor can't find a field
3. **Scheduled** (Phase 2): Weekly cron re-explores all approved forms

Pipeline: re-explore → diff old vs new graph → classify severity → update status → notify

Severity classification:
- **Cosmetic**: Label text changed slightly → stays approved
- **Structural**: New field, type changed → status = outdated, notify
- **Breaking**: Required field removed, step gone → status = broken, MCP tool disabled
