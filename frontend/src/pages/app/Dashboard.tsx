import type { ComponentType } from "react"
import { Link } from "react-router-dom"
import { BookOpen, MessageSquareText, Presentation, Upload } from "lucide-react"

import { buttonVariants } from "@/components/ui/button"
import { useAuth } from "@/lib/auth"
import { cn } from "@/lib/utils"

export function DashboardPage() {
  const { session } = useAuth()
  if (!session?.school || !session.membership) return null

  const { school, user, buckets, can_manage, can_upload, membership } = session
  const quotaGb = Math.round(Number(school.bucket_quota_bytes || 0) / (1024 ** 3)) || 1

  return (
    <div className="w-full space-y-8">
      <div>
        <p className="font-display text-sm tracking-[0.12em] uppercase text-[var(--brand)]">
          {school.name}
        </p>
        <h1 className="mt-1 font-display text-3xl tracking-tight">
          Welcome{user.full_name ? `, ${user.full_name}` : ""}
        </h1>
        <p className="mt-1 text-muted-foreground">
          {membership.role_display} · {buckets.length} AI Bucket
          {buckets.length === 1 ? "" : "s"} available
        </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        <Stat label="AI Buckets" value={String(buckets.length)} hint={`of ${school.max_buckets ?? "—"}`} />
        <Stat label="Per-bucket size" value={`${quotaGb} GB`} hint="Plan quota" />
        <Stat
          label="Join code"
          value={can_manage && school.join_code ? school.join_code : "—"}
          hint={can_manage ? "Share with teachers & students" : "Ask your admin"}
          mono={can_manage}
        />
      </div>

      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <QuickCard
          to="/app/buckets"
          icon={BookOpen}
          title="AI Buckets"
          body="Open subject spaces, create new ones, and manage notes."
        />
        <QuickCard
          to={buckets[0] ? `/app/chat?bucket=${buckets[0].id}` : "/app/chat"}
          icon={MessageSquareText}
          title="Chat"
          body="Ask indexed notes with saved history for each conversation."
        />
        <QuickCard
          to={buckets[0] ? `/app/ppt?bucket=${buckets[0].id}` : "/app/ppt"}
          icon={Presentation}
          title="Create PPT"
          body="Preview a slide deck from your notes, then download when ready."
        />
        {can_upload ? (
          <QuickCard
            to={buckets[0] ? `/app/buckets/${buckets[0].id}` : "/app/buckets"}
            icon={Upload}
            title="Upload notes"
            body="Add PDFs, DOCX, or PPTX into an AI Bucket for retrieval."
          />
        ) : null}
      </section>

      <section>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="font-medium">Your AI Buckets</h2>
          <Link to="/app/buckets" className={cn(buttonVariants({ variant: "outline", size: "sm" }))}>
            View all
          </Link>
        </div>
        {buckets.length ? (
          <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
            {buckets.slice(0, 6).map((b) => (
              <li key={b.id}>
                <Link
                  to={`/app/buckets/${b.id}`}
                  className="block rounded-2xl border border-border/80 bg-white/80 p-4 transition hover:border-[var(--brand)] hover:bg-[#e6f4ef]/50"
                >
                  <p className="font-medium">{b.name}</p>
                  <p className="mt-1 text-sm text-muted-foreground">
                    {b.grade_level || "No grade"} · AI Bucket #{b.id}
                  </p>
                </Link>
              </li>
            ))}
          </ul>
        ) : (
          <div className="rounded-2xl border border-dashed border-border bg-white/60 p-6 text-sm text-muted-foreground">
            {can_manage
              ? "No AI Buckets yet. Create your first subject space."
              : "No AI Buckets granted yet. Ask an admin to give you access."}
            {can_manage ? (
              <div className="mt-3">
                <Link to="/app/buckets" className={cn(buttonVariants({ size: "sm" }))}>
                  Create AI Bucket
                </Link>
              </div>
            ) : null}
          </div>
        )}
      </section>
    </div>
  )
}

function Stat({
  label,
  value,
  hint,
  mono,
}: {
  label: string
  value: string
  hint: string
  mono?: boolean
}) {
  return (
    <div className="rounded-2xl border border-border/80 bg-white/80 p-4">
      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className={`mt-1 text-2xl font-semibold tracking-tight ${mono ? "font-mono tracking-widest" : ""}`}>
        {value}
      </p>
      <p className="mt-1 text-xs text-muted-foreground">{hint}</p>
    </div>
  )
}

function QuickCard({
  to,
  icon: Icon,
  title,
  body,
}: {
  to: string
  icon: ComponentType<{ className?: string }>
  title: string
  body: string
}) {
  return (
    <Link
      to={to}
      className="rounded-2xl border border-border/80 bg-white/80 p-4 transition hover:border-[var(--brand)] hover:bg-[#e6f4ef]/50"
    >
      <Icon className="size-5 text-[var(--brand)]" />
      <h3 className="mt-3 font-medium">{title}</h3>
      <p className="mt-1 text-sm text-muted-foreground">{body}</p>
    </Link>
  )
}
