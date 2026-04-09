import type { ReactNode } from "react"

import Sidebar from "@/components/navigation/sidebar"

export default function Layout({ children }: { children: ReactNode }) {
  return (
    <div className="shell">
      <Sidebar />
      <main className="content">{children}</main>
    </div>
  )
}
