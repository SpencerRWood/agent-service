# Prompt Testing README

This guide gives you a repeatable way to test multiple prompts against Agent Service and confirm the main behaviors are working end to end.

It is designed to validate:
- model discovery through `/api/v1/models`
- non-streaming chat completions through `/api/v1/chat/completions`
- public task creation and task readback
- SSE task streaming through `/api/agent-tasks/{task_id}/stream`
- planner, RAG analyst, coder, and reviewer routing
- approval-gated reviewer flow
- deferred terminal handling when no backend is available
- recent-task visibility in the admin UI

## What Good Looks Like

For a healthy run, you should be able to confirm all of the following:
- `GET /api/health/` returns `200`
- `GET /api/v1/models` includes `planner`, `rag-analyst`, `coder`, and `reviewer`
- a non-streaming request returns a `task.id`, `task.state`, and `task.stream_url`
- the task stream ends with `event: terminal`
- the task record at `GET /api/agent-tasks/{task_id}` matches the terminal outcome
- the admin Tasks page shows the same state and summary you saw via API

## Prerequisites

- Agent Service is running locally or remotely
- a worker target is registered and online if you want to exercise worker-backed paths
- `jq` is installed for the shell examples
- `curl` is available

If you are running locally, these are the most useful endpoints:
- API base: `http://localhost:8080/api`
- frontend: `http://localhost:8080/`

If you use another host, export it first:

```sh
export AGENT_BASE_URL="http://localhost:8080/api"
```

## Quick Setup

Run these once at the start of a test session:

```sh
curl -sS "$AGENT_BASE_URL/health/" | jq
curl -sS "$AGENT_BASE_URL/v1/models" | jq '.data[].id'
curl -sS "$AGENT_BASE_URL/admin/execution-targets/" | jq
```

Healthy expectations:
- health responds successfully
- models include all four public agents
- at least one execution target is enabled

If you have a worker online, also check:

```sh
curl -sS "$AGENT_BASE_URL/admin/execution-targets/mbp-primary/health" | jq
```

Replace `mbp-primary` with your actual target ID.

## Reusable Shell Helpers

These helpers make it easier to run several prompts in one session.

```sh
chat() {
  local model="$1"
  local prompt="$2"
  curl -sS "$AGENT_BASE_URL/v1/chat/completions" \
    -H 'Content-Type: application/json' \
    -d "{
      \"model\": \"$model\",
      \"stream\": false,
      \"messages\": [
        {\"role\": \"user\", \"content\": \"$prompt\"}
      ]
    }"
}

task_id_from_chat() {
  jq -r '.task.id'
}

show_task() {
  local task_id="$1"
  curl -sS "$AGENT_BASE_URL/agent-tasks/$task_id" | jq
}

stream_task() {
  local task_id="$1"
  curl -N "$AGENT_BASE_URL/agent-tasks/$task_id/stream"
}
```

## Test Matrix

Run the cases below in order. That gives you a fast signal on broad system health before you move into approval and edge cases.

### 1. Planner: simple plan response

Prompt:

```text
Give me a 5-step rollout plan for adding task retries to this service.
```

Command:

```sh
chat planner "Give me a 5-step rollout plan for adding task retries to this service." | tee /tmp/planner.json
PLANNER_TASK_ID="$(cat /tmp/planner.json | task_id_from_chat)"
echo "$PLANNER_TASK_ID"
show_task "$PLANNER_TASK_ID"
```

Check:
- `task.state` is `completed` or `deferred_until_reset`
- the message content is a planning-style response or the deferred summary
- `runtime_key` is `planner_runtime`
- `stream_url` is present

If state is `deferred_until_reset`, also verify:
- the summary clearly says the backend is unavailable or deferred
- the task record matches that deferred state

### 2. Planner: stream terminal behavior

Prompt:

```text
Summarize the execution flow from Open WebUI to OpenCode in 3 bullets.
```

Command:

```sh
chat planner "Summarize the execution flow from Open WebUI to OpenCode in 3 bullets." | tee /tmp/planner-stream.json
PLANNER_STREAM_TASK_ID="$(cat /tmp/planner-stream.json | task_id_from_chat)"
stream_task "$PLANNER_STREAM_TASK_ID"
```

Check the SSE stream:
- you see `event: progress`
- the stream ends with `event: terminal`
- terminal status is `completed`, `deferred_until_reset`, `pending_approval`, `failed`, or `rejected`
- the stream does not hang indefinitely after the terminal event

### 3. RAG Analyst: uncertainty and evidence framing

Prompt:

```text
Analyze whether this system is ready for retrieval-augmented question answering, and separate evidence from assumptions.
```

Command:

```sh
chat rag-analyst "Analyze whether this system is ready for retrieval-augmented question answering, and separate evidence from assumptions." | tee /tmp/rag.json
RAG_TASK_ID="$(cat /tmp/rag.json | task_id_from_chat)"
show_task "$RAG_TASK_ID"
```

Check:
- `runtime_key` is `rag_analysis_runtime`
- the response distinguishes known facts from inference
- the task state resolves cleanly
- the task appears in the admin Recent Tasks page

### 4. Coder: implementation-oriented prompt

Prompt:

```text
Implement a small fix so deferred planner tasks always show a terminal status and completed timestamp.
```

Command:

```sh
chat coder "Implement a small fix so deferred planner tasks always show a terminal status and completed timestamp." | tee /tmp/coder.json
CODER_TASK_ID="$(cat /tmp/coder.json | task_id_from_chat)"
show_task "$CODER_TASK_ID"
```

Check:
- `runtime_key` is `coding_runtime`
- the task is routed as an implementation task
- if a worker is active, progress should include preflight and running events
- if the worker path succeeds, the summary should mention implementation work and validation

If you are running in dry-run mode:
- expect a synthetic completion summary
- confirm it still reaches a terminal task state

### 5. Reviewer: approval flow

Prompt:

```text
Review the recent routing changes and call out regressions, missing tests, and concrete remediation steps.
```

Command:

```sh
chat reviewer "Review the recent routing changes and call out regressions, missing tests, and concrete remediation steps." | tee /tmp/reviewer.json
REVIEWER_TASK_ID="$(cat /tmp/reviewer.json | task_id_from_chat)"
show_task "$REVIEWER_TASK_ID"
```

Check:
- `task.state` is usually `pending_approval` before execution
- `approve_url` and `reject_url` are present
- the stream can be opened even before approval

Approve it:

```sh
curl -sS "$AGENT_BASE_URL/agent-tasks/$REVIEWER_TASK_ID/approve" \
  -H 'Content-Type: application/json' \
  -d '{"decided_by":"manual-test","comment":"approved during prompt test"}' | jq
```

Reject-path test:

```sh
chat reviewer "Review these changes and decide if they are safe to ship." | tee /tmp/reviewer-reject.json
REVIEWER_REJECT_TASK_ID="$(cat /tmp/reviewer-reject.json | task_id_from_chat)"
curl -sS "$AGENT_BASE_URL/agent-tasks/$REVIEWER_REJECT_TASK_ID/reject" \
  -H 'Content-Type: application/json' \
  -d '{"decided_by":"manual-test","comment":"reject path validation"}' | jq
show_task "$REVIEWER_REJECT_TASK_ID"
```

Check:
- approved tasks leave `pending_approval`
- rejected tasks resolve to `rejected`
- both paths are reflected in the task record and stream

### 6. Direct task API: worker-backed prompt

This bypasses the OpenAI-compatible chat surface and talks directly to the task API.

Command:

```sh
TASK_ID=$(
  curl -sS "$AGENT_BASE_URL/agent-tasks/" \
    -H 'Content-Type: application/json' \
    -d '{
      "public_agent_id": "coder",
      "runtime_key": "coding_runtime",
      "task_class": "implement",
      "prompt": "Inspect the repo and describe where deferred task state is surfaced in the frontend.",
      "repo": "agent-service",
      "return_artifacts": ["summary"],
      "wait_for_completion": false
    }' | jq -r '.task.task_id'
)

echo "$TASK_ID"
stream_task "$TASK_ID"
show_task "$TASK_ID"
```

Check:
- the task exists immediately
- the stream emits progress
- the final task record has a terminal state

## Suggested Prompt Set

If you just want a compact smoke pass, use these six prompts:

1. `planner`: `Give me a short test plan for validating task streaming and terminal states.`
2. `planner`: `Summarize the request flow from /api/v1/chat/completions to /api/agent-tasks/{task_id}/stream.`
3. `rag-analyst`: `Analyze whether the service exposes enough state to debug failed worker executions.`
4. `coder`: `Implement a fix for a task record that never gets a completed timestamp.`
5. `reviewer`: `Review the recent task-state handling and identify missing regression tests.`
6. direct task API: `Inspect the repo and explain how execution targets are selected.`

## Admin UI Checks

After running the prompts above, open these pages:
- `/tasks`
- `/execution-targets`
- `/agents`

On `/tasks`, verify:
- every submitted prompt appears
- `Prompt Preview` matches the request
- `Completed` does not show `In progress` for terminal deferred tasks
- `Run Time` is populated for terminal tasks
- `Latest Event` matches the final meaningful stream event
- `Open Stream` opens a valid SSE endpoint

On `/execution-targets`, verify:
- your target shows `Online`
- `Last seen` is recent
- the supported tool list includes `agent.run_task`

## Failure Cases To Intentionally Check

These are worth testing because they tend to catch integration drift fast.

### Deferred planner path

Trigger this by running the planner when no suitable backend is available.

Expected:
- task state becomes `deferred_until_reset`
- the stream ends with a terminal event
- the task detail page does not keep showing `Running`

### Approval gating

Use the reviewer prompt without approving it.

Expected:
- `pending_approval` state
- approval links are present
- no misleading completed response is shown

### Rejection flow

Reject a reviewer task.

Expected:
- task state becomes `rejected`
- the stream terminates cleanly

### Worker unavailable

Disable your default worker or stop it temporarily, then submit a coder prompt.

Expected:
- you get a visible failure, queue stall, or deferred path
- the task record still remains inspectable

## Cleanup

If you want to review recent prompt runs:

```sh
curl -sS "$AGENT_BASE_URL/agent-tasks/?limit=20" | jq
```

If you want to disable a worker after testing:

```sh
curl -sS -X PATCH "$AGENT_BASE_URL/admin/execution-targets/<target_id>" \
  -H 'Content-Type: application/json' \
  -d '{"enabled": false, "is_default": false}' | jq
```

## Troubleshooting

If a request returns a task but no useful answer:
- read `GET /api/agent-tasks/{task_id}`
- stream `GET /api/agent-tasks/{task_id}/stream`
- check `/tasks` in the admin UI
- check worker health on `/api/admin/execution-targets/{target_id}/health`

If the stream never finishes:
- confirm the stream receives `event: terminal`
- compare the stream terminal status with the task record state
- check whether the task got stuck in `pending_approval`

If the reviewer flow does not pause for approval:
- confirm `review_runtime` still has `approval_mode: required`
- confirm the selected model was actually `reviewer`

If a terminal task still looks active in the UI:
- compare `state`, `completed_at`, and `duration_seconds` on the task record
- confirm the frontend task card reflects the same terminal state
