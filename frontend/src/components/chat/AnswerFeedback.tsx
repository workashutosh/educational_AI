/** 👍/👎 on an AI answer; 👎 can route the question to a teacher (students). */
import { useState } from "react"
import { Link } from "react-router-dom"
import { HelpCircle, ThumbsDown, ThumbsUp } from "lucide-react"

import { api } from "@/lib/api"
import { cn } from "@/lib/utils"

const REASONS = [
  ["incorrect", "Incorrect"],
  ["incomplete", "Incomplete"],
  ["not_in_notes", "Not from my notes"],
  ["unclear", "Hard to understand"],
] as const

export function AnswerFeedback({
  messageId,
  doubtId,
  isStudent,
}: {
  messageId?: number | null
  doubtId?: number | null
  isStudent: boolean
}) {
  const [rating, setRating] = useState<1 | -1 | null>(null)
  const [askOpen, setAskOpen] = useState(false)
  const [sentDoubt, setSentDoubt] = useState<number | null>(doubtId ?? null)
  const [error, setError] = useState("")

  if (!messageId) return null

  async function send(next: 1 | -1, reason = "", askTeacher = false) {
    setError("")
    try {
      const res = await api<{ doubt_id: number | null }>("/api/learning/feedback/", {
        method: "POST",
        body: JSON.stringify({ message_id: messageId, rating: next, reason, ask_teacher: askTeacher }),
      })
      setRating(next)
      if (res.doubt_id) setSentDoubt(res.doubt_id)
      if (next === 1) setAskOpen(false)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save feedback")
    }
  }

  return (
    <div className="mt-2 space-y-1.5 border-t border-border/50 pt-2 text-xs text-muted-foreground">
      <div className="flex flex-wrap items-center gap-1.5">
        <span>Helpful?</span>
        <button type="button" title="Helpful" onClick={() => void send(1)}
          className={cn("rounded p-1 hover:bg-muted", rating === 1 && "bg-brand-soft text-brand")}>
          <ThumbsUp className="size-3.5" />
        </button>
        <button type="button" title="Not helpful" onClick={() => { setAskOpen(true); void send(-1) }}
          className={cn("rounded p-1 hover:bg-muted", rating === -1 && "bg-red-50 text-red-600")}>
          <ThumbsDown className="size-3.5" />
        </button>
        {sentDoubt ? (
          <Link to={`/app/doubts?doubt=${sentDoubt}`} className="ml-1 flex items-center gap-1 text-brand hover:underline">
            <HelpCircle className="size-3" /> Sent to your teacher
          </Link>
        ) : null}
      </div>
      {askOpen && rating === -1 ? (
        <div className="flex flex-wrap items-center gap-1.5">
          {REASONS.map(([key, label]) => (
            <button key={key} type="button" className="rounded-full border border-border px-2 py-0.5 hover:border-brand"
              onClick={() => void send(-1, key, false)}>
              {label}
            </button>
          ))}
          {isStudent && !sentDoubt ? (
            <button type="button" className="rounded-full border border-brand px-2 py-0.5 text-brand"
              onClick={() => void send(-1, "incomplete", true)}>
              Ask my teacher
            </button>
          ) : null}
        </div>
      ) : null}
      {error ? <p className="text-destructive">{error}</p> : null}
    </div>
  )
}
