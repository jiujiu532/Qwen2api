import { useEffect, useMemo, useState } from "react"
import { Trash2, RefreshCw, Bot, ShieldCheck, MailWarning, Activity, FileJson, ChevronLeft, ChevronRight, Search, CheckSquare, Square, XCircle, Lock, Save, ChevronDown } from "lucide-react"
import { Link } from "react-router-dom"
import { toast } from "sonner"
import { getAuthHeader } from "../lib/auth"
import { API_BASE } from "../lib/api"

// Global scrollbar styling
const scrollbarStyles = `
  ::-webkit-scrollbar {
    width: 6px;
    height: 6px;
  }
  ::-webkit-scrollbar-track {
    background: transparent;
  }
  ::-webkit-scrollbar-thumb {
    background: rgba(128, 128, 128, 0.2);
    border-radius: 10px;
  }
  ::-webkit-scrollbar-thumb:hover {
    background: rgba(99, 102, 241, 0.3);
  }
  * {
    scrollbar-width: thin;
    scrollbar-color: rgba(128, 128, 128, 0.2) transparent;
  }
`;

type AccountItem = {
  email: string
  password?: string
  token?: string
  username?: string
  valid?: boolean
  inflight?: number
  rate_limited_until?: number
  activation_pending?: boolean
  status_code?: string
  status_text?: string
  last_error?: string
}

function statusStyle(code?: string) {
  const c = (code || '').toUpperCase()
  switch (c) {
    case "VALID": case "valid":
      return "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 ring-emerald-500/20"
    case "RATE_LIMITED": case "rate_limited":
      return "bg-orange-500/10 text-orange-600 dark:text-orange-300 ring-orange-500/20"
    case "SOFT_ERROR":
      return "bg-amber-500/10 text-amber-600 dark:text-amber-400 ring-amber-500/20"
    case "CIRCUIT_OPEN":
      return "bg-red-500/10 text-red-600 dark:text-red-400 ring-red-500/20"
    case "HALF_OPEN":
      return "bg-yellow-500/10 text-yellow-600 dark:text-yellow-400 ring-yellow-500/20"
    case "BANNED": case "banned":
      return "bg-rose-500/10 text-rose-600 dark:text-rose-400 ring-rose-500/20"
    case "PENDING_REFRESH": case "pending_activation": case "auth_error":
      return "bg-slate-500/10 text-slate-600 dark:text-slate-300 ring-slate-500/20"
    default:
      return "bg-slate-500/10 text-slate-500 ring-slate-500/20"
  }
}

function statusText(acc: AccountItem) {
  const c = (acc.status_code || '').toUpperCase()
  switch (c) {
    case "VALID": case "valid": return "可用"
    case "RATE_LIMITED": case "rate_limited": return "限流中"
    case "SOFT_ERROR": return "软错误"
    case "CIRCUIT_OPEN": return "断路器"
    case "HALF_OPEN": return "半开"
    case "BANNED": case "banned": return "已封禁"
    case "PENDING_REFRESH": return "刷新中"
    case "pending_activation": return "待激活"
    case "auth_error": return "认证失败"
    default: return acc.valid ? "可用" : "失效"
  }
}


function localizeError(error?: string) {
  if (!error) return "未知错误"
  const lower = error.toLowerCase()
  if (lower.includes("activation already in progress")) return "账号正在激活中，请稍后刷新"
  if (lower.includes("activation link or token not found")) return "激活链接或令牌获取失败"
  if (lower.includes("token invalid") || lower.includes("token") || lower.includes("auth")) return "Token 无效或认证失败"
  return error
}

export default function AccountsPage() {
  const [accounts, setAccounts] = useState<AccountItem[]>([])
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [token, setToken] = useState("")
  const [verifying, setVerifying] = useState<string | null>(null)
  const [verifyingAll, setVerifyingAll] = useState(false)
  const [currentPage, setCurrentPage] = useState(1)
  const [pageSize, setPageSize] = useState(10)

  const [rawContent, setRawContent] = useState("")
  const [isMonitorLocked, setIsMonitorLocked] = useState(true)
  const [editedContent, setEditedContent] = useState("")
  const [searchTerm, setSearchTerm] = useState("")
  const [selectedEmails, setSelectedEmails] = useState<string[]>([])
  const [isPageSizeOpen, setIsPageSizeOpen] = useState(false)
  // 自动补号
  const [autoReplenish, setAutoReplenish] = useState(false)
  const [replenishTarget, setReplenishTarget] = useState(30)
  const [replenishConcurrency, setReplenishConcurrency] = useState(3)
  const [replenishSaving, setReplenishSaving] = useState(false)
  // 限流应急补号
  const [autoReplenishOnExhaust, setAutoReplenishOnExhaust] = useState(true)
  const [replenishExhaustCount, setReplenishExhaustCount] = useState(10)
  const [replenishExhaustConcurrency, setReplenishExhaustConcurrency] = useState(3)
  const [exhaustSaving, setExhaustSaving] = useState(false)

  const fetchReplenishSettings = () => {
    fetch(`${API_BASE}/api/admin/settings`, { headers: getAuthHeader() })
      .then(res => res.json())
      .then(data => {
        setAutoReplenish(!!data.auto_replenish)
        setReplenishTarget(data.replenish_target || 30)
        setReplenishConcurrency(data.replenish_concurrency || 3)
        setAutoReplenishOnExhaust(data.auto_replenish_on_exhaust !== false)
        setReplenishExhaustCount(data.replenish_exhaust_count || 10)
        setReplenishExhaustConcurrency(data.replenish_exhaust_concurrency || 3)
      })
      .catch(() => { })
  }

  const handleReplenishToggle = async (enabled: boolean) => {
    setReplenishSaving(true)
    try {
      const res = await fetch(`${API_BASE}/api/admin/settings`, {
        method: 'PUT', headers: { ...getAuthHeader(), 'Content-Type': 'application/json' },
        body: JSON.stringify({ auto_replenish: enabled, replenish_target: replenishTarget, replenish_concurrency: replenishConcurrency }),
      })
      if (!res.ok) throw new Error('Failed')
      setAutoReplenish(enabled)
      toast.success(enabled ? '自动补号已开启' : '自动补号已关闭')
    } catch {
      toast.error('保存补号设置失败')
    } finally {
      setReplenishSaving(false)
    }
  }

  const handleReplenishTargetSave = async () => {
    setReplenishSaving(true)
    try {
      const res = await fetch(`${API_BASE}/api/admin/settings`, {
        method: 'PUT', headers: { ...getAuthHeader(), 'Content-Type': 'application/json' },
        body: JSON.stringify({ replenish_target: replenishTarget, replenish_concurrency: replenishConcurrency }),
      })
      if (!res.ok) throw new Error('Failed')
      toast.success(`目标账号数已更新为 ${replenishTarget}`)
    } catch {
      toast.error('保存失败')
    } finally {
      setReplenishSaving(false)
    }
  }

  const handleExhaustToggle = async (enabled: boolean) => {
    setExhaustSaving(true)
    try {
      const res = await fetch(`${API_BASE}/api/admin/settings`, {
        method: 'PUT', headers: { ...getAuthHeader(), 'Content-Type': 'application/json' },
        body: JSON.stringify({ auto_replenish_on_exhaust: enabled, replenish_exhaust_count: replenishExhaustCount, replenish_exhaust_concurrency: replenishExhaustConcurrency }),
      })
      if (!res.ok) throw new Error('Failed')
      setAutoReplenishOnExhaust(enabled)
      toast.success(enabled ? '应急补号已开启' : '应急补号已关闭')
    } catch {
      toast.error('保存失败')
    } finally {
      setExhaustSaving(false)
    }
  }

  const handleExhaustCountSave = async () => {
    setExhaustSaving(true)
    try {
      const res = await fetch(`${API_BASE}/api/admin/settings`, {
        method: 'PUT', headers: { ...getAuthHeader(), 'Content-Type': 'application/json' },
        body: JSON.stringify({ replenish_exhaust_count: replenishExhaustCount, replenish_exhaust_concurrency: replenishExhaustConcurrency }),
      })
      if (!res.ok) throw new Error('Failed')
      toast.success(`应急补号配置已更新`)
    } catch {
      toast.error('保存失败')
    } finally {
      setExhaustSaving(false)
    }
  }

  const fetchAccounts = () => {
    fetch(`${API_BASE}/api/admin/accounts`, { headers: getAuthHeader() })
      .then(res => {
        if (!res.ok) throw new Error("unauthorized")
        return res.json()
      })
      .then(data => setAccounts(data.accounts || []))
      .catch(() => toast.error("刷新账号列表失败"))

    fetch(`${API_BASE}/api/admin/accounts/raw`, { headers: getAuthHeader() })
      .then(res => res.json())
      .then(data => {
        setRawContent(data.content || "");
        setEditedContent(data.content || "");
      })
  }

  useEffect(() => {
    fetchAccounts()
    fetchReplenishSettings()
  }, [])

  const stats = useMemo(() => {
    const result = { valid: 0, pending: 0, rateLimited: 0, banned: 0, invalid: 0 }
    for (const acc of accounts) {
      const c = (acc.status_code || '').toUpperCase()
      switch (c) {
        case "VALID": case "valid": result.valid++; break
        case "RATE_LIMITED": case "rate_limited": result.rateLimited++; break
        case "BANNED": case "banned": result.banned++; break
        case "PENDING_REFRESH": case "pending_activation": result.pending++; break
        case "SOFT_ERROR": case "CIRCUIT_OPEN": case "HALF_OPEN": result.invalid++; break
        default: if (acc.valid) result.valid++; else result.invalid++
      }
    }
    return result
  }, [accounts])

  const filteredAccounts = useMemo(() => {
    if (!searchTerm.trim()) return accounts;
    const lower = searchTerm.toLowerCase();
    return accounts.filter((acc: AccountItem) =>
      acc.email.toLowerCase().includes(lower) ||
      (acc.status_code || "").toLowerCase().includes(lower) ||
      statusText(acc).includes(searchTerm)
    );
  }, [accounts, searchTerm]);


  const handleAdd = () => {
    if (!token.trim()) return toast.error("请先填写 Token")
    const id = toast.loading("正在注入节点...")
    fetch(`${API_BASE}/api/admin/accounts`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...getAuthHeader() },
      body: JSON.stringify({ email: email || `manual_${Date.now()}@qwen`, password, token })
    }).then(res => res.json())
      .then(data => {
        if (data.ok) {
          toast.success("账号已加入集群", { id })
          setEmail(""); setPassword(""); setToken(""); fetchAccounts()
        } else {
          toast.error(localizeError(data.error) || "注入失败", { id })
        }
      })
      .catch(() => toast.error("请求失败", { id }))
  }

  const handleDelete = (targetEmail: string) => {
    const id = toast.loading(`正在移除 ${targetEmail}...`)
    fetch(`${API_BASE}/api/admin/accounts/${encodeURIComponent(targetEmail)}`, {
      method: "DELETE",
      headers: getAuthHeader(),
    }).then(res => {
      if (!res.ok) throw new Error("delete failed")
      toast.success("节点已移除", { id })
      fetchAccounts()
    }).catch(() => toast.error("移除失败", { id }))
  }

  const handleVerifyAll = () => {
    setVerifyingAll(true)
    const id = toast.loading("正在检测所有账号的有效性...")
    fetch(`${API_BASE}/api/admin/verify`, { method: "POST", headers: getAuthHeader() })
      .then(res => res.json())
      .then(data => {
        if (data.ok) toast.success(`检测完成，并发数: ${data.concurrency}`, { id })
        else toast.error("全量检测中断", { id })
        fetchAccounts()
      })
      .catch(() => toast.error("请求异常", { id }))
      .finally(() => setVerifyingAll(false))
  }

  const handleVerify = (targetEmail: string) => {
    setVerifying(targetEmail)
    const id = toast.loading(`正在验证 ${targetEmail}...`)
    fetch(`${API_BASE}/api/admin/accounts/${encodeURIComponent(targetEmail)}/verify`, { method: "POST", headers: getAuthHeader() })
      .then(res => res.json())
      .then(data => {
        if (data.valid) toast.success(`节点存活：${targetEmail}`, { id })
        else toast.error(`存活异常：${statusText(data)}`, { id })
        fetchAccounts()
      })
      .catch(() => toast.error("验证请求失败", { id }))
      .finally(() => setVerifying(null))
  }

  const handleToggleSelect = (email: string) => {
    setSelectedEmails(prev =>
      prev.includes(email) ? prev.filter(e => e !== email) : [...prev, email]
    )
  }

  const handleSelectAll = (currentSlice: AccountItem[]) => {
    const sliceEmails = currentSlice.map(a => a.email);
    const allSelected = sliceEmails.length > 0 && sliceEmails.every(e => selectedEmails.includes(e));
    if (allSelected) {
      setSelectedEmails(prev => prev.filter(e => !sliceEmails.includes(e)));
    } else {
      setSelectedEmails(prev => Array.from(new Set([...prev, ...sliceEmails])));
    }
  }

  const handleBatchDelete = async () => {
    if (selectedEmails.length === 0) return;
    if (!confirm(`确定要注销选中的 ${selectedEmails.length} 个账号吗？`)) return;

    const id = toast.loading(`正在批量注销 ${selectedEmails.length} 个账号...`);
    let success = 0;
    for (const email of selectedEmails) {
      try {
        const res = await fetch(`${API_BASE}/api/admin/accounts/${encodeURIComponent(email)}`, {
          method: "DELETE",
          headers: getAuthHeader(),
        });
        if (res.ok) success++;
      } catch (e) { }
    }
    toast.success(`成功注销 ${success} 个账号`, { id });
    setSelectedEmails([]);
    fetchAccounts();
  }

  const handleBatchVerify = async () => {
    if (selectedEmails.length === 0) return;
    const id = toast.loading(`正在批量验证 ${selectedEmails.length} 个账号...`);
    let success = 0;
    for (const email of selectedEmails) {
      try {
        const res = await fetch(`${API_BASE}/api/admin/accounts/${encodeURIComponent(email)}/verify`, {
          method: "POST",
          headers: getAuthHeader()
        });
        if (res.ok) success++;
      } catch (e) { }
    }
    toast.success(`验证已提交: ${success}/${selectedEmails.length}`, { id });
    setSelectedEmails([]);
    fetchAccounts();
  }

  const handleActivate = (targetEmail: string) => {
    const id = toast.loading(`正在激活 ${targetEmail}...`)
    fetch(`${API_BASE}/api/admin/accounts/${encodeURIComponent(targetEmail)}/activate`, {
      method: "POST",
      headers: getAuthHeader(),
    }).then(res => res.json())
      .then(data => {
        if (data.pending) {
          toast.success(`账号正在激活中，请稍后刷新：${targetEmail}`, { id, duration: 6000 })
        } else if (data.ok) {
          toast.success(data.message || `激活成功：${targetEmail}`, { id, duration: 6000 })
        } else {
          toast.error(`激活失败：${localizeError(data.error || data.message)}`, { id, duration: 8000 })
        }
        fetchAccounts()
      })
      .catch(() => toast.error("激活请求失败", { id }))
  }

  const handleSaveRaw = () => {
    const id = toast.loading("正在同步账号数据至磁盘...")
    fetch(`${API_BASE}/api/admin/accounts/raw`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...getAuthHeader() },
      body: JSON.stringify({ content: editedContent })
    }).then(res => res.json())
      .then(data => {
        if (data.ok) {
          toast.success("同步成功，集群已重载", { id })
          setIsMonitorLocked(true)
          fetchAccounts()
        } else {
          toast.error(data.detail || "同步失败", { id })
        }
      })
      .catch(() => toast.error("请求失败", { id }))
  }

  return (
    <div className="space-y-12 animate-fade-in-up max-w-[1400px] mx-auto">
      <style>{scrollbarStyles}</style>
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-6">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-indigo-500/10 flex items-center justify-center border border-indigo-500/20">
            <Bot className="w-5 h-5 text-indigo-500" />
          </div>
          <h2 className="text-3xl font-black tracking-tighter text-foreground">账号管理</h2>
        </div>
        <div className="flex gap-3">
          <button onClick={handleVerifyAll} disabled={verifyingAll} className="h-12 px-5 rounded-2xl bg-muted/30 border border-border/40 hover:bg-muted/50 transition-all flex items-center gap-2 font-semibold text-sm">
            <ShieldCheck className={`h-4 w-4 ${verifyingAll ? 'animate-pulse text-indigo-500' : ''}`} /> 一键检测
          </button>
        </div>
      </div>

      <div className="grid gap-6 grid-cols-2 md:grid-cols-5">
        {[
          { label: "就绪", value: stats.valid, color: "emerald", icon: ShieldCheck },
          { label: "待激活", value: stats.pending, color: "amber", icon: MailWarning },
          { label: "限流", value: stats.rateLimited, color: "orange", icon: Activity },
          { label: "风控", value: stats.banned, color: "rose", icon: Bot },
          { label: "失效", value: stats.invalid, color: "slate", icon: Trash2 },
        ].map((s, i) => (
          <div key={i} className="bg-card/50 backdrop-blur-xl p-6 rounded-[2rem] border border-border/40 flex flex-col items-center justify-center text-center group hover:scale-[1.02] transition-all">
            <span className="text-[11px] font-medium text-muted-foreground mb-3">{s.label}</span>
            <span className={`text-3xl font-black text-${s.color}-500 mb-2`}>{s.value}</span>
            <div className={`w-8 h-1 rounded-full bg-${s.color}-500/20 group-hover:bg-${s.color}-500/40 transition-colors`} />
          </div>
        ))}
      </div>

      <div className="grid gap-10 lg:grid-cols-2">
        <div className="bg-card/50 backdrop-blur-xl p-8 rounded-[2.5rem] border border-border/40 space-y-8">
          <div>
            <h3 className="text-xl font-black text-foreground">手动账号导入</h3>
            <p className="text-xs text-muted-foreground font-medium mt-1">将第三方持久化 Token 导入全局账号池。</p>
          </div>
          <div className="space-y-5">
            <div className="space-y-2">
              <label className="text-[11px] font-medium text-muted-foreground ml-1">访问令牌（Token / Authorization）</label>
              <input type="text" value={token} onChange={e => setToken(e.target.value)} className="w-full h-14 bg-muted/30 border border-border/40 rounded-2xl px-5 text-sm focus:ring-2 focus:ring-indigo-500/30 transition-all font-mono" placeholder="eyJhbGci..." />
            </div>
            <div className="grid grid-cols-2 gap-5">
              <div className="space-y-2">
                <label className="text-[11px] font-medium text-muted-foreground ml-1">关联邮箱</label>
                <input type="text" value={email} onChange={e => setEmail(e.target.value)} className="w-full h-14 bg-muted/30 border border-border/40 rounded-2xl px-5 text-sm" placeholder="qwen@api" />
              </div>
              <div className="space-y-2">
                <label className="text-[11px] font-medium text-muted-foreground ml-1">密码凭据</label>
                <input type="password" value={password} onChange={e => setPassword(e.target.value)} className="w-full h-14 bg-muted/30 border border-border/40 rounded-2xl px-5 text-sm font-mono text-indigo-500" />
              </div>
            </div>
            <button onClick={handleAdd} className="w-full h-14 rounded-2xl bg-foreground text-background font-black text-sm shadow-xl hover:scale-[1.01] transition-all">确认加入</button>
          </div>
        </div>

        {/* Raw JSON Data Monitor */}
        <div className="bg-card/50 backdrop-blur-xl p-8 rounded-[2.5rem] border border-indigo-500/20 flex flex-col h-[400px]">
          <div className="flex items-center justify-between mb-6">
            <div className="flex items-center gap-4">
              <div className="h-12 w-12 rounded-2xl bg-indigo-500/10 flex items-center justify-center text-indigo-500 border border-indigo-500/20">
                <FileJson className="h-6 w-6" />
              </div>
              <div>
                <h3 className="text-xl font-black text-foreground">账号可视化文件</h3>
                <p className="text-[10px] text-muted-foreground mt-1">accounts.json 实时预览</p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={() => {
                  if (!isMonitorLocked) {
                    handleSaveRaw();
                  } else {
                    setIsMonitorLocked(false);
                    setEditedContent(rawContent);
                    toast.info("已解除锁定，您可以直接编辑 JSON 数据");
                  }
                }}
                className={`p-3 rounded-xl border transition-all flex items-center gap-2 font-semibold text-[11px] ${isMonitorLocked
                  ? 'bg-muted/40 text-muted-foreground border-border/40 hover:bg-amber-500/10 hover:text-amber-500'
                  : 'bg-emerald-500 text-white border-emerald-400 shadow-lg shadow-emerald-500/20'
                  }`}
              >
                {isMonitorLocked ? <Lock className="h-4 w-4" /> : <Save className="h-4 w-4" />}
                {isMonitorLocked ? "解锁编辑" : "确认保存"}
              </button>
              {!isMonitorLocked && (
                <button
                  onClick={() => setIsMonitorLocked(true)}
                  className="p-3 rounded-xl bg-rose-500/10 text-rose-500 border border-rose-500/20 hover:bg-rose-500 hover:text-white transition-all"
                >
                  <XCircle className="h-4 w-4" />
                </button>
              )}
              <button
                onClick={fetchAccounts}
                className="p-3 rounded-xl bg-muted/40 text-muted-foreground border border-border/40 hover:bg-indigo-500/10 hover:text-indigo-500 transition-all"
              >
                <RefreshCw className="h-4 w-4" />
              </button>
            </div>
          </div>

          <div className="flex-1 bg-[#0a0b12] dark:bg-black/95 rounded-2xl border border-indigo-500/10 font-mono text-[11px] overflow-hidden leading-relaxed shadow-[inset_0_2px_10px_rgba(0,0,0,0.5)] flex flex-col">
            {isMonitorLocked ? (
              <div className="flex-1 p-5 overflow-auto scrollbar-thin scrollbar-thumb-indigo-500/30 scrollbar-track-transparent text-emerald-400/90 custom-scrollbar">
                <pre className="whitespace-pre">
                  {rawContent
                    ? rawContent.replace(/"([^"]+)":/g, '<span style="color: #818cf8">$1</span>:')
                      .split('<span').map((s, i) => i === 0 ? s : <span key={i} dangerouslySetInnerHTML={{ __html: '<span' + s }} />)
                    : "// Loading accounts.json..."}
                </pre>
              </div>
            ) : (
              <textarea
                value={editedContent}
                onChange={e => setEditedContent(e.target.value)}
                className="flex-1 w-full p-5 bg-transparent border-none focus:ring-0 text-amber-200/90 resize-none overflow-auto custom-scrollbar outline-none"
                placeholder='请输入 JSON 内容...'
              />
            )}
          </div>

          <div className="mt-5 flex items-center justify-between">
            <div className="flex items-center gap-2 text-[11px] font-medium text-muted-foreground">
              <div className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse" />
              直连本地文件系统
            </div>
            <Link to="/expansion" className="text-[10px] font-black text-indigo-500 hover:text-indigo-400 transition-colors flex items-center gap-1">
              前往扩容中心 <Bot className="h-3 w-3" />
            </Link>
          </div>
        </div>
      </div>

      {/* 自动补号面板 */}
      <div className="glass-card rounded-[2rem] p-8 border border-border/30">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h3 className="text-lg font-black tracking-tight">自动补号</h3>
            <p className="text-xs text-muted-foreground mt-1">当有账号被系统自动封禁时，自动注册新账号补充到目标数量。</p>
          </div>
          <button
            onClick={() => handleReplenishToggle(!autoReplenish)}
            disabled={replenishSaving}
            className={`relative inline-flex h-7 w-12 items-center rounded-full transition-colors duration-300 focus:outline-none ${autoReplenish ? 'bg-indigo-500' : 'bg-muted/50 border border-border/40'}`}
          >
            <span className={`inline-block h-5 w-5 transform rounded-full bg-white shadow-lg transition-transform duration-300 ${autoReplenish ? 'translate-x-6' : 'translate-x-1'}`} />
          </button>
        </div>
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <span className="text-[11px] font-medium text-muted-foreground">目标数量</span>
            <input
              type="number"
              min={1} max={500}
              value={replenishTarget}
              onChange={e => setReplenishTarget(Math.max(1, parseInt(e.target.value) || 30))}
              className="w-16 h-9 rounded-xl bg-muted/20 border border-border/40 text-center text-sm font-bold focus:ring-2 focus:ring-indigo-500/30 transition-all"
            />
          </div>
          <div className="flex items-center gap-2">
            <span className="text-[11px] font-medium text-muted-foreground">并发数</span>
            <input
              type="number"
              min={1} max={10}
              value={replenishConcurrency}
              onChange={e => setReplenishConcurrency(Math.max(1, parseInt(e.target.value) || 3))}
              className="w-14 h-9 rounded-xl bg-muted/20 border border-border/40 text-center text-sm font-bold focus:ring-2 focus:ring-indigo-500/30 transition-all"
            />
          </div>
          <button
            onClick={handleReplenishTargetSave}
            disabled={replenishSaving}
            className="h-9 px-4 rounded-xl bg-indigo-500/10 text-indigo-500 border border-indigo-500/20 font-semibold text-[11px] hover:bg-indigo-500/20 transition-all"
          >
            保存
          </button>
          <div className="ml-auto flex items-center gap-2">
            <span className="text-[11px] font-medium text-muted-foreground">当前有效</span>
            <span className={`text-sm font-black ${stats.valid >= replenishTarget ? 'text-emerald-500' : 'text-amber-500'}`}>
              {stats.valid} / {replenishTarget}
            </span>
          </div>
        </div>
      </div>

      {/* 限流应急补号面板 */}
      <div className="glass-card rounded-[2rem] p-8 border border-border/30">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h3 className="text-lg font-black tracking-tight">限流应急补号</h3>
            <p className="text-xs text-muted-foreground mt-1">当所有账号均被限流/耗尽时，自动注册指定数量的新账号应急补充。不同于常规补号，不以目标数量补充。</p>
          </div>
          <button
            onClick={() => handleExhaustToggle(!autoReplenishOnExhaust)}
            disabled={exhaustSaving}
            className={`relative inline-flex h-7 w-12 items-center rounded-full transition-colors duration-300 focus:outline-none ${autoReplenishOnExhaust ? 'bg-indigo-500' : 'bg-muted/50 border border-border/40'}`}
          >
            <span className={`inline-block h-5 w-5 transform rounded-full bg-white shadow-lg transition-transform duration-300 ${autoReplenishOnExhaust ? 'translate-x-6' : 'translate-x-1'}`} />
          </button>
        </div>
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <span className="text-[11px] font-medium text-muted-foreground">应急数量</span>
            <input
              type="number"
              min={1} max={100}
              value={replenishExhaustCount}
              onChange={e => setReplenishExhaustCount(Math.max(1, parseInt(e.target.value) || 10))}
              className="w-16 h-9 rounded-xl bg-muted/20 border border-border/40 text-center text-sm font-bold focus:ring-2 focus:ring-indigo-500/30 transition-all"
            />
          </div>
          <div className="flex items-center gap-2">
            <span className="text-[11px] font-medium text-muted-foreground">并发数</span>
            <input
              type="number"
              min={1} max={10}
              value={replenishExhaustConcurrency}
              onChange={e => setReplenishExhaustConcurrency(Math.max(1, parseInt(e.target.value) || 3))}
              className="w-14 h-9 rounded-xl bg-muted/20 border border-border/40 text-center text-sm font-bold focus:ring-2 focus:ring-indigo-500/30 transition-all"
            />
          </div>
          <button
            onClick={handleExhaustCountSave}
            disabled={exhaustSaving}
            className="h-9 px-4 rounded-xl bg-indigo-500/10 text-indigo-500 border border-indigo-500/20 font-semibold text-[11px] hover:bg-indigo-500/20 transition-all"
          >
            保存
          </button>
          <div className="ml-auto flex items-center gap-2">
            <span className={`text-[11px] font-medium ${autoReplenishOnExhaust ? 'text-emerald-500' : 'text-muted-foreground'}`}>
              {autoReplenishOnExhaust ? '已开启 — 耗尽时自动注册 ' + replenishExhaustCount + ' 个新号' : '已关闭'}
            </span>
          </div>
        </div>
      </div>

      <div className="glass-card rounded-[3rem] overflow-hidden">
        <div className="px-10 py-8 border-b border-border/40 bg-muted/5 flex flex-col lg:flex-row items-center justify-between gap-6">
          <h3 className="text-2xl font-black tracking-tighter text-foreground flex items-center gap-3">
            <div className="w-1.5 h-6 bg-indigo-500 rounded-full" />
            账号矩阵明细
            <span className="text-[11px] font-medium bg-indigo-500/10 text-indigo-500 px-3 py-1 rounded-full ml-3 select-none">{filteredAccounts.length} 个活跃账号</span>
          </h3>

          <div className="relative w-full lg:w-96">
            <Search className="absolute left-4 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <input
              type="text"
              placeholder="搜索邮箱、状态或关键词..."
              value={searchTerm}
              onChange={(e) => { setSearchTerm(e.target.value); setCurrentPage(1); }}
              className="w-full h-11 bg-muted/10 border border-border/40 rounded-xl pl-12 pr-5 text-xs focus:ring-2 focus:ring-indigo-500/30 transition-all outline-none"
            />
            {searchTerm && (
              <button onClick={() => setSearchTerm("")} className="absolute right-4 top-1/2 -translate-y-1/2">
                <XCircle className="h-4 w-4 text-muted-foreground hover:text-foreground" />
              </button>
            )}
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead>
              <tr className="bg-muted/10 border-b border-border/40">
                <th className="px-10 py-5 w-10">
                  {(() => {
                    const totalPages = Math.ceil(filteredAccounts.length / pageSize);
                    const safePage = Math.max(1, Math.min(currentPage, totalPages || 1));
                    const start = (safePage - 1) * pageSize;
                    const slice = filteredAccounts.slice(start, start + pageSize);
                    const allInSliceSelected = slice.length > 0 && slice.every(a => selectedEmails.includes(a.email));
                    return (
                      <button onClick={() => handleSelectAll(slice)} className="text-indigo-500 hover:scale-110 transition-transform">
                        {allInSliceSelected ? <CheckSquare className="h-5 w-5" /> : <Square className="h-5 w-5 opacity-40" />}
                      </button>
                    )
                  })()}
                </th>
                <th className="px-10 py-5 text-[11px] font-medium text-muted-foreground">邮箱账号</th>
                <th className="px-10 py-5 text-[11px] font-medium text-muted-foreground text-center">状态</th>
                <th className="px-10 py-5 text-[11px] font-medium text-muted-foreground">并发 / 请求负载</th>
                <th className="px-10 py-5 text-[11px] font-medium text-muted-foreground text-right">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/20">
              {accounts.length === 0 && (
                <tr>
                  <td colSpan={4} className="px-10 py-20 text-center text-muted-foreground font-medium">矩阵节点尚未接入，请执行初始化扩容...</td>
                </tr>
              )}
              {(() => {
                const totalPages = Math.ceil(filteredAccounts.length / pageSize);
                const safePage = Math.max(1, Math.min(currentPage, totalPages || 1));
                const start = (safePage - 1) * pageSize;
                const slice = filteredAccounts.slice(start, start + pageSize);

                if (filteredAccounts.length === 0) return (
                  <tr>
                    <td colSpan={5} className="px-10 py-20 text-center text-muted-foreground font-medium text-xs opacity-40">找不到匹配的账号数据...</td>
                  </tr>
                );

                return slice.map(acc => (
                  <tr key={acc.email} className={`group hover:bg-muted/10 transition-colors ${selectedEmails.includes(acc.email) ? 'bg-indigo-500/5' : ''}`}>
                    <td className="px-10 py-6">
                      <button onClick={() => handleToggleSelect(acc.email)} className="text-indigo-500 transition-all">
                        {selectedEmails.includes(acc.email) ? <CheckSquare className="h-5 w-5" /> : <Square className="h-5 w-5 opacity-20 group-hover:opacity-40" />}
                      </button>
                    </td>
                    <td className="px-10 py-6">
                      <div className="flex flex-col">
                        <span className="font-mono text-sm font-bold text-foreground/90 tracking-tight">{acc.email}</span>
                        <span className="text-[9px] text-muted-foreground font-medium mt-1.5 opacity-0 group-hover:opacity-100 transition-opacity">集群账号</span>
                      </div>
                    </td>
                    <td className="px-10 py-6 text-center">
                      <span className={`inline-flex items-center rounded-xl px-4 py-1.5 text-[10px] font-semibold border transition-all ${statusStyle(acc.status_code)}`}>
                        {statusText(acc)}
                      </span>
                    </td>
                    <td className="px-10 py-6">
                      <div className="flex items-center gap-3">
                        <div className="w-24 h-2 rounded-full bg-muted/30 overflow-hidden border border-border/40">
                          <div className="h-full bg-indigo-500 shadow-[0_0_12px_rgba(99,102,241,0.6)] transition-all duration-1000" style={{ width: `${Math.min(100, (acc.inflight || 0) * 20)}%` }} />
                        </div>
                        <span className="font-mono text-[10px] font-medium text-muted-foreground tracking-tight">{acc.inflight || 0} 活跃请求</span>
                      </div>
                    </td>
                    <td className="px-10 py-6 text-right">
                      <div className="flex items-center justify-end gap-3 opacity-40 group-hover:opacity-100 transition-opacity">
                        {acc.status_code !== "valid" && acc.status_code !== "rate_limited" && acc.status_code !== "banned" && (
                          <button onClick={() => handleActivate(acc.email)} className="p-3 rounded-xl bg-amber-500/10 text-amber-500 border border-amber-500/20 hover:bg-amber-500 hover:text-white transition-all" title="激活账号">
                            <MailWarning className="h-4 w-4" />
                          </button>
                        )}
                        <button onClick={() => handleVerify(acc.email)} disabled={verifying === acc.email} className="p-3 rounded-xl bg-indigo-500/10 text-indigo-500 border border-indigo-500/20 hover:bg-indigo-500 hover:text-white transition-all disabled:opacity-50" title="验证账号">
                          {verifying === acc.email ? <RefreshCw className="h-4 w-4 animate-spin" /> : <ShieldCheck className="h-4 w-4" />}
                        </button>
                        <button onClick={() => handleDelete(acc.email)} className="p-3 rounded-xl bg-muted/40 text-muted-foreground border border-border/40 hover:bg-rose-500/10 hover:text-rose-500 transition-all" title="注销账号">
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </div>
                    </td>
                  </tr>
                ));
              })()}
            </tbody>
          </table>
        </div>

        {/* Advanced Pagination UI - Precision Reordered */}
        <div className="px-10 py-8 border-t border-border/40 bg-muted/5 flex flex-col lg:flex-row items-center justify-end gap-x-8 gap-y-6">
          {/* 1. 总页数 */}
          <div className="flex items-center gap-2">
            <span className="text-[11px] font-medium text-muted-foreground opacity-80">
              共 {Math.ceil(filteredAccounts.length / pageSize)} 页
            </span>
          </div>

          {/* 2. 导航按钮组 */}
          <div className="flex items-center gap-1.5">
            <button
              onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
              disabled={currentPage === 1}
              className="w-10 h-10 rounded-xl border border-border/40 flex items-center justify-center hover:bg-indigo-500 hover:text-white hover:border-indigo-400 disabled:opacity-20 transition-all scale-90"
            >
              <ChevronLeft className="h-4 w-4" />
            </button>

            <div className="flex items-center gap-1 mx-1">
              {(() => {
                const totalItems = filteredAccounts.length;
                const totalPages = Math.ceil(totalItems / pageSize);
                if (totalPages <= 1) return <button key={1} className="w-9 h-9 rounded-xl bg-indigo-500/10 text-indigo-500 border border-indigo-500/20 font-black text-[11px]">1</button>;

                const pages = [];
                let startPage = Math.max(1, currentPage - 1);
                let endPage = Math.min(totalPages, startPage + 2);
                if (endPage - startPage < 2) startPage = Math.max(1, endPage - 2);

                for (let i = startPage; i <= endPage; i++) {
                  pages.push(
                    <button
                      key={i}
                      onClick={() => setCurrentPage(i)}
                      className={`w-9 h-9 rounded-xl font-black text-[11px] transition-all ${currentPage === i
                        ? 'bg-indigo-500 text-white shadow-lg shadow-indigo-500/20 scale-105'
                        : 'hover:bg-muted/40 text-muted-foreground'
                        }`}
                    >
                      {i}
                    </button>
                  );
                }
                return pages;
              })()}
            </div>

            <button
              onClick={() => setCurrentPage(p => Math.min(Math.ceil(filteredAccounts.length / pageSize), p + 1))}
              disabled={currentPage === Math.ceil(filteredAccounts.length / pageSize) || filteredAccounts.length === 0}
              className="w-10 h-10 rounded-xl border border-border/40 flex items-center justify-center hover:bg-indigo-500 hover:text-white hover:border-indigo-400 disabled:opacity-20 transition-all scale-90"
            >
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>

          {/* 3. 每页条数选择 - Compact Dual-Mode Dropdown */}
          <div className="flex items-center gap-2 relative">
            <span className="text-[11px] font-medium text-muted-foreground opacity-60">每页显示:</span>
            <div className="relative">
              <button
                onClick={() => setIsPageSizeOpen(!isPageSizeOpen)}
                className="bg-muted/40 border border-border/40 rounded-lg px-2.5 py-1.5 text-[10px] font-black focus:ring-2 focus:ring-indigo-500/30 outline-none flex items-center gap-2 hover:bg-muted/60 transition-all min-w-[50px] justify-between shadow-sm"
              >
                {pageSize}
                <div className={`transition-transform duration-300 ${isPageSizeOpen ? 'rotate-180' : ''}`}>
                  <ChevronDown className="h-3 w-3 opacity-50" />
                </div>
              </button>

              {isPageSizeOpen && (
                <>
                  <div className="fixed inset-0 z-[110]" onClick={() => setIsPageSizeOpen(false)} />
                  <div className="absolute bottom-full left-0 mb-2 w-16 bg-popover/95 backdrop-blur-2xl border border-border/40 rounded-xl shadow-[0_10px_30px_rgba(0,0,0,0.2)] dark:shadow-[0_20px_500px_rgba(0,0,0,0.3)] overflow-hidden z-[120] animate-in fade-in slide-in-from-bottom-1 duration-200">
                    <div className="p-1 space-y-0.5">
                      {[5, 10, 20, 50, 100].map(v => (
                        <button
                          key={v}
                          onClick={() => {
                            setPageSize(v);
                            setCurrentPage(1);
                            setIsPageSizeOpen(false);
                          }}
                          className={`w-full px-2 py-1.5 rounded-lg text-[10px] font-black transition-all flex items-center justify-center ${pageSize === v
                            ? 'bg-indigo-500 text-white shadow-md shadow-indigo-500/30'
                            : 'text-muted-foreground hover:bg-muted/50 hover:text-foreground'
                            }`}
                        >
                          {v}
                        </button>
                      ))}
                    </div>
                  </div>
                </>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Floating Batch Actions Console - Refined & Compact */}
      {selectedEmails.length > 0 && (
        <div className="fixed bottom-10 left-1/2 -translate-x-1/2 z-[100] animate-in fade-in slide-in-from-bottom-5 duration-300">
          <div className="bg-popover/90 backdrop-blur-3xl border border-border/40 p-1.5 pl-5 rounded-2xl shadow-[0_25px_60px_-12px_rgba(0,0,0,0.5)] flex items-center gap-4 border-white/5">
            <div className="flex flex-col py-0.5">
              <span className="text-[8px] font-black text-muted-foreground leading-tight">已选定</span>
              <span className="text-[12px] font-black text-foreground">{selectedEmails.length} 个账号</span>
            </div>
            <div className="h-6 w-px bg-border/40" />
            <div className="flex gap-2">
              <button
                onClick={handleBatchVerify}
                className="h-10 px-4 rounded-xl bg-indigo-500 text-white font-black text-[11px] hover:bg-indigo-400 transition-all flex items-center gap-2 shadow-lg shadow-indigo-500/20"
              >
                <ShieldCheck className="h-3.5 w-3.5" /> 批量验证
              </button>
              <button
                onClick={handleBatchDelete}
                className="h-10 px-4 rounded-xl bg-rose-500 text-white font-black text-[11px] hover:bg-rose-400 transition-all flex items-center gap-2 shadow-lg shadow-rose-500/20"
              >
                <Trash2 className="h-3.5 w-3.5" /> 批量注销
              </button>
              <button
                onClick={() => setSelectedEmails([])}
                className="h-10 w-10 rounded-xl bg-muted/20 text-muted-foreground flex items-center justify-center hover:bg-muted/40 hover:text-foreground transition-all border border-border/40"
              >
                <XCircle className="h-4 w-4" />
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
