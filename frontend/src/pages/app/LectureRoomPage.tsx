import { useCallback, useEffect, useRef, useState, type FormEvent } from "react"
import { Link, useParams } from "react-router-dom"
import {
  ArrowLeft,
  ExternalLink,
  Loader2,
  SendHorizontal,
  Video,
} from "lucide-react"

import { RichAnswer } from "@/components/chat/RichAnswer"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { api, formatBytes, type AskSource } from "@/lib/api"
import { useAuth } from "@/lib/auth"
import { cn } from "@/lib/utils"

type NoteRow = {
  id: number
  original_filename: string
  page_count: number | null
  byte_size: number | null
}

type Room = {
  id: number
  title: string
  description: string
  status: string
  bucket_id: number
  bucket_name: string
  starts_at: string
  ends_at: string
  teams_join_url: string
  teams_created: boolean
  teams_error: string
  can_manage: boolean
  notes: NoteRow[]
  ai: { bucket_id: number; hint: string }
}

type Msg = {
  role: "user" | "assistant"
  content: string
  sources?: AskSource[]
}

export function LectureRoomPage() {
  const { lectureId } = useParams()
  const id = Number(lectureId)
  const { session } = useAuth()
  const [room, setRoom] = useState<Room | null>(null)
  const [error, setError] = useState("")
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [history, setHistory] = useState<Msg[]>([])
  const [input, setInput] = useState("")
  const bottomRef = useRef<HTMLDivElement>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError("")
    try {
      const data = await api<Room>(`/api/lectures/${id}/room/`)
      setRoom(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load lecture")
      setRoom(null)
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [history, busy])

  async function goLive() {
    if (!room) return
    setBusy(true)
    try {
      const updated = await api<Room>(`/api/lectures/${id}/go-live/`, { method: "POST" })
      setRoom({ ...room, ...updated, notes: room.notes, ai: room.ai })
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not go live")
    } finally {
      setBusy(false)
    }
  }

  async function endLecture() {
    if (!room) return
    setBusy(true)
    try {
      const updated = await api<Room>(`/api/lectures/${id}/end/`, { method: "POST" })
      setRoom({ ...room, ...updated, notes: room.notes, ai: room.ai })
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not end lecture")
    } finally {
      setBusy(false)
    }
  }

  async function retryTeams() {
    if (!room) return
    setBusy(true)
    setError("")
    try {
      const updated = await api<Room>(`/api/lectures/${id}/create-teams/`, {
        method: "POST",
      })
      setRoom({ ...room, ...updated, notes: room.notes, ai: room.ai })
    } catch (err) {
      setError(err instanceof Error ? err.message : "Teams create failed")
    } finally {
      setBusy(false)
    }
  }

  async function ask(e?: FormEvent) {
    e?.preventDefault()
    const q = input.trim()
    if (!q || !room || busy) return
    setInput("")
    setBusy(true)
    const next = [...history, { role: "user" as const, content: q }]
    setHistory(next)
    try {
      const res = await api<{ answer: string; sources: AskSource[] }>("/api/ask/", {
        method: "POST",
        body: JSON.stringify({
          query: q,
          bucket_id: room.bucket_id,
          history: next.slice(0, -1).map((m) => ({
            role: m.role,
            content: m.content,
          })),
        }),
      })
      setHistory([
        ...next,
        { role: "assistant", content: res.answer, sources: res.sources || [] },
      ])
    } catch (err) {
      setError(err instanceof Error ? err.message : "AI ask failed")
      setHistory((h) => h.slice(0, -1))
      setInput(q)
    } finally {
      setBusy(false)
    }
  }

  if (loading) {
    return <p className="text-muted-foreground">Opening lecture room…</p>
  }

  if (!room) {
    return (
      <div className="space-y-3">
        <p className="text-destructive">{error || "Not found"}</p>
        <Link to="/app/lectures" className="text-sm text-[var(--brand)]">
          ← Lectures
        </Link>
      </div>
    )
  }

  return (
    <div className="flex h-full min-h-[calc(100svh-5rem)] w-full flex-col gap-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <Link
            to="/app/lectures"
            className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
          >
            <ArrowLeft className="size-4" />
            Lectures
          </Link>
          <h1 className="mt-1 font-display text-3xl tracking-tight">{room.title}</h1>
          <p className="text-sm text-muted-foreground">
            {room.bucket_name} ·{" "}
            <span className="capitalize">{room.status}</span>
            {session?.membership?.role !== "student" && room.teams_error
              ? ` · ${room.teams_error}`
              : ""}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {room.teams_join_url ? (
            <a
              href={room.teams_join_url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--brand)] px-3 py-2 text-sm font-medium text-white"
            >
              <Video className="size-4" />
              Join Teams
              <ExternalLink className="size-3.5 opacity-80" />
            </a>
          ) : room.can_manage ? (
            <Button type="button" variant="outline" disabled={busy} onClick={() => void retryTeams()}>
              Create Teams meeting
            </Button>
          ) : null}
          {room.can_manage && room.status !== "live" && room.status !== "ended" ? (
            <Button type="button" disabled={busy} onClick={() => void goLive()}>
              Go live
            </Button>
          ) : null}
          {room.can_manage && room.status === "live" ? (
            <Button type="button" variant="outline" disabled={busy} onClick={() => void endLecture()}>
              End lecture
            </Button>
          ) : null}
        </div>
      </div>

      {error ? <p className="text-sm text-destructive">{error}</p> : null}

      <div className="grid min-h-0 flex-1 gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(20rem,28rem)]">
        <section className="flex min-h-[22rem] flex-col rounded-2xl border border-border/80 bg-white/80">
          <div className="border-b border-border/70 px-4 py-3">
            <p className="font-medium">Lecture notes</p>
            <p className="text-xs text-muted-foreground">
              Indexed notes from this AI Bucket — keep these open while you teach on Teams.
            </p>
          </div>
          <div className="flex-1 overflow-y-auto p-4">
            {room.notes.length ? (
              <ul className="space-y-2">
                {room.notes.map((n) => (
                  <li
                    key={n.id}
                    className="rounded-xl border border-border/70 bg-[#f7faf8]/80 px-3 py-2.5"
                  >
                    <p className="truncate text-sm font-medium">{n.original_filename}</p>
                    <p className="text-xs text-muted-foreground">
                      {formatBytes(n.byte_size)}
                      {n.page_count != null ? ` · ${n.page_count} pages` : ""}
                    </p>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="py-10 text-center text-sm text-muted-foreground">
                No indexed notes in this bucket yet. Upload notes under AI Buckets → Notes.
              </p>
            )}
          </div>
          {room.description ? (
            <div className="border-t border-border/70 px-4 py-3 text-sm text-muted-foreground">
              {room.description}
            </div>
          ) : null}
        </section>

        <section className="flex min-h-[22rem] flex-col rounded-2xl border border-border/80 bg-white/80">
          <div className="border-b border-border/70 px-4 py-3">
            <p className="font-medium">AI lecture assist</p>
            <p className="text-xs text-muted-foreground">{room.ai.hint}</p>
          </div>
          <div className="flex-1 space-y-3 overflow-y-auto px-3 py-3">
            {!history.length ? (
              <p className="px-1 py-6 text-center text-sm text-muted-foreground">
                Ask for explanations, examples, or quick checks from the notes while you teach.
              </p>
            ) : null}
            {history.map((m, i) => (
              <div
                key={i}
                className={cn("flex", m.role === "user" ? "justify-end" : "justify-start")}
              >
                <div
                  className={cn(
                    "max-w-[95%] rounded-2xl px-3 py-2 text-sm",
                    m.role === "user"
                      ? "whitespace-pre-wrap bg-[#1e3a5f] text-white"
                      : "border border-border/80 bg-white",
                  )}
                >
                  {m.role === "assistant" ? (
                    <RichAnswer content={m.content} sources={m.sources} />
                  ) : (
                    m.content
                  )}
                </div>
              </div>
            ))}
            {busy ? (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="size-4 animate-spin" /> Thinking…
              </div>
            ) : null}
            <div ref={bottomRef} />
          </div>
          <form
            onSubmit={(e) => void ask(e)}
            className="flex gap-2 border-t border-border/70 p-3"
          >
            <Input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask from the lecture notes…"
              disabled={busy}
            />
            <Button type="submit" disabled={busy || !input.trim()} size="icon">
              <SendHorizontal className="size-4" />
            </Button>
          </form>
        </section>
      </div>
    </div>
  )
}
