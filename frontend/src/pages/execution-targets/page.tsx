import { useEffect, useState } from "react"

import {
  createExecutionTarget,
  getExecutionTargetHealth,
  listExecutionJobs,
  listExecutionTargets,
  type ExecutionJob,
  type ExecutionTarget,
  type ExecutionTargetHealth,
  updateExecutionTarget,
} from "@/features/execution-targets/api"

type HealthMap = Record<string, ExecutionTargetHealth>

const INITIAL_FORM = {
  id: "",
  display_name: "",
  host: "",
  port: "22",
  user_name: "",
  repo_root: "",
  labels: "mac,worker",
  supported_tools: "agent.run_task",
  secret_ref: "",
  enabled: true,
  is_default: false,
}

export default function ExecutionTargetsPage() {
  const [targets, setTargets] = useState<ExecutionTarget[]>([])
  const [health, setHealth] = useState<HealthMap>({})
  const [jobs, setJobs] = useState<ExecutionJob[]>([])
  const [form, setForm] = useState(INITIAL_FORM)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [status, setStatus] = useState<string>("Loading execution targets...")

  async function refresh() {
    try {
      const nextTargets = await listExecutionTargets()
      setTargets(nextTargets)

      const healthResults = await Promise.allSettled(
        nextTargets.map(async (target) => [target.id, await getExecutionTargetHealth(target.id)] as const)
      )
      const nextHealth: HealthMap = {}
      let failedHealthChecks = 0
      for (const result of healthResults) {
        if (result.status === "fulfilled") {
          const [targetId, targetHealth] = result.value
          nextHealth[targetId] = targetHealth
        } else {
          failedHealthChecks += 1
        }
      }
      setHealth(nextHealth)

      try {
        const jobResponse = await listExecutionJobs()
        setJobs(jobResponse.items)
      } catch (error) {
        console.error("Failed to load execution jobs", error)
        setJobs([])
      }

      const targetLabel = `${nextTargets.length} execution target${nextTargets.length === 1 ? "" : "s"}`
      if (failedHealthChecks > 0) {
        setStatus(`Loaded ${targetLabel}, but ${failedHealthChecks} health check${failedHealthChecks === 1 ? "" : "s"} failed.`)
      } else {
        setStatus(`Loaded ${targetLabel}.`)
      }
    } catch (error) {
      console.error("Failed to load execution targets", error)
      setStatus(error instanceof Error ? error.message : "Failed to load execution targets.")
    }
  }

  useEffect(() => {
    void refresh()
  }, [])

  async function handleCreate(event: React.FormEvent) {
    event.preventDefault()
    const payload = {
      id: form.id,
      display_name: form.display_name,
      executor_type: "worker_agent",
      host: form.host || null,
      port: form.port ? Number(form.port) : null,
      user_name: form.user_name || null,
      repo_root: form.repo_root || null,
      labels: form.labels.split(",").map((part) => part.trim()).filter(Boolean),
      supported_tools: form.supported_tools.split(",").map((part) => part.trim()).filter(Boolean),
      secret_ref: form.secret_ref || null,
      enabled: form.enabled,
      is_default: form.is_default,
      metadata: {
        managed_by: "admin_ui",
        target_kind: form.labels.toLowerCase().includes("gpu")
          ? "gpu"
          : form.labels.toLowerCase().includes("mac")
            ? "macbook"
            : "generic",
        route_profile: form.labels.toLowerCase().includes("gpu") ? "gpu" : "code",
      },
    }
    if (editingId) {
      await updateExecutionTarget(editingId, payload)
    } else {
      await createExecutionTarget(payload)
    }
    setEditingId(null)
    setForm(INITIAL_FORM)
    await refresh()
  }

  async function toggleEnabled(target: ExecutionTarget) {
    await updateExecutionTarget(target.id, { enabled: !target.enabled })
    await refresh()
  }

  async function setAsDefault(target: ExecutionTarget) {
    await updateExecutionTarget(target.id, { is_default: true })
    await refresh()
  }

  function beginEdit(target: ExecutionTarget) {
    setEditingId(target.id)
    setForm({
      id: target.id,
      display_name: target.display_name,
      host: target.host || "",
      port: target.port ? String(target.port) : "22",
      user_name: target.user_name || "",
      repo_root: target.repo_root || "",
      labels: target.labels_json.join(","),
      supported_tools: target.supported_tools_json.join(","),
      secret_ref: target.secret_ref || "",
      enabled: target.enabled,
      is_default: target.is_default,
    })
  }

  return (
    <div className="page page--targets">
      <section className="hero hero--compact">
        <div>
          <p className="eyebrow">Execution Targets</p>
          <h1>Route work to your MacBook, GPU node, or future worker pool</h1>
          <p className="lede">
            Register worker-backed execution targets, assign secret references, and watch heartbeat health.
          </p>
        </div>
      </section>

      <section className="grid">
        <form className="panel panel--form" onSubmit={handleCreate}>
          <h2>{editingId ? "Edit Execution Target" : "Add Execution Target"}</h2>
          <label>
            Target ID
            <input
              value={form.id}
              disabled={Boolean(editingId)}
              onChange={(event) => setForm({ ...form, id: event.target.value })}
              required
            />
          </label>
          <label>
            Display Name
            <input
              value={form.display_name}
              onChange={(event) => setForm({ ...form, display_name: event.target.value })}
              required
            />
          </label>
          <label>
            Host
            <input value={form.host} onChange={(event) => setForm({ ...form, host: event.target.value })} />
          </label>
          <label>
            SSH Port
            <input value={form.port} onChange={(event) => setForm({ ...form, port: event.target.value })} />
          </label>
          <label>
            User
            <input value={form.user_name} onChange={(event) => setForm({ ...form, user_name: event.target.value })} />
          </label>
          <label>
            Repo Root
            <input value={form.repo_root} onChange={(event) => setForm({ ...form, repo_root: event.target.value })} />
          </label>
          <label>
            Labels
            <input value={form.labels} onChange={(event) => setForm({ ...form, labels: event.target.value })} />
          </label>
          <label>
            Supported Tools
            <input
              value={form.supported_tools}
              onChange={(event) => setForm({ ...form, supported_tools: event.target.value })}
            />
          </label>
          <label>
            Secret Ref
            <input
              value={form.secret_ref}
              onChange={(event) => setForm({ ...form, secret_ref: event.target.value })}
            />
          </label>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={form.enabled}
              onChange={(event) => setForm({ ...form, enabled: event.target.checked })}
            />
            Enabled
          </label>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={form.is_default}
              onChange={(event) => setForm({ ...form, is_default: event.target.checked })}
            />
            Make default target
          </label>
          <button type="submit">{editingId ? "Update Target" : "Save Target"}</button>
          {editingId ? (
            <button
              type="button"
              onClick={() => {
                setEditingId(null)
                setForm(INITIAL_FORM)
              }}
            >
              Cancel Edit
            </button>
          ) : null}
          <p className="status">{status}</p>
        </form>

        <div className="panel">
          <h2>Registered Targets</h2>
          <div className="target-list">
            {targets.map((target) => {
              const currentHealth = health[target.id]
              return (
                <article className="target-card" key={target.id}>
                  <div className="target-card__header">
                    <div>
                      <h3>{target.display_name}</h3>
                      <p>{target.id}</p>
                    </div>
                    <span className={`pill ${currentHealth?.online ? "pill--online" : "pill--offline"}`}>
                      {currentHealth?.online ? "Online" : "Offline"}
                    </span>
                  </div>
                  <dl className="meta">
                    <div><dt>Executor</dt><dd>{target.executor_type}</dd></div>
                    <div><dt>Host</dt><dd>{target.host || "n/a"}</dd></div>
                    <div><dt>Repo Root</dt><dd>{target.repo_root || "n/a"}</dd></div>
                    <div><dt>Secret Ref</dt><dd>{target.secret_ref || "n/a"}</dd></div>
                    <div><dt>Last Seen</dt><dd>{currentHealth?.last_seen_at || "never"}</dd></div>
                    <div><dt>Tools</dt><dd>{target.supported_tools_json.join(", ") || "n/a"}</dd></div>
                  </dl>
                  <div className="actions">
                    <button type="button" onClick={() => void toggleEnabled(target)}>
                      {target.enabled ? "Disable" : "Enable"}
                    </button>
                    <button type="button" onClick={() => void setAsDefault(target)}>
                      Set Default
                    </button>
                    <button type="button" onClick={() => beginEdit(target)}>
                      Edit
                    </button>
                  </div>
                  {target.metadata_json.last_heartbeat ? (
                    <div className="heartbeat">
                      <strong>Worker heartbeat:</strong>{" "}
                      {JSON.stringify(target.metadata_json.last_heartbeat)}
                    </div>
                  ) : null}
                </article>
              )
            })}
          </div>
        </div>
      </section>

      <section className="panel">
        <h2>Recent Execution Jobs</h2>
        <div className="jobs">
          {jobs.map((job) => (
            <article key={job.id} className="job-row">
              <div>
                <strong>{job.tool_name}</strong>
                <p>{job.id}</p>
              </div>
              <div>
                <span className={`pill ${job.status === "completed" ? "pill--online" : "pill--offline"}`}>
                  {job.status}
                </span>
              </div>
              <div>
                <p>Target: {job.target_id}</p>
                <p>Worker: {job.claimed_by || "unclaimed"}</p>
              </div>
            </article>
          ))}
        </div>
      </section>
    </div>
  )
}
