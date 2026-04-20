import { Outlet, Link, useLocation, useNavigate } from "react-router-dom"
import { Activity, Key, Settings, LayoutDashboard, MessageSquare, Menu, X, Image, LogOut, Sun, Moon, Zap } from "lucide-react"
import QCatIcon from "../components/QCatIcon"
import { useState, useEffect, useRef } from "react"
import { toast } from "sonner"
import { API_BASE } from "../lib/api"

export default function AdminLayout() {
  const loc = useLocation()
  const navigate = useNavigate()
  const [mobileOpen, setMobileOpen] = useState(false)
  const [isDark, setIsDark] = useState(true)

  // Auth check
  useEffect(() => {
    const key = localStorage.getItem('qwen2api_key')
    if (!key) {
      navigate("/login")
    }
  }, [navigate, loc.pathname])

  // SSE 告警订阅
  const sseRef = useRef<EventSource | null>(null)
  useEffect(() => {
    const key = localStorage.getItem('qwen2api_key')
    if (!key) return

    const connect = () => {
      const es = new EventSource(`${API_BASE}/api/admin/events?key=${key}`)
      sseRef.current = es

      es.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data)
          const type = data.type || ''
          const msg = data.message || ''
          if (type === 'account_banned') {
            toast.error(msg, { duration: 10000 })
          } else if (type === 'replenish_success') {
            toast.success(msg, { duration: 8000 })
          } else if (type === 'replenish_error') {
            toast.warning(msg, { duration: 8000 })
          } else if (type === 'replenish_stopped') {
            toast.error(msg, { duration: 15000 })
          } else if (type === 'account_removed') {
            toast.info(msg, { duration: 5000 })
          }
        } catch { }
      }

      es.onerror = () => {
        es.close()
        setTimeout(connect, 5000)  // 自动重连
      }
    }

    connect()
    return () => { sseRef.current?.close() }
  }, [])

  // Light mode color overrides — applied directly to <html> inline style
  // to guarantee they beat Tailwind v4's @theme (which generates unlayered :root vars)
  const lightColorOverrides: Record<string, string> = {
    '--color-background': 'hsl(210 40% 98%)',
    '--color-foreground': 'hsl(222.2 84% 4.9%)',
    '--color-card': 'hsl(0 0% 100%)',
    '--color-card-foreground': 'hsl(222.2 84% 4.9%)',
    '--color-popover': 'hsl(0 0% 100%)',
    '--color-popover-foreground': 'hsl(222.2 84% 4.9%)',
    '--color-primary': 'hsl(221.2 83.2% 53.3%)',
    '--color-primary-foreground': 'hsl(210 40% 98%)',
    '--color-secondary': 'hsl(210 40% 96.1%)',
    '--color-secondary-foreground': 'hsl(222.2 47.4% 11.2%)',
    '--color-muted': 'hsl(210 40% 96.1%)',
    '--color-muted-foreground': 'hsl(215.4 16.3% 46.9%)',
    '--color-accent': 'hsl(210 40% 96.1%)',
    '--color-accent-foreground': 'hsl(222.2 47.4% 11.2%)',
    '--color-destructive': 'hsl(0 84.2% 60.2%)',
    '--color-destructive-foreground': 'hsl(210 40% 98%)',
    '--color-border': 'hsl(214.3 31.8% 91.4%)',
    '--color-input': 'hsl(214.3 31.8% 91.4%)',
    '--color-ring': 'hsl(221.2 83.2% 53.3%)',
  }

  const applyTheme = (theme: string) => {
    const el = document.documentElement
    el.setAttribute('data-theme', theme)
    if (theme === 'light') {
      el.classList.remove('dark')
      Object.entries(lightColorOverrides).forEach(([k, v]) => el.style.setProperty(k, v))
    } else {
      el.classList.add('dark')
      Object.entries(lightColorOverrides).forEach(([k]) => el.style.removeProperty(k))
    }
  }

  // Theme support — apply on mount
  useEffect(() => {
    const saved = localStorage.getItem('theme') || 'dark'
    setIsDark(saved === 'dark')
    applyTheme(saved)
  }, [])

  const themeBtnRef = useRef<HTMLButtonElement>(null)
  const isAnimating = useRef(false)

  const toggleTheme = () => {
    if (isAnimating.current) return
    isAnimating.current = true

    const next = isDark ? 'light' : 'dark'
    const btn = themeBtnRef.current
    const rect = btn?.getBoundingClientRect()
    const x = rect ? rect.left + rect.width / 2 : window.innerWidth / 2
    const y = rect ? rect.top + rect.height / 2 : window.innerHeight / 2

    // Create overlay with the TARGET theme
    const overlay = document.createElement('div')
    overlay.style.cssText = `
      position: fixed; inset: 0; z-index: 99999;
      pointer-events: none;
      background: ${next === 'light' ? '#f0f4f8' : '#0d0e16'};
      clip-path: circle(0px at ${x}px ${y}px);
      transition: clip-path 0.35s cubic-bezier(0.4, 0, 0.2, 1);
    `
    document.body.appendChild(overlay)

    // Trigger the expansion
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        overlay.style.clipPath = `circle(200vmax at ${x}px ${y}px)`
      })
    })

    // Apply theme mid-animation (while overlay covers screen) to avoid any flash
    setTimeout(() => {
      setIsDark(!isDark)
      localStorage.setItem('theme', next)
      applyTheme(next)
    }, 200) // Apply at 200ms into the 350ms animation

    // When circle expansion ends, hold overlay then fade out
    overlay.addEventListener('transitionend', () => {
      // Hold overlay 100ms for browser to fully repaint under it
      setTimeout(() => {
        overlay.style.transition = 'opacity 0.15s ease'
        overlay.style.opacity = '0'
        setTimeout(() => {
          overlay.remove()
          isAnimating.current = false
        }, 150)
      }, 50)
    }, { once: true })
  }

  const handleLogout = () => {
    localStorage.removeItem('qwen2api_key')
    navigate("/login")
  }

  const navs = [
    { name: "核心监控", path: "/", icon: LayoutDashboard },
    { name: "批量注册", path: "/register", icon: Zap },
    { name: "账号列表", path: "/accounts", icon: Activity },
    { name: "密钥管理", path: "/tokens", icon: Key },
    { name: "Playground", path: "/playground", icon: MessageSquare },
    { name: "艺术创想", path: "/images", icon: Image },
    { name: "系统设置", path: "/settings", icon: Settings },
  ]

  return (
    <div className="flex min-h-screen w-full bg-background text-foreground transition-colors duration-500 overflow-hidden font-sans">
      {/* Mobile sidebar backdrop */}
      {mobileOpen && (
        <div
          className="fixed inset-0 bg-black/80 z-40 md:hidden backdrop-blur-3xl"
          onClick={() => setMobileOpen(false)}
        />
      )}

      <aside
        className={`sidebar-themed fixed md:static inset-y-0 left-0 w-72 flex-col flex z-50 border-r border-border/40 shadow-2xl ${isDark ? '' : 'shadow-indigo-500/10'} ${mobileOpen ? "translate-x-0" : "-translate-x-full md:translate-x-0"}`}
        style={{ transition: 'background-color 0.5s ease, color 0.5s ease, transform 0.3s ease' }}
      >
        <div className="h-24 flex items-center justify-between px-8">
          <div className="flex items-center gap-3">
            <div className="h-10 w-10 rounded-2xl flex items-center justify-center shadow-xl shadow-indigo-500/30">
              <QCatIcon className="h-10 w-10" />
            </div>
            <div className="font-black text-2xl tracking-tighter text-gradient">QWEN2API</div>
          </div>
          <button className="md:hidden text-muted-foreground p-2" onClick={() => setMobileOpen(false)}>
            <X className="h-6 w-6" />
          </button>
        </div>

        <nav className="flex-1 space-y-1.5 px-6 py-6 overflow-y-auto">
          {navs.map(n => {
            const active = loc.pathname === n.path || (n.path !== "/" && loc.pathname.startsWith(n.path))
            return (
              <Link
                key={n.path}
                to={n.path}
                onClick={() => setMobileOpen(false)}
                className={`flex items-center gap-4 px-5 py-4 rounded-2xl text-[13px] font-black tracking-wide transition-all ${active
                  ? "bg-primary/10 text-primary border border-primary/20 shadow-lg shadow-primary/5"
                  : "text-muted-foreground hover:bg-muted font-medium hover:text-foreground border border-transparent"
                  }`}
              >
                <n.icon className={`h-5 w-5 ${active ? "opacity-100" : "opacity-40"}`} />
                <span>{n.name}</span>
              </Link>
            )
          })}
        </nav>

        <div className="p-6 space-y-4">
          <div className="rounded-3xl p-5 bg-muted/20 border border-border/40 space-y-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-2xl bg-gradient-to-br from-neutral-800 to-neutral-500 flex items-center justify-center text-xs font-black text-white shadow-inner">AD</div>
              <div className="flex-1 min-w-0">
                <p className="text-[11px] font-medium truncate text-foreground/70">管理员</p>
                <p className="text-[9px] text-muted-foreground/50 font-medium">居安思危⋅长治久安</p>
              </div>
            </div>
            <button
              onClick={handleLogout}
              className="w-full h-10 flex items-center justify-center gap-2 rounded-xl bg-muted/40 hover:bg-rose-500/10 hover:text-rose-500 border border-border/40 transition-all font-black text-[11px]"
            >
              <LogOut className="w-3.5 h-3.5" />
              退出
            </button>

            {/* 主题切换移到这里 */}
            <button
              ref={themeBtnRef}
              onClick={toggleTheme}
              className="w-full h-10 flex items-center justify-center gap-3 rounded-xl bg-muted/30 hover:bg-muted/50 border border-border/40 transition-all text-sm font-semibold"
            >
              {isDark ? (
                <><Sun className="w-3.5 h-3.5 text-amber-500" /> 日光模式</>
              ) : (
                <><Moon className="w-3.5 h-3.5 text-indigo-500" /> 暗夜模式</>
              )}
            </button>
          </div>
        </div>

        {/* 版本号 */}
        <div className="px-6 pb-4">
          <div className="flex items-center justify-center h-9 rounded-2xl bg-indigo-500/10 text-indigo-400 text-[11px] font-medium">
            V2.0.0
          </div>
        </div>
      </aside>

      {/* Main Content */}
      <main className="flex-1 flex flex-col relative overflow-hidden h-screen bg-background">
        <header className="h-20 flex items-center justify-between px-8 border-b border-border/40 bg-background/60 backdrop-blur-3xl md:hidden z-10 shrink-0">
          <div className="flex items-center gap-3">
            <QCatIcon className="h-6 w-6" />
            <div className="font-black text-xl text-foreground tracking-tighter">QWEN2API</div>
          </div>
          <button className="text-muted-foreground p-2" onClick={() => setMobileOpen(true)}>
            <Menu className="h-7 w-7" />
          </button>
        </header>

        <div className="flex-1 overflow-y-auto relative px-6 py-6 md:px-12 md:py-12 custom-scrollbar">
          <Outlet />
        </div>
      </main>
    </div>
  )
}
