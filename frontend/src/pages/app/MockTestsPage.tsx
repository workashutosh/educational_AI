import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { ClipboardList, Plus } from "lucide-react"

import { buttonVariants } from "@/components/ui/button"
import { api } from "@/lib/api"
import { useAuth } from "@/lib/auth"
import { cn } from "@/lib/utils"

export type MockTestListItem = {
  id: number
  title: string
  status: string
  bucket_id: number
  bucket_name: string
  question_count: number
  duration_minutes?: number
  max_score?: number
  assigned_count: number
  submitted_count: number
  created_at: string
  my_status?: string
  my_percent?: number | null
  my_score?: number | null
  my_max_score?: number | null
  my_grading_status?: string | null
  my_results_released?: boolean
  my_awaiting_review?: boolean
}

export function MockTestsPage() {
  const { session } = useAuth()
  const isStudent = session?.membership?.role === "student"
  const canCreate = !!session?.can_upload || !!session?.can_manage
  const [tests, setTests] = useState<MockTestListItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      setLoading(true)
      try {
        const rows = await api<MockTestListItem[]>("/api/mock-tests/")
        if (!cancelled) setTests(rows)
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load")
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <div className="w-full space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 font-display text-3xl tracking-tight">
            <ClipboardList className="size-7 text-brand" />
            {isStudent ? "My Tests" : "Mock Tests"}
          </h1>
          <p className="mt-1 text-muted-foreground">
            {isStudent
              ? "Tests your teacher assigned to you — take them and review your scores."
              : "Generate MCQs from AI Bucket notes, assign students, and track scores."}
          </p>
        </div>
        {canCreate && !isStudent ? (
          <Link to="/app/mock-tests/new" className={cn(buttonVariants())}>
            <Plus className="size-4" data-icon="inline-start" />
            New mock test
          </Link>
        ) : null}
      </div>

      {error ? <p className="text-sm text-destructive">{error}</p> : null}
      {loading ? <p className="text-sm text-muted-foreground">Loading…</p> : null}

      {!loading && !tests.length ? (
        <div className="rounded-2xl border border-dashed border-border bg-white/60 p-8 text-center text-sm text-muted-foreground">
          {isStudent
            ? "No published tests yet. Ask your teacher to assign and publish a mock test."
            : "No mock tests yet. Create one from your AI Bucket notes."}
          {canCreate && !isStudent ? (
            <div className="mt-4">
              <Link to="/app/mock-tests/new" className={cn(buttonVariants({ size: "sm" }))}>
                Create mock test
              </Link>
            </div>
          ) : null}
        </div>
      ) : null}

      <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {tests.map((t) => (
          <li key={t.id}>
            <Link
              to={
                isStudent
                  ? t.my_status === "submitted"
                    ? `/app/mock-tests/${t.id}/take`
                    : `/app/mock-tests/${t.id}/take`
                  : `/app/mock-tests/${t.id}`
              }
              className="block rounded-2xl border border-border/80 bg-white/80 p-4 transition hover:border-brand hover:bg-brand-soft/40"
            >
              <div className="flex items-start justify-between gap-2">
                <p className="font-medium leading-snug">{t.title}</p>
                <StatusBadge status={isStudent ? t.my_status || t.status : t.status} />
              </div>
              <p className="mt-1 text-xs text-muted-foreground">
                {t.bucket_name} · {t.question_count} Q
                {t.duration_minutes != null ? ` · ${t.duration_minutes} min` : ""}
                {t.max_score != null ? ` · max ${t.max_score}` : ""}
              </p>
              {isStudent ? (
                <p className="mt-3 text-sm">
                  {t.my_status === "submitted" ? (
                    t.my_awaiting_review || !t.my_results_released ? (
                      <span className="text-amber-700">
                        Submitted — waiting for teacher review
                      </span>
                    ) : (
                      <span className="font-medium text-brand">
                        Score {t.my_score}/{t.my_max_score} ({t.my_percent}%)
                      </span>
                    )
                  ) : t.my_status === "in_progress" ? (
                    <span className="text-amber-700">In progress — continue</span>
                  ) : (
                    <span className="text-muted-foreground">Not started</span>
                  )}
                </p>
              ) : (
                <p className="mt-3 text-xs text-muted-foreground">
                  {t.submitted_count}/{t.assigned_count} submitted
                </p>
              )}
            </Link>
          </li>
        ))}
      </ul>
    </div>
  )
}

function StatusBadge({ status }: { status: string }) {
  const tone =
    status === "published" || status === "submitted"
      ? "bg-brand-soft text-brand"
      : status === "closed"
        ? "bg-muted text-muted-foreground"
        : status === "in_progress"
          ? "bg-amber-50 text-amber-800"
          : "bg-sky-50 text-sky-800"
  const label =
    status === "not_started"
      ? "Not started"
      : status === "in_progress"
        ? "In progress"
        : status.charAt(0).toUpperCase() + status.slice(1)
  return (
    <span className={cn("shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium", tone)}>
      {label}
    </span>
  )
}
