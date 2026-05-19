import { InputHTMLAttributes } from "react"

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {}

export function Input({ className = "", ...props }: InputProps) {
  return (
    <input
      className={`w-full h-[34px] px-2.5 text-[13px] rounded-lg border border-[#e5e5e5] bg-white transition-colors focus:border-[#bbb] focus:shadow-[0_0_0_2px_rgba(0,0,0,.04)] placeholder:text-[#999] ${className}`}
      {...props}
    />
  )
}
