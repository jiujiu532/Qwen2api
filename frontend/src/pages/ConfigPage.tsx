import { useState, useEffect } from "react"
import { toast } from "sonner"
import { API_BASE } from "../lib/api"
import { getAuthHeader } from "../lib/auth"
import { Button } from "../components/Button"

export default function ConfigPage() {
  const [engineMode, setEngineMode] = useState("hybrid")
  const [maxInflight, setMaxInflight] = useState(1)
  const [defaultStream, setDefaultStream] = useState(true)
  const [modelAliases, setModelAliases] = useState("")
  const [moemailDomain, setMoemailDomain] = useState("")
  const [moemailKey, setMoemailKey] = useState("")
  const [tempmailDomain, setTempmailDomain] = useState("")
  const [tempmailKey, setTempmailKey] = useState("")
  const [proxyEnabled, setProxyEnabled] = useState(false)
  const [proxyUrl, setProxyUrl] = useState("")
  const [proxyUsername, setProxyUsername] = useState("")
  const [proxyPassword, setProxyPassword] = useState("")
  const [autoReplenish, setAutoReplenish] = useState(false)
  const [replenishTarget, setReplenishTarget] = useState(30)
  const [keys, setKeys] = useState<string[]>([])
  const [tab, setTab] = useState("engine")

  const fetchSettings = () => {
    fetch(`${API_BASE}/api/admin/settings`, { headers: getAuthHeader() })
      .then(r => r.json())
      .then(d => {
        setEngineMode(d.engine_mode || "hybrid")
        setMaxInflight(d.max_inflight_per_account || 1)
        setDefaultStream(d.default_stream !== false)
        setModelAliases(JSON.stringify(d.model_aliases || {}, null, 2))
        setMoemailDomain(d.moemail_domain || "")
        setMoemailKey(d.moemail_key || "")
        setTempmailDomain(d.tempmail_domain || "")
        setTempmailKey(d.tempmail_key || "")
        setProxyEnabled(!!d.proxy_enabled)
        setProxyUrl(d.proxy_url || "")
        setProxyUsername(d.proxy_username || "")
        setProxyPassword(d.proxy_password || "")
        setAutoReplenish(!!d.auto_replenish)
        setReplenishTarget(d.replenish_target || 30)
      })
  }

  const fetchKeys = () => {
    fetch(`${API_BASE}/api/admin/keys`, { headers: getAuthHeader() })
      .then(r => r.json())
      .then(d => setKeys(d.keys || []))
  }

  useEffect(() => { fetchSettings(); fetchKeys() }, [])

  const save = (payload: Record<string, any>) => {
    fetch(`${API_BASE}/api/admin/settings`, {
      method: "PUT",
      headers: { "Content-Type": "application/json", ...getAuthHeader() },
      body: JSON.stringify(payload)
    }).then(r => { if (r.ok) toast.success("已保存"); else toast.error("保存失败") })
  }

  const saveAll = () => {
    save({
      engine_mode: engineMode,
      max_inflight_per_account: maxInflight,
      default_stream: defaultStream,
      moemail_domain: moemailDomain,
      moemail_key: moemailKey,
      tempmail_domain: tempmailDomain,
      tempmail_key: tempmailKey,
      proxy_enabled: proxyEnabled,
      proxy_url: proxyUrl,
      proxy_username: proxyUsername,
      proxy_password: proxyPassword,
      auto_replenish: autoReplenish,
      replenish_target: replenishTarget,
    })
    // 模型映射单独保存
    try { save({ model_aliases: JSON.parse(modelAliases) }) } catch {}
  }

  const generateKey = () => {
    fetch(`${API_BASE}/api/admin/keys`, { method: "POST", headers: getAuthHeader() })
      .then(r => r.json())
      .then(d => { if (d.ok) { toast.success("已生成"); fetchKeys() } })
  }

  const deleteKey = (key: string) => {
    fetch(`${API_BASE}/api/admin/keys/${encodeURIComponent(key)}`, { method: "DELETE", headers: getAuthHeader() })
      .then(() => { toast.success("已删除"); fetchKeys() })
  }

  const tabs = [
    { key: "engine", label: "引擎配置" },
    { key: "model", label: "模型映射" },
    { key: "mail", label: "邮箱渠道" },
    { key: "proxy", label: "网络代理" },
    { key: "keys", label: "API 密钥" },
  ]

  return (
    <div>
      {/* Header */}
      <div className="flex items-start justify-between" style={{ marginBottom: "20px" }}>
        <div>
          <h1 className="text-[22px] font-bold leading-tight">配置管理</h1>
          <p className="text-[13px] text-[#8a8a8a]" style={{ marginTop: "4px" }}>管理系统运行时参数与服务默认行为</p>
        </div>
        <Button variant="primary" onClick={saveAll}>保存</Button>
      </div>

      {/* Tabs */}
      <div className="flex items-center gap-1" style={{ marginBottom: "24px" }}>
        {tabs.map(t => (
          <button key={t.key} onClick={() => setTab(t.key)}
            className={`rounded-lg text-[13px] font-medium transition-colors ${
              tab === t.key ? "bg-[#111] text-white" : "text-[#666] hover:bg-[#f3f3f3]"
            }`} style={{ height: "32px", padding: "0 14px" }}>
            {t.label}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="bg-white rounded-[14px] shadow-sm" style={{ padding: "32px" }}>

        {tab === "engine" && (
          <div className="space-y-8">
            <SectionTitle>引擎与并发</SectionTitle>
            <ConfigRow label="驱动引擎" desc="httpx 快速直连 / browser 浏览器指纹 / hybrid 混合">
              <select value={engineMode} onChange={e => setEngineMode(e.target.value)}
                className="w-[200px] h-9 px-3 rounded-lg border border-[#e5e5e5] text-[13px] bg-white text-right">
                <option value="httpx">httpx</option>
                <option value="browser">browser</option>
                <option value="hybrid">hybrid</option>
              </select>
            </ConfigRow>
            <ConfigRow label="单账号并发" desc="每个账号同时处理的最大请求数，1=最安全">
              <input type="number" value={maxInflight} onChange={e => setMaxInflight(+e.target.value)} min={1} max={10}
                className="w-[200px] h-9 px-3 rounded-lg border border-[#e5e5e5] text-[13px] text-right" />
            </ConfigRow>
            <ConfigRow label="默认流式回复" desc="客户端未传 stream 字段时的默认行为">
              <Toggle checked={defaultStream} onChange={setDefaultStream} />
            </ConfigRow>

            <SectionTitle>自动补号</SectionTitle>
            <ConfigRow label="启用自动补号" desc="账号耗尽时自动触发注册补充">
              <Toggle checked={autoReplenish} onChange={setAutoReplenish} />
            </ConfigRow>
            {autoReplenish && (
              <ConfigRow label="目标账号数" desc="池中账号低于此数时触发补号">
                <input type="number" value={replenishTarget} onChange={e => setReplenishTarget(+e.target.value)}
                  className="w-[200px] h-9 px-3 rounded-lg border border-[#e5e5e5] text-[13px] text-right" />
              </ConfigRow>
            )}
          </div>
        )}

        {tab === "model" && (
          <div className="space-y-4">
            <SectionTitle>模型别名映射</SectionTitle>
            <p className="text-[12px] text-[#8a8a8a]">JSON 格式，key 为请求中的模型名，value 为 Qwen 真实模型名</p>
            <textarea value={modelAliases} onChange={e => setModelAliases(e.target.value)}
              className="w-full h-[400px] p-4 text-[12px] font-mono rounded-xl border border-[#e5e5e5] bg-[#fafafa] resize-y leading-relaxed" />
          </div>
        )}

        {tab === "mail" && (
          <div className="space-y-8">
            <SectionTitle>MoeMail</SectionTitle>
            <ConfigRow label="域名" desc="MoeMail 自建邮箱的域名">
              <input value={moemailDomain} onChange={e => setMoemailDomain(e.target.value)} placeholder="example.com"
                className="w-[280px] h-9 px-3 rounded-lg border border-[#e5e5e5] text-[13px] text-right" />
            </ConfigRow>
            <ConfigRow label="API Key" desc="MoeMail 的 API 密钥">
              <input value={moemailKey} onChange={e => setMoemailKey(e.target.value)} placeholder="密钥"
                className="w-[280px] h-9 px-3 rounded-lg border border-[#e5e5e5] text-[13px] text-right" />
            </ConfigRow>

            <SectionTitle>TempMail</SectionTitle>
            <ConfigRow label="域名" desc="TempMail 自建邮箱的域名">
              <input value={tempmailDomain} onChange={e => setTempmailDomain(e.target.value)} placeholder="example.com"
                className="w-[280px] h-9 px-3 rounded-lg border border-[#e5e5e5] text-[13px] text-right" />
            </ConfigRow>
            <ConfigRow label="API Key" desc="TempMail 的 API 密钥">
              <input value={tempmailKey} onChange={e => setTempmailKey(e.target.value)} placeholder="密钥"
                className="w-[280px] h-9 px-3 rounded-lg border border-[#e5e5e5] text-[13px] text-right" />
            </ConfigRow>
          </div>
        )}

        {tab === "proxy" && (
          <div className="space-y-8">
            <SectionTitle>代理设置</SectionTitle>
            <ConfigRow label="启用代理" desc="注册时使用代理绕过 WAF 限制">
              <Toggle checked={proxyEnabled} onChange={setProxyEnabled} />
            </ConfigRow>
            {proxyEnabled && (
              <>
                <ConfigRow label="代理地址" desc="格式: http://host:port 或 socks5://host:port">
                  <input value={proxyUrl} onChange={e => setProxyUrl(e.target.value)} placeholder="http://host:port"
                    className="w-[280px] h-9 px-3 rounded-lg border border-[#e5e5e5] text-[13px] text-right font-mono" />
                </ConfigRow>
                <ConfigRow label="用户名" desc="代理认证用户名（可选）">
                  <input value={proxyUsername} onChange={e => setProxyUsername(e.target.value)}
                    className="w-[200px] h-9 px-3 rounded-lg border border-[#e5e5e5] text-[13px] text-right" />
                </ConfigRow>
                <ConfigRow label="密码" desc="代理认证密码（可选）">
                  <input type="password" value={proxyPassword} onChange={e => setProxyPassword(e.target.value)}
                    className="w-[200px] h-9 px-3 rounded-lg border border-[#e5e5e5] text-[13px] text-right" />
                </ConfigRow>
              </>
            )}
          </div>
        )}

        {tab === "keys" && (
          <div className="space-y-6">
            <SectionTitle>API 密钥管理</SectionTitle>
            <p className="text-[12px] text-[#8a8a8a]">OpenAI 兼容 API 的鉴权密钥。多个值请使用英文逗号分隔；留空则禁用鉴权。</p>
            <div className="flex items-center justify-between">
              <span className="text-[12px] text-[#8a8a8a]">{keys.length} 个密钥</span>
              <Button variant="primary" size="sm" onClick={generateKey}>生成新密钥</Button>
            </div>
            <div className="space-y-2">
              {keys.map(k => (
                <div key={k} className="flex items-center justify-between h-10 px-4 rounded-lg border border-[#e5e5e5]">
                  <code className="text-[12px] font-mono text-[#333]">{k}</code>
                  <button onClick={() => deleteKey(k)} className="text-[11px] text-[#b7726a] hover:text-[#92514b] font-medium">删除</button>
                </div>
              ))}
              {keys.length === 0 && <p className="text-[12px] text-[#999] py-4 text-center">暂无密钥，点击上方按钮生成</p>}
            </div>
          </div>
        )}

      </div>
    </div>
  )
}


// 配置行组件（左标题+描述，右控件）
function ConfigRow({ label, desc, children }: { label: string; desc: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between py-1">
      <div className="flex-1 min-w-0 pr-8">
        <div className="text-[14px] font-semibold text-[#111]">{label}</div>
        <div className="text-[12px] text-[#8a8a8a] mt-0.5">{desc}</div>
      </div>
      <div className="flex-shrink-0">{children}</div>
    </div>
  )
}

// Section 标题
function SectionTitle({ children }: { children: React.ReactNode }) {
  return <div className="text-[12px] font-medium text-[#8a8a8a] tracking-wide pb-2 border-b border-[#f0f0f0]">{children}</div>
}

// Toggle 开关
function Toggle({ checked, onChange }: { checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <button onClick={() => onChange(!checked)}
      className={`relative w-11 h-6 rounded-full transition-colors ${checked ? 'bg-[#111]' : 'bg-[#e5e5e5]'}`}>
      <span className={`absolute top-0.5 w-5 h-5 rounded-full bg-white shadow transition-transform ${checked ? 'translate-x-[22px]' : 'translate-x-0.5'}`} />
    </button>
  )
}
