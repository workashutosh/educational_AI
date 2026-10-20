import { useEffect, useState } from "react"
import { Link, useNavigate } from "react-router-dom"
import { FileText, Loader2, Plus, Trash2 } from "lucide-react"

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
  TextInput,
} from "@/components/app/ui"
import { Button } from "@/components/ui/button"
import { api, errorMessage, formatDate } from "@/lib/api"
import { useAuth } from "@/lib/auth"
import { QTYPE_LABEL, useTopics } from "@/lib/features"

export type PaperSummary = {
  id: number
  bucket: number
  bucket_name: string
  title: string
  exam_name: string
  status: string
  total_marks: number
  question_count: number
  duration_minutes: number
  created_at: string
}

type SectionSpec = { title: string; qtype: string; count: number; marks_each: number; instructions: string }

const DEFAULT_SECTIONS: SectionSpec[] = [
  { title: "Section A", qtype: "mcq", count: 10, marks_each: 1, instructions: "Choose the correct option." },
  { title: "Section B", qtype: "brief", count: 5, marks_each: 2, instructions: "Answer in 30–50 words." },
  { title: "Section C", qtype: "long", count: 3, marks_each: 5, instructions: "Answer in detail." },
]

export function PapersPage() {
  const [papers, setPapers] = useState<PaperSummary[] | null>(null)
  const [error, setError] = useState("")
  const [creating, setCreating] = useState(false)

  useEffect(() => {
    api<PaperSummary[]>("/api/question-bank/papers/").then(setPapers).catch((e) => setError(errorMessage(e)))
  }, [])

  return (
    <div className="w-full space-y-6">
      <PageHeader
        icon={FileText}
        title="Question Papers"
        description="Exam-style papers with sections, marks, and a difficulty mix — exported as PDF/Word with an answer key."
        actions={
          <Button onClick={() => setCreating((c) => !c)}>
            <Plus className="size-4" /> New paper
          </Button>
        }
      />
      <ErrorText>{error}</ErrorText>
      {creating ? <CreatePaperForm /> : null}
      {!papers ? <Loading /> : null}
      {papers && !papers.length && !creating ? (
        <EmptyState>No papers yet. Build one from your question bank — AI fills any gaps.</EmptyState>
      ) : null}
      <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {papers?.map((p) => (
          <li key={p.id}>
            <Link to={`/app/papers/${p.id}`} className="block rounded-2xl border border-border/80 bg-white/80 p-4 transition hover:border-brand hover:bg-brand-soft/40">
              <div className="flex items-start justify-between gap-2">
                <p className="font-medium leading-snug">{p.title}</p>
                <Pill tone={p.status === "final" ? "green" : "sky"}>{p.status}</Pill>
              </div>
              <p className="mt-1 text-xs text-muted-foreground">
                {p.bucket_name} · {p.question_count} Q · {p.total_marks} marks · {p.duration_minutes} min
              </p>
              <p className="mt-2 text-xs text-muted-foreground">{formatDate(p.created_at)}</p>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  )
}

function CreatePaperForm() {
  const { session } = useAuth()
  const navigate = useNavigate()
  const [bucketId, setBucketId] = useState<number | null>(session?.buckets?.[0]?.id ?? null)
  const { topics } = useTopics(bucketId)
  const [form, setForm] = useState({
    title: "",
    exam_name: "",
    class_label: "",
    duration_minutes: 180,
    instructions: "All questions are compulsory.\nMarks are shown against each question.",
    source_mode: "bank_then_ai",
  })
  const [mix, setMix] = useState({ easy: 30, medium: 50, hard: 20 })
  const [topicIds, setTopicIds] = useState<number[]>([])
  const [sections, setSections] = useState<SectionSpec[]>(DEFAULT_SECTIONS)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")

  const total = sections.reduce((s, x) => s + x.count * x.marks_each, 0)
  const update = (i: number, patch: Partial<SectionSpec>) =>
    setSections((rows) => rows.map((r, j) => (j === i ? { ...r, ...patch } : r)))

  async function create() {
    setBusy(true)
    setError("")
    try {
      const paper = await api<{ id: number }>("/api/question-bank/papers/", {
        method: "POST",
        body: JSON.stringify({ ...form, bucket_id: bucketId, difficulty_mix: mix, topic_ids: topicIds, sections }),
      })
      navigate(`/app/papers/${paper.id}`)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Section title="New question paper" description={`Blueprint total: ${total} marks`}>
      <div className="grid gap-3 sm:grid-cols-3">
        <Field label="AI Bucket"><BucketSelect value={bucketId} onChange={setBucketId} /></Field>
        <Field label="Title"><TextInput value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} placeholder="Half-yearly Examination — Physics" /></Field>
        <Field label="Exam / board"><TextInput value={form.exam_name} onChange={(e) => setForm({ ...form, exam_name: e.target.value })} placeholder="CBSE Class XII" /></Field>
        <Field label="Class label"><TextInput value={form.class_label} onChange={(e) => setForm({ ...form, class_label: e.target.value })} placeholder="XII-A" /></Field>
        <Field label="Duration (min)"><TextInput type="number" min={10} value={form.duration_minutes} onChange={(e) => setForm({ ...form, duration_minutes: Number(e.target.value) })} /></Field>
        <Field label="Question source">
          <Select value={form.source_mode} onChange={(e) => setForm({ ...form, source_mode: e.target.value })}>
            <option value="bank_then_ai">Bank first, AI fills gaps</option>
            <option value="bank_only">Only the question bank</option>
            <option value="ai_only">Fresh AI questions</option>
          </Select>
        </Field>
      </div>
      <Field label="Difficulty mix % (easy / medium / hard)">
        <div className="flex max-w-xs gap-1">
          {(Object.keys(mix) as (keyof typeof mix)[]).map((k) => (
            <TextInput key={k} type="number" min={0} max={100} value={mix[k]} onChange={(e) => setMix({ ...mix, [k]: Number(e.target.value) })} />
          ))}
        </div>
      </Field>
      {topics.length ? (
        <Field label="Topics (none = whole syllabus)">
          <div className="flex flex-wrap gap-1.5">
            {topics.map((t) => (
              <button
                key={t.id}
                type="button"
                onClick={() => setTopicIds((ids) => (ids.includes(t.id) ? ids.filter((i) => i !== t.id) : [...ids, t.id]))}
                className={`rounded-full border px-2.5 py-1 text-xs ${topicIds.includes(t.id) ? "border-brand bg-brand-soft text-brand" : "border-border bg-white"}`}
              >
                {t.name}
              </button>
            ))}
          </div>
        </Field>
      ) : null}
      <Field label="General instructions">
        <TextArea value={form.instructions} onChange={(e) => setForm({ ...form, instructions: e.target.value })} />
      </Field>

      <div className="space-y-2">
        <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Sections</p>
        {sections.map((s, i) => (
          <div key={i} className="grid items-end gap-2 rounded-xl border border-border/70 bg-white p-3 sm:grid-cols-[1fr_9rem_5rem_5rem_auto]">
            <Field label="Title"><TextInput value={s.title} onChange={(e) => update(i, { title: e.target.value })} /></Field>
            <Field label="Type">
              <Select value={s.qtype} onChange={(e) => update(i, { qtype: e.target.value })}>
                {Object.entries(QTYPE_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </Select>
            </Field>
            <Field label="Count"><TextInput type="number" min={1} value={s.count} onChange={(e) => update(i, { count: Number(e.target.value) })} /></Field>
            <Field label="Marks each"><TextInput type="number" min={1} value={s.marks_each} onChange={(e) => update(i, { marks_each: Number(e.target.value) })} /></Field>
            <Button variant="ghost" size="icon" onClick={() => setSections((rows) => rows.filter((_, j) => j !== i))} title="Remove section">
              <Trash2 className="size-4" />
            </Button>
            <div className="sm:col-span-5">
              <TextInput value={s.instructions} placeholder="Section instructions" onChange={(e) => update(i, { instructions: e.target.value })} />
            </div>
          </div>
        ))}
        <Button
          variant="outline"
          size="sm"
          onClick={() => setSections((rows) => [...rows, { title: `Section ${String.fromCharCode(65 + rows.length)}`, qtype: "brief", count: 3, marks_each: 3, instructions: "" }])}
        >
          <Plus className="size-3.5" /> Add section
        </Button>
      </div>
      <ErrorText>{error}</ErrorText>
      <Button onClick={() => void create()} disabled={busy || !form.title.trim() || !bucketId || !sections.length}>
        {busy ? <Loader2 className="size-4 animate-spin" /> : null}
        {busy ? "Building paper… (AI may take a minute)" : "Build paper"}
      </Button>
    </Section>
  )
}
