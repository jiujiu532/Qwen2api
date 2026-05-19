import { useState, useEffect } from "react"
import { toast } from "sonner"
import { API_BASE } from "../lib/api"
import { getAuthHeader } from "../lib/auth"
import { Badge } from "../components/Badge"
import { Button } from "../components/Button"

interface Account {
  email: string
  status: string
  token: string
  last_used?: string
  error_count?: number
  consecutive_failures?: number
  rpm_1min?: number
}

export default function AccountsPage() {
  const [accounts, setAccounts] = useState<Account[]>([])
  const [filter, setFilter] = useState("all")
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(50)
  const [importToken, setImportToken] = useState("")
  const [showImport, setShowImport] = useState(false)

  const fetchAccounts = () => {
    fetch(`${API_BASE}/api/admin/accounts`, { headers: getAuthHeader() })
      .then(r => r.json())
      .then(d => setAccounts(d.accounts || []))
      .catch(() => toast.error("获取账号失败"))
  }

  useEffect(() => { fetchAccounts() }, [])

  const stats = {
    total: accounts.length,
    active: accounts.filter(a => a.status?.toUpperCase() === "VALID").length,
    cooling: accounts.filter(a => a.status?.toUpperCase() === "RATE_LIMITED").length,
    invalid: accounts.filter(a => ["AUTH_ERROR", "BANNED"].includes(a.status?.toUpperCase())).length,
    disabled: accounts.filter(a => a.status?.toUpperCase() === "DISABLED").length,
  }

  const filtered = filter === "all" ? accounts : accounts.filter(a => {
    const s = a.status?.toUpperCase()
    if (filter === "active") return s === "VALID"
    if (filter === "cooling") return s === "RATE_LIMITED"
    if (filter === "invalid") return ["AUTH_ERROR", "BANNED"].includes(s)
    if (filter === "disabled") return s === "DISABLED"
    return true
  })

  const totalPages = Math.ceil(filtered.length / pageSize)
  const paged = filtered.slice((page - 1) * pageSize, page * pageSize)

  const handleAdd = async () => {
    if (!importToken.trim()) return toast.error("请输入 Token")
    const tokens = importToken.trim().split("\n").filter(t => t.trim())
    if (tokens.length === 1) {
      await fetch(`${API_BASE}/api/admin/accounts`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...getAuthHeader() },
        body: JSON.stringify({ token: tokens[0].trim() })
      })
    } else {
      await fetch(`${API_BASE}/api/admin/accounts/batch`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...getAuthHeader() },
        body: JSON.stringify({ tokens: importToken.trim() })
      })
    }
    toast.success(`已导入 ${tokens.length} 个`)
    setImportToken("")
    setShowImport(false)
    fetchAccounts()
  }

  const handleDelete = async (email: string) => {
    await fetch(`${API_BASE}/api/admin/accounts/${encodeURIComponent(email)}`, {
      method: "DELETE", headers: getAuthHeader()
    })
    toast.success("已删除")
    fetchAccounts()
  }

  const handleVerify = async (email: string) => {
    const res = await fetch(`${API_BASE}/api/admin/accounts/${encodeURIComponent(email)}/verify`, {
      method: "POST", headers: getAuthHeader()
    })
    const d = await res.json()
    toast[d.valid ? "success" : "error"](d.valid ? "有效" : "无效")
    fetchAccounts()
  }

  const statusBadge = (status: string) => {
    const s = status?.toUpperCase()
    const map: Record<string, { variant: any; label: string }> = {
      VALID: { variant: "active", label: "正常" },
      RATE_LIMITED: { variant: "cooling", label: "限流" },
      AUTH_ERROR: { variant: "invalid", label: "异常" },
      BANNED: { variant: "invalid", label: "封禁" },
      DISABLED: { variant: "disabled", label: "禁用" },
    }
    const m = map[s] || { variant: "basic", label: status }
    return <Badge variant={m.variant}>{m.label}</Badge>
  }

  const maskToken = (t: string) => t ? `${t.slice(0, 10)}...${t.slice(-8)}` : "-"

  return (
    <div>
      {/* Page Header */}
      <div className="flex items-start justify-between mb-5">
        <div>
          <h1 className="text-[22px] font-bold leading-tight">账户管理</h1>
          <p className="text-[13px] text-[#8a8a8a] mt-1">管理 qwen2api 的 Qwen 账户池与运行状态</p>
        </div>
        <div className="flex gap-2">
          <Button variant="secondary" onClick={() => setShowImport(!showImport)}>导入</Button>
          <Button variant="primary" onClick={() => setShowImport(!showImport)}>+ 新增</Button>
        </div>
      </div>

      {/* Import Panel */}
      {showImport && (
        <div className="bg-white rounded-[14px] p-5 mb-5">
          <div className="text-[13px] font-semibold mb-1">新增账户</div>
          <p className="text-[11px] text-[#8a8a8a] mb-3">每行一个 Token，已存在的将自动跳过</p>
          <textarea
            value={importToken}
            onChange={e => setImportToken(e.target.value)}
            placeholder="粘贴 Token，每行一个..."
            className="w-full h-28 p-3 text-[12px] font-mono rounded-xl border border-[#e5e5e5] bg-[#fafafa] resize-y placeholder:text-[#999]"
          />
          <div className="flex justify-end gap-2 mt-3">
            <Button variant="secondary" onClick={() => setShowImport(false)}>取消</Button>
            <Button variant="primary" onClick={handleAdd}>导入账户</Button>
          </div>
        </div>
      )}

      {/* Section: 概览 */}
      <div className="text-[13px] font-semibold text-[#222] mb-3">概览</div>

      {/* Stats Row 1 */}
      <div className="grid grid-cols-5 gap-3 mb-3">
        <StatCell label="账户总数" value={stats.total} icon="user" />
        <StatCell label="正常账户" value={stats.active} color="#16a34a" icon="check" />
        <StatCell label="限流账户" value={stats.cooling} color="#ea580c" icon="clock" />
        <StatCell label="异常账户" value={stats.invalid} color="#dc2626" icon="x" />
        <StatCell label="禁用账户" value={stats.disabled} color="#6f675d" icon="ban" />
      </div>

      {/* Section: 账户列表 */}
      <div className="flex items-baseline justify-between mt-10 mb-3">
        <div className="flex items-center gap-2">
          <span className="text-[13px] font-semibold text-[#222]">账户列表</span>
          <span className="min-w-[20px] h-5 px-1.5 rounded-full bg-[#f1ece2] text-[#6a6459] text-[11px] font-semibold inline-flex items-center justify-center">
            {filtered.length}
          </span>
        </div>
      </div>

      {/* Toolbar */}
      <div className="flex items-center justify-between mb-2 text-[12px] text-[#8f8f8f]">
        <div className="flex items-center gap-1.5">
          <button onClick={() => setPage(Math.max(1, page - 1))} disabled={page <= 1}
            className="w-7 h-7 rounded-md inline-flex items-center justify-center hover:bg-[#e5e5e5] disabled:opacity-30">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="15 18 9 12 15 6"/></svg>
          </button>
          <span className="px-1 tabular-nums">第 {page} / {totalPages || 1} 页</span>
          <button onClick={() => setPage(Math.min(totalPages, page + 1))} disabled={page >= totalPages}
            className="w-7 h-7 rounded-md inline-flex items-center justify-center hover:bg-[#e5e5e5] disabled:opacity-30">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="9 18 15 12 9 6"/></svg>
          </button>
        </div>
        <div className="flex items-center gap-2">
          {/* Filter chips */}
          {[
            { key: "all", label: "全部", count: stats.total },
            { key: "active", label: "正常", count: stats.active },
            { key: "cooling", label: "限流", count: stats.cooling },
            { key: "invalid", label: "异常", count: stats.invalid },
          ].map(f => (
            <button key={f.key} onClick={() => { setFilter(f.key); setPage(1) }}
              className={`h-[26px] px-2.5 rounded-full text-[11px] font-medium flex items-center gap-1 transition-colors ${
                filter === f.key ? "bg-[#111] text-white" : "bg-[#f5f5f5] text-[#8f8f8f] hover:text-[#555]"
              }`}>
              <span>{f.label}</span>
              <span className={`min-w-[16px] h-4 px-1 rounded-full text-[10px] font-semibold inline-flex items-center justify-center ${
                filter === f.key ? "bg-white/20" : "bg-white/70"
              }`}>{f.count}</span>
            </button>
          ))}
          <select value={pageSize} onChange={e => { setPageSize(+e.target.value); setPage(1) }}
            className="h-7 px-2 rounded-full text-[11px] bg-[#fafafa] border-0">
            <option value={50}>50 / 页</option>
            <option value={100}>100 / 页</option>
            <option value={200}>200 / 页</option>
          </select>
        </div>
      </div>

      {/* Table */}
      <div className="bg-white rounded-[14px] overflow-x-auto shadow-[0_1px_3px_rgba(0,0,0,.04)]">
        <table className="w-full border-collapse min-w-[900px]">
          <thead>
            <tr>
              <th className="text-left text-[11px] font-medium text-[#9b9b9b] px-4 py-2.5 tracking-wide">TOKEN</th>
              <th className="text-left text-[11px] font-medium text-[#9b9b9b] px-4 py-2.5">运行状态</th>
              <th className="text-left text-[11px] font-medium text-[#9b9b9b] px-4 py-2.5">Email</th>
              <th className="text-right text-[11px] font-medium text-[#9b9b9b] px-4 py-2.5">操作</th>
            </tr>
          </thead>
          <tbody>
            {paged.length === 0 ? (
              <tr><td colSpan={4} className="text-center text-[13px] text-[#8a8a8a] py-12">暂无账号</td></tr>
            ) : paged.map(acc => (
              <tr key={acc.email} className="hover:bg-[#fdfdfd] transition-colors">
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2">
                    <span className="text-[12px] font-mono text-[#333]">{maskToken(acc.token)}</span>
                    <button onClick={() => { navigator.clipboard.writeText(acc.token); toast.success("已复制") }}
                      className="text-[#9a9a9a] hover:text-[#555]">
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
                    </button>
                  </div>
                </td>
                <td className="px-4 py-3">{statusBadge(acc.status)}</td>
                <td className="px-4 py-3 text-[12px] text-[#666]">{acc.email}</td>
                <td className="px-4 py-3">
                  <div className="flex items-center justify-end gap-2.5">
                    <button onClick={() => handleVerify(acc.email)} title="验证"
                      className="w-[22px] h-[22px] inline-flex items-center justify-center text-[#9a9a9a] hover:text-[#555]">
                      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M20 11a8 8 0 0 0-14.6-4.6"/><path d="M4 4v5h5"/><path d="M4 13a8 8 0 0 0 14.6 4.6"/><path d="M20 20v-5h-5"/></svg>
                    </button>
                    <button onClick={() => handleDelete(acc.email)} title="删除"
                      className="w-[22px] h-[22px] inline-flex items-center justify-center text-[#b7726a] hover:text-[#92514b]">
                      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}


// 统计卡片组件（仿 grok2api）
function StatCell({ label, value, color = "#111", icon }: { label: string; value: number; color?: string; icon?: string }) {
  const icons: Record<string, React.ReactNode> = {
    user: <svg viewBox="0 0 24 24" fill="none" strokeWidth="1.8" className="w-[15px] h-[15px] stroke-current"><path d="M4 19a4 4 0 0 1 4-4h8a4 4 0 0 1 4 4"/><circle cx="12" cy="8" r="4"/></svg>,
    check: <svg viewBox="0 0 24 24" fill="none" strokeWidth="1.9" className="w-[15px] h-[15px] stroke-current"><circle cx="12" cy="12" r="8"/><path d="m8.5 12 2.4 2.4 4.8-4.8"/></svg>,
    clock: <svg viewBox="0 0 24 24" fill="none" strokeWidth="1.8" className="w-[15px] h-[15px] stroke-current"><path d="M12 6v6l4 2"/><circle cx="12" cy="12" r="8"/></svg>,
    x: <svg viewBox="0 0 24 24" fill="none" strokeWidth="1.8" className="w-[15px] h-[15px] stroke-current"><path d="m15 9-6 6m0-6 6 6"/><circle cx="12" cy="12" r="8"/></svg>,
    ban: <svg viewBox="0 0 24 24" fill="none" strokeWidth="1.8" className="w-[15px] h-[15px] stroke-current"><circle cx="12" cy="12" r="8"/><path d="M8.5 8.5 15.5 15.5"/></svg>,
  }

  return (
    <div className="min-h-[88px] p-[14px_16px] rounded-xl bg-white shadow-[0_1px_3px_rgba(0,0,0,.04)] flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <span className="text-[11px] text-[#8a8a8a] tracking-wide">{label}</span>
        <span className="w-6 h-6 flex items-center justify-center" style={{ color: color === "#111" ? "#a3a3a3" : color }}>
          {icon && icons[icon]}
        </span>
      </div>
      <div className="text-[22px] font-semibold leading-none tracking-tight mt-auto" style={{ color }}>
        {value}
      </div>
    </div>
  )
}
