/** Small layout + form primitives shared by feature pages (matches existing page styling). */
import type { ComponentProps, ReactNode } from "react"
import type { LucideIcon } from "lucide-react"

import { useAuth } from "@/lib/auth"
import { cn } from "@/lib/utils"

export function PageHeader({
  icon: Icon,
  title,
  description,
  actions,
}: {
  icon?: LucideIcon
  title: string
  description?: ReactNode
  actions?: ReactNode
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 className="flex items-center gap-2 font-display text-3xl tracking-tight">
          {Icon ? <Icon className="size-7 text-brand" /> : null}
          {title}
        </h1>
        {description ? <p className="mt-1 text-muted-foreground">{description}</p> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  )
}

export function Section({
  title,
  description,
  actions,
  children,
  className,
}: {
  title?: ReactNode
  description?: ReactNode
  actions?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <section className={cn("space-y-3 rounded-2xl border border-border/80 bg-white/80 p-5", className)}>
      {title || actions ? (
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            {title ? <h2 className="font-medium">{title}</h2> : null}
            {description ? <p className="mt-0.5 text-sm text-muted-foreground">{description}</p> : null}
          </div>
          {actions ? <div className="flex flex-wrap gap-2">{actions}</div> : null}
        </div>
      ) : null}
      {children}
    </section>
  )
}

export function EmptyState({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-2xl border border-dashed border-border bg-white/60 p-8 text-center text-sm text-muted-foreground">
      {children}
    </div>
  )
}

const TONES: Record<string, string> = {
  green: "bg-brand-soft text-brand",
  amber: "bg-amber-50 text-amber-800",
  red: "bg-red-50 text-red-700",
  sky: "bg-sky-50 text-sky-800",
  gray: "bg-muted text-muted-foreground",
}

export function Pill({ tone = "gray", children }: { tone?: keyof typeof TONES; children: ReactNode }) {
  return (
    <span className={cn("inline-flex shrink-0 items-center rounded-full px-2 py-0.5 text-[11px] font-medium", TONES[tone])}>
      {children}
    </span>
  )
}

export function ErrorText({ children }: { children?: ReactNode }) {
  return children ? <p className="text-sm text-destructive">{children}</p> : null
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return <p className="text-sm text-muted-foreground">{label}</p>
}

const fieldClass =
  "w-full rounded-lg border border-input bg-transparent px-2.5 py-2 text-sm outline-none focus-visible:border-ring disabled:opacity-50"

export function Field({ label, hint, children }: { label: string; hint?: ReactNode; children: ReactNode }) {
  return (
    <label className="block space-y-1 text-sm">
      <span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">{label}</span>
      {children}
      {hint ? <span className="block text-xs text-muted-foreground">{hint}</span> : null}
    </label>
  )
}

export function Select({ className, ...props }: ComponentProps<"select">) {
  return <select className={cn(fieldClass, className)} {...props} />
}

export function TextArea({ className, ...props }: ComponentProps<"textarea">) {
  return <textarea className={cn(fieldClass, "min-h-24", className)} {...props} />
}

export function TextInput({ className, ...props }: ComponentProps<"input">) {
  return <input className={cn(fieldClass, className)} {...props} />
}

/** AI Bucket picker using the buckets in the signed-in session. */
export function BucketSelect({
  value,
  onChange,
  allowAll = false,
  className,
}: {
  value: number | null
  onChange: (id: number | null) => void
  allowAll?: boolean
  className?: string
}) {
  const { session } = useAuth()
  const buckets = session?.buckets || []
  return (
    <Select
      value={value ?? ""}
      onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}
      className={className}
    >
      {allowAll ? <option value="">All AI Buckets</option> : null}
      {buckets.map((b) => (
        <option key={b.id} value={b.id}>
          {b.name}
          {b.grade_level ? ` · ${b.grade_level}` : ""}
        </option>
      ))}
    </Select>
  )
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: ReactNode }) {
  return (
    <div className="rounded-xl border border-border/70 bg-white p-3">
      <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p>
      {hint ? <p className="text-xs text-muted-foreground">{hint}</p> : null}
    </div>
  )
}

/** Accuracy bar used by analytics views. */
export function AccuracyBar({ value }: { value: number | null }) {
  if (value == null) return <span className="text-xs text-muted-foreground">—</span>
  const tone = value < 60 ? "bg-red-500" : value < 80 ? "bg-amber-500" : "bg-brand"
  return (
    <div className="flex items-center gap-2">
      <div className="h-2 w-24 overflow-hidden rounded-full bg-muted">
        <div className={cn("h-full rounded-full", tone)} style={{ width: `${Math.max(3, value)}%` }} />
      </div>
      <span className="text-xs tabular-nums text-muted-foreground">{Math.round(value)}%</span>
    </div>
  )
}
