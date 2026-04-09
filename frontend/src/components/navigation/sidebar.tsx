import { NavLink } from "react-router-dom"

import { appRoutes } from "@/app/routes"

export default function Sidebar() {
  return (
    <aside className="sidebar">
      <div className="sidebar__brand">
        <h1>Agent Service</h1>
        <p>Admin Console</p>
      </div>
      <nav className="sidebar__nav">
        {appRoutes
          .filter((route) => route.showInNav)
          .map((route) => (
            <NavLink
              key={route.path}
              className={({ isActive }) =>
                `sidebar__link${isActive ? " sidebar__link--active" : ""}`
              }
              to={route.path}
            >
              {route.label}
            </NavLink>
          ))}
      </nav>
    </aside>
  )
}
