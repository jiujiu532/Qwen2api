import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom"
import { Toaster } from "sonner"
import { Layout } from "./components/Layout"
import LoginPage from "./pages/LoginPage"
import AccountsPage from "./pages/AccountsPage"
import ConfigPage from "./pages/ConfigPage"
import RegisterPage from "./pages/RegisterPage"

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const key = localStorage.getItem("qwen2api_key")
  if (!key) return <Navigate to="/login" replace />
  return <>{children}</>
}

export default function App() {
  return (
    <BrowserRouter>
      <Toaster position="top-center" richColors />
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/admin" element={<ProtectedRoute><Layout /></ProtectedRoute>}>
          <Route index element={<Navigate to="accounts" replace />} />
          <Route path="accounts" element={<AccountsPage />} />
          <Route path="config" element={<ConfigPage />} />
          <Route path="register" element={<RegisterPage />} />
        </Route>
        <Route path="*" element={<Navigate to="/admin/accounts" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
