"use client";

interface LeadScoreBadgeProps {
  score: number;
  tier: string;
  showLabel?: boolean;
  size?: "sm" | "md" | "lg";
}

const TIER_CONFIG = {
  hot: {
    label: "🔥 HOT",
    bg: "bg-red-500/20",
    border: "border-red-500/50",
    text: "text-red-400",
    glow: "shadow-red-500/30",
    dot: "bg-red-400",
  },
  warm: {
    label: "⚡ WARM",
    bg: "bg-amber-500/20",
    border: "border-amber-500/50",
    text: "text-amber-400",
    glow: "shadow-amber-500/30",
    dot: "bg-amber-400",
  },
  none: {
    label: "○ COLD",
    bg: "bg-zinc-700/20",
    border: "border-zinc-600/50",
    text: "text-zinc-400",
    glow: "",
    dot: "bg-zinc-500",
  },
};

export function LeadScoreBadge({
  score,
  tier,
  showLabel = true,
  size = "md",
}: LeadScoreBadgeProps) {
  const config = TIER_CONFIG[tier as keyof typeof TIER_CONFIG] || TIER_CONFIG.none;

  const sizeClasses = {
    sm: "text-xs px-2 py-0.5 gap-1",
    md: "text-sm px-3 py-1 gap-1.5",
    lg: "text-base px-4 py-1.5 gap-2",
  }[size];

  const scoreSizes = {
    sm: "text-xs w-5 h-5",
    md: "text-sm w-6 h-6",
    lg: "text-base w-7 h-7",
  }[size];

  return (
    <div className="flex items-center gap-2">
      {/* Numeric score bubble */}
      <div
        className={`
          ${scoreSizes} rounded-full flex items-center justify-center font-black
          ${config.bg} ${config.border} ${config.text} border
          ${config.glow ? `shadow-md ${config.glow}` : ""}
        `}
      >
        {score}
      </div>

      {/* Tier label badge */}
      {showLabel && (
        <span
          className={`
            inline-flex items-center rounded-full border font-semibold tracking-wider uppercase
            ${sizeClasses} ${config.bg} ${config.border} ${config.text}
          `}
        >
          <span className={`w-1.5 h-1.5 rounded-full ${config.dot} mr-1`} />
          {config.label}
        </span>
      )}
    </div>
  );
}
