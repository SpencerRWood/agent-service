import { BrowserRouter, Route, Routes } from "react-router-dom"

import Layout from "./layout"
import { appRoutes } from "./routes"

export default function AppRouter() {
  return (
    <BrowserRouter>
      <Layout>
        <Routes>
          {appRoutes.map((route) => (
            <Route key={route.path} path={route.path} Component={route.component} />
          ))}
        </Routes>
      </Layout>
    </BrowserRouter>
  )
}
