import { resolveApiUrl } from "@/config/env"

export type AgentWorkflowActionDefinition = {
  action: string
  to: string | null
  prompt: string | null
}

export type AgentWorkflowStepDefinition = {
  id: string
  title: string | null
  instructions: string
  run: string | null
  when: string | null
  output: string | null
  on_success: AgentWorkflowActionDefinition | null
  on_needs_changes: AgentWorkflowActionDefinition | null
  on_failure: AgentWorkflowActionDefinition | null
}

export type AgentWorkflowDefinition = {
  goal: string | null
  max_iterations: number
  entry_step: string | null
  handoff_to: string | null
  handoff_summary_prompt: string | null
  metadata: Record<string, unknown>
  steps: AgentWorkflowStepDefinition[]
}

export type AgentDefinition = {
  id: string
  display_name: string
  description: string
  supports_streaming: boolean
  requires_approval: boolean
  system_prompt: string | null
  workflow: AgentWorkflowDefinition | null
  runtime: string
}

export type RuntimeDefinition = {
  key: string
  task_class: string
  route_profile: string
  approval_mode: string
  prompt_preamble: string | null
}

export type AgentCatalogDefinition = {
  agents: AgentDefinition[]
  runtimes: RuntimeDefinition[]
}

export type AgentCatalogConfig = {
  default_path: string
  override_path: string
  has_override: boolean
  default_yaml: string
  override_yaml: string | null
  effective_yaml: string
  default_catalog: AgentCatalogDefinition
  override_catalog: AgentCatalogDefinition | null
  effective_catalog: AgentCatalogDefinition
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

export async function getAgentCatalogConfig(): Promise<AgentCatalogConfig> {
  return request("/platform/agents/config")
}

export async function saveAgentCatalog(catalog: AgentCatalogDefinition): Promise<AgentCatalogConfig> {
  return request("/platform/agents/config", {
    method: "PUT",
    body: JSON.stringify({ catalog }),
  })
}

export async function resetAgentCatalogOverride(): Promise<AgentCatalogConfig> {
  return request("/platform/agents/config/override", {
    method: "DELETE",
  })
}
