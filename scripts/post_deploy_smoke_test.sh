#!/usr/bin/env bash

set -euo pipefail

AGENT_BASE_URL="${AGENT_BASE_URL:-https://agents.woodhost.cloud/api}"
WORKER_TARGET_ID="${WORKER_TARGET_ID:-}"
KEEP_TASK_OUTPUTS="${KEEP_TASK_OUTPUTS:-false}"
STREAM_TIMEOUT_SECONDS="${STREAM_TIMEOUT_SECONDS:-180}"

if ! command -v curl >/dev/null 2>&1; then
  echo "curl is required but not installed." >&2
  exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
  echo "jq is required but not installed." >&2
  exit 1
fi

WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/agent-service-post-deploy.XXXXXX")"
trap 'if [[ "${KEEP_TASK_OUTPUTS}" != "true" ]]; then rm -rf "${WORK_DIR}"; else echo "Kept post-deploy artifacts in ${WORK_DIR}"; fi' EXIT

PASS_COUNT=0
FAIL_COUNT=0

log() {
  printf '\n[%s] %s\n' "$1" "$2"
}

pass() {
  PASS_COUNT=$((PASS_COUNT + 1))
  printf '[PASS] %s\n' "$1"
}

fail() {
  FAIL_COUNT=$((FAIL_COUNT + 1))
  printf '[FAIL] %s\n' "$1" >&2
}

skip() {
  printf '[SKIP] %s\n' "$1"
  exit 0
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

require_jq() {
  local file="$1"
  local filter="$2"
  local message="$3"

  if jq -e "${filter}" "${file}" >/dev/null; then
    pass "${message}"
    return 0
  fi

  fail "${message}"
  jq . "${file}" >&2 || cat "${file}" >&2
  return 1
}

select_worker_target() {
  local targets_file="$1"

  if [[ -n "${WORKER_TARGET_ID}" ]]; then
    if jq -e --arg id "${WORKER_TARGET_ID}" '.[] | select(.id == $id and .enabled == true and (.supported_tools_json // [] | index("agent.run_task")))' "${targets_file}" >/dev/null; then
      printf '%s\n' "${WORKER_TARGET_ID}"
      return 0
    fi
    fail "WORKER_TARGET_ID=${WORKER_TARGET_ID} was not an enabled target supporting agent.run_task."
    return 1
  fi

  jq -r '
    [
      .[]
      | select(.enabled == true)
      | select((.supported_tools_json // []) | index("agent.run_task"))
    ]
    | sort_by(.is_default == true) | reverse | .[0].id // empty
  ' "${targets_file}"
}

check_health() {
  log INFO "Checking service health."
  local out="${WORK_DIR}/health.json"
  curl_json GET "${AGENT_BASE_URL}/health/" "${out}"
  require_jq "${out}" '.status == "ok"' "Health endpoint returned ok."
}

check_models() {
  log INFO "Checking required public models."
  local out="${WORK_DIR}/models.json"
  curl_json GET "${AGENT_BASE_URL}/v1/models" "${out}"
  require_jq "${out}" '.data[] | select(.id == "planner")' "planner model is present."
  require_jq "${out}" '.data[] | select(.id == "rag-analyst")' "rag-analyst model is present."
}

check_worker_target() {
  log INFO "Checking for an enabled worker target."
  local targets="${WORK_DIR}/targets.json"
  curl_json GET "${AGENT_BASE_URL}/admin/execution-targets/" "${targets}"

  local selected_target
  selected_target="$(select_worker_target "${targets}")"
  if [[ -z "${selected_target}" ]]; then
    skip "No enabled execution target supports agent.run_task; post-deploy agent smoke tests were not run."
  fi
  pass "Selected worker target '${selected_target}'."

  local health="${WORK_DIR}/worker-health.json"
  curl_json GET "${AGENT_BASE_URL}/admin/execution-targets/${selected_target}/health" "${health}"
  require_jq "${health}" '.online == true' "Worker target '${selected_target}' is online."

  printf '%s\n' "${selected_target}" > "${WORK_DIR}/selected-worker-target"
}

submit_chat_task() {
  local name="$1"
  local model="$2"
  local prompt="$3"
  local out="${WORK_DIR}/${name}.json"

  log INFO "Submitting ${name} task with model '${model}'."
  curl_json POST "${AGENT_BASE_URL}/v1/chat/completions" "${out}" "$(jq -nc --arg model "${model}" --arg prompt "${prompt}" '{
    model: $model,
    stream: false,
    messages: [{role: "user", content: $prompt}]
  }')"

  require_jq "${out}" '.task.id | strings | length > 0' "${name} returned a task id."
  require_jq "${out}" '.task.stream_url | strings | length > 0' "${name} returned a stream URL."
}

stream_task() {
  local name="$1"
  local task_id="$2"
  local out="${WORK_DIR}/${name}-stream.txt"

  log INFO "Streaming ${name} task ${task_id}."
  if ! curl -sS -N --max-time "${STREAM_TIMEOUT_SECONDS}" "${AGENT_BASE_URL}/agent-tasks/${task_id}/stream" > "${out}"; then
    fail "${name} stream failed or timed out."
    cat "${out}" >&2
    return 1
  fi

  if grep -q 'event: terminal' "${out}"; then
    pass "${name} stream emitted a terminal event."
  else
    fail "${name} stream did not emit a terminal event."
    cat "${out}" >&2
    return 1
  fi
}

assert_task_completed() {
  local name="$1"
  local task_id="$2"
  local out="${WORK_DIR}/${name}-task.json"

  curl_json GET "${AGENT_BASE_URL}/agent-tasks/${task_id}" "${out}"
  require_jq "${out}" '.state == "completed"' "${name} task completed."
}

assert_worker_path_used() {
  local name="$1"
  local stream_file="${WORK_DIR}/${name}-stream.txt"
  local selected_target
  selected_target="$(cat "${WORK_DIR}/selected-worker-target")"

  if grep -q 'agent.task.worker.claimed' "${stream_file}"; then
    pass "${name} was claimed by a worker."
  else
    fail "${name} did not emit a worker claimed event."
    cat "${stream_file}" >&2
    return 1
  fi

  if grep -q "\"dispatch_target\":\"${selected_target}\"" "${stream_file}" || grep -q "\"dispatch_target\": \"${selected_target}\"" "${stream_file}"; then
    pass "${name} dispatched to '${selected_target}'."
  else
    fail "${name} did not dispatch to '${selected_target}'."
    cat "${stream_file}" >&2
    return 1
  fi
}

run_worker_backed_smoke() {
  submit_chat_task \
    "rag-analyst-worker" \
    "rag-analyst" \
    "Analyze this post-deploy smoke test in two bullets. Do not edit files."

  local task_id
  task_id="$(jq -r '.task.id' "${WORK_DIR}/rag-analyst-worker.json")"
  stream_task "rag-analyst-worker" "${task_id}"
  assert_worker_path_used "rag-analyst-worker"
  assert_task_completed "rag-analyst-worker" "${task_id}"
}

run_planner_smoke() {
  submit_chat_task \
    "planner-inline" \
    "planner" \
    "Give me three concise post-deploy validation checks."

  local task_id
  task_id="$(jq -r '.task.id' "${WORK_DIR}/planner-inline.json")"
  stream_task "planner-inline" "${task_id}"
  assert_task_completed "planner-inline" "${task_id}"
}

main() {
  log INFO "Post-deploy artifacts for this run will be stored in ${WORK_DIR}"
  check_health
  check_worker_target
  check_models
  run_worker_backed_smoke
  run_planner_smoke

  log INFO "Post-deploy smoke test complete."
  printf 'Passes: %s\nFailures: %s\n' "${PASS_COUNT}" "${FAIL_COUNT}"

  if [[ "${FAIL_COUNT}" -gt 0 ]]; then
    exit 1
  fi
}

main "$@"
