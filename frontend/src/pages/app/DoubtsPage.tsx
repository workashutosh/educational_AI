import { useCallback, useEffect, useState } from "react"
import { useSearchParams } from "react-router-dom"
import { HelpCircle, Loader2, Send } from "lucide-react"

import {
  BucketSelect,
  EmptyState,
  ErrorText,
  Field,
  Loading,
  PageHeader,
  Pill,
  Section,
  Select,
  TextArea,
} from "@/components/app/ui"
import { RichAnswer } from "@/components/chat/RichAnswer"
import { Button } from "@/components/ui/button"
import { api, errorMessage, formatDate, type Page } from "@/lib/api"
import { useAuth } from "@/lib/auth"
import { useRole } from "@/lib/features"
import { cn } from "@/lib/utils"

export type Doubt = {
  id: number
  bucket: number
  bucket_name: string
  student_name: string
  question: string
  student_note: string
  ai_answer: string
  reason: string
  status: "open" | "answered" | "closed"
  answer: string
  answered_by_name: string
  answered_at: string | null
  published_document: number | null
  created_at: string
}

const REASON_LABEL: Record<string, string> = {
  no_answer: "AI couldn't find it in the notes",
  low_rating: "Marked unhelpful",
  student_request: "Asked a teacher",
}
const STATUS_TONE = { open: "amber", answered: "green", closed: "gray" } as const

export function DoubtsPage() {
  const { isStudent } = useRole()
  const { session } = useAuth()
  const [params, setParams] = useSearchParams()
  const [status, setStatus] = useState(isStudent ? "" : "open")
  const [bucketId, setBucketId] = useState<number | null>(null)
  const [page, setPage] = useState<(Page<Doubt> & { open_count: number }) | null>(null)
  const [error, setError] = useState("")
  const [asking, setAsking] = useState(false)
  const selectedId = Number(params.get("doubt") || 0) || null

  const load = useCallback(async () => {
    const q = new URLSearchParams({ limit: "50" })
    if (status) q.set("status", status)
    if (bucketId) q.set("bucket_id", String(bucketId))
    try {
      setPage(await api(`/api/learning/doubts/?${q}`))
    } catch (err) {
      setError(errorMessage(err))
    }
  }, [status, bucketId])

  useEffect(() => {
    void load()
  }, [load])

  const selected = page?.results.find((d) => d.id === selectedId) || null

  return (
    <div className="w-full space-y-6">
      <PageHeader
        icon={HelpCircle}
        title={isStudent ? "My Doubts" : "Doubts Inbox"}
        description={
          isStudent
            ? "Questions the AI couldn't answer from your notes go to your teacher. Answers show up here."
            : "Student questions the AI couldn't answer well. Your answer can be added to the notes so the AI knows it next time."
        }
        actions={
          isStudent && session?.buckets?.length ? (
            <Button onClick={() => setAsking((a) => !a)}>Ask a teacher</Button>
          ) : null
        }
      />
      <ErrorText>{error}</ErrorText>
      {asking ? <AskTeacherForm onDone={() => { setAsking(false); void load() }} /> : null}

      <div className="flex flex-wrap items-end gap-3">
        <Field label="Status">
          <Select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">All</option>
            <option value="open">Open</option>
            <option value="answered">Answered</option>
            <option value="closed">Closed</option>
          </Select>
        </Field>
        <Field label="AI Bucket">
          <BucketSelect value={bucketId} onChange={setBucketId} allowAll className="min-w-48" />
        </Field>
        {page ? <p className="pb-2 text-sm text-muted-foreground">{page.open_count} open</p> : null}
      </div>

      {!page ? <Loading /> : !page.results.length ? <EmptyState>No doubts here.</EmptyState> : (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,22rem)_minmax(0,1fr)]">
          <ul className="space-y-2">
            {page.results.map((d) => (
              <li key={d.id}>
                <button
                  type="button"
                  onClick={() => setParams({ doubt: String(d.id) })}
                  className={cn(
                    "w-full rounded-xl border bg-white p-3 text-left transition",
                    d.id === selectedId ? "border-brand bg-brand-soft/40" : "border-border/80 hover:border-brand",
                  )}
                >
                  <div className="flex items-center justify-between gap-2">
                    <Pill tone={STATUS_TONE[d.status]}>{d.status}</Pill>
                    <span className="text-xs text-muted-foreground">{formatDate(d.created_at, true)}</span>
                  </div>
                  <p className="mt-1.5 line-clamp-2 text-sm font-medium">{d.question}</p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {d.bucket_name}{!isStudent ? ` · ${d.student_name}` : ""}
                  </p>
                </button>
              </li>
            ))}
          </ul>
          {selected ? <DoubtDetail key={selected.id} doubt={selected} onChange={load} /> : (
            <EmptyState>Select a doubt to see details.</EmptyState>
          )}
        </div>
      )}
    </div>
  )
}

function DoubtDetail({ doubt, onChange }: { doubt: Doubt; onChange: () => void }) {
  const { isStudent } = useRole()
  const [answer, setAnswer] = useState(doubt.answer)
  const [addToNotes, setAddToNotes] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")

  useEffect(() => {
    // Opening marks an answered doubt as seen for the student.
    void api(`/api/learning/doubts/${doubt.id}/`).catch(() => undefined)
  }, [doubt.id])

  async function submit() {
    setBusy(true)
    setError("")
    try {
      await api(`/api/learning/doubts/${doubt.id}/answer/`, {
        method: "POST",
        body: JSON.stringify({ answer, add_to_notes: addToNotes }),
      })
      onChange()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  async function close() {
    await api(`/api/learning/doubts/${doubt.id}/close/`, { method: "POST" })
    onChange()
  }

  return (
    <Section
      title={doubt.question}
      description={`${doubt.bucket_name} · ${REASON_LABEL[doubt.reason] || doubt.reason}${isStudent ? "" : ` · ${doubt.student_name}`}`}
      actions={doubt.status !== "closed" ? <Button size="sm" variant="ghost" onClick={() => void close()}>Close</Button> : null}
    >
      {doubt.student_note ? <p className="rounded-lg bg-muted px-3 py-2 text-sm">“{doubt.student_note}”</p> : null}
      {doubt.ai_answer ? (
        <details className="text-sm">
          <summary className="cursor-pointer text-muted-foreground">AI's answer</summary>
          <div className="mt-2 rounded-lg border border-border/70 p-3"><RichAnswer content={doubt.ai_answer} /></div>
        </details>
      ) : null}
      {doubt.answer ? (
        <div className="rounded-lg border border-brand/30 bg-brand-soft/40 p-3 text-sm">
          <p className="mb-1 text-xs font-medium text-brand">
            {doubt.answered_by_name || "Teacher"} · {formatDate(doubt.answered_at, true)}
            {doubt.published_document ? " · added to notes" : ""}
          </p>
          <RichAnswer content={doubt.answer} />
        </div>
      ) : isStudent ? (
        <p className="text-sm text-muted-foreground">Waiting for your teacher to reply.</p>
      ) : null}

      {!isStudent && doubt.status !== "closed" ? (
        <div className="space-y-2">
          <TextArea value={answer} onChange={(e) => setAnswer(e.target.value)} placeholder="Write the answer (LaTeX supported)…" className="min-h-32" />
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={addToNotes} onChange={(e) => setAddToNotes(e.target.checked)} />
            Add this Q&A to the AI Bucket notes so the AI can answer it next time
          </label>
          <ErrorText>{error}</ErrorText>
          <Button onClick={() => void submit()} disabled={busy || !answer.trim()}>
            {busy ? <Loader2 className="size-4 animate-spin" /> : <Send className="size-4" />}
            {doubt.answer ? "Update answer" : "Send answer"}
          </Button>
        </div>
      ) : null}
    </Section>
  )
}

function AskTeacherForm({ onDone }: { onDone: () => void }) {
  const { session } = useAuth()
  const [bucketId, setBucketId] = useState<number | null>(session?.buckets?.[0]?.id ?? null)
  const [question, setQuestion] = useState("")
  const [note, setNote] = useState("")
  const [error, setError] = useState("")

  async function send() {
    try {
      await api("/api/learning/doubts/", { method: "POST", body: JSON.stringify({ bucket_id: bucketId, question, note }) })
      onDone()
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  return (
    <Section title="Ask a teacher">
      <Field label="AI Bucket"><BucketSelect value={bucketId} onChange={setBucketId} /></Field>
      <Field label="Your question"><TextArea value={question} onChange={(e) => setQuestion(e.target.value)} /></Field>
      <Field label="Anything else? (optional)"><TextArea value={note} onChange={(e) => setNote(e.target.value)} className="min-h-16" /></Field>
      <ErrorText>{error}</ErrorText>
      <Button onClick={() => void send()} disabled={!question.trim() || !bucketId}>Send</Button>
    </Section>
  )
}
