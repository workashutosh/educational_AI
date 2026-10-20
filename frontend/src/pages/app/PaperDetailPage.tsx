import { useCallback, useEffect, useState } from "react"
import { useNavigate, useParams } from "react-router-dom"
import { ArrowLeftRight, ClipboardList, Download, Lock, RefreshCw, Trash2, Unlock } from "lucide-react"

import { ErrorText, Loading, PageHeader, Pill, Section } from "@/components/app/ui"
import { RichAnswer } from "@/components/chat/RichAnswer"
import { Button } from "@/components/ui/button"
import { api, downloadFile, errorMessage } from "@/lib/api"
import { QTYPE_LABEL } from "@/lib/features"

type PaperItem = {
  id: number
  order: number
  question: number | null
  qtype: string
  prompt: string
  options: string[]
  correct_indices: number[]
  answer: string
  explanation: string
  marks: number
  difficulty: string
  topic_name: string
}

type PaperSection = {
  id: number
  title: string
  instructions: string
  qtype: string
  marks_each: number
  requested_count: number
  total_marks: number
  items: PaperItem[]
}

type Paper = {
  id: number
  title: string
  exam_name: string
  class_label: string
  bucket_name: string
  instructions: string
  duration_minutes: number
  status: string
  total_marks: number
  question_count: number
  generation_notes: string[]
  sections: PaperSection[]
}

export function PaperDetailPage() {
  const { paperId } = useParams()
  const navigate = useNavigate()
  const [paper, setPaper] = useState<Paper | null>(null)
  const [error, setError] = useState("")
  const [busy, setBusy] = useState("")
  const [showAnswers, setShowAnswers] = useState(false)
  const base = `/api/question-bank/papers/${paperId}`

  const load = useCallback(async () => {
    try {
      setPaper(await api<Paper>(`${base}/`))
    } catch (err) {
      setError(errorMessage(err))
    }
  }, [base])

  useEffect(() => {
    void load()
  }, [load])

  async function run(label: string, fn: () => Promise<unknown>) {
    setBusy(label)
    setError("")
    try {
      await fn()
      await load()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy("")
    }
  }

  if (!paper) return error ? <ErrorText>{error}</ErrorText> : <Loading />
  const locked = paper.status === "final"
  let n = 0

  return (
    <div className="w-full max-w-4xl space-y-6">
      <PageHeader
        title={paper.title}
        description={[paper.exam_name, paper.class_label, paper.bucket_name, `${paper.duration_minutes} min`, `${paper.total_marks} marks`].filter(Boolean).join(" · ")}
        actions={
          <>
            <Button variant="outline" onClick={() => void run("pdf", () => downloadFile(`${base}/export/?fmt=pdf`, "paper.pdf"))} disabled={!!busy}>
              <Download className="size-4" /> PDF
            </Button>
            <Button variant="outline" onClick={() => void run("key", () => downloadFile(`${base}/export/?fmt=pdf&answers=1`, "answer-key.pdf"))} disabled={!!busy}>
              <Download className="size-4" /> Answer key
            </Button>
            <Button variant="outline" onClick={() => void run("docx", () => downloadFile(`${base}/export/?fmt=docx`, "paper.docx"))} disabled={!!busy}>
              <Download className="size-4" /> Word
            </Button>
            <Button
              variant="outline"
              onClick={() =>
                void run("mock", async () => {
                  const res = await api<{ mock_test_id: number }>(`${base}/to-mock-test/`, { method: "POST" })
                  navigate(`/app/mock-tests/${res.mock_test_id}`)
                })
              }
              disabled={!!busy}
            >
              <ClipboardList className="size-4" /> Use as mock test
            </Button>
            <Button
              onClick={() => void run("status", () => api(`${base}/`, { method: "PATCH", body: JSON.stringify({ status: locked ? "draft" : "final" }) }))}
              disabled={!!busy}
            >
              {locked ? <Unlock className="size-4" /> : <Lock className="size-4" />} {locked ? "Unlock" : "Mark final"}
            </Button>
          </>
        }
      />
      <ErrorText>{error}</ErrorText>
      {paper.generation_notes?.length ? (
        <div className="rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800">
          {paper.generation_notes.map((note) => <p key={note}>{note}</p>)}
        </div>
      ) : null}
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={showAnswers} onChange={(e) => setShowAnswers(e.target.checked)} /> Show answers
      </label>

      {paper.instructions ? (
        <Section title="General instructions">
          <p className="whitespace-pre-wrap text-sm">{paper.instructions}</p>
        </Section>
      ) : null}

      {paper.sections.map((section) => (
        <Section
          key={section.id}
          title={`${section.title} · ${QTYPE_LABEL[section.qtype] || section.qtype}`}
          description={`${section.items.length}/${section.requested_count} questions · ${section.total_marks} marks${section.instructions ? ` · ${section.instructions}` : ""}`}
          actions={
            !locked ? (
              <Button size="sm" variant="outline" disabled={!!busy} onClick={() => void run(`refill-${section.id}`, () => api(`${base}/sections/${section.id}/refill/`, { method: "POST" }))}>
                <RefreshCw className="size-3.5" /> Re-pick
              </Button>
            ) : null
          }
        >
          <ol className="space-y-3">
            {section.items.map((item) => {
              n += 1
              return (
                <li key={item.id} className="rounded-xl border border-border/70 bg-white p-3">
                  <div className="flex items-start gap-2">
                    <span className="font-medium">Q{n}.</span>
                    <div className="min-w-0 flex-1 text-sm">
                      <RichAnswer content={item.prompt} />
                      {item.options.length ? (
                        <ol className="mt-1 grid gap-0.5 sm:grid-cols-2">
                          {item.options.map((o, i) => (
                            <li key={i} className={showAnswers && item.correct_indices.includes(i) ? "font-medium text-brand" : ""}>
                              ({String.fromCharCode(65 + i)}) {o}
                            </li>
                          ))}
                        </ol>
                      ) : null}
                      {showAnswers && item.answer ? <p className="mt-1 text-brand">Answer: {item.answer}</p> : null}
                      {showAnswers && item.explanation ? <p className="mt-0.5 text-xs text-muted-foreground">{item.explanation}</p> : null}
                    </div>
                    <div className="flex shrink-0 flex-col items-end gap-1">
                      <span className="text-xs text-muted-foreground">[{item.marks}]</span>
                      <div className="flex gap-1">
                        {item.topic_name ? <Pill>{item.topic_name}</Pill> : null}
                        <Pill tone="sky">{item.difficulty}</Pill>
                      </div>
                      {!locked ? (
                        <div className="flex gap-1">
                          <Button size="icon-xs" variant="ghost" title="Swap for another bank question" disabled={!!busy}
                            onClick={() => void run(`swap-${item.id}`, () => api(`${base}/items/${item.id}/swap/`, { method: "POST" }))}>
                            <ArrowLeftRight className="size-3" />
                          </Button>
                          <Button size="icon-xs" variant="ghost" title="Remove" disabled={!!busy}
                            onClick={() => void run(`del-${item.id}`, () => api(`${base}/items/${item.id}/`, { method: "DELETE" }))}>
                            <Trash2 className="size-3" />
                          </Button>
                        </div>
                      ) : null}
                    </div>
                  </div>
                </li>
              )
            })}
          </ol>
        </Section>
      ))}
    </div>
  )
}
