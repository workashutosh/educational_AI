import { useCallback, useEffect, useState, type FormEvent } from "react"
import { Link, useNavigate, useParams } from "react-router-dom"
import { ArrowLeft, Loader2 } from "lucide-react"

import { Button } from "@/components/ui/button"
import { api } from "@/lib/api"
import { useAuth } from "@/lib/auth"
import { cn } from "@/lib/utils"

type QuizDetail = {
  id: number
  title: string
  bucket_name: string
  status: string
  questions: {
    id: number
    order: number
    prompt: string
    options: string[]
    correct_index?: number
  }[]
  my_attempt: {
    score: number
    max_score: number
    answers: Record<string, number>
    submitted_at: string
  } | null
}

export function MicroQuizTakePage() {
  const { quizId } = useParams()
  const id = Number(quizId)
  const { session } = useAuth()
  const navigate = useNavigate()
  const [quiz, setQuiz] = useState<QuizDetail | null>(null)
  const [answers, setAnswers] = useState<Record<number, number>>({})
  const [error, setError] = useState("")
  const [busy, setBusy] = useState(false)
  const [doneMsg, setDoneMsg] = useState("")

  const load = useCallback(async () => {
    try {
      const data = await api<QuizDetail>(`/api/engagement/micro-quizzes/${id}/`)
      setQuiz(data)
      if (data.my_attempt?.answers) {
        const mapped: Record<number, number> = {}
        for (const [k, v] of Object.entries(data.my_attempt.answers)) {
          mapped[Number(k)] = Number(v)
        }
        setAnswers(mapped)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load quick check")
    }
  }, [id])

  useEffect(() => {
    void load()
  }, [load])

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (!quiz || busy) return
    setBusy(true)
    setError("")
    try {
      const payload: Record<string, number> = {}
      for (const [k, v] of Object.entries(answers)) {
        payload[String(k)] = v
      }
      const res = await api<{
        score: number
        max_score: number
        message: string
        streak: { current_streak: number }
      }>(`/api/engagement/micro-quizzes/${id}/submit/`, {
        method: "POST",
        body: JSON.stringify({ answers: payload }),
      })
      setDoneMsg(
        `${res.message} You’re on a ${res.streak?.current_streak ?? 0}-day streak.`,
      )
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : "Submit failed")
    } finally {
      setBusy(false)
    }
  }

  if (!session?.membership) return null

  if (!quiz && !error) {
    return <p className="text-muted-foreground">Loading quick check…</p>
  }

  if (!quiz) {
    return (
      <div className="space-y-3">
        <p className="text-destructive">{error}</p>
        <Link to="/app" className="text-sm text-brand">
          ← Home
        </Link>
      </div>
    )
  }

  const submitted = !!quiz.my_attempt

  return (
    <div className="mx-auto w-full max-w-2xl space-y-6">
      <div>
        <button
          type="button"
          className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
          onClick={() => navigate(-1)}
        >
          <ArrowLeft className="size-4" />
          Back
        </button>
        <h1 className="mt-2 font-display text-3xl tracking-tight">{quiz.title}</h1>
        <p className="text-sm text-muted-foreground">
          {quiz.bucket_name} · 3 questions · about 2 minutes
        </p>
      </div>

      {error ? <p className="text-sm text-destructive">{error}</p> : null}
      {doneMsg ? (
        <p className="rounded-xl border border-emerald-200 bg-emerald-50/80 px-3 py-2 text-sm text-emerald-950">
          {doneMsg}
        </p>
      ) : null}

      {submitted ? (
        <p className="text-sm font-medium text-brand">
          Score {quiz.my_attempt!.score}/{quiz.my_attempt!.max_score}
        </p>
      ) : null}

      <form onSubmit={(e) => void submit(e)} className="space-y-5">
        {quiz.questions.map((q, qi) => (
          <fieldset
            key={q.id}
            className="rounded-2xl border border-border/80 bg-white/80 p-4"
          >
            <legend className="px-1 text-sm font-medium">
              {qi + 1}. {q.prompt}
            </legend>
            <div className="mt-3 space-y-2">
              {q.options.map((opt, oi) => {
                const selected = answers[q.id] === oi
                const showCorrect =
                  submitted && typeof q.correct_index === "number"
                const isCorrect = showCorrect && oi === q.correct_index
                const isWrong = showCorrect && selected && oi !== q.correct_index
                return (
                  <label
                    key={oi}
                    className={cn(
                      "flex cursor-pointer items-start gap-2 rounded-lg border px-3 py-2 text-sm",
                      selected && !submitted && "border-brand bg-brand-soft/50",
                      isCorrect && "border-emerald-400 bg-emerald-50/80",
                      isWrong && "border-amber-400 bg-amber-50/80",
                      submitted && "cursor-default",
                    )}
                  >
                    <input
                      type="radio"
                      name={`q-${q.id}`}
                      className="mt-1"
                      disabled={submitted || busy}
                      checked={selected}
                      onChange={() =>
                        setAnswers((a) => ({ ...a, [q.id]: oi }))
                      }
                    />
                    <span>{opt}</span>
                  </label>
                )
              })}
            </div>
          </fieldset>
        ))}

        {!submitted ? (
          <Button
            type="submit"
            disabled={
              busy || quiz.questions.some((q) => answers[q.id] === undefined)
            }
          >
            {busy ? (
              <>
                <Loader2 className="size-4 animate-spin" data-icon="inline-start" />
                Submitting…
              </>
            ) : (
              "Submit quick check"
            )}
          </Button>
        ) : (
          <Link to="/app" className="text-sm text-brand">
            Back to home
          </Link>
        )}
      </form>
    </div>
  )
}
