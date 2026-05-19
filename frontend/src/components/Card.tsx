interface CardProps {
  title?: string
  children: React.ReactNode
  className?: string
}

export function Card({ title, children, className = "" }: CardProps) {
  return (
    <div className={`bg-white rounded-[14px] p-6 ${className}`}>
      {title && <h3 className="text-[13px] font-semibold text-[#222] mb-4">{title}</h3>}
      {children}
    </div>
  )
}
