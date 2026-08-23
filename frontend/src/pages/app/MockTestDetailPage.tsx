import { useCallback, useEffect, useState } from "react"
import { Link, Navigate, useNavigate, useParams } from "react-router-dom"
import { ArrowLeft, Loader2 } from "lucide-react"

import { Button } from "@/components/ui/button"
import { api, type MemberRow } from "@/lib/api"
import { useAuth } from "@/lib/auth"
import { cn } from "@/lib/utils"

type Tab = "questions" | "students" | "results"

type Question = {
  id: number
  order: number
  qtype: "mcq" | "multi" | "brief"
  prompt: string
  options: string[]
  marks: number
  correct_indices?: number[]
  correct_index?: number
  model_answer?: string
}

type TestDetail = {
  id: number
  title: string
  status: string
  bucket_name: string
  topic_prompt: string
  question_count: number
  duration_minutes: number
  max_score: number
  count_mcq: number
  count_multi: number
  count_brief: number
  results_mode?: string
  can_manage: boolean
  questions: Question[]
  assignments: { student_id: number; username: string; full_name: string }[]
  assigned_count: number
  submitted_count: number
}

type ResultsPayload = {
  summary: {
    assigned: number
    started: number
    submitted: number
    not_started: number
    avg_percent: number | null
    high_percent: number | null
    low_percent: number | null
    question_count: number
    max_score?: number
    duration_minutes?: number
    pending_brief_grades?: number
    results_mode?: string
    ready_to_release?: number
    results_released_count?: number
  }
  roster: {
    student_id: number
    username: string
    full_name: string
    status: string
    score: number | null
    max_score: number | null
    percent: number | null
    submitted_at: string | null
    brief_pending_count?: number | null
    results_released?: boolean
  }[]
  questions: {
    question_id: number
    order: number
    qtype?: string
    prompt: string
    marks?: number
    correct_count: number
    wrong_count: number
    unanswered_count: number
    correct_rate: number
  }[]
}

export function MockTestDetailPage() {
  const { testId } = useParams()
  const id = Number(testId)
  const { session } = useAuth()
  const navigate = useNavigate()
  const isStudent = session?.membership?.role === "student"

  const [tab, setTab] = useState<Tab>("questions")
  const [test, setTest] = useState<TestDetail | null>(null)
  const [results, setResults] = useState<ResultsPayload | null>(null)
  const [allStudents, setAllStudents] = useState<MemberRow[]>([])
  const [studentsLoading, setStudentsLoading] = useState(true)
  const [studentsError, setStudentsError] = useState("")
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")

  const load = useCallback(async () => {
    setLoading(true)
    setError("")
    try {
      const detail = await api<TestDetail>(`/api/mock-tests/${id}/`)
      setTest(detail)
      if (!detail.can_manage) {
        navigate(`/app/mock-tests/${id}/take`, { replace: true })
        return
      }
      if (detail.status !== "draft") {
        const r = await api<ResultsPayload>(`/api/mock-tests/${id}/results/`)
        setResults(r)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load")
    } finally {
      setLoading(false)
    }
  }, [id, navigate])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    setStudentsLoading(true)
    setStudentsError("")
    void api<MemberRow[]>("/api/admin/members/?role=student")
      .then((rows) => {
        setAllStudents(rows)
      })
      .catch((err) => {
        setAllStudents([])
        setStudentsError(
          err instanceof Error ? err.message : "Could not load student roster",
        )
      })
      .finally(() => setStudentsLoading(false))
  }, [])

  if (isStudent) {
    return <Navigate to={`/app/mock-tests/${id}/take`} replace />
  }

  if (loading) return <p className="text-muted-foreground">Loading…</p>
  if (!test) {
    return (
      <div>
        <p className="text-destructive">{error || "Not found"}</p>
        <Link to="/app/mock-tests" className="text-sm text-brand">
          ← Back
        </Link>
      </div>
    )
  }

  const assignedIds = new Set((test.assignments || []).map((a) => a.student_id))
  const grantable = allStudents.filter((s) => !assignedIds.has(s.id))

  async function assignSelected(publishAfter = test.status === "draft") {
    if (!selected.size) return
    setBusy(true)
    setError("")
    try {
      await api(`/api/mock-tests/${id}/assign/`, {
        method: "POST",
        body: JSON.stringify({
          student_ids: [...selected],
          publish: publishAfter,
        }),
      })
      setSelected(new Set())
      await load()
      if (publishAfter) setTab("results")
    } catch (err) {
      setError(err instanceof Error ? err.message : "Assign failed")
      setTab("students")
    } finally {
      setBusy(false)
    }
  }

  async function unassign(studentId: number) {
    setBusy(true)
    try {
      await api(`/api/mock-tests/${id}/assign/${studentId}/`, { method: "DELETE" })
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unassign failed")
    } finally {
      setBusy(false)
    }
  }

  async function publish() {
    if (test.assigned_count < 1) {
      setError("Select at least one student on the Students tab before publishing.")
      setTab("students")
      return
    }
    setBusy(true)
    setError("")
    try {
      await api(`/api/mock-tests/${id}/publish/`, { method: "POST" })
      await load()
      setTab("results")
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Publish failed"
      setError(msg)
      if (/assign at least one student/i.test(msg)) setTab("students")
    } finally {
      setBusy(false)
    }
  }

  async function closeTest() {
    setBusy(true)
    try {
      await api(`/api/mock-tests/${id}/close/`, { method: "POST" })
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : "Close failed")
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="w-full space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <Link
            to="/app/mock-tests"
            className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-brand"
          >
            <ArrowLeft className="size-3.5" /> Mock Tests
          </Link>
          <h1 className="mt-1 font-display text-3xl tracking-tight">{test.title}</h1>
          <p className="text-sm text-muted-foreground">
            {test.bucket_name} · {test.status} · {test.duration_minutes} min · max{" "}
            {test.max_score} · {test.submitted_count}/{test.assigned_count} submitted
          </p>
          <p className="text-xs text-muted-foreground">
            Blueprint: {test.count_mcq} MCQ · {test.count_multi} multi · {test.count_brief}{" "}
            brief
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {test.status === "draft" ? (
            <Button
              type="button"
              disabled={busy || test.assigned_count < 1}
              onClick={() => void publish()}
            >
              Publish
            </Button>
          ) : null}
          {test.status === "published" ? (
            <Button type="button" variant="outline" disabled={busy} onClick={() => void closeTest()}>
              Close test
            </Button>
          ) : null}
        </div>
      </div>

      {error ? <p className="text-sm text-destructive">{error}</p> : null}

      {test.status === "draft" ? (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-amber-200 bg-amber-50/70 px-4 py-3 text-sm">
          <p className="text-amber-900">
            This test is still a <strong>draft</strong>. Students cannot see it until you
            assign them and publish
            {test.assigned_count
              ? ` (${test.assigned_count} student${test.assigned_count === 1 ? "" : "s"} already assigned).`
              : " — go to the Students tab to pick who should take it."}
          </p>
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={busy}
              onClick={() => setTab("students")}
            >
              Assign students
            </Button>
            <Button
              type="button"
              size="sm"
              disabled={busy || test.assigned_count < 1}
              onClick={() => void publish()}
            >
              Publish now
            </Button>
          </div>
        </div>
      ) : null}

      <div className="flex gap-1 rounded-xl border border-border/80 bg-white/80 p-1 w-fit">
        {(
          [
            ["questions", "Questions"],
            ["students", "Students"],
            ["results", "Results"],
          ] as const
        ).map(([key, label]) => (
          <button
            key={key}
            type="button"
            onClick={() => setTab(key)}
            className={cn(
              "rounded-lg px-3 py-1.5 text-sm font-medium transition",
              tab === key
                ? "bg-brand text-white"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {label}
            {key === "students" &&
            test.status === "draft" &&
            test.assigned_count < 1 ? (
              <span className="ml-1.5 inline-block size-2 rounded-full bg-amber-400" />
            ) : null}
          </button>
        ))}
      </div>

      {tab === "questions" ? (
        <ol className="space-y-3">
          {test.questions.map((q) => {
            const correct = new Set(q.correct_indices || (q.correct_index != null ? [q.correct_index] : []))
            return (
              <li
                key={q.id}
                className="rounded-2xl border border-border/80 bg-white/80 p-4 text-sm"
              >
                <p className="font-medium">
                  {q.order}.{" "}
                  <span className="text-xs font-normal uppercase text-muted-foreground">
                    {q.qtype} · {q.marks} mark{q.marks === 1 ? "" : "s"}
                  </span>
                </p>
                <p className="mt-1">{q.prompt}</p>
                {q.qtype === "brief" ? (
                  <p className="mt-2 text-xs text-muted-foreground">
                    Model answer: {q.model_answer || "—"}
                  </p>
                ) : (
                  <ul className="mt-2 space-y-1 text-muted-foreground">
                    {q.options.map((opt, i) => (
                      <li
                        key={i}
                        className={cn(correct.has(i) && "font-medium text-brand")}
                      >
                        {String.fromCharCode(65 + i)}. {opt}
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            )
          })}
        </ol>
      ) : null}

      {tab === "students" ? (
        <div className="grid gap-4 lg:grid-cols-2">
          <section className="rounded-2xl border border-border/80 bg-white/80 p-4">
            <h2 className="font-medium">Assigned ({test.assignments?.length ?? 0})</h2>
            <ul className="mt-3 space-y-2">
              {test.assignments?.length ? (
                test.assignments.map((a) => (
                  <li
                    key={a.student_id}
                    className="flex items-center justify-between gap-2 rounded-xl border border-border/70 px-3 py-2 text-sm"
                  >
                    <span>
                      {a.full_name || a.username}{" "}
                      <span className="text-muted-foreground">@{a.username}</span>
                    </span>
                    {test.status === "draft" || test.status === "published" ? (
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        disabled={busy}
                        onClick={() => void unassign(a.student_id)}
                      >
                        Remove
                      </Button>
                    ) : null}
                  </li>
                ))
              ) : (
                <p className="text-sm text-muted-foreground">No students assigned yet.</p>
              )}
            </ul>
          </section>
          <section className="rounded-2xl border border-border/80 bg-white/80 p-4">
            <h2 className="font-medium">Add students</h2>
            {studentsLoading ? (
              <p className="mt-3 text-sm text-muted-foreground">Loading student roster…</p>
            ) : studentsError ? (
              <p className="mt-3 text-sm text-destructive">{studentsError}</p>
            ) : !allStudents.length ? (
              <div className="mt-3 space-y-2 text-sm text-muted-foreground">
                <p>No student accounts in your school yet.</p>
                <p>
                  Create one under{" "}
                  <Link to="/app/students" className="font-medium text-brand hover:underline">
                    Students
                  </Link>{" "}
                  (teachers) or{" "}
                  <Link to="/app/members" className="font-medium text-brand hover:underline">
                    Members
                  </Link>{" "}
                  (admins), then come back here to assign.
                </p>
              </div>
            ) : (
              <>
                <ul className="mt-3 max-h-72 space-y-1 overflow-y-auto">
                  {grantable.map((s) => (
                    <li key={s.id}>
                      <label className="flex cursor-pointer items-center gap-2 rounded-lg px-2 py-1.5 text-sm hover:bg-muted/60">
                        <input
                          type="checkbox"
                          checked={selected.has(s.id)}
                          onChange={() =>
                            setSelected((prev) => {
                              const next = new Set(prev)
                              if (next.has(s.id)) next.delete(s.id)
                              else next.add(s.id)
                              return next
                            })
                          }
                          disabled={busy}
                        />
                        <span>
                          {s.full_name || s.username}{" "}
                          <span className="text-muted-foreground">@{s.username}</span>
                        </span>
                      </label>
                    </li>
                  ))}
                  {!grantable.length ? (
                    <p className="text-sm text-muted-foreground">
                      All students in your school are already assigned to this test.
                    </p>
                  ) : null}
                </ul>
                <div className="mt-3 flex flex-wrap gap-2">
                  <Button
                    type="button"
                    disabled={busy || !selected.size}
                    onClick={() => void assignSelected(true)}
                  >
                    {busy ? (
                      <Loader2 className="size-4 animate-spin" />
                    ) : test.status === "draft" ? (
                      "Assign & publish"
                    ) : (
                      "Assign selected"
                    )}
                  </Button>
                  {test.status === "draft" ? (
                    <Button
                      type="button"
                      variant="outline"
                      disabled={busy || !selected.size}
                      onClick={() => void assignSelected(false)}
                    >
                      Assign only (keep draft)
                    </Button>
                  ) : null}
                </div>
                {test.status === "draft" ? (
                  <p className="mt-2 text-xs text-muted-foreground">
                    <strong>Assign & publish</strong> is the usual path — students see the
                    test under My Tests right away.
                  </p>
                ) : null}
              </>
            )}
          </section>
        </div>
      ) : null}

      {tab === "results" ? (
        results ? (
          <ResultsPanel
            testId={id}
            results={results}
            resultsMode={test.results_mode || "after_review"}
            onChanged={() => void load()}
          />
        ) : (
          <p className="text-sm text-muted-foreground">
            Publish the test to start collecting scores.
          </p>
        )
      ) : null}
    </div>
  )
}

function ResultsPanel({
  testId,
  results,
  resultsMode,
  onChanged,
}: {
  testId: number
  results: ResultsPayload
  resultsMode: string
  onChanged: () => void
}) {
  const s = results.summary
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState("")
  const [lbEnabled, setLbEnabled] = useState(false)
  const [lbRows, setLbRows] = useState<
    { display_name: string; percent: number; score: number; max_score: number }[]
  >([])

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const data = await api<{
          enabled: boolean
          entries: {
            display_name: string
            percent: number
            score: number
            max_score: number
          }[]
        }>(`/api/engagement/mock-tests/${testId}/leaderboard/`)
        if (!cancelled) {
          setLbEnabled(!!data.enabled)
          setLbRows(data.entries || [])
        }
      } catch {
        /* ignore */
      }
    })()
    return () => {
      cancelled = true
    }
  }, [testId, results])

  async function toggleLeaderboard(enabled: boolean) {
    setBusy(true)
    setErr("")
    try {
      const data = await api<{ enabled: boolean }>(
        `/api/engagement/mock-tests/${testId}/leaderboard/settings/`,
        {
          method: "PATCH",
          body: JSON.stringify({ enabled }),
        },
      )
      setLbEnabled(!!data.enabled)
      const board = await api<{
        entries: {
          display_name: string
          percent: number
          score: number
          max_score: number
        }[]
      }>(`/api/engagement/mock-tests/${testId}/leaderboard/`)
      setLbRows(board.entries || [])
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not update leaderboard")
    } finally {
      setBusy(false)
    }
  }
  async function setMode(mode: "immediate" | "after_review") {
    setBusy(true)
    setErr("")
    try {
      await api(`/api/mock-tests/${testId}/`, {
        method: "PATCH",
        body: JSON.stringify({ results_mode: mode }),
      })
      onChanged()
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not update mode")
    } finally {
      setBusy(false)
    }
  }

  const [mailNote, setMailNote] = useState("")

  function noteFromRelease(res: {
    emailed?: number
    email_skipped?: number
    email_failed?: number
    email_status?: string
  }) {
    if (res.email_status) {
      if (res.email_status === "sent") return "Results released and emailed to the student."
      if (res.email_status === "skipped_no_email")
        return "Results released in panel. Student has no email on file — skipped mail."
      return "Results released in panel. Email failed — check Brevo settings."
    }
    const parts = [
      `Released to panel.`,
      `Emailed ${res.emailed ?? 0}.`,
    ]
    if (res.email_skipped)
      parts.push(`${res.email_skipped} skipped (no email).`)
    if (res.email_failed) parts.push(`${res.email_failed} email failed.`)
    return parts.join(" ")
  }

  async function releaseAll() {
    setBusy(true)
    setErr("")
    setMailNote("")
    try {
      const res = await api<{
        emailed?: number
        email_skipped?: number
        email_failed?: number
      }>(`/api/mock-tests/${testId}/results/release/`, {
        method: "POST",
        body: JSON.stringify({}),
      })
      setMailNote(noteFromRelease(res))
      onChanged()
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Release failed")
    } finally {
      setBusy(false)
    }
  }

  async function releaseOne(studentId: number) {
    setBusy(true)
    setErr("")
    setMailNote("")
    try {
      const res = await api<{
        emailed?: number
        email_skipped?: number
        email_failed?: number
        email_status?: string
      }>(`/api/mock-tests/${testId}/results/${studentId}/release/`, {
        method: "POST",
      })
      setMailNote(noteFromRelease(res))
      onChanged()
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Release failed")
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3 rounded-2xl border border-border/80 bg-white/80 p-4">
        <div>
          <p className="text-sm font-medium">Class leaderboard</p>
          <p className="text-xs text-muted-foreground">
            Opt-in. Students see anonymous ranks; names stay private to the class
            roster here.
          </p>
        </div>
        <Button
          type="button"
          size="sm"
          variant={lbEnabled ? "default" : "outline"}
          disabled={busy}
          onClick={() => void toggleLeaderboard(!lbEnabled)}
        >
          {lbEnabled ? "Leaderboard on" : "Show class leaderboard"}
        </Button>
      </div>
      {lbEnabled && lbRows.length ? (
        <ol className="rounded-2xl border border-border/80 bg-white/80 p-4 text-sm">
          {lbRows.slice(0, 15).map((r, i) => (
            <li
              key={`${r.display_name}-${i}`}
              className="flex items-center justify-between border-b border-border/50 py-2 last:border-0"
            >
              <span>
                #{i + 1} {r.display_name}
              </span>
              <span className="tabular-nums text-muted-foreground">
                {r.percent}% ({r.score}/{r.max_score})
              </span>
            </li>
          ))}
        </ol>
      ) : null}

      <div className="flex flex-wrap items-start justify-between gap-3 rounded-2xl border border-border/80 bg-white/80 p-4">
        <div>
          <p className="text-sm font-medium">Results for students</p>
          <p className="text-xs text-muted-foreground">
            {resultsMode === "immediate"
              ? "Immediate mode — students see scores as soon as they submit."
              : "Review mode — review submissions here, then release results to students."}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            Released {s.results_released_count ?? 0} · Waiting{" "}
            {s.ready_to_release ?? 0}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            size="sm"
            variant={resultsMode === "after_review" ? "default" : "outline"}
            disabled={busy}
            onClick={() => void setMode("after_review")}
          >
            Review first
          </Button>
          <Button
            type="button"
            size="sm"
            variant={resultsMode === "immediate" ? "default" : "outline"}
            disabled={busy}
            onClick={() => void setMode("immediate")}
          >
            Show immediately
          </Button>
          {resultsMode !== "immediate" ? (
            <Button
              type="button"
              disabled={busy || !s.submitted}
              onClick={() => void releaseAll()}
            >
              {busy ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                "Release & email all"
              )}
            </Button>
          ) : null}
        </div>
      </div>
      {err ? <p className="text-sm text-destructive">{err}</p> : null}
      {mailNote ? <p className="text-sm text-brand">{mailNote}</p> : null}

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Assigned" value={String(s.assigned)} />
        <StatCard label="Submitted" value={`${s.submitted}/${s.assigned}`} />
        <StatCard
          label="Average"
          value={s.avg_percent != null ? `${s.avg_percent}%` : "—"}
        />
        <StatCard
          label="High / Low"
          value={
            s.high_percent != null ? `${s.high_percent}% / ${s.low_percent}%` : "—"
          }
        />
        <StatCard
          label="Brief pending"
          value={String(s.pending_brief_grades ?? 0)}
        />
      </div>

      <section className="rounded-2xl border border-border/80 bg-white/80 p-4">
        <h2 className="font-medium">Roster</h2>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[36rem] text-left text-sm">
            <thead className="text-xs text-muted-foreground">
              <tr className="border-b border-border/70">
                <th className="py-2 pr-3 font-medium">Student</th>
                <th className="py-2 pr-3 font-medium">Status</th>
                <th className="py-2 pr-3 font-medium">Score</th>
                <th className="py-2 pr-3 font-medium">Student view</th>
                <th className="py-2 font-medium" />
              </tr>
            </thead>
            <tbody>
              {results.roster.map((r) => (
                <tr key={r.student_id} className="border-b border-border/50">
                  <td className="py-2.5 pr-3">
                    <p className="font-medium">{r.full_name || r.username}</p>
                    <p className="text-xs text-muted-foreground">@{r.username}</p>
                  </td>
                  <td className="py-2.5 pr-3 capitalize">
                    {r.status.replaceAll("_", " ")}
                  </td>
                  <td className="py-2.5 pr-3">
                    {r.percent != null ? `${r.score}/${r.max_score} (${r.percent}%)` : "—"}
                  </td>
                  <td className="py-2.5 pr-3 text-xs">
                    {!r.submitted_at
                      ? "—"
                      : r.results_released
                        ? "Visible"
                        : "Hidden (awaiting release)"}
                  </td>
                  <td className="py-2.5 text-right">
                    <div className="flex flex-wrap items-center justify-end gap-2">
                      {r.status === "submitted" ||
                      r.status === "grading" ||
                      r.status === "ready_to_release" ||
                      r.status === "final" ? (
                        <Link
                          to={`/app/mock-tests/${testId}/results/${r.student_id}`}
                          className="text-sm font-medium text-brand"
                        >
                          {r.status === "grading" || (r.brief_pending_count ?? 0) > 0
                            ? "Review"
                            : "Open"}
                        </Link>
                      ) : null}
                      {r.submitted_at &&
                      !r.results_released &&
                      resultsMode !== "immediate" ? (
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          disabled={busy}
                          onClick={() => void releaseOne(r.student_id)}
                        >
                          Release & email
                        </Button>
                      ) : null}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="rounded-2xl border border-border/80 bg-white/80 p-4">
        <h2 className="font-medium">Per-question performance</h2>
        <ul className="mt-3 space-y-3">
          {results.questions.map((q) => (
            <li key={q.question_id}>
              <div className="flex justify-between gap-2 text-sm">
                <p className="min-w-0 truncate">
                  Q{q.order}. {q.prompt}
                </p>
                <span className="shrink-0 text-muted-foreground">
                  {Math.round(q.correct_rate * 100)}% correct
                </span>
              </div>
              <div className="mt-1 h-2 overflow-hidden rounded-full bg-muted">
                <div
                  className="h-full rounded-full bg-brand"
                  style={{ width: `${Math.round(q.correct_rate * 100)}%` }}
                />
              </div>
            </li>
          ))}
        </ul>
      </section>
    </div>
  )
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-border/80 bg-white/80 p-4">
      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </p>
      <p className="mt-1 text-2xl font-semibold tracking-tight">{value}</p>
    </div>
  )
}
