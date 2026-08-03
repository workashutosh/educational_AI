import { useEffect, useMemo, useState } from "react"
import { Link, useParams } from "react-router-dom"
import { ArrowLeft, CheckCircle2, Loader2, XCircle } from "lucide-react"

import { Button } from "@/components/ui/button"
import { api } from "@/lib/api"
import { cn } from "@/lib/utils"

type QType = "mcq" | "multi" | "brief"

type Question = {
  id: number
  order: number
  qtype: QType
  prompt: string
  options: string[]
  marks: number
}

type ReviewItem = {
  question_id: number
  order: number
  qtype: QType
  prompt: string
  options: string[]
  marks: number
  selected_index: number | null
  selected_indices: number[]
  correct_indices: number[]
  is_correct: boolean | null
  student_answer?: string
  model_answer?: string
  earned_marks?: number | null
  provisional_marks?: number | null
  ai_feedback?: string
  teacher_score?: number | null
  confirmed?: boolean
}

type TestDetail = {
  id: number
  title: string
  status: string
  bucket_name: string
  question_count: number
  duration_minutes: number
  max_score: number
  questions: Question[]
  my_attempt: {
    started_at?: string
    ends_at?: string | null
    submitted_at?: string | null
    score?: number | null
    max_score?: number | null
    percent?: number | null
    objective_score?: number | null
    brief_pending_count?: number | null
    grading_status?: string | null
    answers?: Record<string, number | number[] | string>
    review?: ReviewItem[] | null
    results_released?: boolean
    awaiting_teacher_review?: boolean
    results_mode?: string
  } | null
}

type AnswerMap = Record<number, number | number[] | string>

export function MockTestTakePage() {
  const { testId } = useParams()
  const id = Number(testId)
  const [test, setTest] = useState<TestDetail | null>(null)
  const [answers, setAnswers] = useState<AnswerMap>({})
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [review, setReview] = useState<ReviewItem[] | null>(null)
  const [score, setScore] = useState<{
    score: number
    max_score: number
    percent: number
    brief_pending_count?: number
    grading_status?: string
  } | null>(null)
  const [awaitingReview, setAwaitingReview] = useState(false)
  const [endsAt, setEndsAt] = useState<string | null>(null)
  const [now, setNow] = useState(Date.now())

  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(t)
  }, [])

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      setLoading(true)
      try {
        const start = await api<{ ends_at?: string }>(`/api/mock-tests/${id}/start/`, {
          method: "POST",
        }).catch(() => null)
        const detail = await api<TestDetail>(`/api/mock-tests/${id}/`)
        if (cancelled) return
        setTest(detail)
        const end = detail.my_attempt?.ends_at || start?.ends_at || null
        setEndsAt(end)
        if (detail.my_attempt?.awaiting_teacher_review) {
          setAwaitingReview(true)
        } else if (detail.my_attempt?.review) {
          setReview(detail.my_attempt.review)
          setScore({
            score: detail.my_attempt.score || 0,
            max_score: detail.my_attempt.max_score || 0,
            percent: detail.my_attempt.percent || 0,
            brief_pending_count: detail.my_attempt.brief_pending_count || 0,
            grading_status: detail.my_attempt.grading_status || undefined,
          })
        } else if (detail.my_attempt?.answers) {
          const mapped: AnswerMap = {}
          for (const [k, v] of Object.entries(detail.my_attempt.answers)) {
            mapped[Number(k)] = v
          }
          setAnswers(mapped)
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load")
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [id])

  const remainingMs = useMemo(() => {
    if (!endsAt || review) return null
    return new Date(endsAt).getTime() - now
  }, [endsAt, now, review])

  useEffect(() => {
    if (remainingMs == null || remainingMs > 0 || review || busy || !test) return
    void submit(true)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [remainingMs])

  async function submit(auto = false) {
    if (busy || review) return
    if (!auto && !window.confirm("Submit your answers? You cannot retake this test.")) return
    setBusy(true)
    setError("")
    try {
      const payload: Record<string, number | number[] | string> = {}
      for (const [k, v] of Object.entries(answers)) {
        payload[String(k)] = v
      }
      const res = await api<{
        score: number | null
        max_score: number | null
        percent: number | null
        brief_pending_count: number | null
        grading_status: string | null
        review: ReviewItem[] | null
        awaiting_teacher_review?: boolean
        results_released?: boolean
      }>(`/api/mock-tests/${id}/submit/`, {
        method: "POST",
        body: JSON.stringify({ answers: payload, auto }),
      })
      if (res.awaiting_teacher_review || !res.review) {
        setAwaitingReview(true)
        setReview(null)
        setScore(null)
      } else {
        setAwaitingReview(false)
        setScore({
          score: res.score || 0,
          max_score: res.max_score || 0,
          percent: res.percent || 0,
          brief_pending_count: res.brief_pending_count || 0,
          grading_status: res.grading_status || undefined,
        })
        setReview(res.review)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Submit failed")
    } finally {
      setBusy(false)
    }
  }

  if (loading) {
    return <p className="text-sm text-muted-foreground">Loading test…</p>
  }
  if (!test) {
    return <p className="text-sm text-destructive">{error || "Test not found."}</p>
  }

  if (awaitingReview) {
    return (
      <div className="w-full space-y-6">
        <Link
          to="/app/mock-tests"
          className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="size-4" />
          My Tests
        </Link>
        <div className="rounded-2xl border border-border/80 bg-white/80 p-8">
          <h1 className="font-display text-3xl tracking-tight">{test.title}</h1>
          <p className="mt-3 text-lg font-medium text-[var(--brand)]">Submitted</p>
          <p className="mt-2 max-w-xl text-sm text-muted-foreground">
            Your answers are with your teacher for review. Score and answer review will
            appear here once they release your results.
          </p>
          <Link
            to="/app/mock-tests"
            className={cn(
              "mt-6 inline-flex rounded-lg bg-[var(--brand)] px-3 py-2 text-sm font-medium text-white",
            )}
          >
            Back to My Tests
          </Link>
        </div>
      </div>
    )
  }

  if (review && score) {
    return (
      <div className="w-full space-y-6">
        <Link
          to="/app/mock-tests"
          className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="size-4" />
          My Tests
        </Link>
        <div>
          <h1 className="font-display text-3xl tracking-tight">{test.title}</h1>
          <p className="mt-2 text-2xl font-medium text-[var(--brand)]">
            {score.score}/{score.max_score} ({score.percent}%)
          </p>
          {score.brief_pending_count ? (
            <p className="mt-1 text-sm text-amber-700">
              {score.brief_pending_count} brief answer(s) awaiting teacher confirmation.
              Official score may update after review.
            </p>
          ) : (
            <p className="mt-1 text-sm text-muted-foreground">Final score confirmed.</p>
          )}
        </div>
        <ul className="grid gap-3 lg:grid-cols-2">
          {review.map((r) => (
            <li key={r.question_id} className="rounded-2xl border border-border/80 bg-white/80 p-4">
              <div className="mb-2 flex items-start gap-2">
                {r.qtype === "brief" ? (
                  <span className="mt-0.5 text-xs text-muted-foreground">Brief</span>
                ) : r.is_correct ? (
                  <CheckCircle2 className="mt-0.5 size-4 text-[var(--brand)]" />
                ) : (
                  <XCircle className="mt-0.5 size-4 text-destructive" />
                )}
                <div className="flex-1">
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <p className="text-sm font-medium">Q{r.order}</p>
                    <p
                      className={cn(
                        "text-sm font-semibold tabular-nums",
                        r.qtype === "brief" && !r.confirmed
                          ? "text-amber-700"
                          : (r.earned_marks ?? 0) > 0
                            ? "text-[var(--brand)]"
                            : "text-destructive",
                      )}
                    >
                      {r.qtype === "brief" && !r.confirmed
                        ? `Pending · max ${r.marks}`
                        : `${r.earned_marks ?? 0}/${r.marks} marks`}
                    </p>
                  </div>
                  <p className="mt-1 text-sm whitespace-pre-wrap">{r.prompt}</p>
                </div>
              </div>
              {r.qtype === "brief" ? (
                <div className="space-y-1 text-sm">
                  <p>
                    <span className="text-muted-foreground">Your answer: </span>
                    {r.student_answer || "—"}
                  </p>
                  <p className="text-muted-foreground">
                    Provisional AI: {r.provisional_marks ?? "—"} / {r.marks}
                    {r.ai_feedback ? ` — ${r.ai_feedback}` : ""}
                  </p>
                  <p>
                    Teacher:{" "}
                    {r.confirmed
                      ? `${r.teacher_score} / ${r.marks}`
                      : "Pending confirmation"}
                  </p>
                </div>
              ) : (
                <ul className="space-y-1 text-sm">
                  {r.options.map((opt, i) => {
                    const selected = (r.selected_indices || []).includes(i)
                    const correct = (r.correct_indices || []).includes(i)
                    return (
                      <li
                        key={i}
                        className={cn(
                          "rounded-lg px-2 py-1",
                          correct && "bg-[#e6f4ef] text-[var(--brand)]",
                          selected && !correct && "bg-red-50 text-destructive",
                        )}
                      >
                        {String.fromCharCode(65 + i)}. {opt}
                        {correct ? " ✓" : ""}
                        {selected && !correct ? " (yours)" : ""}
                      </li>
                    )
                  })}
                </ul>
              )}
            </li>
          ))}
        </ul>
      </div>
    )
  }

  const mins = remainingMs != null ? Math.max(0, Math.floor(remainingMs / 60000)) : null
  const secs =
    remainingMs != null ? Math.max(0, Math.floor((remainingMs % 60000) / 1000)) : null

  return (
    <div className="w-full space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <Link
            to="/app/mock-tests"
            className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
          >
            <ArrowLeft className="size-4" />
            My Tests
          </Link>
          <h1 className="mt-2 font-display text-3xl tracking-tight">{test.title}</h1>
          <p className="text-sm text-muted-foreground">
            {test.bucket_name} · {test.question_count} questions · max {test.max_score}
          </p>
        </div>
        {mins != null && secs != null ? (
          <div
            className={cn(
              "rounded-xl border px-3 py-2 text-center",
              remainingMs != null && remainingMs < 60_000
                ? "border-destructive/40 bg-red-50 text-destructive"
                : "border-border bg-white/80",
            )}
          >
            <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Time left</p>
            <p className="font-mono text-lg font-medium">
              {String(mins).padStart(2, "0")}:{String(secs).padStart(2, "0")}
            </p>
          </div>
        ) : null}
      </div>

      {error ? <p className="text-sm text-destructive">{error}</p> : null}

      <ul className="grid gap-4 lg:grid-cols-2">
        {test.questions.map((q) => (
          <li key={q.id} className="rounded-2xl border border-border/80 bg-white/80 p-4">
            <p className="text-sm font-medium">
              Q{q.order}{" "}
              <span className="text-xs font-normal text-muted-foreground">
                {q.qtype === "multi"
                  ? "Multi-select"
                  : q.qtype === "brief"
                    ? "Brief"
                    : "MCQ"}{" "}
                · {q.marks} mark{q.marks === 1 ? "" : "s"}
              </span>
            </p>
            <p className="mt-1 text-sm whitespace-pre-wrap">{q.prompt}</p>

            {q.qtype === "brief" ? (
              <textarea
                className="mt-3 flex w-full rounded-lg border border-input bg-transparent px-2.5 py-2 text-sm"
                rows={4}
                value={typeof answers[q.id] === "string" ? (answers[q.id] as string) : ""}
                onChange={(e) =>
                  setAnswers((prev) => ({ ...prev, [q.id]: e.target.value }))
                }
                disabled={busy}
                placeholder="Write your answer…"
              />
            ) : q.qtype === "multi" ? (
              <ul className="mt-3 space-y-2">
                {q.options.map((opt, i) => {
                  const selected = Array.isArray(answers[q.id])
                    ? (answers[q.id] as number[]).includes(i)
                    : false
                  return (
                    <li key={i}>
                      <label className="flex cursor-pointer items-start gap-2 text-sm">
                        <input
                          type="checkbox"
                          checked={selected}
                          disabled={busy}
                          onChange={() => {
                            setAnswers((prev) => {
                              const cur = Array.isArray(prev[q.id])
                                ? [...(prev[q.id] as number[])]
                                : []
                              const next = selected
                                ? cur.filter((x) => x !== i)
                                : [...cur, i].sort((a, b) => a - b)
                              return { ...prev, [q.id]: next }
                            })
                          }}
                          className="mt-0.5"
                        />
                        <span>
                          {String.fromCharCode(65 + i)}. {opt}
                        </span>
                      </label>
                    </li>
                  )
                })}
              </ul>
            ) : (
              <ul className="mt-3 space-y-2">
                {q.options.map((opt, i) => (
                  <li key={i}>
                    <label className="flex cursor-pointer items-start gap-2 text-sm">
                      <input
                        type="radio"
                        name={`q-${q.id}`}
                        checked={answers[q.id] === i}
                        disabled={busy}
                        onChange={() =>
                          setAnswers((prev) => ({ ...prev, [q.id]: i }))
                        }
                        className="mt-0.5"
                      />
                      <span>
                        {String.fromCharCode(65 + i)}. {opt}
                      </span>
                    </label>
                  </li>
                ))}
              </ul>
            )}
          </li>
        ))}
      </ul>

      <Button disabled={busy} onClick={() => void submit(false)}>
        {busy ? (
          <>
            <Loader2 className="size-4 animate-spin" data-icon="inline-start" />
            Submitting…
          </>
        ) : (
          "Submit test"
        )}
      </Button>
    </div>
  )
}
