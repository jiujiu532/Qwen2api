import { ButtonHTMLAttributes } from "react"

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary" | "danger"
  size?: "sm" | "md"
}

export function Button({ variant = "secondary", size = "md", className = "", children, ...props }: ButtonProps) {
  const base = "inline-flex items-center justify-center gap-1.5 font-semibold rounded-full transition-all whitespace-nowrap"
  const sizes = {
    sm: "h-7 px-3 text-[11px]",
    md: "h-8 px-3.5 text-[13px]",
  }
  const variants = {
    primary: "bg-[#111] text-white border border-[#111] hover:bg-[#222]",
    secondary: "bg-[#fafafa] text-[#444] border border-[#e6e6e6] hover:bg-[#f3f3f3]",
    danger: "bg-[#fff5f4] text-[#b42318] border border-[#fecdc9] hover:bg-[#feeceb]",
  }

  return (
    <button className={`${base} ${sizes[size]} ${variants[variant]} ${className}`} {...props}>
      {children}
    </button>
  )
}
