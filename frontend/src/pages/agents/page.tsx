import { useEffect, useState } from "react"

import {
  getBackendModelsConfig,
  getAgentCatalogConfig,
  resetBackendModels,
  resetAgentCatalogOverride,
  saveBackendModels,
  saveAgentCatalog,
  type AgentCatalogConfig,
  type AgentCatalogDefinition,
  type AgentDefinition,
  type AgentWorkflowActionDefinition,
  type AgentWorkflowDefinition,
  type AgentWorkflowStepDefinition,
  type BackendModelsConfig,
  type RuntimeDefinition,
} from "@/features/agents/api"

const BACKEND_MODEL_KEYS = ["local_llm", "codex", "copilot_cli"]

const TASK_CLASS_OPTIONS = [
  "classify_only",
  "answer_question",
  "summarize",
  "plan_only",
  "inspect_repo",
  "analyze",
  "implement",
  "refactor",
  "debug",
  "review",
  "test",
  "document",
]

const APPROVAL_MODE_OPTIONS = ["none", "required"]
const WORKFLOW_ACTION_OPTIONS = ["finish", "handoff", "loop", "retry"]

function createEmptyRuntime(index: number): RuntimeDefinition {
  return {
    key: `runtime_${index + 1}`,
    task_class: "implement",
    route_profile: "implementation",
    approval_mode: "none",
    prompt_preamble: "",
  }
}

function createEmptyWorkflowAction(action = "finish"): AgentWorkflowActionDefinition {
  return {
    action,
    to: null,
    prompt: null,
  }
}

function createEmptyWorkflowStep(index: number): AgentWorkflowStepDefinition {
  return {
    id: `step-${index + 1}`,
    title: "",
    instructions: "",
    run: "",
    when: "",
    output: "",
    on_success: createEmptyWorkflowAction("finish"),
    on_needs_changes: null,
    on_failure: createEmptyWorkflowAction("finish"),
  }
}

function createEmptyWorkflow(): AgentWorkflowDefinition {
  return {
    goal: "",
    max_iterations: 1,
    entry_step: "",
    handoff_to: "",
    handoff_summary_prompt: "",
    metadata: {},
    steps: [createEmptyWorkflowStep(0)],
  }
}

function createEmptyAgent(index: number, runtimeKey: string): AgentDefinition {
  return {
    id: `agent-${index + 1}`,
    display_name: `Agent ${index + 1}`,
    description: "",
    supports_streaming: true,
    requires_approval: false,
    system_prompt: "",
    workflow: null,
    runtime: runtimeKey,
  }
}

function cloneCatalog(catalog: AgentCatalogDefinition): AgentCatalogDefinition {
  return JSON.parse(JSON.stringify(catalog)) as AgentCatalogDefinition
}

function toOptionalString(value: string | null | undefined): string | null {
  const normalized = (value ?? "").trim()
  return normalized ? normalized : null
}

function normalizeAction(
  action: AgentWorkflowActionDefinition | null
): AgentWorkflowActionDefinition | null {
  if (!action) {
    return null
  }
  return {
    action: action.action.trim() || "finish",
    to: toOptionalString(action.to),
    prompt: toOptionalString(action.prompt),
  }
}

function normalizeStep(step: AgentWorkflowStepDefinition): AgentWorkflowStepDefinition {
  return {
    ...step,
    id: step.id.trim(),
    title: toOptionalString(step.title),
    instructions: step.instructions.trim(),
    run: toOptionalString(step.run),
    when: toOptionalString(step.when),
    output: toOptionalString(step.output),
    on_success: normalizeAction(step.on_success),
    on_needs_changes: normalizeAction(step.on_needs_changes),
    on_failure: normalizeAction(step.on_failure),
  }
}

function normalizeWorkflow(workflow: AgentWorkflowDefinition | null): AgentWorkflowDefinition | null {
  if (!workflow) {
    return null
  }
  return {
    ...workflow,
    goal: toOptionalString(workflow.goal),
    max_iterations: workflow.max_iterations || 1,
    entry_step: toOptionalString(workflow.entry_step),
    handoff_to: toOptionalString(workflow.handoff_to),
    handoff_summary_prompt: toOptionalString(workflow.handoff_summary_prompt),
    steps: workflow.steps.map(normalizeStep),
  }
}

function normalizeCatalog(catalog: AgentCatalogDefinition): AgentCatalogDefinition {
  return {
    agents: catalog.agents.map((agent) => ({
      ...agent,
      id: agent.id.trim(),
      display_name: agent.display_name.trim(),
      description: agent.description.trim(),
      system_prompt: toOptionalString(agent.system_prompt),
      runtime: agent.runtime.trim(),
      workflow: normalizeWorkflow(agent.workflow),
    })),
    runtimes: catalog.runtimes.map((runtime) => ({
      ...runtime,
      key: runtime.key.trim(),
      route_profile: runtime.route_profile.trim(),
      approval_mode: runtime.approval_mode.trim() || "none",
      prompt_preamble: toOptionalString(runtime.prompt_preamble),
    })),
  }
}

type ActionKey = "on_success" | "on_needs_changes" | "on_failure"

function ActionEditor({
  title,
  value,
  onChange,
}: {
  title: string
  value: AgentWorkflowActionDefinition | null
  onChange: (value: AgentWorkflowActionDefinition | null) => void
}) {
  const actionOptions = value
    ? Array.from(new Set([...WORKFLOW_ACTION_OPTIONS, value.action])).filter(Boolean)
    : WORKFLOW_ACTION_OPTIONS

  return (
    <div className="agent-config__action">
      <div className="agent-config__action-header">
        <strong>{title}</strong>
        <label className="checkbox">
          <input
            type="checkbox"
            checked={Boolean(value)}
            onChange={(event) => onChange(event.target.checked ? createEmptyWorkflowAction() : null)}
          />
          Enabled
        </label>
      </div>
      {value ? (
        <div className="agent-config__grid agent-config__grid--three">
          <label>
            Action
            <select value={value.action} onChange={(event) => onChange({ ...value, action: event.target.value })}>
              {actionOptions.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </label>
          <label>
            Route To
            <input value={value.to ?? ""} onChange={(event) => onChange({ ...value, to: event.target.value })} />
          </label>
          <label>
            Prompt
            <input
              value={value.prompt ?? ""}
              onChange={(event) => onChange({ ...value, prompt: event.target.value })}
            />
          </label>
        </div>
      ) : null}
    </div>
  )
}

export default function AgentsPage() {
  const [config, setConfig] = useState<AgentCatalogConfig | null>(null)
  const [catalog, setCatalog] = useState<AgentCatalogDefinition | null>(null)
  const [backendModelsConfig, setBackendModelsConfig] = useState<BackendModelsConfig | null>(null)
  const [backendModels, setBackendModels] = useState<Record<string, string>>({})
  const [status, setStatus] = useState("Loading agent catalog...")
  const [backendModelStatus, setBackendModelStatus] = useState("Loading backend model mappings...")
  const [isSaving, setIsSaving] = useState(false)
  const [isSavingBackendModels, setIsSavingBackendModels] = useState(false)

  useEffect(() => {
    async function refresh() {
      try {
        const [nextConfig, nextBackendModelsConfig] = await Promise.all([
          getAgentCatalogConfig(),
          getBackendModelsConfig(),
        ])
        setConfig(nextConfig)
        setCatalog(cloneCatalog(nextConfig.effective_catalog))
        setBackendModelsConfig(nextBackendModelsConfig)
        setBackendModels({ ...nextBackendModelsConfig.effective_models })
        setStatus(
          nextConfig.has_override
            ? "Loaded the database-backed agent catalog override."
            : "Loaded default catalog values from the repository."
        )
        setBackendModelStatus(
          nextBackendModelsConfig.override_models
            ? "Loaded database-backed backend model mappings."
            : "Loaded backend model mappings from environment defaults."
        )
      } catch (error) {
        console.error("Failed to load agent catalog config", error)
        setStatus(error instanceof Error ? error.message : "Failed to load agent catalog config.")
        setBackendModelStatus(error instanceof Error ? error.message : "Failed to load backend model mappings.")
      }
    }

    void refresh()
  }, [])

  function updateAgent(index: number, updater: (agent: AgentDefinition) => AgentDefinition) {
    setCatalog((current) => {
      if (!current) {
        return current
      }
      const agents = current.agents.map((agent, agentIndex) => (agentIndex === index ? updater(agent) : agent))
      return { ...current, agents }
    })
  }

  function updateRuntime(index: number, updater: (runtime: RuntimeDefinition) => RuntimeDefinition) {
    setCatalog((current) => {
      if (!current) {
        return current
      }
      const runtimes = current.runtimes.map((runtime, runtimeIndex) =>
        runtimeIndex === index ? updater(runtime) : runtime
      )
      return { ...current, runtimes }
    })
  }

  function updateWorkflowStep(
    agentIndex: number,
    stepIndex: number,
    updater: (step: AgentWorkflowStepDefinition) => AgentWorkflowStepDefinition
  ) {
    updateAgent(agentIndex, (agent) => {
      if (!agent.workflow) {
        return agent
      }
      return {
        ...agent,
        workflow: {
          ...agent.workflow,
          steps: agent.workflow.steps.map((step, currentStepIndex) =>
            currentStepIndex === stepIndex ? updater(step) : step
          ),
        },
      }
    })
  }

  function updateWorkflowAction(
    agentIndex: number,
    stepIndex: number,
    actionKey: ActionKey,
    value: AgentWorkflowActionDefinition | null
  ) {
    updateWorkflowStep(agentIndex, stepIndex, (step) => ({
      ...step,
      [actionKey]: value,
    }))
  }

  async function handleSave() {
    if (!catalog) {
      return
    }
    setIsSaving(true)
    try {
      const nextConfig = await saveAgentCatalog(normalizeCatalog(catalog))
      setConfig(nextConfig)
      setCatalog(cloneCatalog(nextConfig.effective_catalog))
      setStatus("Saved agent settings to the backend database and refreshed the effective catalog.")
    } catch (error) {
      console.error("Failed to save agent catalog", error)
      setStatus(error instanceof Error ? error.message : "Failed to save agent catalog.")
    } finally {
      setIsSaving(false)
    }
  }

  async function handleReset() {
    setIsSaving(true)
    try {
      const nextConfig = await resetAgentCatalogOverride()
      setConfig(nextConfig)
      setCatalog(cloneCatalog(nextConfig.effective_catalog))
      setStatus("Removed saved overrides and restored the default catalog from the repository.")
    } catch (error) {
      console.error("Failed to reset agent catalog override", error)
      setStatus(error instanceof Error ? error.message : "Failed to reset agent catalog override.")
    } finally {
      setIsSaving(false)
    }
  }

  async function handleSaveBackendModels() {
    setIsSavingBackendModels(true)
    try {
      const normalized = Object.fromEntries(
        Object.entries(backendModels)
          .map(([backend, model]) => [backend.trim(), model.trim()])
          .filter(([backend, model]) => backend && model)
      )
      const nextConfig = await saveBackendModels(normalized)
      setBackendModelsConfig(nextConfig)
      setBackendModels({ ...nextConfig.effective_models })
      setBackendModelStatus("Saved backend model mappings to the backend database.")
    } catch (error) {
      console.error("Failed to save backend model mappings", error)
      setBackendModelStatus(error instanceof Error ? error.message : "Failed to save backend model mappings.")
    } finally {
      setIsSavingBackendModels(false)
    }
  }

  async function handleResetBackendModels() {
    setIsSavingBackendModels(true)
    try {
      const nextConfig = await resetBackendModels()
      setBackendModelsConfig(nextConfig)
      setBackendModels({ ...nextConfig.effective_models })
      setBackendModelStatus("Reset backend model mappings to environment defaults.")
    } catch (error) {
      console.error("Failed to reset backend model mappings", error)
      setBackendModelStatus(error instanceof Error ? error.message : "Failed to reset backend model mappings.")
    } finally {
      setIsSavingBackendModels(false)
    }
  }

  function addAgent() {
    setCatalog((current) => {
      if (!current) {
        return current
      }
      const fallbackRuntime = current.runtimes[0]?.key ?? ""
      return {
        ...current,
        agents: [...current.agents, createEmptyAgent(current.agents.length, fallbackRuntime)],
      }
    })
  }

  function addRuntime() {
    setCatalog((current) => {
      if (!current) {
        return current
      }
      return {
        ...current,
        runtimes: [...current.runtimes, createEmptyRuntime(current.runtimes.length)],
      }
    })
  }

  return (
    <div className="page">
      <section className="hero hero--compact">
        <div>
          <p className="eyebrow">Agent Config</p>
          <h1>Edit agents as structured records and persist them in the backend database</h1>
          <p className="lede">
            This page treats <code>backend/config/agents.yaml</code> as the default catalog, then lets you save a
            database-backed override as editable agents, runtimes, and workflow loops. No YAML editing is required.
          </p>
        </div>
      </section>

      <section className="panel">
        <div className="config-page__header">
          <div>
            <h2>Catalog Editor</h2>
            <p className="status">{status}</p>
          </div>
          {config && catalog ? (
            <dl className="meta meta--three-up">
              <div>
                <dt>Default Path</dt>
                <dd>{config.default_path}</dd>
              </div>
              <div>
                <dt>Saved Override</dt>
                <dd>{config.has_override ? "Database record active" : "Using defaults only"}</dd>
              </div>
              <div>
                <dt>Current Catalog</dt>
                <dd>
                  {catalog.agents.length} agents / {catalog.runtimes.length} runtimes
                </dd>
              </div>
            </dl>
          ) : null}
        </div>

        <div className="actions">
          <button type="button" disabled={isSaving || !catalog} onClick={handleSave}>
            {isSaving ? "Saving..." : "Save Changes"}
          </button>
          <button type="button" disabled={isSaving} onClick={handleReset}>
            Reset To Defaults
          </button>
          <button type="button" disabled={!catalog} onClick={addAgent}>
            + Add Agent
          </button>
          <button type="button" disabled={!catalog} onClick={addRuntime}>
            + Add Runtime
          </button>
        </div>
      </section>

      <section className="panel">
        <div className="config-page__header">
          <div>
            <h2>Backend Models</h2>
            <p className="status">{backendModelStatus}</p>
          </div>
          {backendModelsConfig ? (
            <dl className="meta meta--three-up">
              <div>
                <dt>Default Source</dt>
                <dd>{Object.keys(backendModelsConfig.default_models).length ? ".env" : "None configured"}</dd>
              </div>
              <div>
                <dt>Saved Override</dt>
                <dd>{backendModelsConfig.override_models ? "Database record active" : "Using defaults only"}</dd>
              </div>
              <div>
                <dt>Mapped Backends</dt>
                <dd>{Object.keys(backendModelsConfig.effective_models).length}</dd>
              </div>
            </dl>
          ) : null}
        </div>

        <div className="agent-config__grid agent-config__grid--three">
          {BACKEND_MODEL_KEYS.map((backend) => (
            <label key={backend}>
              {backend}
              <input
                value={backendModels[backend] ?? ""}
                onChange={(event) =>
                  setBackendModels((current) => ({ ...current, [backend]: event.target.value }))
                }
                placeholder="provider/model"
              />
            </label>
          ))}
        </div>

        <div className="actions">
          <button type="button" disabled={isSavingBackendModels} onClick={handleSaveBackendModels}>
            {isSavingBackendModels ? "Saving..." : "Save Backend Models"}
          </button>
          <button type="button" disabled={isSavingBackendModels} onClick={handleResetBackendModels}>
            Reset Backend Models
          </button>
        </div>
      </section>

      {catalog ? (
        <div className="config-grid agent-config-layout">
          <section className="panel">
            <div className="agent-config__section-header">
              <div>
                <h2>Agents</h2>
                <p className="status">Edit each agent as its own persisted row with prompts, flags, and workflow steps.</p>
              </div>
            </div>
            <div className="agent-config__list">
              {catalog.agents.map((agent, agentIndex) => (
                <details className="agent-config__card" key={`${agent.id}-${agentIndex}`} open>
                  <summary className="agent-config__summary">
                    <div>
                      <strong>{agent.display_name || "Untitled Agent"}</strong>
                      <p>
                        {agent.id || "missing-id"} · {agent.runtime || "no runtime"}
                      </p>
                    </div>
                    <button
                      type="button"
                      className="button button--ghost"
                      onClick={(event) => {
                        event.preventDefault()
                        setCatalog((current) =>
                          current
                            ? { ...current, agents: current.agents.filter((_, index) => index !== agentIndex) }
                            : current
                        )
                      }}
                    >
                      Remove
                    </button>
                  </summary>

                  <div className="agent-config__body">
                    <div className="agent-config__grid agent-config__grid--three">
                      <label>
                        Agent ID
                        <input
                          value={agent.id}
                          onChange={(event) => updateAgent(agentIndex, (current) => ({ ...current, id: event.target.value }))}
                          required
                        />
                      </label>
                      <label>
                        Display Name
                        <input
                          value={agent.display_name}
                          onChange={(event) =>
                            updateAgent(agentIndex, (current) => ({ ...current, display_name: event.target.value }))
                          }
                          required
                        />
                      </label>
                      <label>
                        Runtime
                        <select
                          value={agent.runtime}
                          onChange={(event) => updateAgent(agentIndex, (current) => ({ ...current, runtime: event.target.value }))}
                        >
                          <option value="">Select runtime</option>
                          {catalog.runtimes.map((runtime) => (
                            <option key={runtime.key} value={runtime.key}>
                              {runtime.key}
                            </option>
                          ))}
                        </select>
                      </label>
                    </div>

                    <label>
                      Description
                      <input
                        value={agent.description}
                        onChange={(event) =>
                          updateAgent(agentIndex, (current) => ({ ...current, description: event.target.value }))
                        }
                      />
                    </label>

                    <label>
                      System Prompt
                      <textarea
                        rows={5}
                        value={agent.system_prompt ?? ""}
                        onChange={(event) =>
                          updateAgent(agentIndex, (current) => ({ ...current, system_prompt: event.target.value }))
                        }
                      />
                    </label>

                    <div className="agent-config__flags">
                      <label className="checkbox">
                        <input
                          type="checkbox"
                          checked={agent.supports_streaming}
                          onChange={(event) =>
                            updateAgent(agentIndex, (current) => ({
                              ...current,
                              supports_streaming: event.target.checked,
                            }))
                          }
                        />
                        Supports streaming
                      </label>
                      <label className="checkbox">
                        <input
                          type="checkbox"
                          checked={agent.requires_approval}
                          onChange={(event) =>
                            updateAgent(agentIndex, (current) => ({
                              ...current,
                              requires_approval: event.target.checked,
                            }))
                          }
                        />
                        Requires approval
                      </label>
                      <label className="checkbox">
                        <input
                          type="checkbox"
                          checked={Boolean(agent.workflow)}
                          onChange={(event) =>
                            updateAgent(agentIndex, (current) => ({
                              ...current,
                              workflow: event.target.checked ? current.workflow ?? createEmptyWorkflow() : null,
                            }))
                          }
                        />
                        Workflow enabled
                      </label>
                    </div>

                    {agent.workflow ? (
                      <div className="agent-config__workflow">
                        <div className="agent-config__workflow-header">
                          <h3>Workflow Loop</h3>
                          <button
                            type="button"
                            onClick={() =>
                              updateAgent(agentIndex, (current) => ({
                                ...current,
                                workflow: current.workflow
                                  ? {
                                      ...current.workflow,
                                      steps: [...current.workflow.steps, createEmptyWorkflowStep(current.workflow.steps.length)],
                                    }
                                  : current.workflow,
                              }))
                            }
                          >
                            + Add Step
                          </button>
                        </div>

                        <div className="agent-config__grid agent-config__grid--three">
                          <label>
                            Goal
                            <input
                              value={agent.workflow.goal ?? ""}
                              onChange={(event) =>
                                updateAgent(agentIndex, (current) => ({
                                  ...current,
                                  workflow: current.workflow
                                    ? { ...current.workflow, goal: event.target.value }
                                    : current.workflow,
                                }))
                              }
                            />
                          </label>
                          <label>
                            Entry Step
                            <input
                              value={agent.workflow.entry_step ?? ""}
                              onChange={(event) =>
                                updateAgent(agentIndex, (current) => ({
                                  ...current,
                                  workflow: current.workflow
                                    ? { ...current.workflow, entry_step: event.target.value }
                                    : current.workflow,
                                }))
                              }
                            />
                          </label>
                          <label>
                            Max Iterations
                            <input
                              type="number"
                              min={1}
                              value={agent.workflow.max_iterations}
                              onChange={(event) =>
                                updateAgent(agentIndex, (current) => ({
                                  ...current,
                                  workflow: current.workflow
                                    ? {
                                        ...current.workflow,
                                        max_iterations: Number(event.target.value) || 1,
                                      }
                                    : current.workflow,
                                }))
                              }
                            />
                          </label>
                        </div>

                        <div className="agent-config__grid agent-config__grid--two">
                          <label>
                            Default Handoff Target
                            <input
                              value={agent.workflow.handoff_to ?? ""}
                              onChange={(event) =>
                                updateAgent(agentIndex, (current) => ({
                                  ...current,
                                  workflow: current.workflow
                                    ? { ...current.workflow, handoff_to: event.target.value }
                                    : current.workflow,
                                }))
                              }
                            />
                          </label>
                          <label>
                            Handoff Summary Prompt
                            <input
                              value={agent.workflow.handoff_summary_prompt ?? ""}
                              onChange={(event) =>
                                updateAgent(agentIndex, (current) => ({
                                  ...current,
                                  workflow: current.workflow
                                    ? {
                                        ...current.workflow,
                                        handoff_summary_prompt: event.target.value,
                                      }
                                    : current.workflow,
                                }))
                              }
                            />
                          </label>
                        </div>

                        <div className="agent-config__steps">
                          {agent.workflow.steps.map((step, stepIndex) => (
                            <article className="agent-config__step" key={`${step.id}-${stepIndex}`}>
                              <div className="agent-config__workflow-header">
                                <h4>{step.title || step.id || `Step ${stepIndex + 1}`}</h4>
                                <button
                                  type="button"
                                  onClick={() =>
                                    updateAgent(agentIndex, (current) => ({
                                      ...current,
                                      workflow: current.workflow
                                        ? {
                                            ...current.workflow,
                                            steps: current.workflow.steps.filter((_, index) => index !== stepIndex),
                                          }
                                        : current.workflow,
                                    }))
                                  }
                                >
                                  Remove Step
                                </button>
                              </div>

                              <div className="agent-config__grid agent-config__grid--three">
                                <label>
                                  Step ID
                                  <input
                                    value={step.id}
                                    onChange={(event) =>
                                      updateWorkflowStep(agentIndex, stepIndex, (current) => ({
                                        ...current,
                                        id: event.target.value,
                                      }))
                                    }
                                  />
                                </label>
                                <label>
                                  Title
                                  <input
                                    value={step.title ?? ""}
                                    onChange={(event) =>
                                      updateWorkflowStep(agentIndex, stepIndex, (current) => ({
                                        ...current,
                                        title: event.target.value,
                                      }))
                                    }
                                  />
                                </label>
                                <label>
                                  Run Command
                                  <input
                                    value={step.run ?? ""}
                                    onChange={(event) =>
                                      updateWorkflowStep(agentIndex, stepIndex, (current) => ({
                                        ...current,
                                        run: event.target.value,
                                      }))
                                    }
                                  />
                                </label>
                              </div>

                              <label>
                                Instructions
                                <textarea
                                  rows={4}
                                  value={step.instructions}
                                  onChange={(event) =>
                                    updateWorkflowStep(agentIndex, stepIndex, (current) => ({
                                      ...current,
                                      instructions: event.target.value,
                                    }))
                                  }
                                />
                              </label>

                              <div className="agent-config__grid agent-config__grid--two">
                                <label>
                                  Condition
                                  <input
                                    value={step.when ?? ""}
                                    onChange={(event) =>
                                      updateWorkflowStep(agentIndex, stepIndex, (current) => ({
                                        ...current,
                                        when: event.target.value,
                                      }))
                                    }
                                  />
                                </label>
                                <label>
                                  Output Contract
                                  <input
                                    value={step.output ?? ""}
                                    onChange={(event) =>
                                      updateWorkflowStep(agentIndex, stepIndex, (current) => ({
                                        ...current,
                                        output: event.target.value,
                                      }))
                                    }
                                  />
                                </label>
                              </div>

                              <div className="agent-config__actions">
                                <ActionEditor
                                  title="On Success"
                                  value={step.on_success}
                                  onChange={(value) => updateWorkflowAction(agentIndex, stepIndex, "on_success", value)}
                                />
                                <ActionEditor
                                  title="On Needs Changes"
                                  value={step.on_needs_changes}
                                  onChange={(value) =>
                                    updateWorkflowAction(agentIndex, stepIndex, "on_needs_changes", value)
                                  }
                                />
                                <ActionEditor
                                  title="On Failure"
                                  value={step.on_failure}
                                  onChange={(value) => updateWorkflowAction(agentIndex, stepIndex, "on_failure", value)}
                                />
                              </div>
                            </article>
                          ))}
                        </div>
                      </div>
                    ) : null}
                  </div>
                </details>
              ))}
            </div>
          </section>

          <section className="panel">
            <div className="agent-config__section-header">
              <div>
                <h2>Runtimes</h2>
                <p className="status">Manage reusable execution presets that agents map onto.</p>
              </div>
            </div>
            <div className="agent-config__list">
              {catalog.runtimes.map((runtime, runtimeIndex) => {
                const taskClassOptions = Array.from(new Set([...TASK_CLASS_OPTIONS, runtime.task_class])).filter(Boolean)
                const approvalModeOptions = Array.from(
                  new Set([...APPROVAL_MODE_OPTIONS, runtime.approval_mode])
                ).filter(Boolean)

                return (
                <article className="agent-config__card" key={`${runtime.key}-${runtimeIndex}`}>
                  <div className="agent-config__summary agent-config__summary--static">
                    <div>
                      <strong>{runtime.key || "Untitled Runtime"}</strong>
                      <p>
                        {runtime.task_class} · {runtime.route_profile}
                      </p>
                    </div>
                    <button
                      type="button"
                      className="button button--ghost"
                      onClick={() =>
                        setCatalog((current) =>
                          current
                            ? { ...current, runtimes: current.runtimes.filter((_, index) => index !== runtimeIndex) }
                            : current
                        )
                      }
                    >
                      Remove
                    </button>
                  </div>

                  <div className="agent-config__body">
                    <div className="agent-config__grid agent-config__grid--two">
                      <label>
                        Runtime Key
                        <input
                          value={runtime.key}
                          onChange={(event) => updateRuntime(runtimeIndex, (current) => ({ ...current, key: event.target.value }))}
                          required
                        />
                      </label>
                      <label>
                        Route Profile
                        <input
                          value={runtime.route_profile}
                          onChange={(event) =>
                            updateRuntime(runtimeIndex, (current) => ({ ...current, route_profile: event.target.value }))
                          }
                          required
                        />
                      </label>
                    </div>

                    <div className="agent-config__grid agent-config__grid--two">
                      <label>
                        Task Class
                        <select
                          value={runtime.task_class}
                          onChange={(event) => updateRuntime(runtimeIndex, (current) => ({ ...current, task_class: event.target.value }))}
                        >
                          {taskClassOptions.map((option) => (
                            <option key={option} value={option}>
                              {option}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label>
                        Approval Mode
                        <select
                          value={runtime.approval_mode}
                          onChange={(event) =>
                            updateRuntime(runtimeIndex, (current) => ({ ...current, approval_mode: event.target.value }))
                          }
                        >
                          {approvalModeOptions.map((option) => (
                            <option key={option} value={option}>
                              {option}
                            </option>
                          ))}
                        </select>
                      </label>
                    </div>

                    <label>
                      Prompt Preamble
                      <textarea
                        rows={4}
                        value={runtime.prompt_preamble ?? ""}
                        onChange={(event) =>
                          updateRuntime(runtimeIndex, (current) => ({ ...current, prompt_preamble: event.target.value }))
                        }
                      />
                    </label>
                  </div>
                </article>
                )
              })}
            </div>
          </section>
        </div>
      ) : null}
    </div>
  )
}
