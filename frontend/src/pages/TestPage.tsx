import { useEffect, useRef, useState } from "react"
import { Send, RefreshCw, Bot, ChevronDown, Check, Zap, ZapOff, FlaskConical } from "lucide-react"
import { getAuthHeader } from "../lib/auth"
import { API_BASE } from "../lib/api"
import { toast } from "sonner"

// 渲染消息内容：自动把 Markdown 图片和图片 URL 渲染成 <img>
function MessageContent({ content }: { content: string }) {
  type Seg = { start: number; end: number; url: string }
  const segs: Seg[] = []
  const fullRe = /!\[[^\]]*\]\((https?:\/\/[^)\s]+)\)|(https?:\/\/[^\s"<>]+\.(?:jpg|jpeg|png|webp|gif)[^\s"<>]*)/gi
  let m: RegExpExecArray | null
  while ((m = fullRe.exec(content)) !== null) {
    segs.push({ start: m.index, end: m.index + m[0].length, url: (m[1] || m[2]) as string })
  }

  if (segs.length === 0) {
    return <div className="whitespace-pre-wrap leading-relaxed">{content}</div>
  }

  const nodes: React.ReactNode[] = []
  let cursor = 0
  segs.forEach((seg, i) => {
    if (seg.start > cursor) {
      nodes.push(<span key={"t" + i}>{content.slice(cursor, seg.start)}</span>)
    }
    nodes.push(
      <div key={"i" + i} className="my-2">
        <img
          src={seg.url}
          alt="generated"
          className="max-w-full rounded-lg shadow-md border"
          loading="lazy"
          onError={e => { (e.currentTarget as HTMLImageElement).style.display = "none" }}
        />
        <div className="text-xs text-muted-foreground mt-1 break-all font-mono">{seg.url}</div>
      </div>
    )
    cursor = seg.end
  })
  if (cursor < content.length) {
    nodes.push(<span key="tail">{content.slice(cursor)}</span>)
  }
  return <div className="whitespace-pre-wrap leading-relaxed">{nodes}</div>
}

const MODELS = [
  { id: "qwen3.6-plus", name: "Qwen 3.6 Plus" },
  { id: "qwen-max", name: "Qwen Max" },
  { id: "qwen-turbo", name: "Qwen Turbo" },
]

export default function TestPage() {
  const [messages, setMessages] = useState<{ role: string; content: string; reasoning_content?: string; error?: boolean }[]>([])
  const [input, setInput] = useState("")
  const [loading, setLoading] = useState(false)
  const [model, setModel] = useState("qwen3.6-plus")
  const [showModelList, setShowModelList] = useState(false)
  const [stream, setStream] = useState(true)
  const bottomRef = useRef<HTMLDivElement>(null)
  const modelRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages])

  // Close model list on click outside
  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (modelRef.current && !modelRef.current.contains(e.target as Node)) {
        setShowModelList(false)
      }
    }
    document.addEventListener("mousedown", handleClick)
    return () => document.removeEventListener("mousedown", handleClick)
  }, [])

  const handleSend = async () => {
    if (!input.trim() || loading) return
    const userMsg = { role: "user", content: input }
    setMessages(prev => [...prev, userMsg])
    setInput("")
    setLoading(true)

    try {
      if (!stream) {
        const res = await fetch(`${API_BASE}/v1/chat/completions`, {
          method: "POST",
          headers: { "Content-Type": "application/json", ...getAuthHeader() },
          body: JSON.stringify({ model, messages: [...messages, userMsg], stream: false })
        })
        const data = await res.json()
        if (data.error) {
          setMessages(prev => [...prev, { role: "assistant", content: `❌ ${data.error}`, error: true }])
        } else if (data.choices?.[0]) {
          setMessages(prev => [...prev, data.choices[0].message])
        } else {
          setMessages(prev => [...prev, { role: "assistant", content: `❌ 未知响应: ${JSON.stringify(data)}`, error: true }])
        }
      } else {
        const res = await fetch(`${API_BASE}/v1/chat/completions`, {
          method: "POST",
          headers: { "Content-Type": "application/json", ...getAuthHeader() },
          body: JSON.stringify({ model, messages: [...messages, userMsg], stream: true })
        })

        if (!res.ok) {
          const errText = await res.text()
          setMessages(prev => [...prev, { role: "assistant", content: `❌ HTTP ${res.status}: ${errText}`, error: true }])
          return
        }

        if (!res.body) throw new Error("No response body")

        setMessages(prev => [...prev, { role: "assistant", content: "" }])
        const reader = res.body.getReader()
        const decoder = new TextDecoder()
        let hasContent = false

        while (true) {
          const { done, value } = await reader.read()
          if (done) break

          const chunk = decoder.decode(value, { stream: true })
          for (const rawLine of chunk.split("\n")) {
            const line = rawLine.trim()
            if (!line || line.startsWith(":") || line === "data: [DONE]") continue
            if (line.startsWith("data: ")) {
              try {
                const data = JSON.parse(line.slice(6))
                if (data.error) {
                  setMessages(prev => {
                    const msgs = [...prev]
                    msgs[msgs.length - 1] = { role: "assistant", content: `❌ ${data.error}`, error: true }
                    return msgs
                  })
                  hasContent = true
                  break
                }
                const delta = data.choices?.[0]?.delta
                const reasoning: string = delta?.reasoning_content ?? ""
                const content: string = delta?.content ?? ""

                if (reasoning || content) {
                  hasContent = true
                  setMessages(prev => {
                    if (prev.length === 0) return prev
                    const msgs = [...prev]
                    const last = msgs[msgs.length - 1]
                    msgs[msgs.length - 1] = {
                      ...last,
                      reasoning_content: reasoning ? (last.reasoning_content || "") + reasoning : last.reasoning_content,
                      content: content ? (last.content || "") + content : last.content
                    }
                    return msgs
                  })
                }
              } catch (_) { /* skip */ }
            }
          }
        }

        if (!hasContent) {
          setMessages(prev => {
            const msgs = [...prev]
            msgs[msgs.length - 1] = { role: "assistant", content: "❌ 响应为空（账号可能未激活或无可用账号）", error: true }
            return msgs
          })
        }
      }
    } catch (err: any) {
      toast.error(`网络错误: ${err.message}`)
      setMessages(prev => [...prev, { role: "assistant", content: `❌ 网络错误: ${err.message}`, error: true }])
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex flex-col h-[calc(100vh-10rem)] space-y-8 max-w-[1400px] mx-auto animate-fade-in-up">
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-6">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-indigo-500/10 flex items-center justify-center border border-indigo-500/20">
            <FlaskConical className="w-5 h-5 text-indigo-500" />
          </div>
          <h2 className="text-3xl font-black tracking-tighter text-foreground">交互测试</h2>
        </div>
        <div className="flex gap-4 items-center flex-wrap">
          {/* Custom Model Dropdown */}
          <div className="relative" ref={modelRef}>
            <button
              onClick={() => setShowModelList(!showModelList)}
              className="flex items-center h-11 bg-muted/30 border border-border/40 rounded-2xl px-5 gap-3 hover:bg-muted/50 transition-all group"
            >
              <span className="text-[10px] font-black text-muted-foreground whitespace-nowrap">当前模型</span>
              <span className="text-xs font-semibold text-indigo-500">{MODELS.find(m => m.id === model)?.name}</span>
              <ChevronDown className={`h-4 w-4 text-indigo-500 transition-transform duration-300 ${showModelList ? 'rotate-180' : ''}`} />
            </button>

            {showModelList && (
              <div className="absolute top-full mt-3 left-0 w-56 glass-card rounded-2xl border border-border/40 shadow-2xl py-2 z-50 animate-in fade-in zoom-in duration-200 origin-top">
                {MODELS.map(m => (
                  <button
                    key={m.id}
                    onClick={() => { setModel(m.id); setShowModelList(false) }}
                    className={`w-full flex items-center justify-between px-5 py-3.5 text-xs font-semibold transition-colors hover:bg-indigo-500/10 ${model === m.id ? 'text-indigo-500 bg-indigo-500/5' : 'text-foreground/70'}`}
                  >
                    {m.name}
                    {model === m.id && <Check className="h-4 w-4" />}
                  </button>
                ))}
              </div>
            )}
          </div>

          <button
            onClick={() => setStream(!stream)}
            className={`flex items-center h-11 px-5 rounded-2xl border transition-all gap-3 group relative overflow-hidden ${stream
              ? "bg-indigo-500 text-white border-indigo-400 shadow-lg shadow-indigo-500/20"
              : "bg-muted/30 text-muted-foreground border-border/40 hover:bg-muted/50"
              }`}
          >
            {stream ? <Zap className="h-4 w-4 animate-pulse" /> : <ZapOff className="h-4 w-4" />}
            <span className="text-[10px] font-black whitespace-nowrap">
              {stream ? "流式输出模式" : "非流式输出"}
            </span>
          </button>

          <button
            onClick={() => { setMessages([]); toast.success("会话已重置") }}
            className="h-11 px-5 rounded-2xl bg-muted/30 border border-border/40 hover:bg-rose-500/10 hover:text-rose-500 hover:border-rose-500/20 transition-all flex items-center gap-3 font-black text-[11px]"
          >
            <RefreshCw className="h-4 w-4" /> 清空
          </button>
        </div>
      </div>

      <div className="flex-1 glass-card rounded-[3rem] overflow-hidden flex flex-col shadow-2xl">
        <div className="flex-1 overflow-y-auto p-10 space-y-10 flex flex-col custom-scrollbar">
          {messages.length === 0 && (
            <div className="h-full flex flex-col items-center justify-center text-center space-y-6">
              <div className="w-20 h-20 rounded-3xl bg-muted/10 flex items-center justify-center border border-border/20">
                <Bot className="h-10 w-10 text-muted-foreground/20" />
              </div>
              <div className="space-y-2">
                <p className="text-sm font-semibold text-foreground">实验室待命</p>
                <p className="text-xs text-muted-foreground max-w-xs mx-auto leading-relaxed">发送测试指令，系统将通过 /v1/chat/completions 路由至当前最优负载节点。</p>
              </div>
            </div>
          )}
          {messages.map((msg, i) => (
            <div key={i} className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"} animate-fade-in-up`}>
              <div className={`max-w-[75%] px-6 py-3.5 text-sm transition-all
                ${msg.role === "user"
                  ? "bg-foreground text-background font-medium shadow-xl shadow-foreground/10 rounded-2xl rounded-tr-none"
                  : msg.error
                    ? "bg-rose-500/10 border border-rose-500/20 text-rose-500 rounded-2xl rounded-tl-none"
                    : "glass-card border-border/40 text-foreground rounded-2xl rounded-tl-none"}`}>
                {msg.role === "assistant" && !msg.content && !msg.reasoning_content && loading ? (
                  <span className="animate-pulse flex items-center gap-3 text-indigo-500 font-black text-xs">
                    正在实时计算
                  </span>
                ) : msg.role === "assistant" && !msg.error ? (
                  <div className="space-y-4">
                    {msg.reasoning_content && (
                      <div className="bg-indigo-500/5 border-l-2 border-indigo-500/30 p-3 rounded-r-xl">
                        <div className="flex items-center gap-2 mb-2">
                          <div className="h-1.5 w-1.5 rounded-full bg-indigo-500 animate-pulse" />
                          <span className="text-[10px] font-black text-indigo-500/60">模型思考中...</span>
                        </div>
                        <div className="text-[12px] text-muted-foreground/80 font-medium italic leading-relaxed">
                          {msg.reasoning_content}
                        </div>
                      </div>
                    )}
                    {msg.content && <MessageContent content={msg.content} />}
                  </div>
                ) : (
                  <div className="whitespace-pre-wrap leading-relaxed">{msg.content}</div>
                )}
              </div>
            </div>
          ))}
          <div ref={bottomRef} />
        </div>

        <div className="p-8 border-t border-border/40 bg-muted/5 flex gap-4 items-center">
          <input
            type="text"
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => e.key === "Enter" && handleSend()}
            className="flex-1 h-14 bg-muted/20 border border-border/40 rounded-[1.5rem] px-8 text-sm focus:ring-2 focus:ring-indigo-500/30 transition-all placeholder:text-muted-foreground"
            placeholder="在此键入测试指令..."
          />
          <button
            onClick={handleSend}
            disabled={loading || !input.trim()}
            className="h-14 w-14 rounded-2xl bg-indigo-500 text-white flex items-center justify-center shadow-lg shadow-indigo-500/20 hover:scale-[1.05] active:scale-[0.95] transition-all disabled:opacity-50"
          >
            {loading ? <RefreshCw className="h-5 w-5 animate-spin" /> : <Send className="h-5 w-5" />}
          </button>
        </div>
      </div>
    </div>
  )
}
