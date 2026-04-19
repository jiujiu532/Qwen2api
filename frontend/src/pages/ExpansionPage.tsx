import { useEffect, useMemo, useState, useRef } from "react"
import { Link } from "react-router-dom"
import { Bot, RefreshCw, Zap, ShieldAlert, CheckCircle2, FlaskConical, Cpu, ExternalLink, Mail, StopCircle, ChevronUp, Info, Sparkles, BookOpen, X, ChevronRight } from "lucide-react"
import { toast } from "sonner"
import { getAuthHeader } from "../lib/auth"
import { API_BASE } from "../lib/api"

const PROVIDERS = [
    { id: "guerrilla", name: "GuerrillaMail（推荐）", desc: "老牌高抗封驱动，具备极强的反爬对抗能力，首选推荐" },
    { id: "default", name: "官方助手（ChatGPT.org.uk）", desc: "同步项目根目录 main.py 的底层核心邮箱引擎" },
    { id: "moemail", name: "MoeMail（自建方案）", desc: "需在系统设置中配置专用域名与 API 密钥" },
    { id: "tempmail", name: "TempMail（CF Workers）", desc: "基于 Cloudflare Workers 的临时邮箱，需配置 Workers 域名与管理密码" },
]

export default function ExpansionPage() {
    // 从 localStorage 初始化状态
    const [batchCount, setBatchCount] = useState(() => Number(localStorage.getItem("qwen_expansion_count")) || 10)
    const [batchThreads, setBatchThreads] = useState(() => Number(localStorage.getItem("qwen_expansion_threads")) || 2)
    const [batchMaxRetries, setBatchMaxRetries] = useState(() => Number(localStorage.getItem("qwen_expansion_max_retries")) || 15)
    const [provider, setProvider] = useState(() => localStorage.getItem("qwen_expansion_provider") || "guerrilla")
    const [sysInfo, setSysInfo] = useState<any>(null)

    const [batching, setBatching] = useState(false)
    const [logs, setLogs] = useState<string[]>([])
    const [autoScroll, setAutoScroll] = useState(true)
    const [settings, setSettings] = useState<any>(null)
    const logContainerRef = useRef<HTMLDivElement>(null)
    const [logVerbosity, setLogVerbosity] = useState(() => Number(localStorage.getItem("qwen_log_verbosity")) || 0)
    const [showVerbosityPicker, setShowVerbosityPicker] = useState(false)
    const [showGuide, setShowGuide] = useState(false)

    // 当设置变更时保存到 localStorage
    useEffect(() => {
        localStorage.setItem("qwen_expansion_count", batchCount.toString())
        localStorage.setItem("qwen_expansion_threads", batchThreads.toString())
        localStorage.setItem("qwen_expansion_max_retries", batchMaxRetries.toString())
        localStorage.setItem("qwen_expansion_provider", provider)
    }, [batchCount, batchThreads, batchMaxRetries, provider])

    useEffect(() => {
        // 初始获取设置以检查 MoeMail 配置
        fetch(`${API_BASE}/api/admin/settings`, { headers: getAuthHeader() })
            .then(res => res.json())
            .then(data => setSettings(data))
            .catch(() => { })

        fetch(`${API_BASE}/api/admin/system-info`, { headers: getAuthHeader() })
            .then(res => res.json())
            .then(data => setSysInfo(data))
            .catch(() => { })

        const intv = setInterval(() => {
            fetch(`${API_BASE}/api/admin/logs`, { headers: getAuthHeader() })
                .then(res => res.json())
                .then(data => setLogs(data.logs || []))
                .catch(() => { })
        }, 2000)
        return () => clearInterval(intv)
    }, [])

    useEffect(() => {
        if (autoScroll && logContainerRef.current) {
            logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight
        }
    }, [logs, autoScroll])

    const handleBatchRegister = () => {
        if (provider === "moemail" && (!settings?.moemail_domain || !settings?.moemail_key)) {
            return toast.error("MoeMail 配置缺失！请先前往 [系统设置] 填写域名及密钥。")
        }
        if (provider === "tempmail" && (!settings?.tempmail_domain || !settings?.tempmail_key)) {
            return toast.error("TempMail 配置缺失！请先前往 [系统设置] 填写 Workers 域名及管理密码。")
        }

        setBatching(true)
        const id = toast.loading(`启动批量扩容任务 (渠道: ${provider})...`)
        fetch(`${API_BASE}/api/admin/accounts/batch-register`, {
            method: "POST",
            headers: { "Content-Type": "application/json", ...getAuthHeader() },
            body: JSON.stringify({ count: batchCount, threads: batchThreads, provider, max_retries: batchMaxRetries })
        }).then(res => res.json())
            .then(data => {
                if (data.ok) toast.success("异步扩容序列已启动，请观察实时日志", { id })
                else toast.error("扩容启动失败", { id })
            })
            .catch(() => toast.error("请求异常", { id }))
            .finally(() => setBatching(false))
    }

    const handleStopRegister = () => {
        fetch(`${API_BASE}/api/admin/accounts/stop-register`, {
            method: "POST",
            headers: { ...getAuthHeader() },
        }).then(res => res.json())
            .then(data => {
                if (data.ok) toast.success("停止信号已发送，进行中的任务将完成后停止")
                else toast.error("停止失败")
            })
            .catch(() => toast.error("请求异常"))
    }

    // 日志详细程度过滤
    const VERBOSITY_LEVELS = [
        { value: 0, label: "全部" },
        { value: 1, label: "精简", desc: "隐藏 HTTP 请求" },
        { value: 2, label: "仅关键", desc: "仅成功/失败/错误" },
    ]

    const filteredLogs = useMemo(() => {
        if (logVerbosity === 0) return logs
        if (logVerbosity === 1) {
            return logs.filter(l => !l.includes("HTTP Request:") && !l.includes("HTTP/1.1"))
        }
        // verbosity === 2: 仅关键日志
        return logs.filter(l =>
            l.includes("成功") || l.includes("失败") || l.includes("[ERROR]") ||
            l.includes("[WARNING]") || l.includes("完成") || l.includes("同步到池") ||
            l.includes("停止") || l.includes("启动") || l.includes("批量注册")
        )
    }, [logs, logVerbosity])

    return (
        <div className="space-y-12 animate-fade-in-up max-w-[1400px] mx-auto pb-20">
            <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-xl bg-indigo-500/10 flex items-center justify-center border border-indigo-500/20">
                    <Cpu className="w-5 h-5 text-indigo-500" />
                </div>
                <h2 className="text-3xl font-black tracking-tighter text-foreground">账号扩容中心</h2>
            </div>

            <div className="grid gap-10 lg:grid-cols-12">
                <div className="lg:col-span-5 space-y-8 flex flex-col">
                    <div className="glass-card p-10 rounded-[3rem] space-y-10 border-indigo-500/20 bg-indigo-500/[0.02] flex-1">
                        <div className="flex items-center justify-between gap-4">
                            <div className="flex items-center gap-4">
                                <div className="w-14 h-14 rounded-3xl bg-indigo-500 flex items-center justify-center shadow-2xl shadow-indigo-500/40">
                                    <Cpu className="text-white w-7 h-7" />
                                </div>
                                <div>
                                    <h3 className="text-xl font-black text-foreground">账号注册</h3>
                                </div>
                            </div>
                            <button
                                onClick={() => setShowGuide(true)}
                                className="flex items-center gap-2 px-4 py-2 rounded-2xl bg-indigo-500/10 border border-indigo-500/20 text-indigo-500 hover:bg-indigo-500 hover:text-white transition-all text-[12px] font-bold"
                            >
                                <BookOpen className="w-4 h-4" />
                                使用指南
                            </button>
                        </div>

                        <div className="space-y-8">
                            <div className="space-y-3">
                                <label className="text-[11px] font-medium text-muted-foreground ml-1">扩容渠道选择</label>
                                <div className="grid grid-cols-1 gap-3">
                                    {PROVIDERS.map(p => (
                                        <button
                                            key={p.id}
                                            onClick={() => setProvider(p.id)}
                                            className={`flex items-start gap-4 p-5 rounded-3xl border transition-all text-left group ${provider === p.id
                                                ? "bg-indigo-500/10 border-indigo-500/40 ring-2 ring-indigo-500/10"
                                                : "bg-muted/10 border-border/40 hover:bg-muted/30 hover:border-indigo-500/20"
                                                }`}
                                        >
                                            <div className={`mt-1 p-2 rounded-xl transition-colors ${provider === p.id ? "bg-indigo-500/20 text-indigo-500" : "bg-muted/30 text-muted-foreground group-hover:text-indigo-400"}`}>
                                                {p.id === 'moemail' ? <FlaskConical className="w-4 h-4" /> : p.id === 'tempmail' ? <Mail className="w-4 h-4" /> : <Zap className="w-4 h-4" />}
                                            </div>
                                            <div className="min-w-0">
                                                <p className={`text-[13px] font-black transition-colors ${provider === p.id ? "text-indigo-400" : "text-foreground/80"}`}>{p.name}</p>
                                                <p className="text-[10px] text-muted-foreground font-medium mt-1 truncate">{p.desc}</p>
                                            </div>
                                        </button>
                                    ))}
                                </div>
                                {provider === "moemail" && !settings?.moemail_domain && (
                                    <div className="p-4 rounded-2xl bg-amber-500/10 border border-amber-500/20 flex items-center gap-3 mt-2">
                                        <ShieldAlert className="w-4 h-4 text-amber-500 shrink-0" />
                                        <p className="text-[11px] text-amber-500 font-medium flex-1">未检测到 MoeMail 自建设置，任务将无法启动。</p>
                                        <Link to="/settings" className="flex items-center gap-1 text-[10px] font-black text-amber-500 border border-amber-500/40 rounded-lg px-2 py-1 hover:bg-amber-500/20 transition-all shrink-0">
                                            <ExternalLink className="w-3 h-3" /> 前往设置
                                        </Link>
                                    </div>
                                )}
                                {provider === "tempmail" && !settings?.tempmail_domain && (
                                    <div className="p-4 rounded-2xl bg-amber-500/10 border border-amber-500/20 flex items-center gap-3 mt-2">
                                        <ShieldAlert className="w-4 h-4 text-amber-500 shrink-0" />
                                        <p className="text-[11px] text-amber-500 font-medium flex-1">未检测到 TempMail 自建设置，任务将无法启动。</p>
                                        <Link to="/settings" className="flex items-center gap-1 text-[10px] font-black text-amber-500 border border-amber-500/40 rounded-lg px-2 py-1 hover:bg-amber-500/20 transition-all shrink-0">
                                            <ExternalLink className="w-3 h-3" /> 前往设置
                                        </Link>
                                    </div>
                                )}
                            </div>

                            <div className="grid grid-cols-3 gap-6">
                                <div className="space-y-3">
                                    <div className="flex items-center h-5 ml-1">
                                        <label className="text-[11px] font-medium text-muted-foreground">扩容总数</label>
                                    </div>
                                    <input type="number" value={batchCount} onChange={e => setBatchCount(parseInt(e.target.value) || 1)} className="w-full h-14 bg-muted/20 border border-border/40 rounded-2xl px-6 text-sm font-black focus:ring-2 focus:ring-indigo-500/30 transition-all" />
                                </div>
                                <div className="space-y-3">
                                    <div className="flex items-center justify-between h-5 ml-1">
                                        <label className="text-[11px] font-medium text-muted-foreground">邮件查询次数</label>
                                        <span className="text-[9px] text-muted-foreground/50">每5秒查一次</span>
                                    </div>
                                    <input
                                        type="number" min={1} value={batchMaxRetries}
                                        onChange={e => setBatchMaxRetries(parseInt(e.target.value) || 1)}
                                        className="w-full h-14 bg-muted/20 border border-border/40 rounded-2xl px-6 text-sm font-black text-rose-400 focus:ring-2 focus:ring-rose-500/30 transition-all"
                                    />
                                </div>
                                <div className="space-y-3">
                                    <div className="flex items-center justify-between h-5 ml-1">
                                        <label className="text-[11px] font-medium text-muted-foreground">并行并发</label>
                                        {sysInfo && (
                                            <button
                                                onClick={() => setBatchThreads(sysInfo.recommended_threads)}
                                                className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-indigo-500/10 border border-indigo-500/20 hover:bg-indigo-500/20 transition-all"
                                                title={`CPU: ${sysInfo.cpu_cores}核, 可用RAM: ${sysInfo.ram_available_gb}GB`}
                                            >
                                                <Sparkles className="w-2.5 h-2.5 text-indigo-400" />
                                                <span className="text-[10px] font-black text-indigo-400">推荐 {sysInfo.recommended_threads}</span>
                                            </button>
                                        )}
                                    </div>
                                    <input type="number" min={1} max={30} value={batchThreads} onChange={e => setBatchThreads(parseInt(e.target.value) || 1)} className="w-full h-14 bg-muted/20 border border-border/40 rounded-2xl px-6 text-sm font-black text-indigo-500 focus:ring-2 focus:ring-indigo-500/30 transition-all" />
                                </div>
                            </div>

                            {/* 全宽资源使用指示器 */}
                            {sysInfo && (
                                <div className="space-y-2 pt-1">
                                    <div className="flex items-center gap-4">
                                        {[
                                            { label: "CPU", color: "bg-blue-400/60", val: batchThreads, max: sysInfo.limits.by_cpu, hint: `${sysInfo.cpu_cores}核` },
                                            { label: "RAM", color: "bg-emerald-400/60", val: batchThreads, max: sysInfo.limits.by_ram, hint: `${sysInfo.ram_available_gb}G可用` },
                                            { label: "代理IP", color: settings?.proxy_enabled ? "bg-violet-400/60" : "bg-rose-400/80", val: 1, max: 1, hint: settings?.proxy_enabled ? "已启用" : "未启用" },
                                        ].map(({ label, color, val, max, hint }) => (
                                            <div key={label} className="flex-1 flex items-center gap-2">
                                                <span className="text-[9px] text-muted-foreground/60 w-10 shrink-0">{label}</span>
                                                <div className="flex-1 h-1 rounded-full bg-muted/30 overflow-hidden">
                                                    <div className={`h-full rounded-full transition-all ${color}`} style={{ width: `${Math.min(100, (val / max) * 100)}%` }} />
                                                </div>
                                                <span className="text-[9px] text-muted-foreground/50 shrink-0">{hint}</span>
                                            </div>
                                        ))}
                                        {!settings?.proxy_enabled && (
                                            <p className="text-[10px] text-amber-500 font-black flex items-center gap-1 shrink-0">
                                                <Info className="w-2.5 h-2.5 shrink-0" />
                                                建议启用代理池以提高成功率
                                            </p>
                                        )}
                                    </div>
                                </div>
                            )}

                            <div className="grid grid-cols-2 gap-4">
                                <button
                                    onClick={handleBatchRegister}
                                    disabled={batching}
                                    className="h-14 rounded-2xl bg-indigo-500 text-white font-black text-sm shadow-xl shadow-indigo-500/30 hover:scale-[1.02] active:scale-[0.98] transition-all disabled:opacity-50 flex items-center justify-center gap-2"
                                >
                                    {batching ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Bot className="h-4 w-4" />}
                                    启动
                                </button>
                                <button
                                    onClick={handleStopRegister}
                                    className="h-14 rounded-2xl bg-rose-500/10 border-2 border-rose-500/30 text-rose-500 font-black text-sm hover:bg-rose-500 hover:text-white hover:scale-[1.02] active:scale-[0.98] transition-all flex items-center justify-center gap-2"
                                >
                                    <StopCircle className="h-4 w-4" />
                                    停止
                                </button>
                            </div>
                        </div>
                    </div>
                </div>

                <div className="lg:col-span-7 space-y-6 flex flex-col h-full">
                    <div className="glass-card rounded-[3rem] overflow-hidden flex-1 flex flex-col border-indigo-500/20 bg-black/40">
                        <div className="px-10 py-8 border-b border-border/40 flex items-center justify-between shrink-0 bg-muted/5">
                            <div className="flex items-center gap-4">
                                <div className="relative">
                                    <div className="w-3 h-3 rounded-full bg-indigo-500 animate-ping absolute inset-0 opacity-40" />
                                    <div className="w-3 h-3 rounded-full bg-indigo-500 shadow-lg shadow-indigo-500/50" />
                                </div>
                                <h3 className="text-sm font-semibold text-foreground">实时日志</h3>
                            </div>
                            <div className="flex items-center gap-4">
                                {/* 日志详细程度选择器 */}
                                <div className="relative">
                                    <button
                                        onClick={() => setShowVerbosityPicker(!showVerbosityPicker)}
                                        className="flex items-center gap-1.5 px-3 py-1.5 rounded-full transition-all border bg-indigo-500/10 border-indigo-500/30 text-indigo-400 hover:bg-indigo-500/20"
                                    >
                                        <span className="text-[10px] font-black">{VERBOSITY_LEVELS.find(v => v.value === logVerbosity)?.label}</span>
                                        <ChevronUp className={`w-3 h-3 transition-transform ${showVerbosityPicker ? '' : 'rotate-180'}`} />
                                    </button>
                                    {showVerbosityPicker && (
                                        <div className="absolute top-full mt-2 left-1/2 -translate-x-1/2 bg-card/95 backdrop-blur-xl border border-border/60 rounded-2xl shadow-2xl shadow-black/20 p-1.5 min-w-[100px] z-50 animate-fade-in-up">
                                            {VERBOSITY_LEVELS.map(v => (
                                                <button
                                                    key={v.value}
                                                    onClick={() => {
                                                        setLogVerbosity(v.value)
                                                        localStorage.setItem("qwen_log_verbosity", v.value.toString())
                                                        setShowVerbosityPicker(false)
                                                    }}
                                                    className={`w-full px-4 py-2 rounded-xl text-[12px] font-bold transition-all text-center ${logVerbosity === v.value
                                                        ? 'bg-indigo-500 text-white shadow-lg shadow-indigo-500/30'
                                                        : 'text-foreground/70 hover:bg-muted/40'
                                                        }`}
                                                >
                                                    {v.label}
                                                </button>
                                            ))}
                                        </div>
                                    )}
                                </div>
                                <button
                                    onClick={() => setAutoScroll(!autoScroll)}
                                    className={`flex items-center gap-2 px-3 py-1.5 rounded-full transition-all border ${autoScroll
                                        ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-500"
                                        : "bg-muted/30 border-border/40 text-muted-foreground"
                                        }`}
                                >
                                    <div className={`w-1.5 h-1.5 rounded-full ${autoScroll ? "bg-emerald-500 animate-pulse" : "bg-muted-foreground/40"}`} />
                                    <span className="text-[10px] font-medium">
                                        {autoScroll ? "自动滚动：开启" : "自动滚动：已锁定"}
                                    </span>
                                </button>
                                <button onClick={() => setLogs([])} className="text-[11px] font-medium text-muted-foreground hover:text-rose-500 transition-colors">重置日志</button>
                            </div>
                        </div>

                        <div
                            ref={logContainerRef}
                            className="p-10 overflow-y-auto font-mono text-[13px] leading-[1.9] space-y-1 scrollbar-thin scrollbar-thumb-indigo-500/20 scroll-smooth h-[740px]"
                        >
                            {logs.length === 0 ? (
                                <div className="h-full flex flex-col items-center justify-center text-muted-foreground/30 space-y-6">
                                    <FlaskConical className="w-16 h-16 opacity-10" />
                                    <p className="font-black text-sm opacity-60">等待任务启动...</p>
                                </div>
                            ) : (
                                filteredLogs.map((log, i) => {
                                    const isSuccess = log.includes("成功") || log.includes("同步到池") || log.includes("完成");
                                    const isError = !isSuccess && (log.includes("[ERROR]") || log.includes("失败") || log.includes("异常"));
                                    const isWarning = log.includes("[WARNING]") || log.includes("等待");

                                    let icon = <Zap className="w-3.5 h-3.5 mt-0.5 opacity-40" />;
                                    let colorClass = "text-foreground/70";

                                    if (isSuccess) {
                                        icon = <CheckCircle2 className="w-3.5 h-3.5 mt-1 text-indigo-500" />;
                                        colorClass = "text-indigo-400 bg-indigo-500/5 p-3 rounded-2xl border border-indigo-500/10 my-2";
                                    } else if (isError) {
                                        icon = <ShieldAlert className="w-3.5 h-3.5 mt-1 text-rose-500" />;
                                        colorClass = "text-rose-400 bg-rose-500/5 p-3 rounded-2xl border border-rose-500/10 my-2";
                                    } else if (isWarning) {
                                        colorClass = "text-amber-400";
                                    }

                                    return (
                                        <div key={i} className={`flex gap-4 transition-all duration-500 hover:bg-white/5 p-1 rounded-lg ${colorClass}`}>
                                            <span className="opacity-20 shrink-0 font-black tabular-nums">{String(i + 1).padStart(4, '0')}</span>
                                            <div className="flex gap-3 min-w-0">
                                                <span className="shrink-0">{icon}</span>
                                                <span className="break-all font-medium tracking-tight">{log}</span>
                                            </div>
                                        </div>
                                    );
                                })
                            )}
                        </div>
                    </div>
                </div>
            </div>

            {/* 使用指南 Modal */}
            {showGuide && (
                <div
                    className="fixed inset-0 z-[9999] flex items-center justify-center p-6"
                    style={{ background: "rgba(0,0,0,0.55)", backdropFilter: "blur(6px)" }}
                    onClick={() => setShowGuide(false)}
                >
                    <div
                        className="glass-card guide-modal rounded-[2rem] w-full max-w-xl max-h-[80vh] overflow-y-auto"
                        style={{ background: "hsl(var(--popover))", color: "hsl(var(--popover-foreground))" }}
                        onClick={e => e.stopPropagation()}
                    >
                        {/* Header */}
                        <div className="flex items-center justify-between px-7 pt-7 pb-5 border-b border-border/30">
                            <div className="flex items-center gap-3">
                                <div className="w-9 h-9 rounded-2xl bg-indigo-500/10 flex items-center justify-center border border-indigo-500/20">
                                    <BookOpen className="w-4 h-4 text-indigo-500" />
                                </div>
                                <div>
                                    <h3 className="text-base font-black">使用指南</h3>
                                    <p className="text-[11px] text-muted-foreground">账号注册 · 快速上手</p>
                                </div>
                            </div>
                            <button onClick={() => setShowGuide(false)} className="p-2 rounded-xl hover:bg-muted/40 transition-colors">
                                <X className="w-4 h-4 text-muted-foreground" />
                            </button>
                        </div>

                        {/* Body */}
                        <div className="px-7 py-5 space-y-5">

                            {/* Step 1 — 注册流程 */}
                            <div>
                                <p className="text-[11px] font-black uppercase tracking-widest text-indigo-500 mb-2">注册流程</p>
                                <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
                                    {["选渠道", "配参数", "开始注册", "查看日志", "完成"].map((s, i, arr) => (
                                        <>
                                            <span key={s} className="px-2.5 py-1 rounded-xl bg-muted/40 font-semibold">{s}</span>
                                            {i < arr.length - 1 && <ChevronRight className="w-3 h-3 opacity-30" />}
                                        </>
                                    ))}
                                </div>
                            </div>

                            <div className="border-t border-border/20" />

                            {/* Step 2 — 邮箱渠道 2×2 grid */}
                            <div>
                                <p className="text-[11px] font-black uppercase tracking-widest text-indigo-500 mb-2.5">邮箱渠道</p>
                                <div className="grid grid-cols-2 gap-2">
                                    {[
                                        { name: "GuerrillaMail", badge: "推荐", color: "#10b981", desc: "无需配置，老牌抗封，首选" },
                                        { name: "官方助手", badge: null, color: "#6366f1", desc: "同步 main.py 底层引擎" },
                                        { name: "MoeMail", badge: "自建", color: "#a855f7", desc: "需配置域名与 API 密钥" },
                                        { name: "TempMail", badge: "CF", color: "#f59e0b", desc: "基于 Cloudflare Workers" },
                                    ].map(r => (
                                        <div key={r.name} className="p-3 rounded-2xl bg-muted/20 border border-border/30">
                                            <div className="flex items-center gap-1.5 mb-1">
                                                <div className="w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ background: r.color }} />
                                                <span className="text-[12px] font-black" style={{ color: r.color }}>{r.name}</span>
                                                {r.badge && <span className="text-[9px] font-black px-1.5 py-0.5 rounded-lg" style={{ background: r.color + "22", color: r.color }}>{r.badge}</span>}
                                            </div>
                                            <p className="text-[10px] text-muted-foreground leading-snug">{r.desc}</p>
                                        </div>
                                    ))}
                                </div>
                            </div>

                            <div className="border-t border-border/20" />

                            {/* Step 3 — 参数说明 */}
                            <div>
                                <p className="text-[11px] font-black uppercase tracking-widest text-indigo-500 mb-2.5">参数说明</p>
                                <div className="space-y-2">
                                    {[
                                        ["注册数量", "单批目标账号数，建议不超过 50 个"],
                                        ["并发线程", "同时运行的注册任务数，参考上方推荐值"],
                                        ["最大重试", "单账号失败后最多重试次数，込小可节約时间"],
                                    ].map(([k, v]) => (
                                        <div key={k} className="flex gap-3 p-2.5 rounded-xl bg-muted/15 text-[11px]">
                                            <span className="font-black text-foreground/70 flex-shrink-0 w-[4.5rem]">{k}</span>
                                            <span className="text-muted-foreground">{v}</span>
                                        </div>
                                    ))}
                                </div>
                            </div>

                            <div className="border-t border-border/20" />

                            {/* Step 4+5 — 代理池 & 完成后 */}
                            <div className="grid grid-cols-2 gap-3">
                                <div>
                                    <p className="text-[11px] font-black uppercase tracking-widest text-indigo-500 mb-2">代理池（可选）</p>
                                    <p className="text-[11px] text-muted-foreground leading-relaxed">在「系统设置 → 代理池」配置后自动轮换 IP，提升高频注册成功率。</p>
                                </div>
                                <div>
                                    <p className="text-[11px] font-black uppercase tracking-widest text-indigo-500 mb-2">注册完成后</p>
                                    <ul className="text-[11px] text-muted-foreground space-y-1">
                                        <li>→ 账号自动加入账号池</li>
                                        <li>→ 进入「账号列表」执行「一键检测」</li>
                                        <li>→ 外部调用 <code className="px-1 rounded bg-muted/50 text-indigo-400 font-mono text-[9px]">/v1/chat/completions</code></li>
                                    </ul>
                                </div>
                            </div>

                        </div>

                        {/* Footer */}
                        <div className="px-7 pb-7">
                            <button
                                onClick={() => setShowGuide(false)}
                                className="w-full h-10 rounded-2xl bg-indigo-500 text-white font-black text-sm hover:bg-indigo-400 transition-all"
                            >
                                知道了
                            </button>
                        </div>
                    </div>
                </div>
            )}

        </div>
    )
}
