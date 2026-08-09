import { useEffect, useMemo, useState, type FormEvent } from "react"
import { Link, Navigate, useNavigate } from "react-router-dom"
import { ArrowLeft, Loader2, Trash2 } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { api, type MemberRow } from "@/lib/api"
import { useAuth } from "@/lib/auth"
import { cn } from "@/lib/utils"

type QType = "mcq" | "multi" | "brief"

type Question = {
  id: number
  order: number
  qtype: QType
  prompt: string
  options: string[]
  marks: number
  correct_indices?: number[]
  model_answer?: string
}

type SourceMode = "notes" | "question_papers" | "both"

type GeneratedTest = {
  id: number
  title: string
  status: string
  topic_prompt?: string
  duration_minutes: number
  max_score: number
  question_count: number
  count_mcq?: number
  count_multi?: number
  count_brief?: number
  marks_mcq?: number
  marks_multi?: number
  marks_brief?: number
  results_mode?: "immediate" | "after_review"
  source_mode?: SourceMode
  questions: Question[]
  assignments: { student_id: number; username: string; full_name: string }[]
}

type Step = 1 | 2 | 3

export function MockTestCreatePage() {
  const { session } = useAuth()
  const navigate = useNavigate()
  const isStudent = session?.membership?.role === "student"
  const buckets = session?.buckets || []

  const [step, setStep] = useState<Step>(1)
  const [bucketId, setBucketId] = useState(String(buckets[0]?.id || ""))
  const [title, setTitle] = useState("")
  const [prompt, setPrompt] = useState("")
  const [duration, setDuration] = useState(60)
  const [countMcq, setCountMcq] = useState(8)
  const [countMulti, setCountMulti] = useState(2)
  const [countBrief, setCountBrief] = useState(1)
  const [marksMcq, setMarksMcq] = useState(1)
  const [marksMulti, setMarksMulti] = useState(2)
  const [marksBrief, setMarksBrief] = useState(5)
  const [resultsMode, setResultsMode] = useState<"immediate" | "after_review">(
    "after_review",
  )
  const [sourceMode, setSourceMode] = useState<SourceMode>("notes")

  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [test, setTest] = useState<GeneratedTest | null>(null)
  const [editingId, setEditingId] = useState<number | null>(null)

  const [students, setStudents] = useState<MemberRow[]>([])
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [assignBusy, setAssignBusy] = useState(false)

  const totalQuestions = countMcq + countMulti + countBrief
  const blueprintMax = useMemo(
    () => countMcq * marksMcq + countMulti * marksMulti + countBrief * marksBrief,
    [countMcq, countMulti, countBrief, marksMcq, marksMulti, marksBrief],
  )

  useEffect(() => {
    if (!session?.can_create_students && !session?.can_manage) return
    void api<MemberRow[]>("/api/admin/members/?role=student")
      .then(setStudents)
      .catch(() => setStudents([]))
  }, [session?.can_create_students, session?.can_manage])

  if (isStudent) return <Navigate to="/app/mock-tests" replace />

  function blueprintBody() {
    return {
      title: title.trim(),
      topic_prompt: prompt.trim(),
      duration_minutes: duration,
      count_mcq: countMcq,
      count_multi: countMulti,
      count_brief: countBrief,
      marks_mcq: marksMcq,
      marks_multi: marksMulti,
      marks_brief: marksBrief,
      results_mode: resultsMode,
      source_mode: sourceMode,
    }
  }

  function syncFormFromTest(t: GeneratedTest) {
    setTitle(t.title || "")
    if (t.topic_prompt) setPrompt(t.topic_prompt)
    setDuration(t.duration_minutes || 60)
    if (t.count_mcq != null) setCountMcq(t.count_mcq)
    if (t.count_multi != null) setCountMulti(t.count_multi)
    if (t.count_brief != null) setCountBrief(t.count_brief)
    if (t.marks_mcq != null) setMarksMcq(t.marks_mcq)
    if (t.marks_multi != null) setMarksMulti(t.marks_multi)
    if (t.marks_brief != null) setMarksBrief(t.marks_brief)
    if (t.results_mode) setResultsMode(t.results_mode)
    if (t.source_mode) setSourceMode(t.source_mode)
  }

  async function generate(e: FormEvent) {
    e.preventDefault()
    if (!bucketId || !prompt.trim() || totalQuestions < 1) return
    setBusy(true)
    setError("")
    try {
      // Re-using an existing draft (Back from preview) → regenerate in place
      if (test) {
        const res = await api<GeneratedTest>(`/api/mock-tests/${test.id}/regenerate/`, {
          method: "POST",
          body: JSON.stringify(blueprintBody()),
        })
        setTest(res)
        syncFormFromTest(res)
      } else {
        const res = await api<GeneratedTest>("/api/mock-tests/", {
          method: "POST",
          body: JSON.stringify({
            bucket_id: Number(bucketId),
            prompt: prompt.trim(),
            ...blueprintBody(),
          }),
        })
        setTest(res)
        syncFormFromTest(res)
      }
      setEditingId(null)
      setStep(2)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Generation failed")
    } finally {
      setBusy(false)
    }
  }

  async function saveSettings(opts?: { regenerate?: boolean }) {
    if (!test) return
    setBusy(true)
    setError("")
    try {
      if (opts?.regenerate) {
        const res = await api<GeneratedTest>(`/api/mock-tests/${test.id}/regenerate/`, {
          method: "POST",
          body: JSON.stringify(blueprintBody()),
        })
        setTest(res)
        syncFormFromTest(res)
        setEditingId(null)
      } else {
        const res = await api<GeneratedTest>(`/api/mock-tests/${test.id}/`, {
          method: "PATCH",
          body: JSON.stringify(blueprintBody()),
        })
        setTest(res)
        syncFormFromTest(res)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not update test settings")
    } finally {
      setBusy(false)
    }
  }

  async function regenerate() {
    await saveSettings({ regenerate: true })
  }

  async function saveQuestion(q: Question) {
    if (!test) return
    setBusy(true)
    setError("")
    try {
      await api<Question>(`/api/mock-tests/${test.id}/questions/${q.id}/`, {
        method: "PATCH",
        body: JSON.stringify({
          prompt: q.prompt,
          options: q.options,
          correct_indices: q.correct_indices || [],
          model_answer: q.model_answer || "",
          marks: q.marks,
        }),
      })
      const detail = await api<GeneratedTest>(`/api/mock-tests/${test.id}/`)
      setTest(detail)
      setEditingId(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save question")
    } finally {
      setBusy(false)
    }
  }

  async function removeQuestion(qid: number) {
    if (!test) return
    setBusy(true)
    setError("")
    try {
      await api(`/api/mock-tests/${test.id}/questions/${qid}/`, { method: "DELETE" })
      const detail = await api<GeneratedTest>(`/api/mock-tests/${test.id}/`)
      setTest(detail)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not remove question")
    } finally {
      setBusy(false)
    }
  }

  function toggleStudent(id: number) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  async function assignAndPublish() {
    if (!test) return
    if (!selected.size) {
      setError("Select at least one student.")
      return
    }
    setAssignBusy(true)
    setError("")
    try {
      // publish=true so students immediately see the test on My Tests
      await api(`/api/mock-tests/${test.id}/assign/`, {
        method: "POST",
        body: JSON.stringify({ student_ids: [...selected], publish: true }),
      })
      navigate(`/app/mock-tests/${test.id}`)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Assign/publish failed")
    } finally {
      setAssignBusy(false)
    }
  }

  return (
    <div className="w-full space-y-6">
      <div>
        <Link
          to="/app/mock-tests"
          className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="size-4" />
          Mock Tests
        </Link>
        <h1 className="mt-2 font-display text-3xl tracking-tight">New mock test</h1>
        <p className="mt-1 text-muted-foreground">
          Configure blueprint, generate &amp; edit questions, then assign and publish.
        </p>
      </div>

      <ol className="flex flex-wrap gap-2 text-sm">
        {(
          [
            [1, "Basics & blueprint"],
            [2, "Preview & edit"],
            [3, "Assign & publish"],
          ] as const
        ).map(([n, label]) => (
          <li
            key={n}
            className={cn(
              "rounded-full px-3 py-1",
              step === n
                ? "bg-brand text-white"
                : step > n
                  ? "bg-brand-soft text-brand"
                  : "bg-muted text-muted-foreground",
            )}
          >
            {n}. {label}
          </li>
        ))}
      </ol>

      {error ? <p className="text-sm text-destructive">{error}</p> : null}

      {step === 1 ? (
        <form onSubmit={generate} className="space-y-5">
          <div className="grid gap-5 xl:grid-cols-2">
            <section className="space-y-4 rounded-2xl border border-border/80 bg-white/80 p-5">
              <h2 className="text-sm font-medium">Basics</h2>
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="space-y-1.5 sm:col-span-2">
                  <Label htmlFor="mt-title">Title (optional — AI can suggest)</Label>
                  <Input
                    id="mt-title"
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    placeholder="e.g. Calculus mid-term"
                    disabled={busy}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="mt-bucket">AI Bucket</Label>
                  <select
                    id="mt-bucket"
                    value={bucketId}
                    onChange={(e) => setBucketId(e.target.value)}
                    disabled={busy}
                    className="flex h-9 w-full rounded-lg border border-input bg-transparent px-2.5 text-sm"
                    required
                  >
                    {buckets.map((b) => (
                      <option key={b.id} value={b.id}>
                        {b.name}
                        {b.grade_level ? ` · ${b.grade_level}` : ""}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="mt-duration">Duration (minutes)</Label>
                  <Input
                    id="mt-duration"
                    type="number"
                    min={5}
                    max={300}
                    value={duration}
                    onChange={(e) => setDuration(Number(e.target.value) || 60)}
                    disabled={busy}
                    required
                  />
                </div>
                <div className="space-y-1.5 sm:col-span-2">
                  <Label htmlFor="mt-prompt">Topic / instructions</Label>
                  <textarea
                    id="mt-prompt"
                    value={prompt}
                    onChange={(e) => setPrompt(e.target.value)}
                    disabled={busy}
                    required
                    rows={5}
                    placeholder="e.g. Calculus chapter 2 — definite integrals, Class 12 level"
                    className="flex min-h-[8rem] w-full rounded-lg border border-input bg-transparent px-2.5 py-2 text-sm"
                  />
                </div>
              </div>
            </section>

            <section className="space-y-4 rounded-2xl border border-border/80 bg-white/80 p-5">
              <h2 className="text-sm font-medium">Question blueprint</h2>
              <div className="grid gap-3">
                <BlueprintRow
                  label="Single MCQ"
                  hint="4 options, one correct"
                  count={countMcq}
                  marks={marksMcq}
                  onCount={setCountMcq}
                  onMarks={setMarksMcq}
                  disabled={busy}
                />
                <BlueprintRow
                  label="Multi-select"
                  hint="4 options, 2+ correct — full marks only if exact set"
                  count={countMulti}
                  marks={marksMulti}
                  onCount={setCountMulti}
                  onMarks={setMarksMulti}
                  disabled={busy}
                />
                <BlueprintRow
                  label="Brief / short answer"
                  hint="AI suggests score; you confirm after submit"
                  count={countBrief}
                  marks={marksBrief}
                  onCount={setCountBrief}
                  onMarks={setMarksBrief}
                  disabled={busy}
                />
              </div>
              <div className="space-y-2 rounded-xl border border-border/60 px-3 py-3">
                <p className="text-sm font-medium">Generate from</p>
                {(
                  [
                    [
                      "notes",
                      "Teaching notes",
                      "Use indexed notes in this AI Bucket.",
                    ],
                    [
                      "question_papers",
                      "Previous year papers",
                      "Match style & difficulty of past exam papers (upload under Question papers).",
                    ],
                    [
                      "both",
                      "Notes + previous year papers",
                      "Exam-style wording grounded in your notes.",
                    ],
                  ] as const
                ).map(([value, label, hint]) => (
                  <label
                    key={value}
                    className="flex cursor-pointer items-start gap-2 text-sm"
                  >
                    <input
                      type="radio"
                      name="source-mode"
                      checked={sourceMode === value}
                      onChange={() => setSourceMode(value)}
                      disabled={busy}
                      className="mt-1"
                    />
                    <span>
                      <span className="font-medium">{label}</span>
                      <span className="block text-xs text-muted-foreground">{hint}</span>
                    </span>
                  </label>
                ))}
              </div>
              <div className="space-y-2 rounded-xl border border-border/60 px-3 py-3">
                <p className="text-sm font-medium">When students see results</p>
                <label className="flex cursor-pointer items-start gap-2 text-sm">
                  <input
                    type="radio"
                    name="results-mode"
                    checked={resultsMode === "after_review"}
                    onChange={() => setResultsMode("after_review")}
                    disabled={busy}
                    className="mt-1"
                  />
                  <span>
                    <span className="font-medium">Teacher reviews first</span>
                    <span className="block text-xs text-muted-foreground">
                      You grade submissions, then release results to each student.
                    </span>
                  </span>
                </label>
                <label className="flex cursor-pointer items-start gap-2 text-sm">
                  <input
                    type="radio"
                    name="results-mode"
                    checked={resultsMode === "immediate"}
                    onChange={() => setResultsMode("immediate")}
                    disabled={busy}
                    className="mt-1"
                  />
                  <span>
                    <span className="font-medium">Show immediately after submit</span>
                    <span className="block text-xs text-muted-foreground">
                      Students see score and answer review as soon as they submit.
                    </span>
                  </span>
                </label>
              </div>
              <p className="text-sm text-muted-foreground">
                Total <span className="font-medium text-foreground">{totalQuestions}</span>{" "}
                questions · Max score{" "}
                <span className="font-medium text-foreground">{blueprintMax}</span> ·{" "}
                {duration} min
              </p>
              <Button
                type="submit"
                disabled={busy || !bucketId || !prompt.trim() || totalQuestions < 1}
              >
                {busy ? (
                  <>
                    <Loader2 className="size-4 animate-spin" data-icon="inline-start" />
                    Generating…
                  </>
                ) : test ? (
                  "Regenerate with these settings"
                ) : (
                  "Generate questions"
                )}
              </Button>
            </section>
          </div>
        </form>
      ) : null}

      {step === 2 && test ? (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <h2 className="font-medium">{test.title}</h2>
              <p className="text-xs text-muted-foreground">
                {test.question_count} questions · max {test.max_score} ·{" "}
                {test.duration_minutes} min
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button type="button" variant="outline" disabled={busy} onClick={() => setStep(1)}>
                Edit blueprint
              </Button>
              <Button
                type="button"
                disabled={busy || !test.questions.length}
                onClick={() => setStep(3)}
              >
                Continue to assign
              </Button>
            </div>
          </div>

          <section className="space-y-4 rounded-2xl border border-border/80 bg-white/80 p-5">
            <div className="flex flex-wrap items-end justify-between gap-2">
              <div>
                <h3 className="text-sm font-medium">Timing &amp; blueprint</h3>
                <p className="text-xs text-muted-foreground">
                  Change duration anytime. Change counts/marks, then regenerate to rebuild
                  questions.
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button
                  type="button"
                  variant="outline"
                  disabled={busy}
                  onClick={() => void saveSettings()}
                >
                  Save timing / settings
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  disabled={busy || totalQuestions < 1}
                  onClick={() => void regenerate()}
                >
                  {busy ? (
                    <Loader2 className="size-4 animate-spin" />
                  ) : (
                    "Apply counts & regenerate"
                  )}
                </Button>
              </div>
            </div>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <div className="space-y-1.5 sm:col-span-2">
                <Label htmlFor="mt2-title">Title</Label>
                <Input
                  id="mt2-title"
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  disabled={busy}
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="mt2-duration">Duration (minutes)</Label>
                <Input
                  id="mt2-duration"
                  type="number"
                  min={5}
                  max={300}
                  value={duration}
                  onChange={(e) => setDuration(Number(e.target.value) || 60)}
                  disabled={busy}
                />
              </div>
              <div className="space-y-1.5">
                <Label>Results</Label>
                <select
                  value={resultsMode}
                  onChange={(e) =>
                    setResultsMode(e.target.value as "immediate" | "after_review")
                  }
                  disabled={busy}
                  className="flex h-9 w-full rounded-lg border border-input bg-transparent px-2.5 text-sm"
                >
                  <option value="after_review">Teacher reviews first</option>
                  <option value="immediate">Show immediately</option>
                </select>
              </div>
            </div>
            <div className="grid gap-3">
              <BlueprintRow
                label="Single MCQ"
                hint="Count = how many questions of this type"
                count={countMcq}
                marks={marksMcq}
                onCount={setCountMcq}
                onMarks={setMarksMcq}
                disabled={busy}
              />
              <BlueprintRow
                label="Multi-select"
                hint="Full marks only if exact option set"
                count={countMulti}
                marks={marksMulti}
                onCount={setCountMulti}
                onMarks={setMarksMulti}
                disabled={busy}
              />
              <BlueprintRow
                label="Brief / short answer"
                hint="AI suggests; you confirm after submit"
                count={countBrief}
                marks={marksBrief}
                onCount={setCountBrief}
                onMarks={setMarksBrief}
                disabled={busy}
              />
            </div>
            <p className="text-sm text-muted-foreground">
              Blueprint: {totalQuestions} questions · max {blueprintMax} · {duration} min
            </p>
          </section>

          <ul className="grid gap-3 lg:grid-cols-2">
            {test.questions.map((q) => (
              <li
                key={q.id}
                className="rounded-2xl border border-border/80 bg-white/80 p-4"
              >
                {editingId === q.id ? (
                  <QuestionEditor
                    question={q}
                    busy={busy}
                    onCancel={() => setEditingId(null)}
                    onSave={(next) => void saveQuestion(next)}
                  />
                ) : (
                  <QuestionPreview
                    question={q}
                    onEdit={() => setEditingId(q.id)}
                    onRemove={() => void removeQuestion(q.id)}
                    busy={busy}
                  />
                )}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {step === 3 && test ? (
        <div className="grid gap-5 xl:grid-cols-[1fr_20rem]">
          <section className="space-y-4 rounded-2xl border border-border/80 bg-white/80 p-5">
            <div>
              <h2 className="font-medium">Assign students</h2>
              <p className="text-sm text-muted-foreground">
                {test.title} · {test.question_count} Q · {test.duration_minutes} min · max{" "}
                {test.max_score}
              </p>
            </div>
            {!students.length ? (
              <p className="text-sm text-muted-foreground">
                No students yet. Create student logins under Students first.
              </p>
            ) : (
              <ul className="grid max-h-[28rem] gap-1 overflow-y-auto sm:grid-cols-2 lg:grid-cols-3">
                {students.map((s) => (
                  <li key={s.id}>
                    <label className="flex cursor-pointer items-center gap-2 rounded-lg border border-border/60 px-3 py-2 text-sm hover:bg-muted/60">
                      <input
                        type="checkbox"
                        checked={selected.has(s.id)}
                        onChange={() => toggleStudent(s.id)}
                        disabled={assignBusy}
                      />
                      <span className="min-w-0 truncate">
                        {s.full_name || s.username}{" "}
                        <span className="text-muted-foreground">@{s.username}</span>
                      </span>
                    </label>
                  </li>
                ))}
              </ul>
            )}
          </section>
          <aside className="space-y-3 rounded-2xl border border-border/80 bg-white/80 p-5 xl:sticky xl:top-4 xl:self-start">
            <p className="text-sm text-muted-foreground">
              {selected.size} student{selected.size === 1 ? "" : "s"} selected
            </p>
            <p className="text-xs text-muted-foreground">
              This publishes the test. Assigned students will see it under My Tests right away.
            </p>
            <Button
              type="button"
              className="w-full"
              disabled={assignBusy || !selected.size}
              onClick={() => void assignAndPublish()}
            >
              {assignBusy ? (
                <>
                  <Loader2 className="size-4 animate-spin" data-icon="inline-start" />
                  Publishing…
                </>
              ) : (
                "Assign & publish"
              )}
            </Button>
            <Button
              type="button"
              variant="ghost"
              className="w-full"
              onClick={() => setStep(2)}
              disabled={assignBusy}
            >
              Back to preview
            </Button>
          </aside>
        </div>
      ) : null}
    </div>
  )
}

function BlueprintRow({
  label,
  hint,
  count,
  marks,
  onCount,
  onMarks,
  disabled,
}: {
  label: string
  hint: string
  count: number
  marks: number
  onCount: (n: number) => void
  onMarks: (n: number) => void
  disabled?: boolean
}) {
  return (
    <div className="grid gap-2 rounded-xl border border-border/60 px-3 py-3 sm:grid-cols-[1fr_6rem_6rem]">
      <div>
        <p className="text-sm font-medium">{label}</p>
        <p className="text-xs text-muted-foreground">{hint}</p>
      </div>
      <div className="space-y-1">
        <Label className="text-xs">Count</Label>
        <Input
          type="number"
          min={0}
          max={40}
          value={count}
          onChange={(e) => onCount(Math.max(0, Number(e.target.value) || 0))}
          disabled={disabled}
        />
      </div>
      <div className="space-y-1">
        <Label className="text-xs">Marks each</Label>
        <Input
          type="number"
          min={1}
          max={100}
          value={marks}
          onChange={(e) => onMarks(Math.max(1, Number(e.target.value) || 1))}
          disabled={disabled}
        />
      </div>
    </div>
  )
}

function typeLabel(t: QType) {
  if (t === "multi") return "Multi-select"
  if (t === "brief") return "Brief"
  return "MCQ"
}

function QuestionPreview({
  question: q,
  onEdit,
  onRemove,
  busy,
}: {
  question: Question
  onEdit: () => void
  onRemove: () => void
  busy: boolean
}) {
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <p className="text-sm font-medium">
          Q{q.order}{" "}
          <span className="rounded bg-muted px-1.5 py-0.5 text-[11px] font-normal text-muted-foreground">
            {typeLabel(q.qtype)} · {q.marks} mark{q.marks === 1 ? "" : "s"}
          </span>
        </p>
        <div className="flex gap-1">
          <Button type="button" size="sm" variant="outline" onClick={onEdit} disabled={busy}>
            Edit
          </Button>
          <Button type="button" size="sm" variant="ghost" onClick={onRemove} disabled={busy}>
            <Trash2 className="size-3.5" />
          </Button>
        </div>
      </div>
      <p className="text-sm whitespace-pre-wrap">{q.prompt}</p>
      {q.qtype !== "brief" ? (
        <ul className="space-y-1 text-sm">
          {q.options.map((opt, i) => {
            const ok = (q.correct_indices || []).includes(i)
            return (
              <li
                key={i}
                className={cn(
                  "rounded-lg px-2 py-1",
                  ok ? "bg-brand-soft text-brand" : "text-muted-foreground",
                )}
              >
                {String.fromCharCode(65 + i)}. {opt}
              </li>
            )
          })}
        </ul>
      ) : (
        <p className="text-xs text-muted-foreground">
          Model answer: {q.model_answer || "—"}
        </p>
      )}
    </div>
  )
}

function QuestionEditor({
  question,
  busy,
  onCancel,
  onSave,
}: {
  question: Question
  busy: boolean
  onCancel: () => void
  onSave: (q: Question) => void
}) {
  const [q, setQ] = useState(question)

  function toggleCorrect(i: number) {
    if (q.qtype === "mcq") {
      setQ({ ...q, correct_indices: [i] })
      return
    }
    const set = new Set(q.correct_indices || [])
    if (set.has(i)) set.delete(i)
    else set.add(i)
    setQ({ ...q, correct_indices: [...set].sort((a, b) => a - b) })
  }

  function addOption() {
    if (q.options.length >= 8) return
    setQ({ ...q, options: [...q.options, ""] })
  }

  function removeOption(i: number) {
    if (q.options.length <= 2) return
    const options = q.options.filter((_, idx) => idx !== i)
    const correct_indices = (q.correct_indices || [])
      .filter((idx) => idx !== i)
      .map((idx) => (idx > i ? idx - 1 : idx))
    setQ({
      ...q,
      options,
      correct_indices:
        q.qtype === "mcq"
          ? correct_indices.length
            ? [correct_indices[0]]
            : []
          : correct_indices,
    })
  }

  const canSave =
    !!q.prompt.trim() &&
    (q.qtype === "brief" ||
      (q.options.filter((o) => o.trim()).length >= 2 &&
        (q.correct_indices || []).length >= 1 &&
        (q.qtype !== "multi" || (q.correct_indices || []).length >= 2)))

  return (
    <div className="space-y-3">
      <div className="space-y-1.5">
        <Label>Prompt</Label>
        <textarea
          value={q.prompt}
          onChange={(e) => setQ({ ...q, prompt: e.target.value })}
          rows={3}
          className="flex w-full rounded-lg border border-input bg-transparent px-2.5 py-2 text-sm"
          disabled={busy}
        />
      </div>
      <div className="w-28 space-y-1.5">
        <Label>Marks</Label>
        <Input
          type="number"
          min={1}
          value={q.marks}
          onChange={(e) => setQ({ ...q, marks: Math.max(1, Number(e.target.value) || 1) })}
          disabled={busy}
        />
      </div>
      {q.qtype !== "brief" ? (
        <div className="space-y-2">
          <div className="flex items-center justify-between gap-2">
            <Label>Options (letter = correct)</Label>
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={busy || q.options.length >= 8}
              onClick={addOption}
            >
              Add option
            </Button>
          </div>
          {q.options.map((opt, i) => (
            <div key={i} className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => toggleCorrect(i)}
                className={cn(
                  "size-8 shrink-0 rounded-lg border text-xs font-medium",
                  (q.correct_indices || []).includes(i)
                    ? "border-brand bg-brand-soft text-brand"
                    : "border-border",
                )}
              >
                {String.fromCharCode(65 + i)}
              </button>
              <Input
                value={opt}
                onChange={(e) => {
                  const options = [...q.options]
                  options[i] = e.target.value
                  setQ({ ...q, options })
                }}
                disabled={busy}
              />
              <Button
                type="button"
                size="sm"
                variant="ghost"
                disabled={busy || q.options.length <= 2}
                onClick={() => removeOption(i)}
                aria-label="Remove option"
              >
                <Trash2 className="size-3.5" />
              </Button>
            </div>
          ))}
          <p className="text-[11px] text-muted-foreground">
            {q.qtype === "mcq"
              ? "Pick exactly one correct option."
              : "Pick at least two correct options."}{" "}
            2–8 options.
          </p>
        </div>
      ) : (
        <div className="space-y-1.5">
          <Label>Model answer</Label>
          <textarea
            value={q.model_answer || ""}
            onChange={(e) => setQ({ ...q, model_answer: e.target.value })}
            rows={3}
            className="flex w-full rounded-lg border border-input bg-transparent px-2.5 py-2 text-sm"
            disabled={busy}
          />
        </div>
      )}
      <div className="flex gap-2">
        <Button type="button" variant="outline" onClick={onCancel} disabled={busy}>
          Cancel
        </Button>
        <Button type="button" onClick={() => onSave(q)} disabled={busy || !canSave}>
          Save
        </Button>
      </div>
    </div>
  )
}
