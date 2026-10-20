import { useCallback, useEffect, useState } from "react"
import { Link, useNavigate } from "react-router-dom"
import { BarChart3, Loader2, MessageSquareText, Target, ThumbsDown, ThumbsUp } from "lucide-react"

import {
  AccuracyBar,
  BucketSelect,
  EmptyState,
  ErrorText,
  Field,
  Loading,
  PageHeader,
  Pill,
  Section,
  Stat,
} from "@/components/app/ui"
import { Button } from "@/components/ui/button"
import { api, errorMessage, formatDate } from "@/lib/api"
import { useAuth } from "@/lib/auth"
import { useRole } from "@/lib/features"
import { cn } from "@/lib/utils"

type TopicRow = {
  topic_id: number
  topic_name: string
  bucket_id: number
  bucket_name: string
  accuracy: number | null
  items: number
  status: "weak" | "developing" | "strong" | "not_enough_data"
  chat_prompt: string
}

type TopicReport = { topics: TopicRow[]; weak_topics: TopicRow[]; summary: string | null }

type Heatmap = {
  topics: { topic_id: number; topic_name: string; class_accuracy: number | null; weak_students: number }[]
  students: {
    student_id: number
    name: string
    weak_count: number
    weak_topics: string[]
    cells: Record<string, { accuracy: number | null; status: string }>
  }[]
}

type Attendance = {
  total: number
  attended: number
  percent: number | null
  recent: { lecture_id: number; lecture_title: string; bucket_name: string; starts_at: string; status: string }[]
}

const STATUS_TONE = { weak: "red", developing: "amber", strong: "green", not_enough_data: "gray" } as const
const STATUS_LABEL = { weak: "Needs work", developing: "Getting there", strong: "Strong", not_enough_data: "Not enough data" }

export function InsightsPage() {
  const { isStudent } = useRole()
  return isStudent ? <StudentInsights /> : <StaffInsights />
}

function StudentInsights() {
  const { session } = useAuth()
  const navigate = useNavigate()
  const [bucketId, setBucketId] = useState<number | null>(session?.buckets?.[0]?.id ?? null)
  const [report, setReport] = useState<TopicReport | null>(null)
  const [attendance, setAttendance] = useState<Attendance | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")

  useEffect(() => {
    if (!bucketId) return
    setReport(null)
    api<TopicReport>(`/api/analytics/me/topics/?bucket_id=${bucketId}`).then(setReport).catch((e) => setError(errorMessage(e)))
  }, [bucketId])

  useEffect(() => {
    api<Attendance>("/api/attendance/me/").then(setAttendance).catch(() => setAttendance(null))
  }, [])

  async function practice() {
    if (!bucketId) return
    setBusy(true)
    setError("")
    try {
      const res = await api<{ mock_test_id: number }>("/api/analytics/me/practice/", {
        method: "POST",
        body: JSON.stringify({ bucket_id: bucketId }),
      })
      navigate(`/app/mock-tests/${res.mock_test_id}/take`)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="w-full max-w-4xl space-y-6">
      <PageHeader icon={Target} title="My Progress" description="Topics you've mastered, topics that need work, and your class attendance." />
      <div className="flex flex-wrap items-end gap-3">
        <Field label="AI Bucket"><BucketSelect value={bucketId} onChange={setBucketId} className="min-w-56" /></Field>
        <Button onClick={() => void practice()} disabled={busy || !report?.weak_topics.length}>
          {busy ? <Loader2 className="size-4 animate-spin" /> : <Target className="size-4" />} Practice my weak topics
        </Button>
      </div>
      <ErrorText>{error}</ErrorText>

      {report?.summary ? <p className="rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800">{report.summary}</p> : null}
      <Section title="Topics">
        {!report ? <Loading /> : !report.topics.length ? (
          <p className="text-sm text-muted-foreground">Take a test or a quick check in this subject to see topic-level results.</p>
        ) : (
          <TopicTable rows={report.topics} />
        )}
      </Section>

      {attendance && attendance.total ? (
        <Section title="Attendance" description={`${attendance.attended} of ${attendance.total} lectures attended`}>
          <AccuracyBar value={attendance.percent} />
          <ul className="divide-y divide-border/60 text-sm">
            {attendance.recent.slice(0, 8).map((r) => (
              <li key={r.lecture_id} className="flex items-center justify-between py-1.5">
                <span>{r.lecture_title} <span className="text-xs text-muted-foreground">· {r.bucket_name} · {formatDate(r.starts_at)}</span></span>
                <Pill tone={r.status === "present" ? "green" : r.status === "late" ? "amber" : r.status === "excused" ? "sky" : "red"}>{r.status}</Pill>
              </li>
            ))}
          </ul>
        </Section>
      ) : null}
    </div>
  )
}

function TopicTable({ rows }: { rows: TopicRow[] }) {
  return (
    <ul className="divide-y divide-border/60">
      {rows.map((r) => (
        <li key={r.topic_id} className="flex flex-wrap items-center gap-3 py-2 text-sm">
          <span className="min-w-40 flex-1 font-medium">{r.topic_name}</span>
          <AccuracyBar value={r.accuracy} />
          <Pill tone={STATUS_TONE[r.status]}>{STATUS_LABEL[r.status]}</Pill>
          <span className="w-16 text-right text-xs text-muted-foreground">{r.items} items</span>
          <Link
            to={`/app/chat?bucket=${r.bucket_id}&q=${encodeURIComponent(r.chat_prompt)}`}
            className="flex items-center gap-1 text-xs text-brand hover:underline"
          >
            <MessageSquareText className="size-3" /> Ask AI
          </Link>
        </li>
      ))}
    </ul>
  )
}

function StaffInsights() {
  const { session } = useAuth()
  const navigate = useNavigate()
  const [bucketId, setBucketId] = useState<number | null>(session?.buckets?.[0]?.id ?? null)
  const [heat, setHeat] = useState<Heatmap | null>(null)
  const [selectedStudents, setSelectedStudents] = useState<number[]>([])
  const [selectedTopics, setSelectedTopics] = useState<number[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")

  const load = useCallback(async () => {
    if (!bucketId) return
    setHeat(null)
    try {
      setHeat(await api<Heatmap>(`/api/analytics/buckets/${bucketId}/heatmap/`))
    } catch (err) {
      setError(errorMessage(err))
    }
  }, [bucketId])

  useEffect(() => {
    void load()
  }, [load])

  async function remediate() {
    if (!bucketId) return
    setBusy(true)
    setError("")
    try {
      const res = await api<{ mock_test_id: number }>("/api/analytics/remediate/", {
        method: "POST",
        body: JSON.stringify({ bucket_id: bucketId, student_ids: selectedStudents, topic_ids: selectedTopics, question_count: 10 }),
      })
      navigate(`/app/mock-tests/${res.mock_test_id}`)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  const toggle = (list: number[], set: (v: number[]) => void, id: number) =>
    set(list.includes(id) ? list.filter((x) => x !== id) : [...list, id])

  return (
    <div className="w-full space-y-6">
      <PageHeader
        icon={BarChart3}
        title="Class Insights"
        description="Topic accuracy for every student from tests, quick checks, and flashcards. Pick weak topics and assign a revision test in one click."
      />
      <div className="flex flex-wrap items-end gap-3">
        <Field label="AI Bucket"><BucketSelect value={bucketId} onChange={setBucketId} className="min-w-56" /></Field>
        <Button onClick={() => void remediate()} disabled={busy || !heat?.students.length}>
          {busy ? <Loader2 className="size-4 animate-spin" /> : <Target className="size-4" />}
          Assign revision test
          {selectedStudents.length ? ` (${selectedStudents.length} students)` : " (whole class)"}
        </Button>
      </div>
      <p className="text-xs text-muted-foreground">
        Tip: select topic columns and/or student rows to target the test; with nothing selected, the class's weakest topics are used.
        Tag older tests with topics from Question Bank → “Sync topics from notes”.
      </p>
      <ErrorText>{error}</ErrorText>

      {!heat ? <Loading /> : !heat.topics.length ? (
        <EmptyState>No topics yet for this bucket. Open the Question Bank and sync topics from your notes.</EmptyState>
      ) : (
        <div className="overflow-x-auto rounded-2xl border border-border/80 bg-white">
          <table className="min-w-full text-sm">
            <thead>
              <tr className="border-b border-border/70">
                <th className="sticky left-0 bg-white px-3 py-2 text-left font-medium">Student</th>
                {heat.topics.map((t) => (
                  <th key={t.topic_id} className="px-2 py-2 text-left align-bottom">
                    <button
                      type="button"
                      onClick={() => toggle(selectedTopics, setSelectedTopics, t.topic_id)}
                      className={cn("max-w-28 rounded px-1 text-left text-xs font-medium", selectedTopics.includes(t.topic_id) && "bg-brand-soft text-brand")}
                      title={t.topic_name}
                    >
                      <span className="line-clamp-2">{t.topic_name}</span>
                      <span className="block font-normal text-muted-foreground">
                        class {t.class_accuracy == null ? "—" : `${Math.round(t.class_accuracy)}%`}
                      </span>
                    </button>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {heat.students.map((s) => (
                <tr key={s.student_id} className="border-b border-border/40 last:border-0">
                  <td className="sticky left-0 bg-white px-3 py-1.5">
                    <label className="flex items-center gap-2">
                      <input type="checkbox" checked={selectedStudents.includes(s.student_id)} onChange={() => toggle(selectedStudents, setSelectedStudents, s.student_id)} />
                      <span className="whitespace-nowrap">{s.name}</span>
                      {s.weak_count ? <Pill tone="red">{s.weak_count} weak</Pill> : null}
                    </label>
                  </td>
                  {heat.topics.map((t) => {
                    const cell = s.cells[String(t.topic_id)]
                    const acc = cell?.accuracy
                    const tone =
                      acc == null ? "bg-muted/40 text-muted-foreground"
                        : cell.status === "not_enough_data" ? "bg-muted text-muted-foreground"
                        : acc < 60 ? "bg-red-100 text-red-800"
                        : acc < 80 ? "bg-amber-100 text-amber-800"
                        : "bg-emerald-100 text-emerald-800"
                    return (
                      <td key={t.topic_id} className="px-2 py-1.5">
                        <span className={cn("inline-block min-w-11 rounded px-1.5 py-0.5 text-center text-xs tabular-nums", tone)}>
                          {acc == null ? "—" : `${Math.round(acc)}%`}
                        </span>
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {bucketId ? <AttendanceSummary bucketId={bucketId} /> : null}
      {bucketId ? <FeedbackSummary bucketId={bucketId} /> : null}
    </div>
  )
}

function AttendanceSummary({ bucketId }: { bucketId: number }) {
  const [rows, setRows] = useState<{ student_id: number; name: string; total: number; attended: number; percent: number | null }[] | null>(null)
  useEffect(() => {
    api<{ students: typeof rows }>(`/api/attendance/buckets/${bucketId}/`).then((r) => setRows(r.students)).catch(() => setRows([]))
  }, [bucketId])
  if (!rows?.some((r) => r.total)) return null
  return (
    <Section title="Attendance" description="Lowest first — auto-marked when students open the live lecture room.">
      <ul className="grid gap-x-6 gap-y-1.5 text-sm sm:grid-cols-2">
        {rows.map((r) => (
          <li key={r.student_id} className="flex items-center justify-between gap-2">
            <span className="truncate">{r.name}</span>
            <span className="flex items-center gap-2">
              <AccuracyBar value={r.percent} />
              <span className="w-10 text-right text-xs text-muted-foreground">{r.attended}/{r.total}</span>
            </span>
          </li>
        ))}
      </ul>
    </Section>
  )
}

type Feedback = {
  total: number
  helpful: number
  not_helpful: number
  helpful_rate: number | null
  by_reason: { reason: string; n: number }[]
  avg_top_score_helpful: number | null
  avg_top_score_not_helpful: number | null
  current_min_score: number
  suggested_min_score: number | null
  recent_negative: { feedback_id: number; question: string; answer_excerpt: string; reason: string; comment: string; created_at: string }[]
}

function FeedbackSummary({ bucketId }: { bucketId: number }) {
  const [data, setData] = useState<Feedback | null>(null)
  useEffect(() => {
    api<Feedback>(`/api/learning/feedback/summary/?bucket_id=${bucketId}&days=30`).then(setData).catch(() => setData(null))
  }, [bucketId])
  if (!data || !data.total) return null
  return (
    <Section title="AI answer quality (30 days)" description="From students' 👍/👎 on chat answers.">
      <div className="grid gap-3 sm:grid-cols-4">
        <Stat label="Helpful rate" value={data.helpful_rate == null ? "—" : `${data.helpful_rate}%`} />
        <Stat label={"👍"} value={<span className="flex items-center gap-1"><ThumbsUp className="size-5 text-brand" />{data.helpful}</span>} />
        <Stat label={"👎"} value={<span className="flex items-center gap-1"><ThumbsDown className="size-5 text-red-600" />{data.not_helpful}</span>} />
        <Stat
          label="Retrieval score"
          value={data.avg_top_score_not_helpful == null ? "—" : data.avg_top_score_not_helpful.toFixed(2)}
          hint={`👎 avg vs ${data.avg_top_score_helpful?.toFixed(2) ?? "—"} for 👍`}
        />
      </div>
      {data.suggested_min_score ? (
        <p className="rounded-lg bg-sky-50 px-3 py-2 text-sm text-sky-800">
          Unhelpful answers come from weaker matches. Consider raising RAG_MIN_SCORE from {data.current_min_score} to about {data.suggested_min_score}.
        </p>
      ) : null}
      {data.recent_negative.length ? (
        <ul className="space-y-2">
          {data.recent_negative.slice(0, 6).map((n) => (
            <li key={n.feedback_id} className="rounded-xl border border-border/70 bg-white p-3 text-sm">
              <p className="font-medium">{n.question || "(question not saved)"}</p>
              <p className="mt-1 line-clamp-2 text-muted-foreground">{n.answer_excerpt}</p>
              <p className="mt-1 text-xs text-muted-foreground">
                {n.reason ? <Pill tone="red">{n.reason.replace(/_/g, " ")}</Pill> : null} {n.comment} · {formatDate(n.created_at)}
              </p>
            </li>
          ))}
        </ul>
      ) : null}
    </Section>
  )
}
