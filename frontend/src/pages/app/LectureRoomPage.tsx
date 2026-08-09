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
  suggestions?: string[]
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
  const [joinUrlDraft, setJoinUrlDraft] = useState("")
  const bottomRef = useRef<HTMLDivElement>(null)
  const lectureChatRef = useRef<HTMLDivElement>(null)

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
    const el = lectureChatRef.current
    if (el) el.scrollTop = el.scrollHeight
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
      setError(
        err instanceof Error
          ? err.message
          : "Couldn’t create a Teams link. Connect Microsoft first, then try again.",
      )
    } finally {
      setBusy(false)
    }
  }

  async function saveJoinUrl(e?: FormEvent) {
    e?.preventDefault()
    const url = joinUrlDraft.trim()
    if (!room || !url) return
    setBusy(true)
    setError("")
    try {
      const updated = await api<Room>(`/api/lectures/${id}/`, {
        method: "PATCH",
        body: JSON.stringify({ teams_join_url: url }),
      })
      setRoom({ ...room, ...updated, notes: room.notes, ai: room.ai })
      setJoinUrlDraft("")
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save join URL")
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
      const res = await api<{
        answer: string
        sources: AskSource[]
        suggestions?: string[]
      }>("/api/ask/", {
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
        {
          role: "assistant",
          content: res.answer,
          sources: res.sources || [],
          suggestions: res.suggestions || [],
        },
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
        <Link to="/app/lectures" className="text-sm text-brand">
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
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {room.teams_join_url ? (
            <a
              href={room.teams_join_url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1.5 rounded-lg bg-brand px-3 py-2 text-sm font-medium text-white"
            >
              <Video className="size-4" />
              Join Teams
              <ExternalLink className="size-3.5 opacity-80" />
            </a>
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

      {room.can_manage && !room.teams_join_url ? (
        <div className="space-y-3 rounded-xl border border-amber-200 bg-amber-50/80 px-4 py-3">
          <div className="flex flex-wrap items-center gap-2">
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium text-amber-950">Create Teams meeting</p>
              <p className="text-xs text-amber-900/80">
                Uses your connected Microsoft account (Lectures → Connect Microsoft).
                Sign in with a work/school account that has Teams.
              </p>
            </div>
            <Button type="button" disabled={busy} onClick={() => void retryTeams()}>
              {busy ? (
                <>
                  <Loader2 className="size-4 animate-spin" data-icon="inline-start" />
                  Creating…
                </>
              ) : (
                "Create meeting link"
              )}
            </Button>
            <Link
              to="/app/lectures"
              className="text-xs text-amber-950 underline underline-offset-2"
            >
              Connect Microsoft
            </Link>
          </div>
          <form
            onSubmit={(e) => void saveJoinUrl(e)}
            className="flex flex-wrap items-end gap-2 border-t border-amber-200/80 pt-3"
          >
            <div className="min-w-[16rem] flex-1 space-y-1">
              <p className="text-xs font-medium text-amber-950">Or paste a join URL</p>
              <Input
                type="url"
                value={joinUrlDraft}
                onChange={(e) => setJoinUrlDraft(e.target.value)}
                placeholder="https://teams.microsoft.com/l/meetup-join/..."
                disabled={busy}
              />
            </div>
            <Button type="submit" variant="outline" disabled={busy || !joinUrlDraft.trim()}>
              Save link
            </Button>
          </form>
        </div>
      ) : null}

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
                    className="rounded-xl border border-border/70 bg-[#f7f9fd]/80 px-3 py-2.5"
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
          <div ref={lectureChatRef} className="min-h-0 flex-1 space-y-3 overflow-y-auto overscroll-contain px-3 py-3">
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
                    <>
                      <RichAnswer content={m.content} sources={m.sources} />
                      {m.suggestions?.length && i === history.length - 1 ? (
                        <div className="mt-2 flex flex-wrap gap-1.5 border-t border-border/50 pt-2">
                          {m.suggestions.map((s) => (
                            <button
                              key={s}
                              type="button"
                              className="rounded-lg border border-border px-2 py-1 text-xs hover:border-brand"
                              onClick={() => setInput(s)}
                            >
                              {s}
                            </button>
                          ))}
                        </div>
                      ) : null}
                    </>
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
