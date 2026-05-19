import { useState, useEffect } from "react"
import { toast } from "sonner"
import { API_BASE } from "../lib/api"
import { getAuthHeader } from "../lib/auth"
import { StatCard } from "../components/StatCard"
import { Badge } from "../components/Badge"
import { Button } from "../components/Button"
import { Card } from "../components/Card"

interface Account {
  email: string
  status: string
  token: string
  last_used?: string
  error_count?: number
}

export default function AccountsPage() {
  const [accounts, setAccounts] = useState<Account[]>([])
  const [filter, setFilter] = useState("all")
  const [importToken, setImportToken] = useState("")

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

  const handleAdd = async () => {
    if (!importToken.trim()) return toast.error("请输入 Token")
    const res = await fetch(`${API_BASE}/api/admin/accounts`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...getAuthHeader() },
      body: JSON.stringify({ token: importToken.trim() })
    })
    if (res.ok) {
      toast.success("添加成功")
      setImportToken("")
      fetchAccounts()
    } else {
      toast.error("添加失败")
    }
  }

  const handleDelete = async (email: string) => {
    const res = await fetch(`${API_BASE}/api/admin/accounts/${encodeURIComponent(email)}`, {
      method: "DELETE", headers: getAuthHeader()
    })
    if (res.ok) { toast.success("已删除"); fetchAccounts() }
    else toast.error("删除失败")
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

  const maskToken = (t: string) => t ? `${t.slice(0, 8)}...${t.slice(-6)}` : "-"

  return (
    <div>
      {/* Header */}
      <div className="flex items-start justify-between mb-5">
        <div>
          <h1 className="text-[22px] font-bold leading-tight">账户列表</h1>
          <p className="text-[13px] text-[#8a8a8a] mt-1">管理 Qwen 服务账户池</p>
        </div>
        <div className="flex gap-2">
          <Button variant="secondary" onClick={fetchAccounts}>刷新</Button>
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-5 gap-3 mb-5">
        <StatCard label="账户总数" value={stats.total} />
        <StatCard label="正常" value={stats.active} color="#16a34a" />
        <StatCard label="限流" value={stats.cooling} color="#ea580c" />
        <StatCard label="异常" value={stats.invalid} color="#dc2626" />
        <StatCard label="禁用" value={stats.disabled} color="#6f675d" />
      </div>

      {/* Add Token */}
      <Card className="mb-4">
        <div className="flex gap-2">
          <input
            value={importToken}
            onChange={e => setImportToken(e.target.value)}
            onKeyDown={e => e.key === "Enter" && handleAdd()}
            placeholder="粘贴 Token 快速添加..."
            className="flex-1 h-8 px-2.5 text-[12px] rounded-lg border border-[#e5e5e5] bg-white focus:border-[#bbb] placeholder:text-[#999] font-mono"
          />
          <Button variant="primary" onClick={handleAdd}>添加</Button>
        </div>
      </Card>

      {/* Filter */}
      <div className="flex gap-1.5 mb-3">
        {[
          { key: "all", label: "全部", count: stats.total },
          { key: "active", label: "正常", count: stats.active },
          { key: "cooling", label: "限流", count: stats.cooling },
          { key: "invalid", label: "异常", count: stats.invalid },
          { key: "disabled", label: "禁用", count: stats.disabled },
        ].map(f => (
          <button
            key={f.key}
            onClick={() => setFilter(f.key)}
            className={`h-[30px] min-w-[84px] px-3 rounded-full text-[12px] font-medium flex items-center justify-between gap-1.5 transition-colors ${
              filter === f.key ? "bg-[#111] text-white" : "bg-[#f5f5f5] text-[#8f8f8f] hover:text-[#555]"
            }`}
          >
            <span>{f.label}</span>
            <span className={`min-w-[18px] h-[18px] px-1 rounded-full text-[11px] font-semibold inline-flex items-center justify-center ${
              filter === f.key ? "bg-white/20 text-white" : "bg-white/70"
            }`}>{f.count}</span>
          </button>
        ))}
      </div>

      {/* Table */}
      <div className="bg-white rounded-[14px] overflow-x-auto">
        <table className="w-full border-collapse">
          <thead>
            <tr>
              <th className="text-left text-[11px] font-medium text-[#9b9b9b] px-4 py-2.5">Token</th>
              <th className="text-left text-[11px] font-medium text-[#9b9b9b] px-4 py-2.5">状态</th>
              <th className="text-left text-[11px] font-medium text-[#9b9b9b] px-4 py-2.5">Email</th>
              <th className="text-right text-[11px] font-medium text-[#9b9b9b] px-4 py-2.5">操作</th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 ? (
              <tr><td colSpan={4} className="text-center text-[13px] text-[#8a8a8a] py-12">暂无账号</td></tr>
            ) : filtered.map(acc => (
              <tr key={acc.email} className="hover:bg-[#fdfdfd]">
                <td className="px-4 py-3 text-[12px] font-mono text-[#333]">{maskToken(acc.token)}</td>
                <td className="px-4 py-3">{statusBadge(acc.status)}</td>
                <td className="px-4 py-3 text-[13px] text-[#3f3f3f]">{acc.email}</td>
                <td className="px-4 py-3 text-right">
                  <div className="flex items-center justify-end gap-2">
                    <button onClick={() => handleVerify(acc.email)} className="text-[11px] text-[#929292] hover:text-[#555]">验证</button>
                    <button onClick={() => handleDelete(acc.email)} className="text-[11px] text-[#b7726a] hover:text-[#92514b]">删除</button>
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
