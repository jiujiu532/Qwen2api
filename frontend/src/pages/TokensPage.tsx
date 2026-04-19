import { useState, useEffect } from "react"
import { Plus, RefreshCw, Copy, Check, Trash2, Key } from "lucide-react"
import { toast } from "sonner"
import { getAuthHeader } from "../lib/auth"
import { API_BASE } from "../lib/api"

export default function TokensPage() {
  const [keys, setKeys] = useState<string[]>([])
  const [copied, setCopied] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const fetchKeys = () => {
    setLoading(true)
    fetch(`${API_BASE}/api/admin/keys`, { headers: getAuthHeader() })
      .then(res => {
        if (!res.ok) throw new Error("Unauthorized")
        return res.json()
      })
      .then(data => setKeys(data.keys || []))
      .catch(() => toast.error("刷新失败，请确认管理密钥正确"))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    fetchKeys()
  }, [])

  const handleGenerate = () => {
    fetch(`${API_BASE}/api/admin/keys`, {
      method: "POST",
      headers: getAuthHeader()
    }).then(res => {
      if (res.ok) {
        toast.success("已生成新的分发密钥")
        fetchKeys()
      } else {
        toast.error("生成失败，权限受限")
      }
    })
  }

  const handleDelete = (key: string) => {
    fetch(`${API_BASE}/api/admin/keys/${encodeURIComponent(key)}`, {
      method: "DELETE",
      headers: getAuthHeader()
    }).then(res => {
      if (res.ok) {
        toast.success("密钥已注销")
        fetchKeys()
      } else {
        toast.error("注销失败")
      }
    })
  }

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text)
    setCopied(text)
    toast.success("密钥已复制")
    setTimeout(() => setCopied(null), 2000)
  }

  return (
    <div className="space-y-10 animate-fade-in-up max-w-[1400px] mx-auto">
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-6">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-indigo-500/10 flex items-center justify-center border border-indigo-500/20">
            <Key className="w-5 h-5 text-indigo-500" />
          </div>
          <h2 className="text-3xl font-black tracking-tighter text-foreground">分发密钥管理</h2>
        </div>
        <div className="flex gap-3">
          <button
            onClick={() => { fetchKeys(); toast.success("数据同步完成"); }}
            className="h-12 px-5 rounded-2xl bg-muted/20 border border-border/40 hover:bg-muted/40 transition-all flex items-center gap-2 font-semibold text-sm"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} /> 刷新列表
          </button>
          <button
            onClick={handleGenerate}
            className="h-12 px-6 rounded-2xl bg-foreground text-background font-semibold flex items-center gap-2 hover:scale-[1.02] active:scale-95 transition-all text-sm shadow-xl shadow-black/5"
          >
            <Plus className="h-4 w-4" /> 生成全新密钥
          </button>
        </div>
      </div>

      <div className="glass-card rounded-[2.5rem] overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead>
              <tr className="bg-muted/10 border-b border-border/40">
                <th className="px-8 py-5 text-[11px] font-medium text-muted-foreground w-20">#</th>
                <th className="px-8 py-5 text-[11px] font-medium text-muted-foreground">下游 API 密钥</th>
                <th className="px-8 py-5 text-[11px] font-medium text-muted-foreground text-right">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/20">
              {keys.length === 0 && !loading && (
                <tr>
                  <td colSpan={3} className="px-8 py-16 text-center text-muted-foreground font-medium">
                    暂无分发密钥，点击上方按钮生成。
                  </td>
                </tr>
              )}
              {keys.map((k, i) => (
                <tr key={k} className="group hover:bg-muted/20 transition-colors">
                  <td className="px-8 py-6">
                    <span className="text-xs font-black text-muted-foreground/60 font-mono tracking-tighter">#{(i + 1).toString().padStart(2, '0')}</span>
                  </td>
                  <td className="px-8 py-6">
                    <div className="flex items-center gap-4">
                      <code className="text-[13px] font-mono font-bold text-foreground/80 bg-muted/30 px-3 py-1.5 rounded-lg border border-border/20 group-hover:bg-background transition-colors">
                        {k}
                      </code>
                    </div>
                  </td>
                  <td className="px-8 py-6 text-right">
                    <div className="flex items-center justify-end gap-3">
                      <button
                        onClick={() => copyToClipboard(k)}
                        className="p-3 rounded-xl bg-indigo-500/10 text-indigo-500 border border-indigo-500/20 hover:bg-indigo-500 hover:text-white transition-all shadow-lg shadow-indigo-500/5"
                        title="复制密钥"
                      >
                        {copied === k ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
                      </button>
                      <button
                        onClick={() => handleDelete(k)}
                        className="p-3 rounded-xl bg-muted/40 text-muted-foreground border border-border/40 hover:bg-rose-500/10 hover:text-rose-500 transition-all font-medium text-[10px]"
                        title="注销密钥"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="p-8 rounded-[2rem] bg-indigo-500/5 border border-indigo-500/10 space-y-3">
        <div className="flex items-center gap-2">
          <ShieldCheck className="w-4 h-4 text-indigo-500" />
          <span className="text-[10px] font-medium text-indigo-500">安全提示</span>
        </div>
        <p className="text-xs text-muted-foreground/80 font-medium leading-relaxed">
          API 密钥用于下游客户端（如 NextChat, LobeChat, OpenAI SDK 等）进行流量鉴权。每一枚生成的密钥均具备独立的访问配额与统计权限。请妥善保管，密钥泄露可能导致流量被滥用。
        </p>
      </div>
    </div>
  )
}

function ShieldCheck(props: any) {
  return (
    <svg
      {...props}
      xmlns="http://www.w3.org/2000/svg"
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10" />
      <path d="m9 12 2 2 4-4" />
    </svg>
  )
}
