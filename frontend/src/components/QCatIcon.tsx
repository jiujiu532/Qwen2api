// Q-Cat Logo Component — the official Qwen2API mascot icon
// Usage: <QCatIcon className="h-8 w-8" />
export default function QCatIcon({ className = "h-8 w-8" }: { className?: string }) {
    return (
        <svg
            className={className}
            viewBox="0 0 100 100"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
        >
            <defs>
                <linearGradient id="qcat-g" x1="0" y1="0" x2="100" y2="100" gradientUnits="userSpaceOnUse">
                    <stop offset="0%" stopColor="#818cf8" />
                    <stop offset="100%" stopColor="#c084fc" />
                </linearGradient>
            </defs>
            {/* Cat ears */}
            <path d="M28 34 L17 13 L43 29 Z" fill="url(#qcat-g)" />
            <path d="M72 34 L83 13 L57 29 Z" fill="url(#qcat-g)" />
            {/* Inner ear highlight */}
            <path d="M29 33 L21 18 L40 30 Z" fill="#f3e8ff" opacity="0.55" />
            <path d="M71 33 L79 18 L60 30 Z" fill="#f3e8ff" opacity="0.55" />
            {/* Head — the Q circle */}
            <circle cx="50" cy="53" r="30" fill="white" stroke="url(#qcat-g)" strokeWidth="10" />
            {/* Eyes */}
            <circle cx="40" cy="51" r="3.5" fill="#4338ca" />
            <circle cx="60" cy="51" r="3.5" fill="#4338ca" />
            {/* Eye shine */}
            <circle cx="41.5" cy="49.5" r="1.2" fill="white" />
            <circle cx="61.5" cy="49.5" r="1.2" fill="white" />
            {/* Smile */}
            <path d="M45 60 Q50 64.5 55 60" stroke="#4338ca" strokeWidth="2.5" fill="none" strokeLinecap="round" />
            {/* Q tail (cat tail) */}
            <path d="M72 76 Q86 88 82 72 Q78 60 72 65" stroke="url(#qcat-g)" strokeWidth="8" strokeLinecap="round" fill="none" />
        </svg>
    );
}
