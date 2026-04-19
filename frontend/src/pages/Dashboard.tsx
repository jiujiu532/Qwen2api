import { useEffect, useState, useCallback, useRef } from "react"
import ReactDOM from "react-dom"
import {
  BarChart2, Zap,
  Activity, TrendingUp, RefreshCw, Shield,
  ChevronLeft, ChevronRight, Calendar, Clock,
  CheckCircle2, AlertTriangle, XCircle, Server
} from "lucide-react"
import { getAuthHeader } from "../lib/auth"
import { API_BASE } from "../lib/api"
import { toast } from "sonner"

// ─────────────────────────────────────────────────────
// SPARKLINE
// ─────────────────────────────────────────────────────
function Sparkline({ data, color = "#6366f1", height = 52 }: { data: number[]; color?: string; height?: number }) {
  if (!data || data.length < 2 || data.every(v => v === 0)) {
    return (
      <svg viewBox={`0 0 100 ${height}`} preserveAspectRatio="none" style={{ width: "100%", height, opacity: 0.15 }}>
        <line x1="0" y1={height} x2="100" y2={height} stroke={color} strokeWidth="1.5" strokeDasharray="4 3" />
      </svg>
    )
  }
  const max = Math.max(...data, 1)
  const pts = data.map((v, i) => `${(i / (data.length - 1)) * 100},${height - (v / max) * height * 0.85}`).join(" ")
  return (
    <svg viewBox={`0 0 100 ${height}`} preserveAspectRatio="none" style={{ width: "100%", height }}>
      <polyline points={pts} fill="none" stroke={color} strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
      <polygon points={`0,${height} ${pts} 100,${height}`} fill={`${color}22`} />
    </svg>
  )
}

// ─────────────────────────────────────────────────────
// CHECK-CX STYLE STATUS TIMELINE (60 segments)
// ─────────────────────────────────────────────────────
function StatusTimeline({
  segments, nextRefreshAt, historyItems
}: {
  segments: string[];
  nextRefreshAt?: number;
  historyItems?: { ts: number; valid_pct: number; seg: string; valid?: number; total?: number }[]
}) {
  const COLOR: Record<string, string> = { green: "#10b981", amber: "#f59e0b", red: "#f43f5e", empty: "rgba(180,180,200,0.15)" }
  const [msLeft, setMsLeft] = useState(() => nextRefreshAt ? Math.max(0, nextRefreshAt - Date.now()) : 0)
  const [tip, setTip] = useState<{ x: number; y: number; item: { ts: number; valid_pct: number; seg: string; valid?: number; total?: number } } | null>(null)

  // 实时倒计时，每秒更新
  useEffect(() => {
    if (!nextRefreshAt) return
    setMsLeft(Math.max(0, nextRefreshAt - Date.now()))
    const t = setInterval(() => setMsLeft(Math.max(0, nextRefreshAt - Date.now())), 1000)
    return () => clearInterval(t)
  }, [nextRefreshAt])

  const remaining = Math.ceil(msLeft / 1000)
  const label = remaining > 0
    ? (remaining >= 60 ? `${Math.floor(remaining / 60)}M ${remaining % 60}S` : `${remaining}S`)
    : null

  const fmtTs = (ts: number) => {
    const d = new Date(ts * 1000)
    const p = (n: number) => String(n).padStart(2, "0")
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
  }
  const segLabel = (s: string) => s === "green" ? "正常" : s === "amber" ? "降级" : "故障"

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6, alignItems: "center" }}>
        <span style={{ fontSize: 9, fontWeight: 700, letterSpacing: "0.12em", textTransform: "uppercase", opacity: 0.4 }}>HISTORY ({segments.length}PTS)</span>
        {label && (
          <span style={{ fontSize: 9, fontWeight: 700, color: "#6366f1", display: "flex", alignItems: "center", gap: 4 }}>
            <Clock style={{ width: 9, height: 9 }} /> NEXT UPDATE IN {label}
          </span>
        )}
      </div>
      <div style={{ position: "relative", height: 32, borderRadius: 4, overflow: "visible", background: "rgba(180,180,200,0.08)", padding: 2 }}>
        <div style={{ display: "flex", flexDirection: "row-reverse", height: "100%", gap: 2, padding: "0 1px" }}>
          {segments.map((c, i) => {
            const item = historyItems && i < historyItems.length ? historyItems[i] : null
            return (
              <div
                key={i}
                style={{
                  flex: 1,
                  height: c === "empty" ? "30%" : c === "green" ? "100%" : c === "amber" ? "65%" : "35%",
                  alignSelf: "flex-end",
                  borderRadius: 2,
                  background: COLOR[c] ?? COLOR.empty,
                  opacity: item && tip && tip.item === item ? 1 : 0.85,
                  cursor: item ? "crosshair" : "default",
                  transition: "opacity 0.12s",
                }}
                onMouseEnter={item ? (e) => {
                  const r = (e.currentTarget as HTMLElement).getBoundingClientRect()
                  setTip({ x: r.left + r.width / 2, y: r.top, item })
                } : undefined}
                onMouseLeave={item ? () => setTip(null) : undefined}
              />
            )
          })}
        </div>
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", marginTop: 4 }}>
        <span style={{ fontSize: 8, opacity: 0.3, letterSpacing: "0.1em" }}>PAST</span>
        <span style={{ fontSize: 8, opacity: 0.3, letterSpacing: "0.1em" }}>NOW</span>
      </div>

      {tip && ReactDOM.createPortal(
        <div style={{
          position: "fixed",
          left: tip.x,
          top: tip.y - 10,
          transform: "translate(-50%, -100%)",
          zIndex: 99999,
          padding: "10px 14px",
          borderRadius: 12,
          background: "hsl(var(--popover))",
          color: "hsl(var(--popover-foreground))",
          border: "1px solid rgba(140,140,180,0.2)",
          boxShadow: "0 8px 32px rgba(0,0,0,0.35)",
          minWidth: 190,
          pointerEvents: "none",
          fontSize: 11,
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 7, marginBottom: 8 }}>
            <div style={{ width: 8, height: 8, borderRadius: "50%", background: COLOR[tip.item.seg], flexShrink: 0 }} />
            <span style={{ fontWeight: 800, color: COLOR[tip.item.seg] }}>{segLabel(tip.item.seg)}</span>
            <span style={{ marginLeft: "auto", opacity: 0.45, fontSize: 9, fontFamily: "monospace" }}>{fmtTs(tip.item.ts)}</span>
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", padding: "6px 0", borderTop: "1px solid rgba(140,140,180,0.12)" }}>
            <span style={{ opacity: 0.55 }}>可用率</span>
            <span style={{ fontWeight: 700, fontFamily: "monospace" }}>{tip.item.valid_pct.toFixed(1)}&nbsp;%</span>
          </div>
          {tip.item.valid !== undefined && tip.item.total !== undefined && (
            <div style={{ display: "flex", justifyContent: "space-between", padding: "6px 0", borderTop: "1px solid rgba(140,140,180,0.12)" }}>
              <span style={{ opacity: 0.55 }}>节点在线</span>
              <span style={{ fontWeight: 700, fontFamily: "monospace" }}>{tip.item.valid}&nbsp;/&nbsp;{tip.item.total}</span>
            </div>
          )}
        </div>,
        document.body
      )}
    </div>
  )
}

// ─────────────────────────────────────────────────────
// DONUT PIE CHART
// ─────────────────────────────────────────────────────
function DonutChart({ slices, size = 100, thickness = 20 }: { slices: { value: number; color: string; label: string }[]; size?: number; thickness?: number }) {
  const r = (size - thickness) / 2
  const cx = size / 2, cy = size / 2
  const circumference = 2 * Math.PI * r
  const total = slices.reduce((s, v) => s + v.value, 0) || 1
  let offset = 0
  const paths = slices.map(s => {
    const pct = s.value / total
    const el = <circle key={s.label} cx={cx} cy={cy} r={r} fill="none" stroke={s.color} strokeWidth={thickness} strokeDasharray={`${pct * circumference} ${(1 - pct) * circumference}`} strokeDashoffset={-offset * circumference} style={{ transition: "stroke-dasharray 0.5s" }} />
    offset += pct
    return el
  })
  return (
    <svg width={size} height={size} style={{ transform: "rotate(-90deg)" }}>
      <circle cx={cx} cy={cy} r={r} fill="none" stroke="rgba(180,180,200,0.12)" strokeWidth={thickness} />
      {paths}
    </svg>
  )
}

// ─────────────────────────────────────────────────────
// DATE TIME PICKER
// ─────────────────────────────────────────────────────
const MONTHS_LABEL = ["01", "02", "03", "04", "05", "06", "07", "08", "09", "10", "11", "12"]
const WEEK_DAYS = ["一", "二", "三", "四", "五", "六", "日"]

function DateTimePicker({ value, onChange, onClear, placeholder }: { value: Date | null; onChange: (d: Date) => void; onClear?: () => void; placeholder: string }) {
  const [open, setOpen] = useState(false)
  const [viewYear, setViewYear] = useState(() => value?.getFullYear() ?? new Date().getFullYear())
  const [viewMonth, setViewMonth] = useState(() => value?.getMonth() ?? new Date().getMonth())
  const [selDate, setSelDate] = useState<Date | null>(value)
  const [hour, setHour] = useState(value?.getHours() ?? 0)
  const [minute, setMinute] = useState(value?.getMinutes() ?? 0)
  const ref = useRef<HTMLDivElement>(null)
  const popupRef = useRef<HTMLDivElement>(null)
  const hourRef = useRef<HTMLDivElement>(null)
  const minRef = useRef<HTMLDivElement>(null)
  const btnRef = useRef<HTMLButtonElement>(null)
  const [popupPos, setPopupPos] = useState({ top: 0, right: 0 })

  useEffect(() => {
    const handler = (e: MouseEvent) => { const t = e.target as Node; if (!ref.current?.contains(t) && !popupRef.current?.contains(t)) setOpen(false) }
    document.addEventListener("mousedown", handler); return () => document.removeEventListener("mousedown", handler)
  }, [])

  const handleOpen = () => {
    if (btnRef.current) { const r = btnRef.current.getBoundingClientRect(); setPopupPos({ top: r.bottom + 6, right: window.innerWidth - r.right }) }
    setOpen(v => !v)
  }
  useEffect(() => { if (open) { setTimeout(() => { hourRef.current?.children[hour]?.scrollIntoView({ block: "center", behavior: "instant" }); minRef.current?.children[minute]?.scrollIntoView({ block: "center", behavior: "instant" }) }, 30) } }, [open, hour, minute])

  const daysInMonth = (y: number, m: number) => new Date(y, m + 1, 0).getDate()
  const firstDayOfMonth = (y: number, m: number) => { const d = new Date(y, m, 1).getDay(); return d === 0 ? 6 : d - 1 }
  const confirmDate = (d: Date | null, h: number, mi: number) => { if (!d) return; const out = new Date(d); out.setHours(h, mi, 0, 0); onChange(out) }
  const fmt = (d: Date | null) => !d ? placeholder : `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}  ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`

  const cells: (number | null)[] = []
  const fd = firstDayOfMonth(viewYear, viewMonth), dim = daysInMonth(viewYear, viewMonth)
  for (let i = 0; i < fd; i++) cells.push(null)
  for (let i = 1; i <= dim; i++) cells.push(i)
  while (cells.length % 7 !== 0) cells.push(null)

  return (
    <div ref={ref} style={{ position: "relative" }}>
      <button ref={btnRef} onClick={handleOpen}
        style={{ display: "flex", alignItems: "center", gap: 7, padding: "5px 11px", borderRadius: 10, border: `1px solid ${open ? "rgba(99,102,241,0.5)" : "rgba(180,180,200,0.3)"}`, background: open ? "rgba(99,102,241,0.08)" : "rgba(120,120,140,0.06)", color: open ? "#6366f1" : undefined, fontSize: 11, fontFamily: "monospace", minWidth: 180, cursor: "pointer" }}>
        <Calendar style={{ width: 12, height: 12, flexShrink: 0, opacity: 0.5 }} />
        <span style={{ color: value ? undefined : "rgba(120,120,140,0.4)", fontSize: 10 }}>{fmt(value)}</span>
      </button>
      {open && ReactDOM.createPortal(
        <div ref={popupRef} style={{ position: "fixed", top: popupPos.top, right: popupPos.right, zIndex: 99999, display: "flex", borderRadius: 16, border: "1px solid rgba(100,100,130,0.18)", boxShadow: "0 20px 60px rgba(0,0,0,0.22)", background: "#ffffff", backdropFilter: "none", isolation: "isolate", overflow: "hidden" }}>
          <div style={{ padding: 16, minWidth: 234 }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
              <button onClick={() => { viewMonth === 0 ? (setViewMonth(11), setViewYear(y => y - 1)) : setViewMonth(m => m - 1) }} style={{ padding: 4, border: "none", background: "transparent", cursor: "pointer", display: "flex", borderRadius: 8 }}><ChevronLeft style={{ width: 16, height: 16 }} /></button>
              <span style={{ fontSize: 14, fontWeight: 900 }}>{viewYear}年{MONTHS_LABEL[viewMonth]}月</span>
              <button onClick={() => { viewMonth === 11 ? (setViewMonth(0), setViewYear(y => y + 1)) : setViewMonth(m => m + 1) }} style={{ padding: 4, border: "none", background: "transparent", cursor: "pointer", display: "flex", borderRadius: 8 }}><ChevronRight style={{ width: 16, height: 16 }} /></button>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(7,1fr)", marginBottom: 4 }}>
              {WEEK_DAYS.map(d => <div key={d} style={{ textAlign: "center", fontSize: 9, fontWeight: 900, opacity: 0.4, padding: "4px 0" }}>{d}</div>)}
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(7,1fr)", gap: "2px 0" }}>
              {cells.map((day, i) => {
                const isSel = selDate && selDate.getDate() === day && selDate.getMonth() === viewMonth && selDate.getFullYear() === viewYear
                const isToday = day !== null && new Date().getDate() === day && new Date().getMonth() === viewMonth && new Date().getFullYear() === viewYear
                return <button key={i} disabled={!day} onClick={() => { if (!day) return; const nd = new Date(viewYear, viewMonth, day); setSelDate(nd); confirmDate(nd, hour, minute) }}
                  style={{ width: 28, height: 28, margin: "0 auto", borderRadius: 10, border: isSel ? "none" : isToday ? "1px solid rgba(99,102,241,0.4)" : "none", background: isSel ? "#6366f1" : "transparent", color: isSel ? "#fff" : isToday ? "#6366f1" : undefined, fontSize: 12, fontWeight: 700, cursor: day ? "pointer" : "default", visibility: day ? "visible" : "hidden", display: "flex", alignItems: "center", justifyContent: "center" }}>{day}</button>
              })}
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", marginTop: 12, paddingTop: 12, borderTop: "1px solid rgba(180,180,200,0.2)" }}>
              <button onClick={() => { setSelDate(null); setOpen(false); onClear?.() }} style={{ fontSize: 11, fontWeight: 800, color: "#6366f1", background: "none", border: "none", cursor: "pointer" }}>清除</button>
              <button onClick={() => { const t = new Date(); setSelDate(t); setViewYear(t.getFullYear()); setViewMonth(t.getMonth()); confirmDate(t, hour, minute) }} style={{ fontSize: 11, fontWeight: 800, color: "#6366f1", background: "none", border: "none", cursor: "pointer" }}>今天</button>
            </div>
          </div>
          <div style={{ width: 1, background: "rgba(180,180,200,0.2)", margin: "12px 0" }} />
          <div style={{ display: "flex" }}>
            <div ref={hourRef} style={{ overflowY: "auto", padding: "8px 4px", height: 240, width: 48, scrollbarWidth: "none" }}>
              {Array.from({ length: 24 }, (_, i) => <button key={i} onClick={() => { setHour(i); confirmDate(selDate, i, minute) }} style={{ width: "100%", padding: "4px 0", borderRadius: 8, border: "none", background: hour === i ? "#6366f1" : "transparent", color: hour === i ? "#fff" : undefined, fontSize: 12, fontWeight: 700, cursor: "pointer", textAlign: "center" }}>{String(i).padStart(2, "0")}</button>)}
            </div>
            <div ref={minRef} style={{ overflowY: "auto", padding: "8px 4px", height: 240, width: 48, scrollbarWidth: "none" }}>
              {Array.from({ length: 60 }, (_, i) => <button key={i} onClick={() => { setMinute(i); confirmDate(selDate, hour, i) }} style={{ width: "100%", padding: "4px 0", borderRadius: 8, border: "none", background: minute === i ? "#6366f1" : "transparent", color: minute === i ? "#fff" : undefined, fontSize: 12, fontWeight: 700, cursor: "pointer", textAlign: "center" }}>{String(i).padStart(2, "0")}</button>)}
            </div>
          </div>
        </div>,
        document.body
      )}
    </div>
  )
}

// ─────────────────────────────────────────────────────
// HELPERS
// ─────────────────────────────────────────────────────
const PRESETS = [{ label: "1H", hours: 1 }, { label: "24H", hours: 24 }, { label: "7D", hours: 168 }, { label: "30D", hours: 720 }]
function formatNum(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(2) + "M"
  if (n >= 1_000) return (n / 1_000).toFixed(1) + "K"
  return String(n)
}

// ─────────────────────────────────────────────────────
// GATEWAY HEALTH (left column of monitoring panel)
// ─────────────────────────────────────────────────────
function GatewayHealth({ accounts, healthHistory, nextRefreshAt }: { accounts: any[]; healthHistory: { ts: number; valid_pct: number; seg: string; valid?: number; total?: number }[]; nextRefreshAt: number }) {
  const total = accounts.length
  const valid = accounts.filter(a => a.status === "VALID").length
  const softErr = accounts.filter(a => a.status === "SOFT_ERROR" || a.status === "RATE_LIMITED" || a.status === "HALF_OPEN" || a.status === "PENDING_REFRESH").length
  const down = accounts.filter(a => a.status === "BANNED" || a.status === "CIRCUIT_OPEN").length
  const healthPct = total ? ((valid + softErr * 0.5) / total * 100) : 0
  const avgScore = healthPct
  const totalRpm = accounts.reduce((s, a) => s + (a.rpm_1min ?? 0), 0)
  const availPct = total ? (valid / total * 100).toFixed(1) : "—"
  const overallStatus = valid === total && total > 0 ? "operational" : valid > total * 0.5 ? "degraded" : "critical"
  const statusCfg = {
    operational: { label: "运行正常", color: "#10b981", icon: CheckCircle2, bg: "rgba(16,185,129,0.08)" },
    degraded: { label: "部分降级", color: "#f59e0b", icon: AlertTriangle, bg: "rgba(245,158,11,0.08)" },
    critical: { label: "严重故障", color: "#f43f5e", icon: XCircle, bg: "rgba(244,63,94,0.08)" },
  }[overallStatus]
  const StatusIcon = statusCfg.icon

  // 快照最新在前（index=0 对应最新，row-reverse 放右侧 = NOW）
  const histNewest = [...healthHistory].reverse()
  const segments: string[] = (() => {
    if (healthHistory.length === 0 && total === 0) return Array(60).fill("empty")
    const real = histNewest.map(p => p.seg)
    return [...real, ...Array(Math.max(0, 60 - real.length)).fill("empty")]
  })()

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {/* Overall banner */}
      <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "12px 16px", borderRadius: 14, background: statusCfg.bg, border: `1px solid ${statusCfg.color}25` }}>
        <StatusIcon style={{ width: 18, height: 18, color: statusCfg.color, flexShrink: 0 }} />
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 14, fontWeight: 900, color: statusCfg.color }}>{statusCfg.label}</div>
          <div style={{ fontSize: 10, opacity: 0.55, marginTop: 1 }}>qwen3.6-plus · Web Gateway</div>
        </div>
        <div style={{ textAlign: "right" }}>
          <div style={{ fontSize: 22, fontWeight: 900, color: statusCfg.color, lineHeight: 1 }}>{availPct}<span style={{ fontSize: 12 }}>%</span></div>
          <div style={{ fontSize: 9, opacity: 0.55, marginTop: 1 }}>可用率</div>
        </div>
      </div>

      {/* 4 metric boxes */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 10 }}>
        {[
          { v: `${valid}/${total}`, l: "在线节点", c: "#10b981" },
          { v: String(softErr), l: "软错误", c: "#f59e0b" },
          { v: String(down), l: "熔断/封禁", c: "#f43f5e" },
          { v: totalRpm.toFixed(1), l: "总 RPM", c: "#6366f1" },
        ].map(m => (
          <div key={m.l} style={{ textAlign: "center", padding: "10px 6px", borderRadius: 12, background: `${m.c}0a`, border: `1px solid ${m.c}20` }}>
            <div style={{ fontSize: 18, fontWeight: 900, color: m.c, lineHeight: 1 }}>{m.v}</div>
            <div style={{ fontSize: 9, fontWeight: 500, opacity: 0.5, marginTop: 4 }}>{m.l}</div>
          </div>
        ))}
      </div>

      {/* Node distribution */}
      <div>
        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
          <span style={{ fontSize: 11, fontWeight: 700, opacity: 0.5 }}>节点分布</span>
          <span style={{ fontSize: 11, fontWeight: 700, opacity: 0.4 }}>{total} 个节点</span>
        </div>
        {total > 0 && (
          <div style={{ height: 6, borderRadius: 6, overflow: "hidden", display: "flex", gap: 1 }}>
            <div style={{ flex: Math.max(valid, 0.01), background: "#10b981", transition: "flex 0.5s" }} />
            <div style={{ flex: Math.max(softErr, 0.01), background: "#f59e0b", transition: "flex 0.5s" }} />
            <div style={{ flex: Math.max(down, 0.01), background: "#f43f5e", transition: "flex 0.5s" }} />
          </div>
        )}
        <div style={{ display: "flex", gap: 14, marginTop: 6 }}>
          {[["#10b981", "正常", valid], ["#f59e0b", "降级", softErr], ["#f43f5e", "故障", down]].map(([c, l, v]) => (
            <div key={l as string} style={{ display: "flex", alignItems: "center", gap: 4 }}>
              <div style={{ width: 7, height: 7, borderRadius: "50%", background: c as string }} />
              <span style={{ fontSize: 10, fontWeight: 700, opacity: 0.55 }}>{l} {v}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Avg Health Score */}
      <div>
        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
          <span style={{ fontSize: 11, fontWeight: 700, opacity: 0.5 }}>平均健康分</span>
          <span style={{ fontSize: 13, fontWeight: 900, color: avgScore >= 80 ? "#10b981" : avgScore >= 50 ? "#f59e0b" : "#f43f5e" }}>{avgScore.toFixed(1)}<span style={{ fontSize: 10, opacity: 0.5 }}> / 100</span></span>
        </div>
        <div style={{ height: 5, borderRadius: 5, background: "rgba(180,180,200,0.15)", overflow: "hidden" }}>
          <div style={{ height: "100%", width: `${Math.min(avgScore, 100)}%`, background: avgScore >= 80 ? "#10b981" : avgScore >= 50 ? "#f59e0b" : "#f43f5e", borderRadius: 5, transition: "width 0.7s" }} />
        </div>
      </div>

      {/* Timeline */}
      <StatusTimeline segments={segments} nextRefreshAt={nextRefreshAt} historyItems={histNewest} />
    </div>
  )
}

// ─────────────────────────────────────────────────────
// DASHBOARD
// ─────────────────────────────────────────────────────
export default function Dashboard() {
  const [stats, setStats] = useState<any>(null)
  const [accounts, setAccounts] = useState<any[]>([])
  const [healthHistory, setHealthHistory] = useState<{ ts: number; valid_pct: number; seg: string; valid?: number; total?: number }[]>([])
  const [nextRefreshAt, setNextRefreshAt] = useState<number>(Date.now() + 30000)
  const [loading, setLoading] = useState(false)
  const [preset, setPreset] = useState(24)
  const [startDate, setStartDate] = useState<Date | null>(null)
  const [endDate, setEndDate] = useState<Date | null>(null)
  const [useCustom, setUseCustom] = useState(false)

  const fetchStats = useCallback(async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams()
      if (useCustom && startDate) params.set("start", String(Math.floor(startDate.getTime() / 1000)))
      else params.set("start", String(Math.floor(Date.now() / 1000 - preset * 3600)))
      if (useCustom && endDate) params.set("end", String(Math.floor(endDate.getTime() / 1000)))
      const [sRes, aRes] = await Promise.all([
        fetch(`${API_BASE}/api/admin/stats/usage?${params}`, { headers: getAuthHeader() }),
        fetch(`${API_BASE}/api/admin/pool-stats`, { headers: getAuthHeader() }),
      ])
      if (sRes.ok) setStats(await sRes.json())
      if (aRes.ok) { const d = await aRes.json(); setAccounts(d.accounts || []); setHealthHistory(d.health_history || []); setNextRefreshAt(Date.now() + 30000) }
    } catch (e: any) { toast.error(e.message) }
    finally { setLoading(false) }
  }, [preset, useCustom, startDate, endDate])

  useEffect(() => {
    fetchStats()
    if (!useCustom) { const t = setInterval(fetchStats, 30000); return () => clearInterval(t) }
  }, [fetchStats, useCustom])

  const tlReqs = (stats?.timeline || []).map((p: any) => p.requests)
  const tlToks = (stats?.timeline || []).map((p: any) => p.tokens)
  const chatReqs = stats?.by_feature?.chat?.requests ?? 0
  const t2iReqs = stats?.by_feature?.t2i?.requests ?? 0
  const totalReqs = stats?.total_requests ?? 0

  const CARD_ACCENT = ["#10b981", "#f59e0b", "#6366f1", "#f43f5e"]
  const cards = [
    { label: "请求次数", icon: BarChart2, key: 0, main: formatNum(totalReqs), s1l: "对话", s1v: formatNum(chatReqs), s2l: "生图", s2v: formatNum(t2iReqs), spark: tlReqs },
    { label: "消耗 Tokens", icon: Zap, key: 1, main: formatNum(stats?.total_tokens ?? 0), s1l: "输入", s1v: formatNum(stats?.total_prompt_tokens ?? 0), s2l: "输出", s2v: formatNum(stats?.total_completion_tokens ?? 0), spark: tlToks },
    { label: "性能指标", icon: TrendingUp, key: 2, main: `${(stats?.rpm ?? 0).toFixed(2)}`, s1l: "RPM", s1v: (stats?.rpm ?? 0).toFixed(2), s2l: "TPM", s2v: formatNum(stats?.tpm ?? 0), spark: tlReqs },
    { label: "风控分析", icon: Shield, key: 3, main: formatNum(totalReqs), s1l: "成功", s1v: formatNum(stats?.success_count ?? 0), s2l: "失败", s2v: formatNum(stats?.error_count ?? 0), spark: tlReqs },
  ]

  const pieSlices = [
    { value: chatReqs, color: "#6366f1", label: "对话" },
    { value: t2iReqs, color: "#a855f7", label: "文生图" },
  ]

  return (
    <div className="animate-fade-in-up" style={{ maxWidth: 1400, margin: "0 auto", display: "flex", flexDirection: "column", gap: 24 }}>

      {/* ── ROW 1: Header ─────────────────────────────── */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <div style={{ width: 42, height: 42, borderRadius: 14, background: "rgba(99,102,241,0.1)", border: "1px solid rgba(99,102,241,0.2)", display: "flex", alignItems: "center", justifyContent: "center" }}>
            <Activity style={{ width: 20, height: 20, color: "#6366f1" }} />
          </div>
          <div>
            <h2 style={{ fontSize: 27, fontWeight: 900, letterSpacing: "-0.03em", margin: 0 }}>使用统计</h2>
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <button onClick={fetchStats} disabled={loading}
            style={{ display: "flex", alignItems: "center", gap: 7, padding: "7px 14px", borderRadius: 12, border: "1px solid rgba(180,180,200,0.3)", background: "rgba(120,120,140,0.06)", fontSize: 12, fontWeight: 600, cursor: "pointer", opacity: loading ? 0.5 : 1 }}>
            <RefreshCw style={{ width: 13, height: 13, animation: loading ? "spin 1s linear infinite" : undefined }} />刷新
          </button>
        </div>
      </div>

      {/* ── ROW 2: Time Filter (restored original style) ── */}
      <div className="glass-card" style={{ padding: "10px 18px", borderRadius: 22, border: "1px solid rgba(180,180,200,0.18)", display: "flex", alignItems: "center", gap: 10 }}>
        <span style={{ fontSize: 10, fontWeight: 500, opacity: 0.45, flexShrink: 0 }}>时间范围</span>
        <div style={{ display: "flex", gap: 5 }}>
          {PRESETS.map(p => (
            <button key={p.hours}
              onClick={() => { setPreset(p.hours); setUseCustom(false); setStartDate(null); setEndDate(null) }}
              style={{ padding: "5px 12px", borderRadius: 9, border: `1px solid ${!useCustom && preset === p.hours ? "#6366f1" : "rgba(180,180,200,0.22)"}`, background: !useCustom && preset === p.hours ? "#6366f1" : "rgba(120,120,140,0.06)", color: !useCustom && preset === p.hours ? "#fff" : undefined, fontSize: 11, fontWeight: 800, letterSpacing: "0.04em", cursor: "pointer" }}>
              {p.label === "1H" ? "1小时" : p.label === "24H" ? "24小时" : p.label === "7D" ? "7天" : "30天"}
            </button>
          ))}
        </div>
        <div style={{ flex: 1 }} />
        <DateTimePicker value={startDate} onChange={d => { setStartDate(d); setUseCustom(true) }} onClear={() => { setStartDate(null); if (!endDate) setUseCustom(false) }} placeholder="开始时间" />
        <span style={{ fontSize: 12, opacity: 0.3, fontFamily: "monospace" }}>→</span>
        <DateTimePicker value={endDate} onChange={d => { setEndDate(d); setUseCustom(true) }} onClear={() => { setEndDate(null); if (!startDate) setUseCustom(false) }} placeholder="结束时间" />
        {useCustom && (
          <button onClick={fetchStats} style={{ padding: "6px 14px", borderRadius: 9, background: "#6366f1", color: "#fff", border: "none", fontSize: 11, fontWeight: 800, cursor: "pointer", flexShrink: 0 }}>查询</button>
        )}
      </div>

      {/* ── ROW 3: Stat Cards ─────────────────────────── */}
      <div style={{ display: "grid", gap: 18, gridTemplateColumns: "repeat(4, 1fr)" }}>
        {cards.map(card => (
          <div key={card.key} className="glass-card"
            style={{ borderRadius: 24, padding: "24px 24px 20px", border: "1px solid rgba(180,180,200,0.18)", position: "relative", overflow: "hidden", display: "flex", flexDirection: "column" }}>
            <div style={{ position: "absolute", top: -20, right: -20, width: 90, height: 90, background: `${CARD_ACCENT[card.key]}07`, borderRadius: "50%", pointerEvents: "none" }} />
            {/* Icon + label */}
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 16 }}>
              <div style={{ padding: 10, borderRadius: 14, background: `${CARD_ACCENT[card.key]}14`, border: `1px solid ${CARD_ACCENT[card.key]}28` }}>
                <card.icon style={{ width: 20, height: 20, color: CARD_ACCENT[card.key] }} />
              </div>
              <span style={{ fontSize: 12, fontWeight: 500, opacity: 0.5, paddingTop: 2 }}>{card.label}</span>
            </div>
            {/* Main number */}
            <div style={{ fontSize: 44, fontWeight: 900, letterSpacing: "-0.04em", lineHeight: 1, marginBottom: 14 }}>
              {loading ? <span style={{ opacity: 0.15 }}>—</span> : card.main}
            </div>
            {/* Sub labels */}
            <div style={{ display: "flex", gap: 18 }}>
              {[{ l: card.s1l, v: card.s1v }, { l: card.s2l, v: card.s2v }].map(sub => (
                <div key={sub.l}>
                  <div style={{ fontSize: 11, fontWeight: 500, opacity: 0.45 }}>{sub.l}</div>
                  <div style={{ fontSize: 15, fontWeight: 800, marginTop: 2 }}>{loading ? "—" : sub.v}</div>
                </div>
              ))}
            </div>
            {/* Sparkline */}
            <div style={{ marginTop: "auto", paddingTop: 14, opacity: 0.5 }}>
              <Sparkline data={card.spark} color={CARD_ACCENT[card.key]} height={48} />
            </div>
          </div>
        ))}
      </div>

      {/* ── ROW 4: Monitoring Panel ───────────────────── */}
      <div className="glass-card" style={{ borderRadius: 24, overflow: "hidden", border: "1px solid rgba(180,180,200,0.18)" }}>
        {/* Panel header */}
        <div style={{ padding: "16px 22px", borderBottom: "1px solid rgba(180,180,200,0.12)", display: "flex", alignItems: "center", gap: 10 }}>
          <Server style={{ width: 16, height: 16, opacity: 0.5 }} />
          <h3 style={{ fontSize: 13, fontWeight: 700, margin: 0 }}>监控总览</h3>
          <div style={{ flex: 1 }} />
          <span style={{ fontSize: 10, opacity: 0.4 }}>请求分析 · 网关健康度 · 实时时间线</span>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "300px 1fr", gap: 0 }}>
          {/* LEFT: Request Analysis — fully filled */}
          <div style={{ padding: "20px 22px", borderRight: "1px solid rgba(180,180,200,0.12)", display: "flex", flexDirection: "column", gap: 18 }}>
            <div style={{ fontSize: 11, fontWeight: 600, opacity: 0.45 }}>请求分析</div>

            {/* Pie + type breakdown */}
            <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
              <div style={{ position: "relative", flexShrink: 0 }}>
                <DonutChart slices={pieSlices} size={96} thickness={19} />
                <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center" }}>
                  <div style={{ fontSize: 15, fontWeight: 900, lineHeight: 1 }}>{formatNum(totalReqs)}</div>
                  <div style={{ fontSize: 8, opacity: 0.4, marginTop: 2 }}>总请求</div>
                </div>
              </div>
              <div style={{ flex: 1 }}>
                {[
                  { label: "对话", color: "#6366f1", reqs: chatReqs, toks: stats?.by_feature?.chat?.tokens ?? 0 },
                  { label: "文生图", color: "#a855f7", reqs: t2iReqs, toks: stats?.by_feature?.t2i?.tokens ?? 0 },
                ].map(row => {
                  const pct = totalReqs ? Math.round(row.reqs / totalReqs * 100) : 0
                  return (
                    <div key={row.label} style={{ marginBottom: 10 }}>
                      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 3 }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
                          <div style={{ width: 6, height: 6, borderRadius: "50%", background: row.color }} />
                          <span style={{ fontSize: 11, fontWeight: 700 }}>{row.label}</span>
                        </div>
                        <span style={{ fontSize: 11, fontWeight: 900, color: row.color }}>{pct}%</span>
                      </div>
                      <div style={{ fontSize: 9, opacity: 0.4, marginBottom: 4 }}>{formatNum(row.reqs)} 次 · {formatNum(row.toks)} tok</div>
                      <div style={{ height: 3, borderRadius: 3, background: "rgba(180,180,200,0.12)", overflow: "hidden" }}>
                        <div style={{ height: "100%", width: `${pct}%`, background: row.color, borderRadius: 3, transition: "width 0.7s" }} />
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>

            {/* Request trend sparkline */}
            <div style={{ padding: "12px 14px", borderRadius: 14, border: "1px solid rgba(180,180,200,0.15)", background: "rgba(99,102,241,0.04)" }}>
              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}>
                <span style={{ fontSize: 10, fontWeight: 600, opacity: 0.5 }}>请求趋势</span>
                <span style={{ fontSize: 10, fontWeight: 700, opacity: 0.45 }}>{(stats?.timeline?.length ?? 0)} 个区间</span>
              </div>
              <Sparkline data={tlReqs} color="#6366f1" height={48} />
            </div>

            {/* Token trend sparkline */}
            <div style={{ padding: "12px 14px", borderRadius: 14, border: "1px solid rgba(180,180,200,0.15)", background: "rgba(245,158,11,0.04)" }}>
              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}>
                <span style={{ fontSize: 10, fontWeight: 600, opacity: 0.5 }}>Token 趋势</span>
                <span style={{ fontSize: 10, fontWeight: 700, color: "#f59e0b", opacity: 0.8 }}>{formatNum(stats?.total_tokens ?? 0)}</span>
              </div>
              <Sparkline data={tlToks} color="#f59e0b" height={48} />
            </div>


          </div>

          {/* RIGHT: Gateway Health */}
          <div style={{ padding: "20px 22px" }}>
            <div style={{ fontSize: 11, fontWeight: 600, opacity: 0.45, marginBottom: 16, display: "flex", justifyContent: "space-between" }}>
              <span style={{ fontWeight: 600, fontSize: 11, opacity: 0.45 }}>网关健康度</span>
              <span style={{ fontFamily: "monospace", fontSize: 10, opacity: 0.6 }}>{accounts.length} 节点 · qwen3.6-plus</span>
            </div>
            {accounts.length === 0
              ? <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: 100, fontSize: 12, opacity: 0.25 }}>暂无节点数据</div>
              : <GatewayHealth accounts={accounts} healthHistory={healthHistory} nextRefreshAt={nextRefreshAt} />
            }
          </div>
        </div>
      </div>

    </div>
  )
}
