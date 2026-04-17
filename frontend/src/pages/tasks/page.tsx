import { useEffect, useState } from "react"

import { API_BASE_URL } from "@/config/env"
import { listAgentTasks, type AgentTaskSummary } from "@/features/tasks/api"

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
                <div>
                  <h3>{task.agent_id || "Unspecified Agent"}</h3>
                  <p>{task.task_id}</p>
                </div>
                <span className={stateClass(task.state)}>{task.state}</span>
              </div>

              <p className="task-card__prompt">{task.prompt}</p>

              <dl className="meta meta--three-up">
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
                  <p>{task.summary}</p>
                </div>
              ) : null}

              {task.last_event_message ? (
                <div className="task-card__summary">
                  <strong>Latest Event</strong>
                  <p>{task.last_event_message}</p>
                </div>
              ) : null}

              <div className="actions">
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
