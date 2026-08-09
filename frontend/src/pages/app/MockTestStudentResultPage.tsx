import { useEffect, useState } from "react"
import { Link, Navigate, useParams } from "react-router-dom"
import { ArrowLeft, CheckCircle2, Loader2, XCircle } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { api } from "@/lib/api"
import { useAuth } from "@/lib/auth"
import { cn } from "@/lib/utils"

type ReviewItem = {
  question_id: number
  order: number
  qtype: "mcq" | "multi" | "brief"
  prompt: string
  options: string[]
  marks: number
  selected_index: number | null
  selected_indices: number[]
  correct_indices: number[]
  is_correct: boolean | null
  student_answer?: string
  model_answer?: string
  ai_score?: number | null
  ai_feedback?: string
  teacher_score?: number | null
  teacher_feedback?: string
  confirmed?: boolean
  provisional_marks?: number | null
  earned_marks?: number | null
}

type Payload = {
  student_id: number
  username: string
  full_name: string
  status: string
  score?: number
  max_score?: number
  percent?: number
  brief_pending_count?: number
  grading_status?: string
  submitted_at?: string
  results_released?: boolean
  results_mode?: string
  review: ReviewItem[] | null
}

export function MockTestStudentResultPage() {
  const { testId, studentId } = useParams()
  const { session } = useAuth()
  const tid = Number(testId)
  const sid = Number(studentId)
  const [data, setData] = useState<Payload | null>(null)
  const [error, setError] = useState("")
  const [loading, setLoading] = useState(true)
  const [busyId, setBusyId] = useState<number | null>(null)
  const [releasing, setReleasing] = useState(false)
  const [drafts, setDrafts] = useState<
    Record<number, { score: string; feedback: string }>
  >({})

  async function load() {
    setLoading(true)
    try {
      const res = await api<Payload>(`/api/mock-tests/${tid}/results/${sid}/`)
      setData(res)
      const next: Record<number, { score: string; feedback: string }> = {}
      for (const r of res.review || []) {
        if (r.qtype === "brief") {
          next[r.question_id] = {
            score: String(
              r.teacher_score ?? r.ai_score ?? r.provisional_marks ?? "",
            ),
            feedback: r.teacher_feedback || r.ai_feedback || "",
          }
        }
      }
      setDrafts(next)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tid, sid])

  async function confirmBrief(qid: number, release = false) {
    const d = drafts[qid]
    if (!d) return
    setBusyId(qid)
    setError("")
    try {
      const res = await api<Payload & { review: ReviewItem[] }>(
        `/api/mock-tests/${tid}/results/${sid}/questions/${qid}/confirm/`,
        {
          method: "POST",
          body: JSON.stringify({
            score: Number(d.score),
            feedback: d.feedback,
            release,
          }),
        },
      )
      setData((prev) =>
        prev
          ? {
              ...prev,
              score: res.score,
              max_score: res.max_score,
              percent: res.percent,
              brief_pending_count: res.brief_pending_count,
              grading_status: res.grading_status,
              results_released: res.results_released,
              status: res.brief_pending_count ? "grading" : "final",
              review: res.review,
            }
          : prev,
      )
    } catch (err) {
      setError(err instanceof Error ? err.message : "Confirm failed")
    } finally {
      setBusyId(null)
    }
  }

  const [mailNote, setMailNote] = useState("")

  async function releaseToStudent() {
    setReleasing(true)
    setError("")
    setMailNote("")
    try {
      const res = await api<{
        email_status?: string
        emailed?: number
      }>(`/api/mock-tests/${tid}/results/${sid}/release/`, { method: "POST" })
      if (res.email_status === "sent" || res.emailed) {
        setMailNote("Results released to panel and emailed to the student.")
      } else if (res.email_status === "skipped_no_email") {
        setMailNote("Results released to panel. No email on file for this student.")
      } else if (res.email_status === "failed") {
        setMailNote("Results released to panel, but email failed. Check Brevo settings.")
      } else {
        setMailNote("Results released to the student panel.")
      }
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : "Release failed")
    } finally {
      setReleasing(false)
    }
  }

  if (session?.membership?.role === "student") {
    return <Navigate to={`/app/mock-tests/${tid}/take`} replace />
  }

  if (loading) return <p className="text-muted-foreground">Loading…</p>
  if (!data) {
    return (
      <div>
        <p className="text-destructive">{error || "Not found"}</p>
        <Link to={`/app/mock-tests/${tid}`} className="text-sm text-brand">
          ← Back
        </Link>
      </div>
    )
  }

  return (
    <div className="w-full space-y-5">
      <div>
        <Link
          to={`/app/mock-tests/${tid}`}
          className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-brand"
        >
          <ArrowLeft className="size-3.5" /> Back to results
        </Link>
        <h1 className="mt-1 font-display text-3xl tracking-tight">
          {data.full_name || data.username}
        </h1>
        <p className="text-sm text-muted-foreground">@{data.username}</p>
        {data.score != null ? (
          <p className="mt-2 text-lg font-semibold text-brand">
            Official score: {data.score}/{data.max_score} ({data.percent}%)
            {data.brief_pending_count
              ? ` · ${data.brief_pending_count} brief pending`
              : " · Final"}
          </p>
        ) : (
          <p className="mt-2 text-sm capitalize text-muted-foreground">
            Status: {data.status.replaceAll("_", " ")}
          </p>
        )}
        {data.submitted_at ? (
          <p className="mt-1 text-sm text-muted-foreground">
            Student view:{" "}
            {data.results_released
              ? "Results are visible to the student"
              : "Hidden until you release"}
          </p>
        ) : null}
      </div>

      {data.submitted_at &&
      !data.results_released &&
      data.results_mode !== "immediate" ? (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-brand/30 bg-brand-soft/50 px-4 py-3">
          <p className="text-sm">
            Review the submission below, then show the student their score and answer key.
          </p>
          <Button
            type="button"
            disabled={releasing || (data.brief_pending_count ?? 0) > 0}
            onClick={() => void releaseToStudent()}
          >
            {releasing ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (data.brief_pending_count ?? 0) > 0 ? (
              "Confirm briefs first"
            ) : (
              "Release & email results"
            )}
          </Button>
        </div>
      ) : null}

      {mailNote ? <p className="text-sm text-brand">{mailNote}</p> : null}
      {error ? <p className="text-sm text-destructive">{error}</p> : null}

      {data.review?.length ? (
        <ol className="grid gap-3 lg:grid-cols-2">
          {data.review.map((r) => {
            if (r.qtype === "brief") {
              const draft = drafts[r.question_id] || { score: "", feedback: "" }
              return (
                <li
                  key={r.question_id}
                  className="rounded-2xl border border-amber-200 bg-amber-50/40 p-4 text-sm"
                >
                  <p className="font-medium">
                    {r.order}. Brief · {r.marks} marks
                  </p>
                  <p className="mt-1">{r.prompt}</p>
                  <p className="mt-2">
                    <span className="text-muted-foreground">Student: </span>
                    {r.student_answer || "—"}
                  </p>
                  <p className="mt-1 text-muted-foreground">
                    Model: {r.model_answer || "—"}
                  </p>
                  <p className="mt-1 text-muted-foreground">
                    AI suggestion: {r.ai_score ?? "—"} / {r.marks}
                    {r.ai_feedback ? ` — ${r.ai_feedback}` : ""}
                  </p>
                  <div className="mt-3 grid gap-2 sm:grid-cols-[8rem_1fr_auto]">
                    <div className="space-y-1">
                      <Label className="text-xs">Your score</Label>
                      <Input
                        type="number"
                        min={0}
                        max={r.marks}
                        step={0.5}
                        value={draft.score}
                        onChange={(e) =>
                          setDrafts((prev) => ({
                            ...prev,
                            [r.question_id]: { ...draft, score: e.target.value },
                          }))
                        }
                      />
                    </div>
                    <div className="space-y-1">
                      <Label className="text-xs">Feedback (optional)</Label>
                      <Input
                        value={draft.feedback}
                        onChange={(e) =>
                          setDrafts((prev) => ({
                            ...prev,
                            [r.question_id]: {
                              ...draft,
                              feedback: e.target.value,
                            },
                          }))
                        }
                      />
                    </div>
                    <div className="flex flex-wrap items-end gap-2">
                      <Button
                        type="button"
                        disabled={busyId === r.question_id || draft.score === ""}
                        onClick={() => void confirmBrief(r.question_id, false)}
                      >
                        {busyId === r.question_id ? (
                          <Loader2 className="size-4 animate-spin" />
                        ) : r.confirmed ? (
                          "Update"
                        ) : (
                          "Confirm"
                        )}
                      </Button>
                      {!data.results_released ? (
                        <Button
                          type="button"
                          variant="outline"
                          disabled={busyId === r.question_id || draft.score === ""}
                          onClick={() => void confirmBrief(r.question_id, true)}
                        >
                          Confirm & release
                        </Button>
                      ) : null}
                    </div>
                  </div>
                  {r.confirmed ? (
                    <p className="mt-2 text-xs text-brand">
                      Confirmed at {r.teacher_score} / {r.marks}
                    </p>
                  ) : null}
                </li>
              )
            }

            const selected = new Set(r.selected_indices || [])
            const correct = new Set(r.correct_indices || [])
            return (
              <li
                key={r.question_id}
                className={cn(
                  "rounded-2xl border p-4 text-sm",
                  r.is_correct
                    ? "border-emerald-200 bg-emerald-50/50"
                    : "border-red-200 bg-red-50/40",
                )}
              >
                <div className="flex items-start gap-2">
                  {r.is_correct ? (
                    <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-emerald-600" />
                  ) : (
                    <XCircle className="mt-0.5 size-4 shrink-0 text-red-600" />
                  )}
                  <div>
                    <p className="font-medium">
                      {r.order}. {r.qtype.toUpperCase()} · {r.marks} marks
                    </p>
                    <p className="mt-1">{r.prompt}</p>
                    <ul className="mt-2 space-y-1">
                      {r.options.map((opt, i) => (
                        <li
                          key={i}
                          className={cn(
                            correct.has(i) && "font-medium text-emerald-700",
                            selected.has(i) &&
                              !correct.has(i) &&
                              "text-red-700",
                          )}
                        >
                          {String.fromCharCode(65 + i)}. {opt}
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>
              </li>
            )
          })}
        </ol>
      ) : null}
    </div>
  )
}
