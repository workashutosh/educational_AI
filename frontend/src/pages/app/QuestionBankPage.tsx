import { useCallback, useEffect, useState } from "react"
import { useNavigate } from "react-router-dom"
import { Archive, Database, FileUp, Loader2, Plus, RefreshCw, Sparkles, Wand2 } from "lucide-react"

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
import { api, errorMessage, type DocumentRow, type Page } from "@/lib/api"
import { useAuth } from "@/lib/auth"
import { QTYPE_LABEL, useTopics, type Topic } from "@/lib/features"

export type BankItem = {
  id: number
  bucket: number
  topic: number | null
  topic_name: string | null
  qtype: string
  prompt: string
  options: string[]
  correct_indices: number[]
  answer: string
  explanation: string
  marks: number
  difficulty: string
  source: string
  source_year: number | null
  times_used: number
  is_archived: boolean
}

type ImportJob = {
  id: number
  document_filename: string
  status: string
  created_count: number
  skipped_duplicates: number
  error_message: string
}

const SOURCE_LABEL: Record<string, string> = {
  manual: "Teacher",
  ai_generated: "AI",
  mock_test: "Mock test",
  past_paper: "Past paper",
  micro_quiz: "Quick check",
}

const DIFF_TONE = { easy: "green", medium: "sky", hard: "amber" } as const

export function QuestionBankPage() {
  const { session } = useAuth()
  const navigate = useNavigate()
  const [bucketId, setBucketId] = useState<number | null>(session?.buckets?.[0]?.id ?? null)
  const { topics, reload: reloadTopics } = useTopics(bucketId)
  const [filters, setFilters] = useState({ topic_id: "", qtype: "", difficulty: "", source: "", q: "" })
  const [page, setPage] = useState<Page<BankItem> | null>(null)
  const [offset, setOffset] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")
  const [panel, setPanel] = useState<"" | "add" | "generate" | "import" | "build">("")
  const [notice, setNotice] = useState("")
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    if (!bucketId) return
    setLoading(true)
    setError("")
    const params = new URLSearchParams({ bucket_id: String(bucketId), limit: "25", offset: String(offset) })
    Object.entries(filters).forEach(([k, v]) => v && params.set(k, v))
    try {
      setPage(await api<Page<BankItem>>(`/api/question-bank/items/?${params}`))
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }, [bucketId, filters, offset])

  useEffect(() => {
    void load()
  }, [load])

  async function syncTopics() {
    if (!bucketId) return
    setBusy(true)
    try {
      const res = await api<{ created: Topic[]; total: number }>("/api/question-bank/topics/sync/", {
        method: "POST",
        body: JSON.stringify({ bucket_id: bucketId }),
      })
      await api("/api/question-bank/topics/tag-untagged/", { method: "POST", body: JSON.stringify({ bucket_id: bucketId }) })
      setNotice(`${res.created.length} new topic(s) from your notes · ${res.total} total. Untagged questions were auto-tagged.`)
      await Promise.all([reloadTopics(), load()])
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  async function archive(item: BankItem) {
    await api(`/api/question-bank/items/${item.id}/`, { method: "DELETE" })
    void load()
  }

  const done = (msg: string) => {
    setPanel("")
    setNotice(msg)
    setOffset(0)
    void load()
    void reloadTopics()
  }

  return (
    <div className="w-full space-y-6">
      <PageHeader
        icon={Database}
        title="Question Bank"
        description="Every question from generated tests, past papers, and your own — tagged by topic and difficulty, reusable without new AI calls."
        actions={
          <>
            <Button variant="outline" onClick={() => setPanel(panel === "add" ? "" : "add")}>
              <Plus className="size-4" /> Add question
            </Button>
            <Button variant="outline" onClick={() => setPanel(panel === "import" ? "" : "import")}>
              <FileUp className="size-4" /> Import past paper
            </Button>
            <Button variant="outline" onClick={() => setPanel(panel === "generate" ? "" : "generate")}>
              <Sparkles className="size-4" /> Generate with AI
            </Button>
            <Button onClick={() => setPanel(panel === "build" ? "" : "build")}>
              <Wand2 className="size-4" /> Build practice test
            </Button>
          </>
        }
      />

      <div className="flex flex-wrap items-end gap-3">
        <Field label="AI Bucket">
          <BucketSelect value={bucketId} onChange={(id) => { setBucketId(id); setOffset(0) }} className="min-w-56" />
        </Field>
        <Button variant="outline" size="sm" onClick={() => void syncTopics()} disabled={busy || !bucketId}>
          {busy ? <Loader2 className="size-3.5 animate-spin" /> : <RefreshCw className="size-3.5" />}
          Sync topics from notes
        </Button>
        <Button variant="ghost" size="sm" onClick={() => navigate("/app/papers")}>
          Question papers →
        </Button>
      </div>

      {notice ? <p className="rounded-lg bg-brand-soft px-3 py-2 text-sm text-brand">{notice}</p> : null}
      <ErrorText>{error}</ErrorText>

      {bucketId && panel === "add" ? <AddQuestionPanel bucketId={bucketId} topics={topics} onDone={done} /> : null}
      {bucketId && panel === "generate" ? <GeneratePanel bucketId={bucketId} topics={topics} onDone={done} /> : null}
      {bucketId && panel === "import" ? <ImportPanel bucketId={bucketId} onDone={done} /> : null}
      {bucketId && panel === "build" ? (
        <BuildTestPanel bucketId={bucketId} topics={topics} onCreated={(id) => navigate(`/app/mock-tests/${id}`)} />
      ) : null}

      <div className="grid gap-5 lg:grid-cols-[15rem_minmax(0,1fr)]">
        <aside className="space-y-1">
          <p className="px-2 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Topics</p>
          <TopicButton active={!filters.topic_id} onClick={() => setFilters({ ...filters, topic_id: "" })} label="All topics" />
          {topics.map((t) => (
            <TopicButton
              key={t.id}
              active={filters.topic_id === String(t.id)}
              onClick={() => { setFilters({ ...filters, topic_id: String(t.id) }); setOffset(0) }}
              label={t.name}
              count={t.item_count}
            />
          ))}
          {!topics.length ? (
            <p className="px-2 text-xs text-muted-foreground">No topics yet — use “Sync topics from notes”.</p>
          ) : null}
        </aside>

        <div className="space-y-3">
          <div className="grid gap-2 sm:grid-cols-4">
            <Select value={filters.qtype} onChange={(e) => { setFilters({ ...filters, qtype: e.target.value }); setOffset(0) }}>
              <option value="">All types</option>
              {Object.entries(QTYPE_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </Select>
            <Select value={filters.difficulty} onChange={(e) => { setFilters({ ...filters, difficulty: e.target.value }); setOffset(0) }}>
              <option value="">Any difficulty</option>
              <option value="easy">Easy</option>
              <option value="medium">Medium</option>
              <option value="hard">Hard</option>
            </Select>
            <Select value={filters.source} onChange={(e) => { setFilters({ ...filters, source: e.target.value }); setOffset(0) }}>
              <option value="">Any source</option>
              {Object.entries(SOURCE_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </Select>
            <TextInput
              placeholder="Search text…"
              value={filters.q}
              onChange={(e) => { setFilters({ ...filters, q: e.target.value }); setOffset(0) }}
            />
          </div>

          {loading && !page ? <Loading /> : null}
          {page && !page.results.length ? (
            <EmptyState>No questions match. Generate some with AI, import a past paper, or add your own.</EmptyState>
          ) : null}
          <ul className="space-y-2">
            {page?.results.map((item) => (
              <li key={item.id} className="rounded-xl border border-border/80 bg-white p-3">
                <div className="flex flex-wrap items-center gap-1.5">
                  <Pill tone="sky">{QTYPE_LABEL[item.qtype] || item.qtype}</Pill>
                  <Pill tone={DIFF_TONE[item.difficulty as keyof typeof DIFF_TONE] || "gray"}>{item.difficulty}</Pill>
                  <Pill>{SOURCE_LABEL[item.source] || item.source}{item.source_year ? ` ${item.source_year}` : ""}</Pill>
                  {item.topic_name ? <Pill tone="green">{item.topic_name}</Pill> : <Pill tone="amber">untagged</Pill>}
                  <span className="ml-auto text-xs text-muted-foreground">
                    {item.marks} mark{item.marks === 1 ? "" : "s"} · used {item.times_used}×
                  </span>
                </div>
                <p className="mt-2 whitespace-pre-wrap text-sm">{item.prompt}</p>
                {item.options.length ? (
                  <ol className="mt-1.5 grid gap-1 text-sm sm:grid-cols-2">
                    {item.options.map((o, i) => (
                      <li key={i} className={item.correct_indices.includes(i) ? "font-medium text-brand" : "text-muted-foreground"}>
                        {String.fromCharCode(65 + i)}. {o}
                      </li>
                    ))}
                  </ol>
                ) : item.answer ? (
                  <p className="mt-1.5 text-sm text-brand">Answer: {item.answer}</p>
                ) : null}
                <div className="mt-2 flex justify-end">
                  <Button variant="ghost" size="xs" onClick={() => void archive(item)}>
                    <Archive className="size-3" /> Archive
                  </Button>
                </div>
              </li>
            ))}
          </ul>
          {page && page.count > page.limit ? (
            <div className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground">
                {page.offset + 1}–{Math.min(page.offset + page.limit, page.count)} of {page.count}
              </span>
              <div className="flex gap-2">
                <Button variant="outline" size="sm" disabled={!page.offset} onClick={() => setOffset(Math.max(0, offset - page.limit))}>Previous</Button>
                <Button variant="outline" size="sm" disabled={page.next_offset == null} onClick={() => setOffset(page.next_offset ?? 0)}>Next</Button>
              </div>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  )
}

function TopicButton({ label, count, active, onClick }: { label: string; count?: number; active: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex w-full items-center justify-between rounded-lg px-2.5 py-1.5 text-left text-sm transition ${
        active ? "bg-brand-soft text-brand" : "hover:bg-muted"
      }`}
    >
      <span className="truncate">{label}</span>
      {count != null ? <span className="text-xs text-muted-foreground">{count}</span> : null}
    </button>
  )
}

function TopicSelect({ topics, value, onChange }: { topics: Topic[]; value: string; onChange: (v: string) => void }) {
  return (
    <Select value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">Auto-tag from notes</option>
      {topics.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
    </Select>
  )
}

function AddQuestionPanel({ bucketId, topics, onDone }: { bucketId: number; topics: Topic[]; onDone: (m: string) => void }) {
  const [form, setForm] = useState({ qtype: "mcq", prompt: "", options: ["", "", "", ""], correct: [0], answer: "", explanation: "", marks: 1, difficulty: "medium", topic_id: "" })
  const [error, setError] = useState("")
  const objective = form.qtype === "mcq" || form.qtype === "multi"

  async function save() {
    setError("")
    try {
      await api("/api/question-bank/items/", {
        method: "POST",
        body: JSON.stringify({
          bucket_id: bucketId,
          qtype: form.qtype,
          prompt: form.prompt,
          options: objective ? form.options.filter((o) => o.trim()) : [],
          correct_indices: objective ? form.correct : [],
          answer: form.answer,
          explanation: form.explanation,
          marks: form.marks,
          difficulty: form.difficulty,
          topic_id: form.topic_id ? Number(form.topic_id) : null,
        }),
      })
      onDone("Question added to the bank.")
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  const toggleCorrect = (i: number) =>
    setForm((f) => ({
      ...f,
      correct: f.qtype === "mcq" ? [i] : f.correct.includes(i) ? f.correct.filter((c) => c !== i) : [...f.correct, i],
    }))

  return (
    <Section title="Add a question">
      <div className="grid gap-3 sm:grid-cols-4">
        <Field label="Type">
          <Select value={form.qtype} onChange={(e) => setForm({ ...form, qtype: e.target.value, correct: [0] })}>
            {Object.entries(QTYPE_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </Select>
        </Field>
        <Field label="Difficulty">
          <Select value={form.difficulty} onChange={(e) => setForm({ ...form, difficulty: e.target.value })}>
            <option value="easy">Easy</option><option value="medium">Medium</option><option value="hard">Hard</option>
          </Select>
        </Field>
        <Field label="Marks">
          <TextInput type="number" min={1} value={form.marks} onChange={(e) => setForm({ ...form, marks: Number(e.target.value) })} />
        </Field>
        <Field label="Topic">
          <TopicSelect topics={topics} value={form.topic_id} onChange={(v) => setForm({ ...form, topic_id: v })} />
        </Field>
      </div>
      <Field label="Question">
        <TextArea value={form.prompt} onChange={(e) => setForm({ ...form, prompt: e.target.value })} placeholder="Supports LaTeX: $E = mc^2$" />
      </Field>
      {objective ? (
        <div className="grid gap-2 sm:grid-cols-2">
          {form.options.map((o, i) => (
            <label key={i} className="flex items-center gap-2 text-sm">
              <input type={form.qtype === "mcq" ? "radio" : "checkbox"} checked={form.correct.includes(i)} onChange={() => toggleCorrect(i)} />
              <TextInput
                value={o}
                placeholder={`Option ${String.fromCharCode(65 + i)}`}
                onChange={(e) => setForm({ ...form, options: form.options.map((x, j) => (j === i ? e.target.value : x)) })}
              />
            </label>
          ))}
        </div>
      ) : (
        <Field label={form.qtype === "numeric" ? "Answer value (with units)" : "Model answer"}>
          <TextArea value={form.answer} onChange={(e) => setForm({ ...form, answer: e.target.value })} />
        </Field>
      )}
      <Field label="Explanation (optional)">
        <TextInput value={form.explanation} onChange={(e) => setForm({ ...form, explanation: e.target.value })} />
      </Field>
      <ErrorText>{error}</ErrorText>
      <Button onClick={() => void save()} disabled={!form.prompt.trim()}>Save question</Button>
    </Section>
  )
}

function GeneratePanel({ bucketId, topics, onDone }: { bucketId: number; topics: Topic[]; onDone: (m: string) => void }) {
  const [topicId, setTopicId] = useState("")
  const [prompt, setPrompt] = useState("")
  const [difficulty, setDifficulty] = useState("medium")
  const [counts, setCounts] = useState({ mcq: 5, multi: 0, brief: 2, long: 0, numeric: 0 })
  const [usePapers, setUsePapers] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")

  async function run() {
    setBusy(true)
    setError("")
    try {
      const rows = await api<BankItem[]>("/api/question-bank/items/generate/", {
        method: "POST",
        body: JSON.stringify({ bucket_id: bucketId, topic_id: topicId ? Number(topicId) : null, prompt, difficulty, counts, use_past_papers: usePapers }),
      })
      onDone(`Generated ${rows.length} question(s) from your notes.`)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Section title="Generate questions with AI" description="Grounded in this bucket's indexed notes; duplicates of existing bank questions are skipped.">
      <div className="grid gap-3 sm:grid-cols-3">
        <Field label="Topic">
          <TopicSelect topics={topics} value={topicId} onChange={setTopicId} />
        </Field>
        <Field label="Difficulty">
          <Select value={difficulty} onChange={(e) => setDifficulty(e.target.value)}>
            <option value="easy">Easy</option><option value="medium">Medium</option><option value="hard">Hard</option>
          </Select>
        </Field>
        <Field label="Style">
          <label className="flex h-9 items-center gap-2 text-sm">
            <input type="checkbox" checked={usePapers} onChange={(e) => setUsePapers(e.target.checked)} />
            Match previous-year paper style
          </label>
        </Field>
      </div>
      <Field label="Instructions (optional if a topic is chosen)">
        <TextInput value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="e.g. Numericals on lens formula with sign convention" />
      </Field>
      <div className="grid grid-cols-5 gap-2">
        {(Object.keys(counts) as (keyof typeof counts)[]).map((k) => (
          <Field key={k} label={QTYPE_LABEL[k]}>
            <TextInput type="number" min={0} max={30} value={counts[k]} onChange={(e) => setCounts({ ...counts, [k]: Number(e.target.value) })} />
          </Field>
        ))}
      </div>
      <ErrorText>{error}</ErrorText>
      <Button onClick={() => void run()} disabled={busy || (!topicId && !prompt.trim())}>
        {busy ? <Loader2 className="size-4 animate-spin" /> : <Sparkles className="size-4" />} Generate
      </Button>
    </Section>
  )
}

function ImportPanel({ bucketId, onDone }: { bucketId: number; onDone: (m: string) => void }) {
  const [docs, setDocs] = useState<DocumentRow[]>([])
  const [jobs, setJobs] = useState<ImportJob[]>([])
  const [error, setError] = useState("")

  const loadJobs = useCallback(async () => {
    setJobs(await api<ImportJob[]>(`/api/question-bank/import-jobs/?bucket_id=${bucketId}`))
  }, [bucketId])

  useEffect(() => {
    void api<DocumentRow[]>(`/api/documents/?bucket_id=${bucketId}&kind=question_paper&status=indexed`).then(setDocs).catch(() => setDocs([]))
    void loadJobs()
  }, [bucketId, loadJobs])

  useEffect(() => {
    if (!jobs.some((j) => j.status === "queued" || j.status === "running")) return
    const t = window.setInterval(() => void loadJobs(), 3000)
    return () => window.clearInterval(t)
  }, [jobs, loadJobs])

  async function start(doc: DocumentRow) {
    setError("")
    try {
      await api("/api/question-bank/items/import-document/", { method: "POST", body: JSON.stringify({ document_id: doc.id }) })
      await loadJobs()
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  return (
    <Section
      title="Import questions from previous-year papers"
      description="AI extracts each question (with answers when the paper has solutions), tags its year from the file name and its topic from your notes."
    >
      {!docs.length ? (
        <p className="text-sm text-muted-foreground">No indexed question papers in this bucket. Upload them under AI Buckets → Question papers.</p>
      ) : (
        <ul className="divide-y divide-border/60 text-sm">
          {docs.map((d) => {
            const job = jobs.find((j) => j.document_filename === d.original_filename)
            return (
              <li key={d.id} className="flex items-center justify-between gap-2 py-2">
                <span className="truncate">{d.original_filename}</span>
                {job && (job.status === "queued" || job.status === "running") ? (
                  <span className="flex items-center gap-1 text-xs text-muted-foreground"><Loader2 className="size-3 animate-spin" /> Extracting…</span>
                ) : job?.status === "done" ? (
                  <button type="button" className="text-xs text-brand" onClick={() => onDone(`Imported ${job.created_count} question(s) from ${d.original_filename}.`)}>
                    {job.created_count} added · {job.skipped_duplicates} skipped — view
                  </button>
                ) : (
                  <Button size="xs" variant="outline" onClick={() => void start(d)}>
                    {job?.status === "failed" ? "Retry" : "Extract questions"}
                  </Button>
                )}
              </li>
            )
          })}
        </ul>
      )}
      {jobs.find((j) => j.status === "failed") ? <ErrorText>{jobs.find((j) => j.status === "failed")?.error_message}</ErrorText> : null}
      <ErrorText>{error}</ErrorText>
    </Section>
  )
}

function BuildTestPanel({ bucketId, topics, onCreated }: { bucketId: number; topics: Topic[]; onCreated: (id: number) => void }) {
  const [title, setTitle] = useState("Practice test")
  const [topicIds, setTopicIds] = useState<number[]>([])
  const [counts, setCounts] = useState({ mcq: 10, multi: 0, brief: 0 })
  const [mix, setMix] = useState({ easy: 30, medium: 50, hard: 20 })
  const [duration, setDuration] = useState(30)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")

  async function build() {
    setBusy(true)
    setError("")
    try {
      const res = await api<{ mock_test_id: number }>("/api/question-bank/build-mock-test/", {
        method: "POST",
        body: JSON.stringify({ bucket_id: bucketId, title, duration_minutes: duration, counts, topic_ids: topicIds, difficulty_mix: mix }),
      })
      onCreated(res.mock_test_id)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Section title="Build a practice test from the bank" description="No AI call — picks least-used questions first. You'll assign students on the next screen.">
      <div className="grid gap-3 sm:grid-cols-3">
        <Field label="Title"><TextInput value={title} onChange={(e) => setTitle(e.target.value)} /></Field>
        <Field label="Duration (min)"><TextInput type="number" min={5} value={duration} onChange={(e) => setDuration(Number(e.target.value))} /></Field>
        <Field label="Difficulty mix %" hint="easy / medium / hard">
          <div className="flex gap-1">
            {(Object.keys(mix) as (keyof typeof mix)[]).map((k) => (
              <TextInput key={k} type="number" min={0} max={100} value={mix[k]} onChange={(e) => setMix({ ...mix, [k]: Number(e.target.value) })} />
            ))}
          </div>
        </Field>
      </div>
      <div className="grid grid-cols-3 gap-2">
        {(Object.keys(counts) as (keyof typeof counts)[]).map((k) => (
          <Field key={k} label={k === "brief" ? "Written" : QTYPE_LABEL[k]}>
            <TextInput type="number" min={0} value={counts[k]} onChange={(e) => setCounts({ ...counts, [k]: Number(e.target.value) })} />
          </Field>
        ))}
      </div>
      <Field label="Topics (none = all)">
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
      <ErrorText>{error}</ErrorText>
      <Button onClick={() => void build()} disabled={busy}>
        {busy ? <Loader2 className="size-4 animate-spin" /> : <Wand2 className="size-4" />} Create draft test
      </Button>
    </Section>
  )
}
