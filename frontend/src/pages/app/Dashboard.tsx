import { useEffect, useState, type ComponentType } from "react"
import { Link } from "react-router-dom"
import {
  BookOpen,
  ClipboardList,
  MessageSquareText,
  Presentation,
  Upload,
} from "lucide-react"

import { buttonVariants } from "@/components/ui/button"
import { api } from "@/lib/api"
import { useAuth } from "@/lib/auth"
import { cn } from "@/lib/utils"
import type { MockTestListItem } from "@/pages/app/MockTestsPage"

export function DashboardPage() {
  const { session } = useAuth()
  if (!session?.school || !session.membership) return null

  if (session.membership.role === "student") {
    return <StudentDashboard />
  }

  return <StaffDashboard />
}

function StudentDashboard() {
  const { session } = useAuth()
  const [tests, setTests] = useState<MockTestListItem[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const rows = await api<MockTestListItem[]>("/api/mock-tests/")
        if (!cancelled) setTests(rows)
      } catch {
        if (!cancelled) setTests([])
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  if (!session?.school || !session.membership) return null
  const { school, user } = session
  const pending = tests.filter((t) => t.my_status !== "submitted")
  const done = tests.filter((t) => t.my_status === "submitted")

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
          Student · mock tests and AI chat on your assigned buckets
        </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Stat label="Tests" value={loading ? "…" : String(tests.length)} hint="Assigned" />
        <Stat
          label="To take"
          value={loading ? "…" : String(pending.length)}
          hint="Not submitted yet"
        />
        <Stat
          label="Completed"
          value={loading ? "…" : String(done.length)}
          hint="Submitted"
        />
        <Stat
          label="AI Buckets"
          value={String(session.buckets?.length || 0)}
          hint="Chat access"
        />
      </div>

      <section className="grid gap-3 sm:grid-cols-2">
        <QuickCard
          to={
            session.buckets?.[0]
              ? `/app/chat?bucket=${session.buckets[0].id}`
              : "/app/chat"
          }
          icon={MessageSquareText}
          title="AI Chat"
          body={
            session.buckets?.length
              ? `Ask grounded questions from ${session.buckets.length} assigned AI Bucket${session.buckets.length === 1 ? "" : "s"}.`
              : "Ask your teacher to grant AI Bucket access to start chatting."
          }
        />
        <QuickCard
          to="/app/mock-tests"
          icon={ClipboardList}
          title="My Tests"
          body="Take assigned mock tests and review scores after your teacher releases them."
        />
      </section>

      {session.buckets?.length ? (
        <section>
          <div className="mb-3 flex items-center justify-between gap-2">
            <h2 className="font-medium">Your AI Buckets</h2>
            <Link
              to="/app/chat"
              className={cn(buttonVariants({ variant: "outline", size: "sm" }))}
            >
              Open chat
            </Link>
          </div>
          <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {session.buckets.map((b) => (
              <li key={b.id}>
                <Link
                  to={`/app/chat?bucket=${b.id}`}
                  className="block rounded-2xl border border-border/80 bg-white/80 p-4 transition hover:border-[var(--brand)] hover:bg-[#e6f4ef]/50"
                >
                  <p className="font-medium">{b.name}</p>
                  <p className="mt-1 text-sm text-muted-foreground">
                    {b.grade_level || "No grade"} · Chat with notes
                  </p>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <section>
        <div className="mb-3 flex items-center justify-between gap-2">
          <h2 className="font-medium">Your tests</h2>
          <Link
            to="/app/mock-tests"
            className={cn(buttonVariants({ variant: "outline", size: "sm" }))}
          >
            View all
          </Link>
        </div>
        {loading ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : tests.length ? (
          <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {tests.slice(0, 6).map((t) => (
              <li key={t.id}>
                <Link
                  to={`/app/mock-tests/${t.id}/take`}
                  className="block rounded-2xl border border-border/80 bg-white/80 p-4 transition hover:border-[var(--brand)] hover:bg-[#e6f4ef]/50"
                >
                  <div className="flex items-start justify-between gap-2">
                    <p className="font-medium">{t.title}</p>
                    <ClipboardList className="size-4 shrink-0 text-[var(--brand)]" />
                  </div>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {t.question_count} Q
                    {t.duration_minutes != null ? ` · ${t.duration_minutes} min` : ""}
                  </p>
                  <p className="mt-2 text-sm">
                    {t.my_status === "submitted" ? (
                      <span className="font-medium text-[var(--brand)]">
                        Score {t.my_score}/{t.my_max_score} ({t.my_percent}%)
                      </span>
                    ) : t.my_status === "in_progress" ? (
                      <span className="text-amber-700">In progress — continue</span>
                    ) : (
                      <span className="text-muted-foreground">Not started</span>
                    )}
                  </p>
                </Link>
              </li>
            ))}
          </ul>
        ) : (
          <div className="rounded-2xl border border-dashed border-border bg-white/60 p-6 text-sm text-muted-foreground">
            No tests assigned yet. Your teacher will assign mock tests here.
          </div>
        )}
      </section>
    </div>
  )
}

function StaffDashboard() {
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
        <QuickCard
          to="/app/mock-tests"
          icon={ClipboardList}
          title="Mock Tests"
          body="Generate, assign, and review student mock tests."
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
