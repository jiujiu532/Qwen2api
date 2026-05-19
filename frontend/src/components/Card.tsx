interface CardProps {
  title?: string
  children: React.ReactNode
  className?: string
}

export function Card({ title, children, className = "" }: CardProps) {
  return (
    <div className={`bg-white rounded-[14px] shadow-sm ${className}`} style={{ padding: "24px" }}>
      {title && <h3 className="text-[13px] font-semibold text-[#222]" style={{ marginBottom: "16px" }}>{title}</h3>}
      {children}
    </div>
  )
}
