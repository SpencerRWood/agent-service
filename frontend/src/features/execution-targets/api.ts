import { API_BASE_URL } from "@/config/env"

export type ExecutionTarget = {
  id: string
  display_name: string
  executor_type: string
  host: string | null
  port: number | null
  user_name: string | null
  repo_root: string | null
  labels_json: string[]
  supported_tools_json: string[]
  metadata_json: Record<string, unknown>
  secret_ref: string | null
  enabled: boolean
  is_default: boolean
  last_seen_at: string | null
  created_at: string
  updated_at: string
}

export type ExecutionTargetHealth = {
  target_id: string
  display_name: string
  enabled: boolean
  online: boolean
  executor_type: string
  last_seen_at: string | null
  labels: string[]
  supported_tools: string[]
}

export type ExecutionJob = {
  id: string
  target_id: string
  tool_name: string
  status: string
  payload_json: Record<string, unknown>
  result_json: Record<string, unknown> | null
  error_json: Record<string, unknown> | null
  claimed_by: string | null
  created_at: string
  claimed_at: string | null
  completed_at: string | null
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    ...init,
  })
  if (!response.ok) {
    const detail = await response.text()
    throw new Error(`Request failed: ${response.status}${detail ? ` ${detail}` : ""}`)
  }
  return response.json() as Promise<T>
}

export async function listExecutionTargets(): Promise<ExecutionTarget[]> {
  return request("/api/admin/execution-targets/")
}

export async function createExecutionTarget(payload: Record<string, unknown>): Promise<ExecutionTarget> {
  return request("/api/admin/execution-targets/", {
    method: "POST",
    body: JSON.stringify(payload),
  })
}

export async function updateExecutionTarget(
  id: string,
  payload: Record<string, unknown>
): Promise<ExecutionTarget> {
  return request(`/api/admin/execution-targets/${id}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  })
}

export async function getExecutionTargetHealth(id: string): Promise<ExecutionTargetHealth> {
  return request(`/api/admin/execution-targets/${id}/health`)
}

export async function listExecutionJobs(targetId?: string): Promise<{ items: ExecutionJob[] }> {
  const suffix = targetId ? `?target_id=${encodeURIComponent(targetId)}` : ""
  return request(`/api/admin/execution-jobs/${suffix}`)
}
