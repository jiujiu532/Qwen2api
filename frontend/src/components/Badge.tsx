interface BadgeProps {
  variant: "active" | "cooling" | "invalid" | "disabled" | "basic" | "info"
  children: React.ReactNode
}

const styles: Record<string, string> = {
  active: "text-[#3e8f69] bg-[#f2f8f4]",
  cooling: "text-[#b47a3d] bg-[#fbf5ed]",
  invalid: "text-[#b66a63] bg-[#fbf3f2]",
  disabled: "text-[#6f675d] bg-[#f1ece4]",
  basic: "text-[#6d6d6d] bg-[#f7f7f7]",
  info: "text-[#4c76b2] bg-[#f1f6fc]",
}

export function Badge({ variant, children }: BadgeProps) {
  return (
    <span className={`inline-flex items-center h-5 px-2 rounded-full text-[11px] font-medium ${styles[variant] || styles.basic}`}>
      {children}
    </span>
  )
}
