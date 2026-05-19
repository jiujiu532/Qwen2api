import { useState, useEffect } from "react"
import { toast } from "sonner"
import { API_BASE } from "../lib/api"
import { getAuthHeader } from "../lib/auth"
import { Card } from "../components/Card"
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

  const save = (key: string, value: any, label = key) => {
    fetch(`${API_BASE}/api/admin/settings`, {
      method: "PUT",
      headers: { "Content-Type": "application/json", ...getAuthHeader() },
      body: JSON.stringify({ [key]: value })
    }).then(r => {
      if (r.ok) toast.success(`${label} 已保存`)
      else toast.error("保存失败")
    })
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

  return (
    <div>
      <h1 className="text-[22px] font-bold mb-1">系统配置</h1>
      <p className="text-[13px] text-[#8a8a8a] mb-6">引擎、模型、渠道、密钥等全局设置</p>

      <div className="grid gap-5">
        {/* 引擎与并发 */}
        <Card title="引擎与并发">
          <div className="grid gap-4">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-[12px] font-semibold">驱动引擎</div>
                <div className="text-[11px] text-[#8a8a8a]">httpx 快速直连 / browser 浏览器指纹 / hybrid 混合</div>
              </div>
              <select value={engineMode} onChange={e => { setEngineMode(e.target.value); save("engine_mode", e.target.value, "引擎模式") }}
                className="h-8 px-3 rounded-lg border border-[#e5e5e5] text-[12px] bg-white">
                <option value="httpx">httpx</option>
                <option value="browser">browser</option>
                <option value="hybrid">hybrid</option>
              </select>
            </div>
            <div className="flex items-center justify-between">
              <div>
                <div className="text-[12px] font-semibold">单账号并发</div>
                <div className="text-[11px] text-[#8a8a8a]">每个账号同时处理的最大请求数</div>
              </div>
              <div className="flex items-center gap-2">
                <input type="range" min="1" max="10" value={maxInflight} onChange={e => setMaxInflight(+e.target.value)}
                  className="w-24 h-1.5 rounded-full appearance-none bg-[#e5e5e5] accent-[#111]" />
                <span className="text-[13px] font-semibold w-5 text-center">{maxInflight}</span>
                <Button size="sm" onClick={() => save("max_inflight_per_account", maxInflight, "并发数")}>保存</Button>
              </div>
            </div>
            <div className="flex items-center justify-between">
              <div>
                <div className="text-[12px] font-semibold">默认流式回复</div>
                <div className="text-[11px] text-[#8a8a8a]">客户端未传 stream 字段时的默认行为</div>
              </div>
              <button onClick={() => { const v = !defaultStream; setDefaultStream(v); save("default_stream", v, "流式") }}
                className={`relative w-10 h-5 rounded-full transition-colors ${defaultStream ? 'bg-[#111]' : 'bg-[#e5e5e5]'}`}>
                <span className={`absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform ${defaultStream ? 'translate-x-5' : 'translate-x-0.5'}`} />
              </button>
            </div>
          </div>
        </Card>

        {/* 模型映射 */}
        <Card title="模型映射">
          <textarea value={modelAliases} onChange={e => setModelAliases(e.target.value)}
            className="w-full h-40 p-3 text-[11px] font-mono rounded-lg border border-[#e5e5e5] bg-[#fafafa] resize-y" />
          <Button className="mt-3" onClick={() => {
            try { save("model_aliases", JSON.parse(modelAliases), "模型映射") }
            catch { toast.error("JSON 格式错误") }
          }}>保存映射</Button>
        </Card>

        {/* 邮箱渠道 */}
        <Card title="邮箱渠道">
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <div className="text-[11px] font-semibold text-[#666]">MoeMail</div>
              <input value={moemailDomain} onChange={e => setMoemailDomain(e.target.value)} placeholder="域名"
                className="w-full h-8 px-2.5 text-[12px] rounded-lg border border-[#e5e5e5]" />
              <input value={moemailKey} onChange={e => setMoemailKey(e.target.value)} placeholder="API Key"
                className="w-full h-8 px-2.5 text-[12px] rounded-lg border border-[#e5e5e5]" />
            </div>
            <div className="space-y-2">
              <div className="text-[11px] font-semibold text-[#666]">TempMail</div>
              <input value={tempmailDomain} onChange={e => setTempmailDomain(e.target.value)} placeholder="域名"
                className="w-full h-8 px-2.5 text-[12px] rounded-lg border border-[#e5e5e5]" />
              <input value={tempmailKey} onChange={e => setTempmailKey(e.target.value)} placeholder="API Key"
                className="w-full h-8 px-2.5 text-[12px] rounded-lg border border-[#e5e5e5]" />
            </div>
          </div>
          <Button className="mt-3" onClick={() => save("moemail_domain", moemailDomain) && save("moemail_key", moemailKey) && save("tempmail_domain", tempmailDomain) && save("tempmail_key", tempmailKey)}>
            保存邮箱配置
          </Button>
        </Card>

        {/* 代理 */}
        <Card title="代理设置">
          <div className="grid gap-3">
            <div className="flex items-center justify-between">
              <span className="text-[12px] font-semibold">启用代理</span>
              <button onClick={() => { const v = !proxyEnabled; setProxyEnabled(v); save("proxy_enabled", v, "代理") }}
                className={`relative w-10 h-5 rounded-full transition-colors ${proxyEnabled ? 'bg-[#111]' : 'bg-[#e5e5e5]'}`}>
                <span className={`absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform ${proxyEnabled ? 'translate-x-5' : 'translate-x-0.5'}`} />
              </button>
            </div>
            {proxyEnabled && (
              <>
                <input value={proxyUrl} onChange={e => setProxyUrl(e.target.value)} placeholder="代理地址 (http://host:port)"
                  className="w-full h-8 px-2.5 text-[12px] rounded-lg border border-[#e5e5e5] font-mono" />
                <div className="grid grid-cols-2 gap-2">
                  <input value={proxyUsername} onChange={e => setProxyUsername(e.target.value)} placeholder="用户名"
                    className="h-8 px-2.5 text-[12px] rounded-lg border border-[#e5e5e5]" />
                  <input value={proxyPassword} onChange={e => setProxyPassword(e.target.value)} placeholder="密码" type="password"
                    className="h-8 px-2.5 text-[12px] rounded-lg border border-[#e5e5e5]" />
                </div>
                <Button size="sm" onClick={() => {
                  save("proxy_url", proxyUrl); save("proxy_username", proxyUsername); save("proxy_password", proxyPassword)
                }}>保存代理</Button>
              </>
            )}
          </div>
        </Card>

        {/* 自动补号 */}
        <Card title="自动补号">
          <div className="flex items-center justify-between mb-3">
            <span className="text-[12px] font-semibold">启用自动补号</span>
            <button onClick={() => { const v = !autoReplenish; setAutoReplenish(v); save("auto_replenish", v, "自动补号") }}
              className={`relative w-10 h-5 rounded-full transition-colors ${autoReplenish ? 'bg-[#111]' : 'bg-[#e5e5e5]'}`}>
              <span className={`absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform ${autoReplenish ? 'translate-x-5' : 'translate-x-0.5'}`} />
            </button>
          </div>
          {autoReplenish && (
            <div className="flex items-center gap-3">
              <span className="text-[11px] text-[#8a8a8a]">目标数量</span>
              <input type="number" value={replenishTarget} onChange={e => setReplenishTarget(+e.target.value)}
                className="w-20 h-7 px-2 text-[12px] rounded-lg border border-[#e5e5e5] text-center" />
              <Button size="sm" onClick={() => save("replenish_target", replenishTarget, "目标数")}>保存</Button>
            </div>
          )}
        </Card>

        {/* API 密钥 */}
        <Card title="API 密钥">
          <div className="flex items-center justify-between mb-3">
            <span className="text-[11px] text-[#8a8a8a]">{keys.length} 个密钥</span>
            <Button variant="primary" size="sm" onClick={generateKey}>生成新密钥</Button>
          </div>
          <div className="space-y-1.5">
            {keys.map(k => (
              <div key={k} className="flex items-center justify-between px-3 py-2 rounded-lg bg-[#fafafa]">
                <code className="text-[11px] font-mono text-[#333]">{k}</code>
                <button onClick={() => deleteKey(k)} className="text-[11px] text-[#b7726a] hover:text-[#92514b]">删除</button>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  )
}
