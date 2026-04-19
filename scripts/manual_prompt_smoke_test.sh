#!/usr/bin/env bash

set -euo pipefail

AGENT_BASE_URL="${AGENT_BASE_URL:-http://localhost:8080/api}"
WORKER_TARGET_ID="${WORKER_TARGET_ID:-}"
REVIEWER_APPROVAL_MODE="${REVIEWER_APPROVAL_MODE:-approve}"
KEEP_TASK_OUTPUTS="${KEEP_TASK_OUTPUTS:-false}"

if ! command -v curl >/dev/null 2>&1; then
  echo "curl is required but not installed." >&2
  exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
  echo "jq is required but not installed." >&2
  exit 1
fi

WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/agent-service-smoke.XXXXXX")"
trap 'if [[ "${KEEP_TASK_OUTPUTS}" != "true" ]]; then rm -rf "${WORK_DIR}"; else echo "Kept smoke test artifacts in ${WORK_DIR}"; fi' EXIT

PASS_COUNT=0
WARN_COUNT=0
FAIL_COUNT=0

log() {
  printf '\n[%s] %s\n' "$1" "$2"
}

pass() {
  PASS_COUNT=$((PASS_COUNT + 1))
  printf '[PASS] %s\n' "$1"
}

warn() {
  WARN_COUNT=$((WARN_COUNT + 1))
  printf '[WARN] %s\n' "$1"
}

fail() {
  FAIL_COUNT=$((FAIL_COUNT + 1))
  printf '[FAIL] %s\n' "$1"
}

require_json_field() {
  local file="$1"
  local jq_filter="$2"
  local label="$3"
  local value
  value="$(jq -r "${jq_filter}" "${file}")"
  if [[ -z "${value}" || "${value}" == "null" ]]; then
    fail "${label} was missing."
    return 1
  fi
  pass "${label}: ${value}"
}

curl_json() {
  local method="$1"
  local url="$2"
  local output_file="$3"
  local body="${4:-}"

  local http_code
  if [[ -n "${body}" ]]; then
    http_code="$(
      curl -sS -o "${output_file}" -w '%{http_code}' \
        -X "${method}" \
        -H 'Content-Type: application/json' \
        "${url}" \
        -d "${body}"
    )"
  else
    http_code="$(
      curl -sS -o "${output_file}" -w '%{http_code}' \
        -X "${method}" \
        -H 'Content-Type: application/json' \
        "${url}"
    )"
  fi

  if [[ "${http_code}" -lt 200 || "${http_code}" -ge 300 ]]; then
    fail "Request failed for ${url} with HTTP ${http_code}."
    cat "${output_file}" >&2
    return 1
  fi
}

check_health() {
  log INFO "Checking API health at ${AGENT_BASE_URL}/health/"
  local out="${WORK_DIR}/health.json"
  curl_json GET "${AGENT_BASE_URL}/health/" "${out}"
  pass "Health endpoint responded successfully."
  cat "${out}" | jq .
}

check_models() {
  log INFO "Checking public model catalog."
  local out="${WORK_DIR}/models.json"
  curl_json GET "${AGENT_BASE_URL}/v1/models" "${out}"

  local expected=("planner" "rag-analyst" "coder" "reviewer")
  local model
  for model in "${expected[@]}"; do
    if jq -e --arg model "${model}" '.data[] | select(.id == $model)' "${out}" >/dev/null; then
      pass "Model '${model}' is present."
    else
      fail "Model '${model}' is missing."
    fi
  done

  cat "${out}" | jq '.data[].id'
}

check_execution_targets() {
  log INFO "Checking execution targets."
  local out="${WORK_DIR}/targets.json"
  curl_json GET "${AGENT_BASE_URL}/admin/execution-targets/" "${out}"

  local enabled_count
  enabled_count="$(jq '[.[] | select(.enabled == true)] | length' "${out}")"
  if [[ "${enabled_count}" -gt 0 ]]; then
    pass "Found ${enabled_count} enabled execution target(s)."
  else
    warn "No enabled execution targets were returned."
  fi

  if [[ -n "${WORKER_TARGET_ID}" ]]; then
    local health_out="${WORK_DIR}/worker-health.json"
    curl_json GET "${AGENT_BASE_URL}/admin/execution-targets/${WORKER_TARGET_ID}/health" "${health_out}"
    if jq -e '.online == true' "${health_out}" >/dev/null; then
      pass "Worker target '${WORKER_TARGET_ID}' is online."
    else
      warn "Worker target '${WORKER_TARGET_ID}' did not report online."
    fi
    cat "${health_out}" | jq .
  fi
}

submit_chat_task() {
  local name="$1"
  local model="$2"
  local prompt="$3"
  local out="${WORK_DIR}/${name}.json"

  log INFO "Submitting ${name} prompt with model '${model}'."
  curl_json POST "${AGENT_BASE_URL}/v1/chat/completions" "${out}" "$(jq -nc --arg model "${model}" --arg prompt "${prompt}" '{
    model: $model,
    stream: false,
    messages: [
      {role: "user", content: $prompt}
    ]
  }')"

  require_json_field "${out}" '.task.id' "${name} task id" || return 1
  require_json_field "${out}" '.task.state' "${name} task state" || return 1
  require_json_field "${out}" '.task.stream_url' "${name} stream url" || return 1

  local content
  content="$(jq -r '.choices[0].message.content // empty' "${out}")"
  if [[ -n "${content}" ]]; then
    pass "${name} returned assistant content."
  else
    warn "${name} response content was empty."
  fi
}

fetch_task_record() {
  local name="$1"
  local task_id="$2"
  local out="${WORK_DIR}/${name}-task.json"

  curl_json GET "${AGENT_BASE_URL}/agent-tasks/${task_id}" "${out}"
  require_json_field "${out}" '.state' "${name} record state" || return 1
  require_json_field "${out}" '.links.stream_url' "${name} public stream url" || return 1
}

stream_task() {
  local name="$1"
  local task_id="$2"
  local out="${WORK_DIR}/${name}-stream.txt"

  log INFO "Streaming task ${task_id} for ${name}."
  curl -sS -N "${AGENT_BASE_URL}/agent-tasks/${task_id}/stream" > "${out}"

  if grep -q 'event: terminal' "${out}"; then
    pass "${name} stream emitted a terminal event."
  else
    fail "${name} stream did not emit a terminal event."
  fi

  local terminal_status
  terminal_status="$(
    grep -A1 'event: terminal' "${out}" \
      | tail -n 1 \
      | sed 's/^data: //' \
      | jq -r '.status // empty' 2>/dev/null || true
  )"
  if [[ -n "${terminal_status}" ]]; then
    pass "${name} terminal status: ${terminal_status}"
  else
    warn "${name} terminal status could not be parsed."
  fi
}

compare_task_state() {
  local name="$1"
  local chat_file="${WORK_DIR}/${name}.json"
  local task_file="${WORK_DIR}/${name}-task.json"

  local create_state
  local task_state
  create_state="$(jq -r '.task.state' "${chat_file}")"
  task_state="$(jq -r '.state' "${task_file}")"

  if [[ "${create_state}" == "${task_state}" ]]; then
    pass "${name} create state matches task record state (${task_state})."
    return
  fi

  if [[ "${create_state}" == "pending_approval" && "${task_state}" == "pending_approval" ]]; then
    pass "${name} approval state matches."
    return
  fi

  warn "${name} create state (${create_state}) differed from task record state (${task_state})."
}

handle_reviewer_decision() {
  local task_id="$1"
  local decision="$2"
  local out="${WORK_DIR}/reviewer-decision.json"

  curl_json POST "${AGENT_BASE_URL}/agent-tasks/${task_id}/${decision}" "${out}" '{"decided_by":"manual-smoke-test","comment":"manual prompt smoke test"}'
  local state
  state="$(jq -r '.state // empty' "${out}")"
  if [[ -n "${state}" ]]; then
    pass "Reviewer ${decision} call returned state '${state}'."
  else
    warn "Reviewer ${decision} call did not include a visible state."
  fi
}

submit_direct_task() {
  local out="${WORK_DIR}/direct-task.json"
  local payload
  payload="$(jq -nc --arg target_id "${WORKER_TARGET_ID}" '{
    public_agent_id: "coder",
    runtime_key: "coding_runtime",
    task_class: "implement",
    prompt: "Inspect the repo and describe where deferred task state is surfaced in the frontend.",
    repo: "agent-service",
    return_artifacts: ["summary"],
    wait_for_completion: false
  } + (if $target_id == "" then {} else {target_id: $target_id} end)')"

  log INFO "Submitting direct task API request."
  curl_json POST "${AGENT_BASE_URL}/agent-tasks/" "${out}" "${payload}"

  require_json_field "${out}" '.task.task_id' "direct task id" || return 1
  require_json_field "${out}" '.task.state' "direct task state" || return 1
}

check_recent_tasks() {
  log INFO "Checking recent tasks."
  local out="${WORK_DIR}/recent-tasks.json"
  curl_json GET "${AGENT_BASE_URL}/agent-tasks/?limit=20" "${out}"

  local count
  count="$(jq '.items | length' "${out}")"
  if [[ "${count}" -gt 0 ]]; then
    pass "Recent tasks returned ${count} item(s)."
  else
    warn "Recent tasks returned no items."
  fi
}

run_case() {
  local name="$1"
  local model="$2"
  local prompt="$3"
  local expect_runtime="$4"

  submit_chat_task "${name}" "${model}" "${prompt}"

  local task_id
  task_id="$(jq -r '.task.id' "${WORK_DIR}/${name}.json")"
  fetch_task_record "${name}" "${task_id}"
  compare_task_state "${name}"
  stream_task "${name}" "${task_id}"

  local runtime_key
  runtime_key="$(jq -r '.runtime_key // empty' "${WORK_DIR}/${name}-task.json")"
  if [[ "${runtime_key}" == "${expect_runtime}" ]]; then
    pass "${name} runtime key matched ${expect_runtime}."
  else
    warn "${name} runtime key was '${runtime_key}', expected '${expect_runtime}'."
  fi

  local state
  state="$(jq -r '.state' "${WORK_DIR}/${name}-task.json")"
  case "${state}" in
    completed|deferred_until_reset|pending_approval|rejected|failed)
      pass "${name} ended in a recognized terminal or approval state (${state})."
      ;;
    *)
      warn "${name} ended in unexpected state '${state}'."
      ;;
  esac
}

main() {
  log INFO "Artifacts for this run will be stored in ${WORK_DIR}"

  check_health
  check_models
  check_execution_targets

  run_case \
    "planner" \
    "planner" \
    "Give me a short test plan for validating task streaming and terminal states." \
    "planner_runtime"

  run_case \
    "planner_stream" \
    "planner" \
    "Summarize the request flow from /api/v1/chat/completions to /api/agent-tasks/{task_id}/stream." \
    "planner_runtime"

  run_case \
    "rag_analyst" \
    "rag-analyst" \
    "Analyze whether the service exposes enough state to debug failed worker executions. Separate evidence from assumptions." \
    "rag_analysis_runtime"

  run_case \
    "coder" \
    "coder" \
    "Implement a fix for a task record that never gets a completed timestamp." \
    "coding_runtime"

  submit_chat_task \
    "reviewer" \
    "reviewer" \
    "Review the recent task-state handling and identify missing regression tests."

  local reviewer_task_id
  reviewer_task_id="$(jq -r '.task.id' "${WORK_DIR}/reviewer.json")"
  fetch_task_record "reviewer" "${reviewer_task_id}"
  compare_task_state "reviewer"
  stream_task "reviewer" "${reviewer_task_id}"

  local reviewer_state
  reviewer_state="$(jq -r '.state' "${WORK_DIR}/reviewer-task.json")"
  if [[ "${reviewer_state}" == "pending_approval" ]]; then
    pass "Reviewer task paused for approval as expected."
    if [[ "${REVIEWER_APPROVAL_MODE}" == "approve" || "${REVIEWER_APPROVAL_MODE}" == "reject" ]]; then
      handle_reviewer_decision "${reviewer_task_id}" "${REVIEWER_APPROVAL_MODE}"
    else
      warn "Skipping reviewer decision because REVIEWER_APPROVAL_MODE=${REVIEWER_APPROVAL_MODE}."
    fi
  else
    warn "Reviewer task did not enter pending_approval; actual state was '${reviewer_state}'."
  fi

  submit_direct_task
  local direct_task_id
  direct_task_id="$(jq -r '.task.task_id' "${WORK_DIR}/direct-task.json")"
  local direct_task_state
  direct_task_state="$(jq -r '.task.state' "${WORK_DIR}/direct-task.json")"
  pass "Direct task created with state '${direct_task_state}'."

  local direct_task_record="${WORK_DIR}/direct-task-record.json"
  curl_json GET "${AGENT_BASE_URL}/agent-tasks/${direct_task_id}" "${direct_task_record}"
  stream_task "direct_task" "${direct_task_id}"

  check_recent_tasks

  log INFO "Smoke test complete."
  printf 'Passes: %s\nWarnings: %s\nFailures: %s\n' "${PASS_COUNT}" "${WARN_COUNT}" "${FAIL_COUNT}"

  if [[ "${FAIL_COUNT}" -gt 0 ]]; then
    exit 1
  fi
}

main "$@"
