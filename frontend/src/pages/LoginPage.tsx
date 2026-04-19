import { useState, useEffect } from "react"
import { useNavigate } from "react-router-dom"
import { KeyRound, Sparkles, ShieldCheck, Zap } from "lucide-react"
import QCatIcon from "../components/QCatIcon"
import { toast } from "sonner"
import { API_BASE } from "../lib/api"

export default function LoginPage() {
    const [key, setKey] = useState("")
    const [loading, setLoading] = useState(false)
    const navigate = useNavigate()

    useEffect(() => {
        const existingKey = localStorage.getItem('qwen2api_key')
        if (existingKey) navigate("/")
    }, [navigate])

    const handleLogin = (e: React.FormEvent) => {
        e.preventDefault()
        if (!key.trim()) return toast.error("请输入管理密钥")

        setLoading(true)
        fetch(`${API_BASE}/api/admin/settings`, {
            headers: { "Authorization": `Bearer ${key.trim()}` }
        }).then(res => {
            if (res.ok) {
                localStorage.setItem('qwen2api_key', key.trim())
                toast.success("欢迎回来，管理员")
                navigate("/")
            } else {
                toast.error("密钥验证失败")
            }
        }).catch(() => {
            toast.error("网络连接异常")
        }).finally(() => {
            setLoading(false)
        })
    }

    return (
        <div className="min-h-screen w-full flex items-center justify-center bg-background relative overflow-hidden p-6 mesh-gradient">
            <div className="absolute top-0 left-0 w-full h-full opacity-30 pointer-events-none">
                <div className="absolute top-[10%] left-[20%] w-64 h-64 bg-indigo-500/20 rounded-full blur-[100px] animate-pulse" />
                <div className="absolute bottom-[20%] right-[10%] w-96 h-96 bg-purple-500/10 rounded-full blur-[120px]" />
            </div>

            <div className="w-full max-w-xl animate-fade-in-up">
                <div className="glass-card rounded-[3.5rem] p-10 md:p-16 space-y-12 relative">
                    <div className="absolute -top-12 left-1/2 -translate-x-1/2">
                        <div className="w-24 h-24 rounded-[2rem] bg-gradient-to-br from-white to-indigo-50 flex items-center justify-center shadow-2xl border-4 border-white">
                            <QCatIcon className="w-16 h-16" />
                        </div>
                    </div>

                    <div className="text-center space-y-4 pt-4">
                        <div className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full bg-indigo-500/10 border border-indigo-500/20">
                            <ShieldCheck className="w-3.5 h-3.5 text-indigo-500" />
                            <span className="text-[10px] font-medium text-indigo-400">安全节点鉴权已就绪</span>
                        </div>
                        <h1 className="text-4xl md:text-5xl font-black text-foreground tracking-tighter uppercase">
                            Qwen2API
                        </h1>
                        <p className="text-muted-foreground text-sm font-medium tracking-wide">
                            请输入您的主管理密钥以激活全网关控制权限。
                        </p>
                    </div>

                    <form onSubmit={handleLogin} className="space-y-8">
                        <div className="space-y-4">
                            <label className="text-[11px] font-medium text-muted-foreground ml-2">管理鉴权私钥</label>
                            <div className="relative group">
                                <div className="absolute inset-y-0 left-6 flex items-center pointer-events-none">
                                    <KeyRound className="w-5 h-5 text-muted-foreground group-focus-within:text-indigo-500 transition-colors" />
                                </div>
                                <input
                                    type="password"
                                    value={key}
                                    onChange={(e) => setKey(e.target.value)}
                                    placeholder="默认：123456"
                                    className="w-full h-16 bg-muted/30 border border-border/40 rounded-3xl pl-16 pr-6 text-foreground placeholder:text-muted-foreground/30 focus:outline-none focus:ring-4 focus:ring-indigo-500/10 focus:border-indigo-500/40 transition-all font-mono"
                                />
                            </div>
                        </div>

                        <button
                            disabled={loading}
                            className="w-full h-16 bg-foreground text-background font-black rounded-[2rem] flex items-center justify-center gap-3 hover:scale-[1.02] active:scale-95 transition-all text-sm shadow-xl shadow-black/5 disabled:opacity-50"
                        >
                            {loading ? (
                                <Zap className="w-5 h-5 animate-spin" />
                            ) : (
                                <><Sparkles className="w-5 h-5" /> 立即接入控制台</>
                            )}
                        </button>
                    </form>

                    <div className="pt-8 border-t border-border/40 text-center">
                        <p className="text-[10px] text-muted-foreground font-medium">
                            © 2026 Qwen2API · v2.0.0
                        </p>
                    </div>
                </div>
            </div>
        </div>
    )
}
