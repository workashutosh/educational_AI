import { useCallback, useEffect, useState } from "react"
import { useParams } from "react-router-dom"
import { Camera, Download, Loader2, RefreshCw, Send } from "lucide-react"

import { ErrorText, Field, Loading, PageHeader, Pill, Section, TextArea, TextInput } from "@/components/app/ui"
import { RichAnswer } from "@/components/chat/RichAnswer"
import { Button } from "@/components/ui/button"
import { api, apiUpload, downloadFile, errorMessage, formatDate } from "@/lib/api"
import { HW_STATUS_TONE, useRole } from "@/lib/features"
import { type Homework } from "@/pages/app/HomeworkPage"

type SubFile = { id: number; name: string; url: string }

type Submission = {
  id: number
  student_id: number
  student_name: string
  text_answer: string
  files: SubFile[]
  is_late: boolean
  submitted_at: string
  released: boolean
  ai_status: string
  ai_score: number | null
  ai_feedback: string
  teacher_score: number | null
  teacher_feedback: string
  max_marks: number
  extracted_text?: string
}

type Roster = {
  counts: Record<string, number>
  students: { student_id: number; student_name: string; status: string; submission: Submission | null }[]
}

export function HomeworkDetailPage() {
  const { homeworkId } = useParams()
  const { isStudent } = useRole()
  const [hw, setHw] = useState<(Homework & { my_submission?: Submission | null }) | null>(null)
  const [error, setError] = useState("")

  const load = useCallback(async () => {
    try {
      setHw(await api(`/api/homework/${homeworkId}/`))
    } catch (err) {
      setError(errorMessage(err))
    }
  }, [homeworkId])

  useEffect(() => {
    void load()
  }, [load])

  if (!hw) return error ? <ErrorText>{error}</ErrorText> : <Loading />

  return (
    <div className="w-full max-w-5xl space-y-6">
      <PageHeader
        title={hw.title}
        description={`${hw.bucket_name} · ${hw.max_marks} marks${hw.due_at ? ` · due ${formatDate(hw.due_at, true)}` : ""}${hw.created_by_name ? ` · ${hw.created_by_name}` : ""}`}
        actions={<Pill tone={HW_STATUS_TONE[(isStudent ? hw.my_status : hw.status) as keyof typeof HW_STATUS_TONE] || "gray"}>{isStudent ? hw.my_status : hw.status}</Pill>}
      />
      <ErrorText>{error}</ErrorText>
      <Section title="Instructions">
        {hw.instructions ? <RichAnswer content={hw.instructions} /> : <p className="text-sm text-muted-foreground">No extra instructions.</p>}
        {hw.attachment_url ? (
          <Button variant="outline" size="sm" onClick={() => void downloadFile(hw.attachment_url!, hw.attachment_name)}>
            <Download className="size-3.5" /> {hw.attachment_name || "Worksheet"}
          </Button>
        ) : null}
      </Section>
      {isStudent ? <StudentView hw={hw} onChange={load} /> : <TeacherView hw={hw} onChange={load} />}
    </div>
  )
}

function StudentView({ hw, onChange }: { hw: Homework & { my_submission?: Submission | null }; onChange: () => void }) {
  const sub = hw.my_submission
  const [text, setText] = useState(sub?.text_answer || "")
  const [files, setFiles] = useState<File[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const canSubmit = hw.status === "published" && !sub?.released && !(hw.is_overdue && !hw.allow_late)

  async function submit() {
    setBusy(true)
    setError("")
    const fd = new FormData()
    fd.set("text_answer", text)
    files.forEach((f) => fd.append("files", f))
    try {
      await apiUpload(`/api/homework/${hw.id}/submit/`, fd)
      setFiles([])
      onChange()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      {sub ? (
        <Section title="Your submission" description={`Submitted ${formatDate(sub.submitted_at, true)}${sub.is_late ? " · late" : ""}`}>
          {sub.text_answer ? <p className="whitespace-pre-wrap text-sm">{sub.text_answer}</p> : null}
          <FileList files={sub.files} />
          {sub.released ? (
            <ResultBox score={sub.teacher_score} max={sub.max_marks} feedback={sub.teacher_feedback || sub.ai_feedback} label="Returned by your teacher" />
          ) : sub.ai_score != null ? (
            <ResultBox score={sub.ai_score} max={sub.max_marks} feedback={sub.ai_feedback} label="AI feedback (provisional — your teacher may change it)" />
          ) : (
            <p className="text-sm text-muted-foreground">Waiting for your teacher to review.</p>
          )}
        </Section>
      ) : null}
      {canSubmit ? (
        <Section title={sub ? "Update submission" : "Submit"} description="Type your answer and/or attach photos of your work (JPG, PNG, PDF).">
          <TextArea value={text} onChange={(e) => setText(e.target.value)} placeholder="Your answer…" className="min-h-40" />
          <label className="flex w-fit cursor-pointer items-center gap-2 rounded-lg border border-dashed border-border px-3 py-2 text-sm hover:border-brand">
            <Camera className="size-4" /> {files.length ? `${files.length} file(s) selected` : "Add photos / files"}
            <input
              type="file"
              multiple
              accept="image/*,.pdf,.docx,.txt"
              capture="environment"
              className="hidden"
              onChange={(e) => setFiles(Array.from(e.target.files || []))}
            />
          </label>
          <ErrorText>{error}</ErrorText>
          <Button onClick={() => void submit()} disabled={busy || (!text.trim() && !files.length)}>
            {busy ? <Loader2 className="size-4 animate-spin" /> : <Send className="size-4" />} Submit
          </Button>
        </Section>
      ) : null}
    </>
  )
}

function ResultBox({ score, max, feedback, label }: { score: number | null; max: number; feedback: string; label: string }) {
  return (
    <div className="rounded-xl border border-brand/30 bg-brand-soft/40 p-3 text-sm">
      <p className="text-xs font-medium text-brand">{label}</p>
      <p className="mt-1 text-2xl font-semibold">{score ?? "—"}<span className="text-base text-muted-foreground">/{max}</span></p>
      {feedback ? <p className="mt-2 whitespace-pre-wrap">{feedback}</p> : null}
    </div>
  )
}

function FileList({ files }: { files: SubFile[] }) {
  if (!files.length) return null
  return (
    <div className="flex flex-wrap gap-2">
      {files.map((f) => (
        <Button key={f.id} variant="outline" size="xs" onClick={() => void downloadFile(f.url, f.name)}>
          <Download className="size-3" /> {f.name}
        </Button>
      ))}
    </div>
  )
}

function TeacherView({ hw, onChange }: { hw: Homework; onChange: () => void }) {
  const [roster, setRoster] = useState<Roster | null>(null)
  const [openId, setOpenId] = useState<number | null>(null)
  const [error, setError] = useState("")

  const load = useCallback(async () => {
    try {
      setRoster(await api<Roster>(`/api/homework/${hw.id}/submissions/`))
    } catch (err) {
      setError(errorMessage(err))
    }
  }, [hw.id])

  useEffect(() => {
    void load()
  }, [load])

  // Poll while AI grading is running.
  useEffect(() => {
    if (!roster?.students.some((s) => s.submission?.ai_status === "pending")) return
    const t = window.setInterval(() => void load(), 4000)
    return () => window.clearInterval(t)
  }, [roster, load])

  async function action(path: string) {
    setError("")
    try {
      await api(path, { method: "POST" })
      await load()
      onChange()
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  return (
    <Section
      title="Submissions"
      description={roster ? Object.entries(roster.counts).map(([k, v]) => `${v} ${k}`).join(" · ") : undefined}
      actions={
        <>
          {hw.status === "draft" ? <Button size="sm" onClick={() => void action(`/api/homework/${hw.id}/publish/`)}>Publish</Button> : null}
          {hw.status === "published" ? <Button size="sm" variant="outline" onClick={() => void action(`/api/homework/${hw.id}/close/`)}>Close</Button> : null}
          <Button size="sm" variant="outline" onClick={() => void action(`/api/homework/${hw.id}/release/`)}>Return all graded</Button>
        </>
      }
    >
      <ErrorText>{error}</ErrorText>
      {!roster ? <Loading /> : (
        <ul className="divide-y divide-border/60">
          {roster.students.map((row) => (
            <li key={row.student_id} className="py-2">
              <button type="button" className="flex w-full items-center justify-between gap-2 text-left text-sm" onClick={() => setOpenId(openId === row.student_id ? null : row.student_id)}>
                <span className="font-medium">{row.student_name}</span>
                <span className="flex items-center gap-2">
                  {row.submission?.ai_status === "pending" ? <span className="flex items-center gap-1 text-xs text-muted-foreground"><Loader2 className="size-3 animate-spin" />AI grading</span> : null}
                  {row.submission?.ai_score != null ? <span className="text-xs text-muted-foreground">AI {row.submission.ai_score}</span> : null}
                  {row.submission?.teacher_score != null ? <span className="text-xs font-medium">{row.submission.teacher_score}/{hw.max_marks}</span> : null}
                  {row.submission?.is_late ? <Pill tone="amber">late</Pill> : null}
                  <Pill tone={HW_STATUS_TONE[row.status as keyof typeof HW_STATUS_TONE] || "gray"}>{row.status}</Pill>
                </span>
              </button>
              {openId === row.student_id && row.submission ? (
                <GradeForm sub={row.submission} max={hw.max_marks} onSaved={load} />
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </Section>
  )
}

function GradeForm({ sub, max, onSaved }: { sub: Submission; max: number; onSaved: () => void }) {
  const [score, setScore] = useState(String(sub.teacher_score ?? sub.ai_score ?? ""))
  const [feedback, setFeedback] = useState(sub.teacher_feedback || sub.ai_feedback || "")
  const [error, setError] = useState("")

  async function save(release: boolean) {
    setError("")
    try {
      await api(`/api/homework/submissions/${sub.id}/grade/`, {
        method: "POST",
        body: JSON.stringify({ score: Number(score), feedback, release }),
      })
      onSaved()
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  return (
    <div className="mt-3 grid gap-3 rounded-xl border border-border/70 bg-white p-3 lg:grid-cols-2">
      <div className="space-y-2 text-sm">
        <p className="text-xs text-muted-foreground">Submitted {formatDate(sub.submitted_at, true)}</p>
        {sub.text_answer ? <p className="whitespace-pre-wrap">{sub.text_answer}</p> : null}
        <FileList files={sub.files} />
        {sub.extracted_text ? (
          <details>
            <summary className="cursor-pointer text-xs text-muted-foreground">Text read from attachments</summary>
            <p className="mt-1 max-h-60 overflow-y-auto whitespace-pre-wrap rounded bg-muted p-2 text-xs">{sub.extracted_text}</p>
          </details>
        ) : null}
      </div>
      <div className="space-y-2">
        {sub.ai_status === "done" ? (
          <p className="rounded-lg bg-sky-50 p-2 text-xs text-sky-800">AI suggests {sub.ai_score}/{max}. {sub.ai_feedback}</p>
        ) : sub.ai_status === "failed" ? (
          <p className="text-xs text-amber-700">AI grading failed — grade manually or retry.</p>
        ) : null}
        <Field label={`Score (out of ${max})`}><TextInput type="number" min={0} max={max} step="0.5" value={score} onChange={(e) => setScore(e.target.value)} /></Field>
        <Field label="Feedback"><TextArea value={feedback} onChange={(e) => setFeedback(e.target.value)} /></Field>
        <ErrorText>{error}</ErrorText>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" onClick={() => void save(true)} disabled={score === ""}>Save & return</Button>
          <Button size="sm" variant="outline" onClick={() => void save(false)} disabled={score === ""}>Save</Button>
          <Button size="sm" variant="ghost" onClick={() => void api(`/api/homework/submissions/${sub.id}/regrade-ai/`, { method: "POST" }).then(onSaved)}>
            <RefreshCw className="size-3.5" /> Re-run AI
          </Button>
        </div>
      </div>
    </div>
  )
}
