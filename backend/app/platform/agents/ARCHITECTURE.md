# Public Agent Facade

This module keeps the public agent catalog separate from internal execution details.
The catalog is config-backed through `backend/config/agents.yaml`, with built-in defaults used as a fallback when config is missing or invalid.

## Public Agent IDs

- `planner`
- `rag-analyst`
- `coder`
- `reviewer`

These are the stable user-facing identities exposed to Open WebUI through `/api/v1/models`.

## Internal Runtimes

Public agent IDs map to internal runtime keys:

- `planner` -> `planner_runtime`
- `rag-analyst` -> `rag_analysis_runtime`
- `coder` -> `coding_runtime`
- `reviewer` -> `review_runtime`

Runtime keys decide internal task defaults such as task class, route profile, approval mode, and prompt guidance. Worker topology, OpenCode routing, backend selection, retries, and fallback behavior remain internal.

## Config Layout

The catalog is split into two config-backed layers:

- `agents`: public personas exposed to clients
- `runtimes`: reusable execution presets used by those personas

Agents can also define:

- `system_prompt`: persona-specific guidance layered above user messages
- `workflow`: structured execution guidance for inner loops, validation steps, and handoff expectations

This preserves the existing many-to-one mapping model:

- many public agents can point to one runtime
- a public agent can switch runtimes without changing its stable public ID

When the config file is unavailable or invalid, the service falls back to built-in defaults so `/api/v1/models` remains stable. The loader prefers YAML and still accepts the legacy JSON path for backward compatibility.

## Request Flow

1. Open WebUI calls `/api/v1/models` to discover selectable agents.
2. Open WebUI sends `/api/v1/chat/completions` with the chosen model ID.
3. The public router resolves the model ID through `AgentRegistry`.
4. The runtime registry converts that agent into internal task defaults.
5. The request is submitted to the existing `agent_tasks` orchestration layer.
6. The broker selects an execution target and dispatches work to a worker when approval allows it.
7. The worker invokes OpenCode, which performs backend-specific execution.

## Approval Flow

Approval-capable tasks remain visible through the public task endpoints:

- `GET /api/agent-tasks/{task_id}`
- `GET /api/agent-tasks/{task_id}/stream`
- `POST /api/agent-tasks/{task_id}/approve`
- `POST /api/agent-tasks/{task_id}/reject`

This keeps the OpenAI-compatible submission surface small while still exposing a stable public control path for long-running or approval-gated work.
