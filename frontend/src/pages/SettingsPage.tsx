import { useState, useEffect } from "react"
import { KeyRound, Code, Mail, Server, Cpu, TriangleAlert, Globe } from "lucide-react"
import { toast } from "sonner"
import { getAuthHeader } from "../lib/auth"
import { API_BASE } from "../lib/api"

// ── 通用卡片组件 ──────────────────────────────────────────
function Card({ title, icon: Icon, color = "indigo", children }: {
  title: string; icon: any; color?: string; children: React.ReactNode
}) {
  const palette: Record<string, { bg: string; border: string; text: string }> = {
    indigo: { bg: "bg-indigo-500/10", border: "border-indigo-500/20", text: "text-indigo-500" },
    amber: { bg: "bg-amber-500/10", border: "border-amber-500/20", text: "text-amber-500" },
    cyan: { bg: "bg-cyan-500/10", border: "border-cyan-500/20", text: "text-cyan-500" },
    rose: { bg: "bg-rose-500/10", border: "border-rose-500/20", text: "text-rose-500" },
    violet: { bg: "bg-violet-500/10", border: "border-violet-500/20", text: "text-violet-500" },
  }
  const c = palette[color] ?? palette.indigo
  return (
    <div className={`glass-card rounded-3xl p-8 space-y-6 border ${c.border}`}>
      <div className="flex items-center gap-3">
        <div className={`w-10 h-10 rounded-xl ${c.bg} flex items-center justify-center border ${c.border} shrink-0`}>
          <Icon className={`w-5 h-5 ${c.text}`} />
        </div>
        <h3 className="text-base font-black tracking-tight text-foreground">{title}</h3>
      </div>
      {children}
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-2">
      <label className="text-[11px] font-medium text-muted-foreground ml-1">{label}</label>
      {children}
    </div>
  )
}

const inputCls = "w-full h-12 bg-muted/20 border border-border/40 rounded-xl px-4 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500/30 transition-all"
const btnIndigo = "w-full h-11 bg-indigo-500 text-white font-semibold rounded-xl text-sm shadow-lg shadow-indigo-500/20 hover:opacity-90 transition-all"

// ── 实际支持的协议端点 ─────────────────────────────────────
const API_ENDPOINTS = [
  { badge: "OpenAI", color: "bg-indigo-500", path: "/v1/chat/completions", desc: "对话补全、工具调用、流式" },
  { badge: "OpenAI", color: "bg-indigo-500", path: "/v1/responses", desc: "Responses API 新格式" },
  { badge: "OpenAI", color: "bg-indigo-500", path: "/v1/images/generations", desc: "示意图生成" },
  { badge: "OpenAI", color: "bg-indigo-500", path: "/v1/embeddings", desc: "Embedding 向量" },
  { badge: "OpenAI", color: "bg-indigo-500", path: "/v1/models", desc: "模型列表" },
  { badge: "Claude", color: "bg-orange-500", path: "/v1/messages", desc: "Anthropic 兼容层" },
  { badge: "Gemini", color: "bg-emerald-500", path: "/v1beta/models/{model}:generateContent", desc: "Google Gemini 透传" },
]

export default function SettingsPage() {
  const [sessionKey, setSessionKey] = useState("")
  const [maxInflight, setMaxInflight] = useState(4)
  const [modelAliases, setModelAliases] = useState("")
  const [moemailDomain, setMoemailDomain] = useState("")
  const [moemailKey, setMoemailKey] = useState("")
  const [tempmailDomain, setTempmailDomain] = useState("")
  const [tempmailKey, setTempmailKey] = useState("")
  const [engineMode, setEngineMode] = useState("hybrid")
  const [mailTab, setMailTab] = useState<'moemail' | 'tempmail'>('moemail')
  const [proxyEnabled, setProxyEnabled] = useState(false)
  const [proxyUrl, setProxyUrl] = useState("")
  const [proxyUsername, setProxyUsername] = useState("")
  const [proxyPassword, setProxyPassword] = useState("")
  const [proxyTesting, setProxyTesting] = useState(false)
  const [proxyTestResult, setProxyTestResult] = useState<{
    ok: boolean; direct_ip: string; proxy_ip: string; error?: string;
  } | null>(null)

  const fetchSettings = () => {
    fetch(`${API_BASE}/api/admin/settings`, { headers: getAuthHeader() })
      .then(res => { if (!res.ok) throw new Error(); return res.json() })
      .then(d => {
        setMaxInflight(d.max_inflight_per_account || 4)
        setModelAliases(JSON.stringify(d.model_aliases || {}, null, 2))
        setMoemailDomain(d.moemail_domain || "")
        setMoemailKey(d.moemail_key || "")
        setTempmailDomain(d.tempmail_domain || "")
        setTempmailKey(d.tempmail_key || "")
        setEngineMode(d.engine_mode || "hybrid")
        setProxyEnabled(!!d.proxy_enabled)
        setProxyUrl(d.proxy_url || "")
        setProxyUsername(d.proxy_username || "")
        setProxyPassword(d.proxy_password || "")
      })
      .catch(() => toast.error("配置获取失败，请检查密钥"))
  }

  useEffect(() => {
    setSessionKey(localStorage.getItem("qwen2api_key") || "")
    fetchSettings()
  }, [])

  const saveSetting = (key: string, value: any, label = key) => {
    const id = toast.loading("保存中...")
    fetch(`${API_BASE}/api/admin/settings`, {
      method: "PUT",
      headers: { "Content-Type": "application/json", ...getAuthHeader() },
      body: JSON.stringify({ [key]: value }),
    })
      .then(res => res.ok ? toast.success(`${label} 已更新`, { id }) : toast.error("更新失败", { id }))
      .catch(() => toast.error("请求异常", { id }))
  }

  const handleSaveAliases = () => {
    try { saveSetting("model_aliases", JSON.parse(modelAliases), "模型重定向") }
    catch { toast.error("JSON 格式错误") }
  }

  const isMoe = mailTab === 'moemail'
  const backendUrl = API_BASE || window.location.origin

  return (
    <div className="animate-fade-in-up max-w-[1400px] mx-auto pb-20 space-y-10">

      {/* 页头 */}
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 rounded-xl bg-indigo-500/10 flex items-center justify-center border border-indigo-500/20">
          <KeyRound className="w-5 h-5 text-indigo-500" />
        </div>
        <h2 className="text-3xl font-black tracking-tighter text-foreground">网关系统设置</h2>
      </div>

      {/* 主体 7/5 网格 */}
      <div className="grid grid-cols-1 xl:grid-cols-12 gap-8 items-start">

        {/* ══ 左列 ═══════════════════════════════════════ */}
        <div className="xl:col-span-7 space-y-6">

          {/* 管理密钥 — 紧凑单行 */}
          <Card title="管理密钥" icon={KeyRound}>
            <div className="flex gap-2">
              <input type="password" value={sessionKey} onChange={e => setSessionKey(e.target.value)}
                placeholder="Admin Key（登录密码）" className={`${inputCls} font-mono flex-1`} />
              <button
                onClick={() => { localStorage.setItem("qwen2api_key", sessionKey); toast.success("密钥已同步"); fetchSettings() }}
                className="h-12 px-5 bg-foreground text-background font-semibold rounded-xl text-sm hover:opacity-90 transition-all whitespace-nowrap">
                保存
              </button>
              <button
                onClick={() => { localStorage.removeItem("qwen2api_key"); setSessionKey(""); toast.info("凭据已清除") }}
                className="h-12 px-4 bg-muted/30 text-muted-foreground font-black rounded-xl text-[11px] hover:bg-rose-500/10 hover:text-rose-500 transition-all whitespace-nowrap">
                清除
              </button>
            </div>
            <p className="text-[10px] text-muted-foreground">
              永久修改请在 <code className="text-indigo-400 font-mono">config.py</code> 中更改 ADMIN_KEY，重启后生效。
            </p>
          </Card>

          {/* 自建邮箱服务 — Tab 切换 */}
          <Card title="自建邮箱服务" icon={Mail} color="indigo">
            <div className="flex gap-1 p-1 bg-muted/30 rounded-xl border border-border/40">
              {(['moemail', 'tempmail'] as const).map(tab => (
                <button key={tab} onClick={() => setMailTab(tab)}
                  className={`flex-1 h-9 rounded-lg text-xs font-black tracking-wide transition-all ${mailTab === tab ? 'bg-background shadow text-foreground' : 'text-muted-foreground hover:text-foreground'
                    }`}>
                  {tab === 'moemail' ? 'MoeMail' : 'TempMail（CF Workers）'}
                </button>
              ))}
            </div>

            <p className="text-xs text-muted-foreground leading-relaxed">
              {isMoe ? (
                <>适用于部署了 <a href="https://github.com/beilunyang/moemail" target="_blank" rel="noreferrer" className="text-indigo-500 underline">MoeMail</a> 的私有域名邮箱。需填写服务域名（含 http/https）与 API 密钥。</>
              ) : (
                <>适用于基于 Cloudflare Workers 部署的 <a href="https://temp-mail-docs.awsl.uk" target="_blank" rel="noreferrer" className="text-indigo-500 underline">TempMail</a> 实例。需填写 Workers 域名与管理密码（x-admin-auth）。</>
              )}
            </p>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <Field label={isMoe ? '服务域名' : 'Workers 域名'}>
                <input type="text"
                  value={isMoe ? moemailDomain : tempmailDomain}
                  onChange={e => isMoe ? setMoemailDomain(e.target.value) : setTempmailDomain(e.target.value)}
                  className={inputCls}
                  placeholder={isMoe ? 'https://api.moemail.app' : 'https://xxxx.xxxx.workers.dev'} />
              </Field>
              <Field label={isMoe ? 'API 密钥' : '管理密码'}>
                <input type="password"
                  value={isMoe ? moemailKey : tempmailKey}
                  onChange={e => isMoe ? setMoemailKey(e.target.value) : setTempmailKey(e.target.value)}
                  className={`${inputCls} font-mono`}
                  placeholder={isMoe ? 'x-api-key' : 'x-admin-auth'} />
              </Field>
            </div>

            <button
              onClick={() => {
                if (isMoe) { saveSetting('moemail_domain', moemailDomain, 'MoeMail 域名'); saveSetting('moemail_key', moemailKey, 'MoeMail 密钥') }
                else { saveSetting('tempmail_domain', tempmailDomain, 'TempMail 域名'); saveSetting('tempmail_key', tempmailKey, 'TempMail 密钥') }
              }}
              className={btnIndigo}>
              保存 {isMoe ? 'MoeMail' : 'TempMail'} 配置
            </button>
          </Card>

          {/* 注册代理池 */}
          <Card title="注册代理池" icon={Globe} color="violet">
            <p className="text-xs text-muted-foreground leading-relaxed">
              启用后，浏览器注册时通过代理 IP 发起请求，有效绕过阿里云 WAF 频率限制。
              支持 <code className="text-violet-400 font-mono">http://</code>、<code className="text-violet-400 font-mono">https://</code>、<code className="text-violet-400 font-mono">socks5://</code> 协议。
            </p>

            {/* 启用开关 */}
            <div className="flex items-center justify-between p-3 rounded-xl bg-muted/30 border border-border/40">
              <div>
                <p className="text-sm font-black">启用代理</p>
                <p className="text-[10px] text-muted-foreground">热更新，下次注册立即生效</p>
              </div>
              <button
                onClick={() => {
                  const next = !proxyEnabled
                  setProxyEnabled(next)
                  saveSetting('proxy_enabled', next, '代理开关')
                }}
                className={`relative w-11 h-6 rounded-full transition-colors ${proxyEnabled ? 'bg-violet-500' : 'bg-muted/50 border border-border/60'
                  }`}>
                <span className={`absolute top-0.5 left-0.5 w-5 h-5 rounded-full bg-white shadow transition-transform ${proxyEnabled ? 'translate-x-5' : ''
                  }`} />
              </button>
            </div>

            {/* 预设服务商 */}
            <div>
              <p className="text-[10px] font-black text-muted-foreground mb-2">快速填入服务商格式</p>
              <div className="grid grid-cols-2 gap-2">
                {[
                  { name: 'BrightData', tpl: 'http://brd.superproxy.io:22225' },
                  { name: 'Oxylabs', tpl: 'http://pr.oxylabs.io:7777' },
                  { name: 'Smartproxy', tpl: 'http://gate.smartproxy.com:7000' },
                  { name: 'ProxyScrape', tpl: 'http://proxy.proxyscrape.com:7777' },
                ].map(p => (
                  <button key={p.name}
                    onClick={() => setProxyUrl(p.tpl)}
                    className="h-8 text-[11px] font-black bg-muted/20 border border-border/40 rounded-lg hover:bg-violet-500/10 hover:border-violet-500/30 hover:text-violet-500 transition-all">
                    {p.name}
                  </button>
                ))}
              </div>
            </div>

            {/* 代理 URL */}
            <div className="grid grid-cols-1 gap-4">
              <Field label="代理地址">
                <input type="text" value={proxyUrl} onChange={e => setProxyUrl(e.target.value)}
                  placeholder="http://host:port 或 socks5://host:port"
                  className={`${inputCls} font-mono`} />
              </Field>
              <div className="grid grid-cols-2 gap-3">
                <Field label="用户名（可选）">
                  <input type="text" value={proxyUsername} onChange={e => setProxyUsername(e.target.value)}
                    placeholder="username"
                    className={`${inputCls} font-mono`} />
                </Field>
                <Field label="密码（可选）">
                  <input type="password" value={proxyPassword} onChange={e => setProxyPassword(e.target.value)}
                    placeholder="password"
                    className={`${inputCls} font-mono`} />
                </Field>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <button
                onClick={() => {
                  // 一次性保存所有代理配置（包括 proxy_enabled）
                  const id = toast.loading("保存中...")
                  fetch(`${API_BASE}/api/admin/settings`, {
                    method: "PUT",
                    headers: { "Content-Type": "application/json", ...getAuthHeader() },
                    body: JSON.stringify({
                      proxy_enabled: proxyEnabled,
                      proxy_url: proxyUrl,
                      proxy_username: proxyUsername,
                      proxy_password: proxyPassword,
                    }),
                  })
                    .then(res => res.ok ? toast.success("代理配置已保存", { id }) : toast.error("保存失败", { id }))
                    .catch(() => toast.error("请求异常", { id }))
                  setProxyTestResult(null)
                }}
                className="h-11 bg-violet-500 text-white font-semibold rounded-xl text-sm hover:opacity-90 transition-all">
                保存代理配置
              </button>
              <button
                disabled={proxyTesting}
                onClick={async () => {
                  setProxyTesting(true)
                  setProxyTestResult(null)
                  try {
                    const res = await fetch(`${API_BASE}/api/admin/proxy-test`, {
                      method: 'POST',
                      headers: { 'Content-Type': 'application/json', ...getAuthHeader() },
                      // 传入当前表单值，无需先保存即可测试
                      body: JSON.stringify({
                        proxy_url: proxyUrl,
                        proxy_username: proxyUsername,
                        proxy_password: proxyPassword,
                      }),
                    })
                    const d = await res.json()
                    setProxyTestResult(d)
                    if (d.ok) toast.success('✅ 代理生效，IP 已替换')
                    else toast.error(d.error || '代理测试失败')
                  } catch (e: any) {
                    toast.error('请求异常: ' + e.message)
                  } finally {
                    setProxyTesting(false)
                  }
                }}
                className="h-11 bg-muted/30 border border-violet-500/40 text-violet-500 font-semibold rounded-xl text-sm hover:bg-violet-500/10 transition-all disabled:opacity-50">
                {proxyTesting ? '测试中...' : '测试连通性'}
              </button>
            </div>

            {/* 测试结果面板 */}
            {proxyTestResult && (
              <div className={`p-4 rounded-xl border text-xs space-y-2.5 ${proxyTestResult.ok
                ? 'bg-green-500/10 border-green-500/30'
                : 'bg-rose-500/10 border-rose-500/30'
                }`}>
                <div className="flex items-center gap-2 font-bold text-sm">
                  <span>{proxyTestResult.ok ? '✅' : '⚠️'}</span>
                  <span className={proxyTestResult.ok ? 'text-green-500' : 'text-rose-500'}>
                    {proxyTestResult.ok ? '代理生效，IP 已替换' : '代理未生效'}
                  </span>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <p className="text-muted-foreground text-[11px] mb-1">直连 IP（服务器）</p>
                    <p className="text-foreground font-mono text-[13px]">{proxyTestResult.direct_ip || '获取失败'}</p>
                  </div>
                  <div>
                    <p className="text-muted-foreground text-[11px] mb-1">浏览器 IP（代理后）</p>
                    <p className={`font-mono text-[13px] ${proxyTestResult.ok ? 'text-green-400' : 'text-rose-400'}`}>
                      {proxyTestResult.proxy_ip || '获取失败'}
                    </p>
                  </div>
                </div>
                {proxyTestResult.error && (
                  <p className="text-rose-400 text-[11px] break-all">错误: {proxyTestResult.error}</p>
                )}
              </div>
            )}
          </Card>

          {/* 模型名称重定向 */}
          <Card title="模型名称重定向" icon={Code} color="amber">
            <p className="text-xs text-muted-foreground leading-relaxed">
              将下游客户端的模型名称映射至物理节点，支持通配符逻辑。编辑 JSON 后点击"应用"即时生效。
            </p>
            <textarea rows={7} value={modelAliases} onChange={e => setModelAliases(e.target.value)}
              className="w-full bg-muted/20 border border-border/40 rounded-2xl p-5 text-[13px] font-mono text-foreground focus:outline-none focus:ring-2 focus:ring-amber-500/20 transition-all leading-relaxed resize-none" />
            <button onClick={handleSaveAliases}
              className="w-full h-11 bg-amber-500 text-black font-semibold rounded-xl text-sm hover:opacity-90 transition-all">
              应用映射规则
            </button>
          </Card>
        </div>

        {/* ══ 右列 ═══════════════════════════════════════ */}
        <div className="xl:col-span-5 space-y-6 xl:sticky xl:top-10">

          {/* 节点集成端点 — 真实协议路径表 */}
          <Card title="节点集成端点" icon={Server}>
            <div className="p-3 rounded-xl bg-muted/30 border border-border/40 flex items-center gap-2">
              <code className="text-indigo-500 font-mono text-sm font-bold flex-1 break-all">{backendUrl}</code>
              <button onClick={() => { navigator.clipboard.writeText(backendUrl); toast.success("已复制") }}
                className="shrink-0 text-xs text-muted-foreground/50 hover:text-indigo-500 transition-colors">📋</button>
            </div>

            <div className="space-y-1">
              <p className="text-[10px] font-black text-muted-foreground mb-2">支持的协议与路径</p>
              {API_ENDPOINTS.map(e => (
                <div
                  key={e.path}
                  title={`点击复制: ${backendUrl}${e.path}`}
                  onClick={() => { navigator.clipboard.writeText(`${backendUrl}${e.path}`); toast.success("已复制完整地址") }}
                  className="flex items-center gap-2.5 px-3 py-2 rounded-xl bg-muted/20 border border-border/30 hover:bg-indigo-500/5 hover:border-indigo-500/20 transition-all group cursor-pointer">
                  <span className={`shrink-0 text-[9px] font-black text-white px-1.5 py-0.5 rounded-md ${e.color}`}>{e.badge}</span>
                  <code className="text-[11px] font-mono text-foreground/80 flex-1 truncate">{e.path}</code>
                  <span className="text-[10px] text-muted-foreground shrink-0 opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap">{e.desc}</span>
                </div>
              ))}
            </div>
          </Card>

          {/* 并发与引擎策略 */}
          <Card title="并发与引擎策略" icon={Cpu} color="cyan">
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs font-black text-foreground">单账号最大并发请求数</span>
                <span className="text-sm font-black text-cyan-500 tabular-nums">{maxInflight}</span>
              </div>
              <p className="text-[10px] text-muted-foreground leading-relaxed">
                控制每个 Qwen 账号同时最多处理几个 API 请求。设为 1 = 严格排队（最安全）；3–5 = 适度提升吞吐；超过 5 容易触发账号限速或封号。
              </p>
              <input type="range" min="1" max="10" value={maxInflight}
                onChange={e => setMaxInflight(parseInt(e.target.value))}
                className="w-full h-2 bg-muted/30 rounded-full appearance-none cursor-pointer accent-cyan-500 mt-1" />
              <div className="flex justify-between text-[9px] text-muted-foreground/60 font-black px-0.5">
                <span>1 最安全</span><span>5 推荐</span><span>10 高压</span>
              </div>
            </div>
            <button onClick={() => saveSetting("max_inflight_per_account", maxInflight, "并发数")}
              className="w-full h-10 bg-muted/30 border border-border/40 font-black text-[11px] rounded-xl hover:bg-muted/50 transition-all">
              应用并发设置
            </button>
            <Field label="驱动引擎模式">
              <select value={engineMode} onChange={e => { setEngineMode(e.target.value); saveSetting("engine_mode", e.target.value, "引擎模式") }}
                className="w-full h-12 bg-muted/20 border border-border/40 rounded-xl px-4 text-sm font-black">
                <option value="browser">浏览器引擎（Camoufox）</option>
                <option value="httpx">直连引擎（Httpx 指纹）</option>
                <option value="hybrid">混合引擎（自适应）</option>
              </select>
            </Field>
            <p className="text-[10px] text-muted-foreground">重启网关后完全生效；并发数变更运行时立即生效。</p>
          </Card>

          {/* 提示栏 */}
          <div className="flex gap-3 p-5 rounded-2xl bg-amber-500/10 border border-amber-500/20">
            <TriangleAlert className="w-5 h-5 text-amber-500 shrink-0 mt-0.5" />
            <p className="text-[11px] text-amber-600 dark:text-amber-400 font-bold leading-relaxed">
              修改引擎模式后建议重启后台服务以确保所有引擎正确初始化。
            </p>
          </div>

        </div>
      </div>
    </div>
  )
}
