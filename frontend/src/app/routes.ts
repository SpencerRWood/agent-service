import type { ComponentType } from "react"

import ExecutionTargetsPage from "@/pages/execution-targets/page"
import HomePage from "@/pages/home/page"
import TasksPage from "@/pages/tasks/page"

export type AppRoute = {
  path: string
  label: string
  component: ComponentType
  showInNav?: boolean
}

export const appRoutes: AppRoute[] = [
  {
    path: "/",
    label: "Home",
    component: HomePage,
    showInNav: true,
  },
  {
    path: "/execution-targets",
    label: "Execution Targets",
    component: ExecutionTargetsPage,
    showInNav: true,
  },
  {
    path: "/tasks",
    label: "Tasks",
    component: TasksPage,
    showInNav: true,
  },
]
