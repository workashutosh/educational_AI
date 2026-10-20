import { useEffect, useState } from "react"
import { Link, useNavigate } from "react-router-dom"
import { BookCheck, Loader2, Plus } from "lucide-react"

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
import { api, apiUpload, errorMessage, formatDate, type MemberRow } from "@/lib/api"
import { useAuth } from "@/lib/auth"
import { HW_STATUS_TONE, useRole } from "@/lib/features"

export type Homework = {
  id: number
  bucket_id: number
  bucket_name: string
  title: string
  instructions: string
  due_at: string | null
  is_overdue: boolean
  max_marks: number
  status: string
  results_mode: string
  ai_grading: boolean
  allow_late: boolean
  attachment_url: string | null
  attachment_name: string
  created_by_name: string
  can_manage: boolean
  assigned_count?: number
  submitted_count?: number
  my_status?: "pending" | "overdue" | "submitted" | "returned"
  rubric?: string
  model_answer?: string
}

export function HomeworkPage() {
  const { isStudent } = useRole()
  const [rows, setRows] = useState<Homework[] | null>(null)
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState("")

  useEffect(() => {
    api<Homework[]>("/api/homework/").then(setRows).catch((e) => setError(errorMessage(e)))
  }, [])

  return (
    <div className="w-full space-y-6">
      <PageHeader
        icon={BookCheck}
        title={isStudent ? "My Homework" : "Homework"}
        description={
          isStudent
            ? "Submit typed answers or photos of your notebook. You'll get feedback when your teacher returns it."
            : "Assign work, collect typed or photographed answers, get AI-suggested marks, then confirm and return."
        }
        actions={!isStudent ? <Button onClick={() => setCreating((c) => !c)}><Plus className="size-4" /> New homework</Button> : null}
      />
      <ErrorText>{error}</ErrorText>
      {creating ? <CreateHomework /> : null}
      {!rows ? <Loading /> : !rows.length ? (
        <EmptyState>{isStudent ? "No homework assigned right now." : "No homework yet."}</EmptyState>
      ) : (
        <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {rows.map((h) => {
            const status = isStudent ? h.my_status || "pending" : h.status
            return (
              <li key={h.id}>
                <Link to={`/app/homework/${h.id}`} className="block rounded-2xl border border-border/80 bg-white/80 p-4 transition hover:border-brand hover:bg-brand-soft/40">
                  <div className="flex items-start justify-between gap-2">
                    <p className="font-medium leading-snug">{h.title}</p>
                    <Pill tone={HW_STATUS_TONE[status as keyof typeof HW_STATUS_TONE] || "gray"}>{status}</Pill>
                  </div>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {h.bucket_name} · {h.max_marks} marks{h.due_at ? ` · due ${formatDate(h.due_at, true)}` : ""}
                  </p>
                  {!isStudent ? (
                    <p className="mt-3 text-xs text-muted-foreground">{h.submitted_count}/{h.assigned_count} submitted</p>
                  ) : null}
                </Link>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}

function CreateHomework() {
  const { session } = useAuth()
  const navigate = useNavigate()
  const [bucketId, setBucketId] = useState<number | null>(session?.buckets?.[0]?.id ?? null)
  const [students, setStudents] = useState<MemberRow[]>([])
  const [selected, setSelected] = useState<number[]>([])
  const [assignAll, setAssignAll] = useState(true)
  const [file, setFile] = useState<File | null>(null)
  const [form, setForm] = useState({
    title: "",
    instructions: "",
    due_at: "",
    max_marks: 10,
    rubric: "",
    model_answer: "",
    results_mode: "after_review",
    ai_grading: true,
    allow_late: true,
  })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")

  useEffect(() => {
    api<MemberRow[]>("/api/admin/members/?role=student")
      // Managers get bucket grants per row; teachers see the roster without them
      // (the API only assigns students who can access the bucket either way).
      .then((rows) => {
        const hasGrants = rows.some((r) => (r.bucket_ids || []).length)
        setStudents(hasGrants && bucketId ? rows.filter((r) => (r.bucket_ids || []).includes(bucketId)) : rows)
      })
      .catch(() => setStudents([]))
  }, [bucketId])

  async function create(publish: boolean) {
    setBusy(true)
    setError("")
    const fd = new FormData()
    fd.set("bucket_id", String(bucketId))
    Object.entries(form).forEach(([k, v]) => {
      if (k === "due_at") {
        if (v) fd.set(k, new Date(String(v)).toISOString())
      } else fd.set(k, String(v))
    })
    fd.set("assign_all", String(assignAll))
    if (!assignAll) selected.forEach((id) => fd.append("student_ids", String(id)))
    fd.set("publish", String(publish))
    if (file) fd.set("attachment", file)
    try {
      const hw = await apiUpload<{ id: number }>("/api/homework/", fd)
      navigate(`/app/homework/${hw.id}`)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Section title="New homework">
      <div className="grid gap-3 sm:grid-cols-3">
        <Field label="AI Bucket"><BucketSelect value={bucketId} onChange={setBucketId} /></Field>
        <Field label="Title"><TextInput value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} /></Field>
        <Field label="Due"><TextInput type="datetime-local" value={form.due_at} onChange={(e) => setForm({ ...form, due_at: e.target.value })} /></Field>
        <Field label="Max marks"><TextInput type="number" min={1} value={form.max_marks} onChange={(e) => setForm({ ...form, max_marks: Number(e.target.value) })} /></Field>
        <Field label="Results">
          <Select value={form.results_mode} onChange={(e) => setForm({ ...form, results_mode: e.target.value })}>
            <option value="after_review">I review, then return</option>
            <option value="immediate">Show AI feedback immediately</option>
          </Select>
        </Field>
        <Field label="Worksheet (optional)"><input type="file" className="text-sm" onChange={(e) => setFile(e.target.files?.[0] || null)} /></Field>
      </div>
      <Field label="Instructions"><TextArea value={form.instructions} onChange={(e) => setForm({ ...form, instructions: e.target.value })} /></Field>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Marking scheme (used by AI + you)"><TextArea value={form.rubric} onChange={(e) => setForm({ ...form, rubric: e.target.value })} placeholder="e.g. 2 marks formula, 2 marks substitution, 1 mark units" /></Field>
        <Field label="Model answer (optional)"><TextArea value={form.model_answer} onChange={(e) => setForm({ ...form, model_answer: e.target.value })} /></Field>
      </div>
      <div className="flex flex-wrap gap-4 text-sm">
        <label className="flex items-center gap-2"><input type="checkbox" checked={form.ai_grading} onChange={(e) => setForm({ ...form, ai_grading: e.target.checked })} /> AI-suggested marks</label>
        <label className="flex items-center gap-2"><input type="checkbox" checked={form.allow_late} onChange={(e) => setForm({ ...form, allow_late: e.target.checked })} /> Accept late submissions</label>
        <label className="flex items-center gap-2"><input type="checkbox" checked={assignAll} onChange={(e) => setAssignAll(e.target.checked)} /> Assign to every student in the bucket</label>
      </div>
      {!assignAll ? (
        <div className="flex flex-wrap gap-1.5">
          {students.map((s) => (
            <button
              key={s.id}
              type="button"
              onClick={() => setSelected((ids) => (ids.includes(s.id) ? ids.filter((i) => i !== s.id) : [...ids, s.id]))}
              className={`rounded-full border px-2.5 py-1 text-xs ${selected.includes(s.id) ? "border-brand bg-brand-soft text-brand" : "border-border bg-white"}`}
            >
              {s.full_name || s.username}
            </button>
          ))}
        </div>
      ) : null}
      <ErrorText>{error}</ErrorText>
      <div className="flex gap-2">
        <Button onClick={() => void create(true)} disabled={busy || !form.title.trim() || !bucketId}>
          {busy ? <Loader2 className="size-4 animate-spin" /> : null} Publish
        </Button>
        <Button variant="outline" onClick={() => void create(false)} disabled={busy || !form.title.trim() || !bucketId}>Save draft</Button>
      </div>
    </Section>
  )
}
