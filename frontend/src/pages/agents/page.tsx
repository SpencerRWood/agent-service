import { useEffect, useState } from "react"

import {
  getAgentCatalogConfig,
  resetAgentCatalogOverride,
  updateAgentCatalogOverride,
  type AgentCatalogConfig,
} from "@/features/agents/api"

const EMPTY_OVERRIDE_MESSAGE = "# Add YAML overrides here.\n# Leave blank to use defaults only.\n"

export default function AgentsPage() {
  const [config, setConfig] = useState<AgentCatalogConfig | null>(null)
  const [editorValue, setEditorValue] = useState("")
  const [status, setStatus] = useState("Loading agent catalog...")
  const [isSaving, setIsSaving] = useState(false)

  useEffect(() => {
    async function refresh() {
      try {
        const nextConfig = await getAgentCatalogConfig()
        setConfig(nextConfig)
        setEditorValue(nextConfig.override_yaml ?? EMPTY_OVERRIDE_MESSAGE)
        setStatus(
          nextConfig.has_override
            ? "Loaded default catalog and active override."
            : "Loaded default catalog. No override file is active."
        )
      } catch (error) {
        console.error("Failed to load agent catalog config", error)
        setStatus(error instanceof Error ? error.message : "Failed to load agent catalog config.")
      }
    }

    void refresh()
  }, [])

  async function handleSave(event: React.FormEvent) {
    event.preventDefault()
    setIsSaving(true)
    try {
      const nextConfig = await updateAgentCatalogOverride(editorValue)
      setConfig(nextConfig)
      setEditorValue(nextConfig.override_yaml ?? EMPTY_OVERRIDE_MESSAGE)
      setStatus(
        nextConfig.has_override
          ? "Saved override YAML and refreshed the effective catalog."
          : "Override cleared. Using defaults only."
      )
    } catch (error) {
      console.error("Failed to save agent catalog override", error)
      setStatus(error instanceof Error ? error.message : "Failed to save agent catalog override.")
    } finally {
      setIsSaving(false)
    }
  }

  async function handleReset() {
    setIsSaving(true)
    try {
      const nextConfig = await resetAgentCatalogOverride()
      setConfig(nextConfig)
      setEditorValue(EMPTY_OVERRIDE_MESSAGE)
      setStatus("Removed the override file. The service is now using default agent config only.")
    } catch (error) {
      console.error("Failed to reset agent catalog override", error)
      setStatus(error instanceof Error ? error.message : "Failed to reset agent catalog override.")
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <div className="page">
      <section className="hero hero--compact">
        <div>
          <p className="eyebrow">Agent Config</p>
          <h1>Adjust agent workflows without editing the default catalog</h1>
          <p className="lede">
            The service treats <code>backend/config/agents.yaml</code> as the default catalog and applies an override file on top.
            Edit only the override YAML here, validate it through the API, and reset back to defaults whenever you want.
          </p>
        </div>
      </section>

      <section className="panel">
        <div className="config-page__header">
          <div>
            <h2>Override Editor</h2>
            <p className="status">{status}</p>
          </div>
          {config ? (
            <dl className="meta meta--three-up">
              <div>
                <dt>Default Path</dt>
                <dd>{config.default_path}</dd>
              </div>
              <div>
                <dt>Override Path</dt>
                <dd>{config.override_path}</dd>
              </div>
              <div>
                <dt>Active Override</dt>
                <dd>{config.has_override ? "Yes" : "No"}</dd>
              </div>
            </dl>
          ) : null}
        </div>

        <form className="config-editor" onSubmit={handleSave}>
          <label>
            Override YAML
            <textarea
              className="config-editor__textarea"
              value={editorValue}
              onChange={(event) => setEditorValue(event.target.value)}
              spellCheck={false}
              rows={24}
            />
          </label>
          <div className="actions">
            <button type="submit" disabled={isSaving}>
              {isSaving ? "Saving..." : "Save Override"}
            </button>
            <button type="button" disabled={isSaving} onClick={handleReset}>
              Reset To Defaults
            </button>
          </div>
        </form>
      </section>

      {config ? (
        <section className="config-grid">
          <article className="panel">
            <h2>Default YAML</h2>
            <p className="status">Read-only base catalog from the repository.</p>
            <pre className="config-preview">{config.default_yaml}</pre>
          </article>
          <article className="panel">
            <h2>Effective YAML</h2>
            <p className="status">Merged result after applying the override on top of the default catalog.</p>
            <pre className="config-preview">{config.effective_yaml}</pre>
          </article>
        </section>
      ) : null}
    </div>
  )
}
