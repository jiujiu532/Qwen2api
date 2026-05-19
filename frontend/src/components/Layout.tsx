import { NavLink, Outlet, useNavigate } from "react-router-dom"

export function Layout() {
  const navigate = useNavigate()

  const handleLogout = () => {
    localStorage.removeItem("qwen2api_key")
    navigate("/login")
  }

  return (
    <div className="min-h-screen bg-[#FAF9F5]">
      {/* Header */}
      <header className="fixed top-0 left-0 right-0 z-50 bg-[#FAF9F5]">
        <div className="max-w-[1280px] w-full h-[54px] mx-auto px-7 grid grid-cols-[1fr_auto_1fr] items-center">
          {/* Brand */}
          <div className="flex items-center gap-2">
            <span className="text-[14px] font-bold">qwen2api</span>
          </div>

          {/* Nav */}
          <nav className="flex items-center gap-0">
            <NavLink to="/admin/accounts" className={({ isActive }) =>
              `text-[14px] px-3.5 py-1.5 font-medium transition-colors ${isActive ? 'text-[#111] font-semibold' : 'text-[#666] hover:text-[#111]'}`
            }>
              账户
            </NavLink>
            <NavLink to="/admin/config" className={({ isActive }) =>
              `text-[14px] px-3.5 py-1.5 font-medium transition-colors ${isActive ? 'text-[#111] font-semibold' : 'text-[#666] hover:text-[#111]'}`
            }>
              配置
            </NavLink>
            <NavLink to="/admin/register" className={({ isActive }) =>
              `text-[14px] px-3.5 py-1.5 font-medium transition-colors ${isActive ? 'text-[#111] font-semibold' : 'text-[#666] hover:text-[#111]'}`
            }>
              扩容
            </NavLink>
          </nav>

          {/* Right */}
          <div className="flex items-center justify-end gap-2">
            <span className="text-[11px] font-semibold px-2.5 h-7 rounded-full bg-[#f1ece2] text-[#6a6459] inline-flex items-center">
              v3.0
            </span>
            <button onClick={handleLogout} className="h-7 px-2.5 rounded-full text-[11px] font-semibold text-[#444] hover:bg-[#f1ece2] transition-colors">
              登出
            </button>
          </div>
        </div>
      </header>

      {/* Main */}
      <main className="max-w-[1280px] mx-auto pt-[78px] px-7 pb-6">
        <Outlet />
      </main>
    </div>
  )
}
