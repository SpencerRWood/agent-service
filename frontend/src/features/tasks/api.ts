import { resolveApiUrl } from "@/config/env"

export type AgentTaskSummary = {
  task_id: string
  agent_id: string | null
  runtime_key: string | null
  task_kind: string
  task_class: string
  state: string
  approval_pending: boolean
  summary: string | null
  prompt: string
  execution_mode: string
  preferred_backend: string | null
  selected_backend: string | null
  target_id: string | null
  route_profile: string | null
  created_at: string
  completed_at: string | null
  duration_seconds: number | null
  last_event_message: string | null
  conversation_title: string | null
  conversation_tags: string[]
  follow_ups: string[]
  stream_url: string
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(resolveApiUrl(path), {
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

export async function listAgentTasks(limit = 40): Promise<{ items: AgentTaskSummary[] }> {
  return request(`/agent-tasks/?limit=${encodeURIComponent(String(limit))}`)
}
