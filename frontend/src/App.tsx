import { BrowserRouter, Routes, Route } from "react-router-dom"
import { Toaster } from "sonner"
import AdminLayout from "./layouts/AdminLayout"
import Dashboard from "./pages/Dashboard"
import AccountsPage from "./pages/AccountsPage"
import TestPage from "./pages/TestPage"
import TokensPage from "./pages/TokensPage"
import SettingsPage from "./pages/SettingsPage"
import ImagePage from "./pages/ImagePage"
import LoginPage from "./pages/LoginPage"
import ExpansionPage from "./pages/ExpansionPage"

function App() {
  return (
    <>
      <Toaster position="top-center" richColors />
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/" element={<AdminLayout />}>
            <Route index element={<Dashboard />} />
            <Route path="accounts" element={<AccountsPage />} />
            <Route path="expansion" element={<ExpansionPage />} />
            <Route path="tokens" element={<TokensPage />} />
            <Route path="test" element={<TestPage />} />
            <Route path="images" element={<ImagePage />} />
            <Route path="settings" element={<SettingsPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </>
  )
}

export default App
