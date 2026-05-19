interface StatCardProps {
  label: string
  value: string | number
  color?: string
  icon?: React.ReactNode
}

export function StatCard({ label, value, color = "#111", icon }: StatCardProps) {
  return (
    <div className="min-h-[88px] p-3.5 rounded-xl bg-white flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <span className="text-[11px] text-[#8a8a8a] tracking-wide">{label}</span>
        {icon && <span className="w-6 h-6 flex items-center justify-center text-[#a3a3a3]">{icon}</span>}
      </div>
      <div className="text-[22px] font-semibold leading-none tracking-tight mt-auto" style={{ color }}>
        {value}
      </div>
    </div>
  )
}
