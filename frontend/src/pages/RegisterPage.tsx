import { useState, useEffect, useRef } from "react"
import { toast } from "sonner"
import { API_BASE } from "../lib/api"
import { getAuthHeader } from "../lib/auth"
import { Card } from "../components/Card"
import { Button } from "../components/Button"
import { StatCard } from "../components/StatCard"

export default function RegisterPage() {
  const [sysInfo, setSysInfo] = useState<any>(null)
  const [count, setCount] = useState(10)
  const [threads, setThreads] = useState(4)
  const [provider, setProvider] = useState("default")
  const [batching, setBatching] = useState(false)
  const [logs, setLogs] = useState<string[]>([])
  const logRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    fetch(`${API_BASE}/api/admin/system-info`, { headers: getAuthHeader() })
      .then(r => r.json())
      .then(d => { setSysInfo(d); setThreads(d.recommended_threads || 4) })
      .catch(() => {})

    const intv = setInterval(() => {
      fetch(`${API_BASE}/api/admin/logs`, { headers: getAuthHeader() })
        .then(r => r.json())
        .then(d => setLogs(d.logs || []))
        .catch(() => {})
    }, 3000)
    return () => clearInterval(intv)
  }, [])

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight
  }, [logs])

  const handleStart = () => {
    setBatching(true)
    fetch(`${API_BASE}/api/admin/accounts/batch-register`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...getAuthHeader() },
      body: JSON.stringify({ count, threads, provider })
    }).then(r => r.json()).then(d => {
      if (d.ok) toast.success(d.message)
      else toast.error("启动失败")
    }).catch(() => toast.error("请求失败"))
  }

  const handleStop = () => {
    fetch(`${API_BASE}/api/admin/accounts/stop-register`, {
      method: "POST", headers: getAuthHeader()
    }).then(() => { toast.success("停止信号已发送"); setBatching(false) })
  }

  return (
    <div>
      <h1 className="text-[22px] font-bold mb-1">扩容中心</h1>
      <p className="text-[13px] text-[#8a8a8a] mb-6">批量注册新账号，扩充账户池</p>

      {/* System Info */}
      {sysInfo && (
        <div className="grid grid-cols-3 gap-3 mb-5">
          <StatCard label="CPU 核心" value={sysInfo.cpu_cores} />
          <StatCard label="可用内存" value={`${sysInfo.ram_available_gb} GB`} />
          <StatCard label="推荐并发" value={sysInfo.recommended_threads} color="#2563eb" />
        </div>
      )}

      {/* Control Panel */}
      <Card title="注册控制" className="mb-5">
        <div className="grid grid-cols-3 gap-4 mb-4">
          <div>
            <label className="text-[11px] text-[#8a8a8a] mb-1 block">注册数量</label>
            <input type="number" value={count} onChange={e => setCount(+e.target.value)} min={1} max={100}
              className="w-full h-8 px-2.5 text-[13px] rounded-lg border border-[#e5e5e5] text-center" />
          </div>
          <div>
            <label className="text-[11px] text-[#8a8a8a] mb-1 block">并发线程</label>
            <input type="number" value={threads} onChange={e => setThreads(+e.target.value)} min={1} max={20}
              className="w-full h-8 px-2.5 text-[13px] rounded-lg border border-[#e5e5e5] text-center" />
          </div>
          <div>
            <label className="text-[11px] text-[#8a8a8a] mb-1 block">邮箱渠道</label>
            <select value={provider} onChange={e => setProvider(e.target.value)}
              className="w-full h-8 px-2.5 text-[12px] rounded-lg border border-[#e5e5e5] bg-white">
              <option value="default">自动选择</option>
              <option value="moemail">MoeMail</option>
              <option value="tempmail">TempMail</option>
            </select>
          </div>
        </div>
        <div className="flex gap-2">
          <Button variant="primary" onClick={handleStart} disabled={batching}>
            {batching ? "运行中..." : "开始注册"}
          </Button>
          {batching && <Button variant="danger" onClick={handleStop}>停止</Button>}
        </div>
      </Card>

      {/* Logs */}
      <Card title="实时日志">
        <div ref={logRef} className="h-[320px] overflow-y-auto rounded-lg bg-[#fafafa] p-3 font-mono text-[11px] text-[#333] leading-relaxed">
          {logs.length === 0 ? (
            <span className="text-[#999]">等待日志...</span>
          ) : logs.map((line, i) => (
            <div key={i} className="whitespace-pre-wrap break-all">{line}</div>
          ))}
        </div>
      </Card>
    </div>
  )
}
