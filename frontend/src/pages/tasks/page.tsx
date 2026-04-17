import { useEffect, useState } from "react"

import { API_BASE_URL } from "@/config/env"
import { listAgentTasks, type AgentTaskSummary } from "@/features/tasks/api"

const PROMPT_PREVIEW_LENGTH = 220

function formatTimestamp(value: string | null): string {
  if (!value) {
    return "In progress"
  }
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value))
}

function formatDuration(seconds: number | null): string {
  if (seconds === null) {
    return "Running"
  }
  if (seconds < 1) {
    return "<1s"
  }
  if (seconds < 60) {
    return `${Math.round(seconds)}s`
  }
  if (seconds < 3600) {
    return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`
  }
  return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`
}

function stateClass(state: string): string {
  return state === "completed" ? "pill pill--online" : "pill pill--offline"
}

function formatLabel(value: string | null | undefined): string {
  if (!value) {
    return "n/a"
  }
  return value
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ")
}

function truncatePrompt(prompt: string): string {
  const normalized = prompt.replace(/\s+/g, " ").trim()
  if (normalized.length <= PROMPT_PREVIEW_LENGTH) {
    return normalized
  }
  return `${normalized.slice(0, PROMPT_PREVIEW_LENGTH).trimEnd()}...`
}

function formatStructuredText(value: string): string {
  try {
    return JSON.stringify(JSON.parse(value), null, 2)
  } catch {
    return value
  }
}

export default function TasksPage() {
  const [tasks, setTasks] = useState<AgentTaskSummary[]>([])
  const [status, setStatus] = useState("Loading recent tasks...")

  useEffect(() => {
    async function refresh() {
      try {
        const response = await listAgentTasks()
        setTasks(response.items)
        setStatus(`Loaded ${response.items.length} recent task${response.items.length === 1 ? "" : "s"}.`)
      } catch (error) {
        console.error("Failed to load recent tasks", error)
        setStatus(error instanceof Error ? error.message : "Failed to load recent tasks.")
      }
    }

    void refresh()
  }, [])

  return (
    <div className="page">
      <section className="hero hero--compact">
        <div>
          <p className="eyebrow">Task History</p>
          <h1>Recent agent runs across the control plane</h1>
          <p className="lede">
            Review recently executed tasks, see which agent and worker handled them, and inspect runtime details without digging through logs.
          </p>
        </div>
      </section>

      <section className="panel">
        <div className="tasks-header">
          <div>
            <h2>Recent Tasks</h2>
            <p className="status">{status}</p>
          </div>
        </div>
        <div className="tasks-list">
          {tasks.map((task) => (
            <article className="task-card" key={task.task_id}>
              <div className="task-card__header">
                <div className="task-card__identity">
                  <h3>{task.agent_id || "Unspecified Agent"}</h3>
                  <p className="task-card__id">{task.task_id}</p>
                  <div className="task-card__badges">
                    <span className="pill pill--neutral">{formatLabel(task.task_class)}</span>
                    <span className="pill pill--neutral">{formatLabel(task.runtime_key)}</span>
                    <span className="pill pill--neutral">{formatLabel(task.selected_backend || task.preferred_backend)}</span>
                  </div>
                </div>
                <span className={stateClass(task.state)}>{task.state}</span>
              </div>

              <div className="task-card__section">
                <p className="task-card__section-label">Prompt Preview</p>
                <p className="task-card__prompt">{truncatePrompt(task.prompt)}</p>
                <details className="task-card__details">
                  <summary>Show full prompt</summary>
                  <pre className="task-card__code">{formatStructuredText(task.prompt)}</pre>
                </details>
              </div>

              <dl className="meta meta--three-up task-card__stats">
                <div>
                  <dt>Runtime</dt>
                  <dd>{task.runtime_key || "n/a"}</dd>
                </div>
                <div>
                  <dt>Task Class</dt>
                  <dd>{task.task_class}</dd>
                </div>
                <div>
                  <dt>Execution Mode</dt>
                  <dd>{task.execution_mode}</dd>
                </div>
                <div>
                  <dt>Target</dt>
                  <dd>{task.target_id || "n/a"}</dd>
                </div>
                <div>
                  <dt>Backend</dt>
                  <dd>{task.selected_backend || task.preferred_backend || "n/a"}</dd>
                </div>
                <div>
                  <dt>Route Profile</dt>
                  <dd>{task.route_profile || "n/a"}</dd>
                </div>
                <div>
                  <dt>Created</dt>
                  <dd>{formatTimestamp(task.created_at)}</dd>
                </div>
                <div>
                  <dt>Completed</dt>
                  <dd>{formatTimestamp(task.completed_at)}</dd>
                </div>
                <div>
                  <dt>Run Time</dt>
                  <dd>{formatDuration(task.duration_seconds)}</dd>
                </div>
              </dl>

              {task.summary ? (
                <div className="task-card__summary">
                  <strong>Result</strong>
                  <pre className="task-card__code">{formatStructuredText(task.summary)}</pre>
                </div>
              ) : null}

              {task.last_event_message ? (
                <div className="task-card__summary">
                  <strong>Latest Event</strong>
                  <pre className="task-card__code">{formatStructuredText(task.last_event_message)}</pre>
                </div>
              ) : null}

              <div className="actions task-card__actions">
                <a
                  className="button-link"
                  href={`${API_BASE_URL}${task.stream_url}`}
                  target="_blank"
                  rel="noreferrer"
                >
                  Open Stream
                </a>
              </div>
            </article>
          ))}
        </div>
      </section>
    </div>
  )
}
