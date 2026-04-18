import { resolveApiUrl } from "@/config/env"

export type AgentCatalogConfig = {
  default_path: string
  override_path: string
  has_override: boolean
  default_yaml: string
  override_yaml: string | null
  effective_yaml: string
  default_catalog: Record<string, unknown>
  override_catalog: Record<string, unknown> | null
  effective_catalog: Record<string, unknown>
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

export async function updateAgentCatalogOverride(yaml: string): Promise<AgentCatalogConfig> {
  return request("/platform/agents/config/override", {
    method: "PUT",
    body: JSON.stringify({ yaml }),
  })
}

export async function resetAgentCatalogOverride(): Promise<AgentCatalogConfig> {
  return request("/platform/agents/config/override", {
    method: "DELETE",
  })
}
