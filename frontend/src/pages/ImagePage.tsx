import { useState, useEffect, useCallback, useRef, useMemo, memo } from "react"
import {
  Image as ImageIcon, Sparkles, Download, Trash2, RefreshCw,
  ChevronLeft, ChevronRight, X, History, Clock, Settings
} from "lucide-react"
import { toast } from "sonner"
import { API_BASE } from "../lib/api"

const STORAGE_KEY = "qwen2api_image_history"

interface GeneratedImage {
  id: string
  url: string
  prompt: string
  timestamp: number
}

interface DateGroup {
  label: string
  dateKey: string
  monthKey: string
  images: GeneratedImage[]
}

// ── localStorage helpers ──────────────────────────────────────
function loadHistory(): GeneratedImage[] {
  try { return JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]") } catch { return [] }
}
function saveHistory(images: GeneratedImage[], maxItems: number) {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(images.slice(0, maxItems))) } catch { /* ignore */ }
}

// ── Date grouping for sidebar ─────────────────────────────────
function groupByDate(images: GeneratedImage[]): DateGroup[] {
  const map = new Map<string, DateGroup>()
  const now = new Date()
  const todayKey = now.toISOString().slice(0, 10)
  const yest = new Date(now); yest.setDate(yest.getDate() - 1)
  const yesterKey = yest.toISOString().slice(0, 10)
  for (const img of images) {
    const d = new Date(img.timestamp)
    const dateKey = d.toISOString().slice(0, 10)
    const monthKey = dateKey.slice(0, 7)
    if (!map.has(dateKey)) {
      let label: string
      if (dateKey === todayKey) label = "今天"
      else if (dateKey === yesterKey) label = "昨天"
      else { const [y, m, day] = dateKey.split("-"); label = `${y}年${parseInt(m)}月${parseInt(day)}日` }
      map.set(dateKey, { label, dateKey, monthKey, images: [] })
    }
    map.get(dateKey)!.images.push(img)
  }
  return Array.from(map.values()).sort((a, b) => b.dateKey.localeCompare(a.dateKey))
}

function formatMonth(monthKey: string) {
  const [y, m] = monthKey.split("-")
  const now = new Date()
  const thisMonth = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`
  return monthKey === thisMonth ? "本月" : `${y}年${parseInt(m)}月`
}

/* ────────── Lightbox ────────── */
function Lightbox({ images, currentIndex, onClose, onNav }: {
  images: GeneratedImage[]; currentIndex: number
  onClose: () => void; onNav: (idx: number) => void
}) {
  const img = images[currentIndex]
  const hasPrev = currentIndex > 0
  const hasNext = currentIndex < images.length - 1

  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.stopPropagation(); onClose() }
      if (e.key === "ArrowLeft" && hasPrev) onNav(currentIndex - 1)
      if (e.key === "ArrowRight" && hasNext) onNav(currentIndex + 1)
    }
    window.addEventListener("keydown", h, true)
    return () => window.removeEventListener("keydown", h, true)
  }, [currentIndex, hasPrev, hasNext, onClose, onNav])

  return (
    <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/80 backdrop-blur-md" onClick={onClose}>
      <button onClick={onClose} className="absolute top-6 right-6 p-2 rounded-xl bg-white/10 hover:bg-white/20 text-white z-10"><X className="w-6 h-6" /></button>
      {hasPrev && (
        <button onClick={e => { e.stopPropagation(); onNav(currentIndex - 1) }}
          className="absolute left-4 md:left-8 p-3 rounded-2xl bg-white/10 hover:bg-white/20 text-white z-10">
          <ChevronLeft className="w-8 h-8" />
        </button>
      )}
      <div className="max-w-[90vw] max-h-[90vh] flex flex-col items-center gap-4" onClick={e => e.stopPropagation()}>
        <img src={img.url} alt={img.prompt} className="max-w-full max-h-[78vh] object-contain rounded-2xl shadow-2xl" />
        <div className="max-w-2xl text-center space-y-2">
          <p className="text-white/90 text-sm leading-relaxed">{img.prompt}</p>
          <div className="flex items-center justify-center gap-3">
            <span className="text-[9px] text-white/40 font-medium">{currentIndex + 1} / {images.length}</span>
            <a href={img.url} download className="px-3 py-1 rounded-lg bg-white/10 hover:bg-white/20 text-white text-[11px] font-medium flex items-center gap-1.5">
              <Download className="w-3 h-3" /> 下载
            </a>
          </div>
        </div>
      </div>
      {hasNext && (
        <button onClick={e => { e.stopPropagation(); onNav(currentIndex + 1) }}
          className="absolute right-4 md:right-8 p-3 rounded-2xl bg-white/10 hover:bg-white/20 text-white z-10">
          <ChevronRight className="w-8 h-8" />
        </button>
      )}
    </div>
  )
}

/* ────────── History Sidebar ────────── */
const HistorySidebar = memo(function HistorySidebar({ images, onClear, onLightbox, onRemove }: {
  images: GeneratedImage[]
  onClear: () => void
  onLightbox: (flat: GeneratedImage[], idx: number) => void
  onRemove: (id: string) => void
}) {
  const groups = useMemo(() => groupByDate(images), [images])
  const months = useMemo(() => Array.from(new Set(groups.map(g => g.monthKey))), [groups])
  const dateRefs = useRef<Map<string, HTMLDivElement>>(new Map())
  const flatImages = useMemo(() => groups.flatMap(g => g.images), [groups])
  const indexMap = new Map(flatImages.map((img, i) => [img.id, i]))

  const scrollToMonth = (monthKey: string) => {
    const firstGroup = groups.find(g => g.monthKey === monthKey)
    if (firstGroup) dateRefs.current.get(firstGroup.dateKey)?.scrollIntoView({ behavior: "smooth", block: "start" })
  }

  if (images.length === 0) return (
    <div className="flex flex-col items-center justify-center h-full text-center gap-3 p-8">
      <ImageIcon className="w-12 h-12 text-muted-foreground/20" />
      <p className="text-xs font-black text-muted-foreground/30">暂无历史记录</p>
    </div>
  )

  return (
    <div className="flex flex-col h-full">
      <div className="flex gap-2 px-4 pt-4 pb-3 overflow-x-auto border-b border-border/30 shrink-0">
        {months.map(m => (
          <button key={m} onClick={() => scrollToMonth(m)}
            className="shrink-0 px-3 py-1 rounded-lg bg-muted/40 hover:bg-indigo-500/20 hover:text-indigo-500 text-[10px] font-black text-muted-foreground border border-border/40 transition-all">
            {formatMonth(m)} · {groups.filter(g => g.monthKey === m).reduce((n, g) => n + g.images.length, 0)}
          </button>
        ))}
      </div>
      <div className="flex-1 overflow-y-auto p-4 space-y-6">
        {groups.map(group => (
          <div key={group.dateKey} ref={el => { if (el) dateRefs.current.set(group.dateKey, el) }}>
            <div className="flex items-center gap-2 mb-3">
              <span className="text-[10px] font-black text-muted-foreground">{group.label}</span>
              <div className="flex-1 h-px bg-border/40" />
              <span className="text-[9px] text-muted-foreground/40 font-mono">{group.images.length}张</span>
            </div>
            <div className="grid grid-cols-2 gap-2">
              {group.images.map(img => (
                <div key={img.id}
                  className="group relative rounded-xl overflow-hidden bg-muted/30 border border-border/40 cursor-pointer aspect-video"
                  onClick={() => onLightbox(flatImages, indexMap.get(img.id) ?? 0)}>
                  <img src={img.url} alt={img.prompt} loading="lazy" className="w-full h-full object-cover transition-transform duration-300 group-hover:scale-105" />
                  <div className="absolute inset-0 bg-gradient-to-t from-black/80 to-transparent opacity-0 group-hover:opacity-100 transition-all duration-200 p-2 flex flex-col justify-end">
                    <p className="text-white text-[9px] leading-tight line-clamp-2 font-medium">{img.prompt}</p>
                    <div className="flex items-center justify-between mt-1.5">
                      <span className="text-white/40 text-[8px] font-mono">
                        {new Date(img.timestamp).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}
                      </span>
                      <div className="flex gap-1">
                        <a href={img.url} download onClick={e => e.stopPropagation()}
                          className="p-1 rounded bg-white/10 hover:bg-white text-white hover:text-black transition-all">
                          <Download className="w-2.5 h-2.5" />
                        </a>
                        <button onClick={e => { e.stopPropagation(); onRemove(img.id) }}
                          className="p-1 rounded bg-white/10 hover:bg-rose-500 text-white transition-all">
                          <Trash2 className="w-2.5 h-2.5" />
                        </button>
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
      <div className="px-4 py-3 border-t border-border/30 shrink-0">
        <button onClick={onClear}
          className="w-full py-2 rounded-xl text-[10px] font-black text-rose-500/70 hover:text-rose-500 hover:bg-rose-500/10 transition-all border border-transparent hover:border-rose-500/20 flex items-center justify-center gap-1.5">
          <Trash2 className="w-3 h-3" /> 清除全部历史
        </button>
      </div>
    </div>
  )
})

/* ═══════════════════════════════════════════════════════════════
   MAIN PAGE — Zero-Jitter Push Layout
   
   The jitter problem: CSS Grid "auto-fill" recalculates column 
   count when container width crosses a breakpoint (e.g. 800px → 
   drops from 4 to 3 columns). During the sidebar width transition,
   this causes a discrete layout jump = "jitter".
   
   Solution: Calculate column count based on the NARROWEST possible 
   state (sidebar OPEN), then use `repeat(N, 1fr)` — a FIXED count.
   When the sidebar toggles, columns smoothly widen/narrow but the
   count NEVER changes → zero jitter.
   ═══════════════════════════════════════════════════════════════ */

export default function ImagePage() {
  const [prompt, setPrompt] = useState("")
  const [generating, setGenerating] = useState(false)
  const [batchSize, setBatchSize] = useState(1)

  // session gallery: in-memory only, clears on page refresh
  const [sessionImages, setSessionImages] = useState<GeneratedImage[]>([])
  // history: persisted in localStorage
  const [history, setHistory] = useState<GeneratedImage[]>(() => loadHistory())

  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [lightbox, setLightbox] = useState<{ images: GeneratedImage[]; index: number } | null>(null)
  const lightboxOpenRef = useRef(false)

  const [galleryOpen, setGalleryOpen] = useState(false)
  const [tempMaxItems, setTempMaxItems] = useState<number>(
    parseInt(localStorage.getItem("gallery_max_items") || "100", 10)
  )
  const maxItems = parseInt(localStorage.getItem("gallery_max_items") || "100", 10)
  const gearRef = useRef<HTMLDivElement>(null)

  // Click-outside to close gallery popover
  useEffect(() => {
    if (!galleryOpen) return
    const handler = (e: MouseEvent) => {
      if (gearRef.current && !gearRef.current.contains(e.target as Node)) {
        setGalleryOpen(false)
      }
    }
    document.addEventListener("mousedown", handler)
    return () => document.removeEventListener("mousedown", handler)
  }, [galleryOpen])

  // ── Fixed column count for zero-jitter push layout ──────────
  const SIDEBAR_W = 380
  const ADMIN_SIDEBAR_W = 288  // w-72 from AdminLayout
  const GRID_GAP = 16
  const GRID_PAD = 48          // px-6 * 2 = 24 * 2
  const MIN_COL_W = 180

  const [cols, setCols] = useState(3)

  useEffect(() => {
    const calc = () => {
      // Calculate based on NARROWEST state (sidebar OPEN) so count never changes on toggle
      const narrowW = window.innerWidth - ADMIN_SIDEBAR_W - SIDEBAR_W - GRID_PAD
      const c = Math.max(2, Math.floor((narrowW + GRID_GAP) / (MIN_COL_W + GRID_GAP)))
      setCols(c)
    }
    calc()
    window.addEventListener("resize", calc)
    return () => window.removeEventListener("resize", calc)
  }, [])

  useEffect(() => { saveHistory(history, maxItems) }, [history, maxItems])
  useEffect(() => { lightboxOpenRef.current = lightbox !== null }, [lightbox])

  // ESC closes sidebar (only when lightbox is closed)
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !lightboxOpenRef.current) setSidebarOpen(false)
    }
    window.addEventListener("keydown", h)
    return () => window.removeEventListener("keydown", h)
  }, [])

  const closeLightbox = useCallback(() => setLightbox(null), [])
  const navLightbox = useCallback((idx: number) => setLightbox(prev => prev ? { ...prev, index: idx } : null), [])

  const handleRemoveHistory = useCallback((id: string) => {
    setHistory(prev => prev.filter(img => img.id !== id))
    setSessionImages(prev => prev.filter(img => img.id !== id))
  }, [])

  const generateRef = useRef<() => void>(() => { })

  const handleGenerate = useCallback(async () => {
    if (!prompt.trim()) { toast.error("请输入创作提示词"); return }
    setGenerating(true)
    const toastId = toast.loading(`正在构思 ${batchSize} 幅艺术作品...`)
    try {
      const response = await fetch(`${API_BASE}/v1/images/generations`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${localStorage.getItem('qwen2api_key') || ''}`
        },
        body: JSON.stringify({ prompt, n: batchSize })
      })
      if (!response.ok) { const err = await response.json(); throw new Error(err.detail || "生成失败") }
      const result = await response.json()
      const newImages: GeneratedImage[] = result.data.map((item: { url: string }) => ({
        id: Math.random().toString(36).substr(2, 9),
        url: item.url, prompt, timestamp: Date.now()
      }))
      setSessionImages(prev => [...newImages, ...prev])
      setHistory(prev => [...newImages, ...prev].slice(0, maxItems))
      setPrompt("")
      toast.success(`已生成 ${newImages.length} 幅作品`, { id: toastId })
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "生成失败，请重试", { id: toastId })
    } finally {
      setGenerating(false)
    }
  }, [prompt, batchSize, maxItems])

  useEffect(() => { generateRef.current = handleGenerate }, [handleGenerate])

  return (
    <div className="flex h-[calc(100vh-80px)] overflow-hidden">

      {/* ── Main creation area ── */}
      <div className="flex flex-col flex-1 min-w-0" style={{ transition: "flex 0.3s cubic-bezier(0.4,0,0.2,1)" }}>

        {/* Header */}
        <div className="flex items-center justify-between px-6 pt-4 pb-3 shrink-0">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-indigo-500/10 flex items-center justify-center border border-indigo-500/20">
              <Sparkles className="w-5 h-5 text-indigo-500" />
            </div>
            <h1 className="text-3xl font-black tracking-tighter text-foreground">艺术画廊</h1>
          </div>
          {/* Right controls */}
          <div className="flex items-center gap-2">
            {/* History toggle */}
            <button
              onClick={() => setSidebarOpen(v => !v)}
              className={`flex items-center gap-2 px-3 py-1.5 rounded-xl border transition-all ${sidebarOpen
                ? "bg-indigo-500/20 border-indigo-500/40 text-indigo-500"
                : "bg-muted/30 border-border/40 text-muted-foreground hover:text-foreground hover:bg-muted/50"
                }`}
            >
              <History className="w-3.5 h-3.5" />
              <span className="text-[10px] font-black">历史记录</span>
              {history.length > 0 && (
                <span className="px-1.5 py-0.5 rounded-md bg-indigo-500/20 text-indigo-500 text-[9px] font-black">
                  {history.length}
                </span>
              )}
            </button>

            {/* Gear icon + popover */}
            <div ref={gearRef} className="relative">
              <button
                onClick={() => setGalleryOpen(v => !v)}
                className={`p-1.5 rounded-xl border transition-all ${galleryOpen
                  ? "bg-indigo-500/20 border-indigo-500/40 text-indigo-500"
                  : "bg-muted/30 border-border/40 text-muted-foreground hover:text-foreground hover:bg-muted/50"
                  }`}
              >
                <Settings className="w-3.5 h-3.5" />
              </button>

              {/* Popover */}
              {galleryOpen && (
                <div className="absolute right-0 top-10 z-50 w-64 p-5 rounded-2xl bg-background border border-border/60 shadow-2xl space-y-4">
                  <p className="text-[11px] font-black text-foreground">图库设置</p>
                  <div className="space-y-2">
                    <div className="flex items-center justify-between">
                      <span className="text-[10px] text-muted-foreground font-black">最多保留图片</span>
                      <span className="text-sm font-black text-indigo-500 tabular-nums">{tempMaxItems} 张</span>
                    </div>
                    <input type="range" min={10} max={500} step={10} value={tempMaxItems}
                      onChange={e => setTempMaxItems(parseInt(e.target.value))}
                      className="w-full h-1.5 bg-muted/40 rounded-full appearance-none cursor-pointer accent-indigo-500" />
                    <div className="flex justify-between text-[9px] text-muted-foreground/50 font-black">
                      <span>10</span><span>200</span><span>500</span>
                    </div>
                  </div>
                  <button
                    onClick={() => {
                      const v = Math.max(10, Math.min(500, tempMaxItems))
                      localStorage.setItem("gallery_max_items", String(v))
                      setTempMaxItems(v)
                      setGalleryOpen(false)
                      toast.success(`图库上限已设为 ${v} 张`)
                    }}
                    className="w-full h-9 bg-indigo-500 text-white font-semibold rounded-xl text-sm hover:opacity-90 transition-all">
                    保存
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Session gallery — FIXED column count, smooth resize, zero jitter */}
        <div className="flex-1 overflow-y-auto px-6 pb-2">
          {sessionImages.length > 0 ? (
            <div style={{
              display: "grid",
              gridTemplateColumns: `repeat(${cols}, 1fr)`,
              gap: `${GRID_GAP}px`,
              alignItems: "start",
            }}>
              {sessionImages.map((img, idx) => (
                <div
                  key={img.id}
                  className="group relative rounded-[1.5rem] overflow-hidden bg-card border border-border/40 shadow-lg hover:shadow-2xl cursor-pointer"
                  onClick={() => setLightbox({ images: sessionImages, index: idx })}
                >
                  <img src={img.url} alt={img.prompt} className="w-full h-auto object-cover transition-transform duration-700 group-hover:scale-105" />
                  <div className="absolute inset-0 bg-gradient-to-t from-black/90 via-black/10 to-transparent opacity-0 group-hover:opacity-100 transition-all p-5 flex flex-col justify-end">
                    <div className="max-h-20 overflow-y-auto mb-3">
                      <p className="text-white text-xs leading-relaxed font-medium">{img.prompt}</p>
                    </div>
                    <div className="flex items-center justify-end border-t border-white/10 pt-3">
                      <a href={img.url} download onClick={e => e.stopPropagation()}
                        className="p-1.5 rounded-lg bg-white/10 hover:bg-white text-white hover:text-black transition-all">
                        <Download className="w-3.5 h-3.5" />
                      </a>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="flex items-center justify-center h-full min-h-[200px]">
              <div className="text-center space-y-3">
                <ImageIcon className="w-16 h-16 mx-auto text-muted-foreground/10" />
                <p className="text-sm font-black text-muted-foreground/30">在下方输入提示词，开始创作</p>
                <p className="text-[10px] text-muted-foreground/20">历史记录已自动保存，点击右上角查看</p>
              </div>
            </div>
          )}
        </div>

        {/* Input bar */}
        <div className="px-6 pt-2 pb-4 shrink-0">
          <div className="glass-card p-4 rounded-[1.5rem] border border-indigo-500/15">
            <div className="space-y-2.5">
              <textarea
                value={prompt}
                onChange={e => setPrompt(e.target.value)}
                onKeyDown={e => {
                  if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
                    e.preventDefault()
                    e.stopPropagation()
                    generateRef.current()
                  }
                }}
                placeholder="描述你想要生成的图片... (Ctrl+Enter 快速生成)"
                className="w-full h-14 bg-transparent border-none outline-none text-foreground placeholder:text-muted-foreground/30 resize-none text-sm leading-relaxed"
              />
              <div className="flex items-center gap-2 border-t border-border/30 pt-2.5">
                <span className="text-[9px] font-black text-muted-foreground/40">数量</span>
                {[1, 2, 4].map(s => (
                  <button key={s} onClick={() => setBatchSize(s)}
                    className={`w-7 h-7 rounded-lg text-[11px] font-black transition-all border ${batchSize === s
                      ? "bg-indigo-500 text-white border-indigo-400"
                      : "bg-muted/30 text-muted-foreground border-border/40 hover:bg-muted/50"
                      }`}>
                    {s}
                  </button>
                ))}
                <div className="flex-1" />
                <button onClick={() => generateRef.current()} disabled={generating}
                  className="h-7 px-4 rounded-lg bg-foreground text-background font-black text-[11px] hover:scale-[1.02] active:scale-[0.98] transition-all disabled:opacity-50 flex items-center gap-1.5">
                  {generating ? <RefreshCw className="w-3 h-3 animate-spin" /> : <Sparkles className="w-3 h-3" />}
                  {generating ? "创作中..." : "立即生成"}
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* ── History Sidebar — push layout, zero jitter ── */}
      <div
        className="shrink-0 overflow-hidden border-l border-border/40 bg-background"
        style={{
          width: sidebarOpen ? SIDEBAR_W : 0,
          transition: "width 0.3s cubic-bezier(0.4, 0, 0.2, 1)",
        }}
      >
        <div style={{ width: SIDEBAR_W }} className="h-full flex flex-col">
          <div className="flex items-center justify-between px-4 pt-4 pb-3 border-b border-border/30 shrink-0">
            <div className="flex items-center gap-2">
              <Clock className="w-3.5 h-3.5 text-muted-foreground" />
              <span className="text-sm font-semibold text-foreground">历史记录</span>
              <span className="text-[9px] text-muted-foreground/50 font-mono">{history.length}张</span>
            </div>
            <button onClick={() => setSidebarOpen(false)}
              className="p-1.5 rounded-lg bg-muted/30 hover:bg-muted/60 text-muted-foreground transition-all">
              <X className="w-4 h-4" />
            </button>
          </div>
          <HistorySidebar
            images={history}
            onClear={() => { setHistory([]); localStorage.removeItem(STORAGE_KEY) }}
            onLightbox={(flatImgs, idx) => setLightbox({ images: flatImgs, index: idx })}
            onRemove={handleRemoveHistory}
          />
        </div>
      </div>

      {/* Lightbox */}
      {lightbox !== null && (
        <Lightbox
          images={lightbox.images}
          currentIndex={lightbox.index}
          onClose={closeLightbox}
          onNav={navLightbox}
        />
      )}
    </div>
  )
}
