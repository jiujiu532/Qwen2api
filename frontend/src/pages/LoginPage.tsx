import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { toast } from "sonner"
import { API_BASE } from "../lib/api"

export default function LoginPage() {
  const [key, setKey] = useState("")
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()

  const login = async () => {
    if (!key.trim()) return
    setLoading(true)
    try {
      const res = await fetch(`${API_BASE}/api/admin/settings`, {
        headers: { Authorization: `Bearer ${key.trim()}` }
      })
      if (res.ok) {
        localStorage.setItem("qwen2api_key", key.trim())
        navigate("/admin/accounts")
      } else {
        toast.error("密钥无效")
      }
    } catch {
      toast.error("连接失败")
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-[#FAF9F5]">
      <div className="w-[min(420px,92vw)] p-6">
        <div className="bg-white rounded-[14px] p-[22px] shadow-[0_20px_50px_rgba(0,0,0,.08)] border border-transparent hover:border-[#111] transition-colors">
          <div className="text-[12px] tracking-wider uppercase text-[#666] font-semibold">qwen2api</div>
          <div className="mt-1.5 text-[18px] font-semibold">管理后台</div>
          <div className="mt-1 text-[12px] text-[#666]">请输入管理密钥以继续</div>
          <div className="mt-4 grid gap-2.5">
            <input
              type="password"
              value={key}
              onChange={e => setKey(e.target.value)}
              onKeyDown={e => e.key === "Enter" && login()}
              placeholder="管理密钥"
              className="w-full h-8 px-2.5 text-[12px] rounded-lg border border-[#e5e5e5] bg-white focus:border-[#bbb] focus:shadow-[0_0_0_2px_rgba(0,0,0,.04)] placeholder:text-[#999] transition-all"
            />
            <button
              onClick={login}
              disabled={loading}
              className="w-full h-8 rounded-lg bg-[#111] text-white text-[12px] font-semibold hover:opacity-90 transition-opacity disabled:opacity-50"
            >
              {loading ? "验证中..." : "继续"}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
