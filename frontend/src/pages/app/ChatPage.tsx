import { useCallback, useEffect, useRef, useState, type FormEvent } from "react"
import { useSearchParams } from "react-router-dom"
import { Loader2, MessageSquarePlus, SendHorizontal } from "lucide-react"

import { RichAnswer } from "@/components/chat/RichAnswer"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { api, type AskSource, type ChatMessage, type ChatSession } from "@/lib/api"
import { useAuth } from "@/lib/auth"
import { cn } from "@/lib/utils"

export function ChatPage() {
  const { session } = useAuth()
  const buckets = session?.buckets || []
  const [searchParams, setSearchParams] = useSearchParams()

  const bucketId = Number(searchParams.get("bucket") || buckets[0]?.id || 0) || null
  const sessionIdParam = searchParams.get("session")
  const activeSessionId = sessionIdParam ? Number(sessionIdParam) : null

  const [sessions, setSessions] = useState<ChatSession[]>([])
  const [history, setHistory] = useState<ChatMessage[]>([])
  const [sessionId, setSessionId] = useState<number | null>(activeSessionId)
  const [input, setInput] = useState("")
  const [busy, setBusy] = useState(false)
  const [loadingSessions, setLoadingSessions] = useState(true)
  const [loadingChat, setLoadingChat] = useState(false)
  const [error, setError] = useState("")
  const bottomRef = useRef<HTMLDivElement>(null)

  const setQuery = useCallback(
    (next: { bucket?: number | null; session?: number | null }) => {
      const params = new URLSearchParams(searchParams)
      if (next.bucket !== undefined) {
        if (next.bucket) params.set("bucket", String(next.bucket))
        else params.delete("bucket")
      }
      if (next.session !== undefined) {
        if (next.session) params.set("session", String(next.session))
        else params.delete("session")
      }
      setSearchParams(params, { replace: true })
    },
    [searchParams, setSearchParams],
  )

  const loadSessions = useCallback(async () => {
    setLoadingSessions(true)
    try {
      const q = bucketId ? `?bucket_id=${bucketId}` : ""
      const rows = await api<ChatSession[]>(`/api/chat/sessions/${q}`)
      setSessions(rows)
    } catch {
      setSessions([])
    } finally {
      setLoadingSessions(false)
    }
  }, [bucketId])

  useEffect(() => {
    void loadSessions()
  }, [loadSessions])

  useEffect(() => {
    if (!bucketId && buckets[0]) {
      setQuery({ bucket: buckets[0].id })
    }
  }, [bucketId, buckets, setQuery])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [history, busy])

  // Skip session→history sync while a send is in flight (avoids wiping the
  // first optimistic user bubble when a brand-new session id hits the URL).
  const busyRef = useRef(false)
  busyRef.current = busy

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      if (!activeSessionId) {
        // Only clear when explicitly leaving a session (e.g. New chat), not mid-send
        if (!busyRef.current) {
          setSessionId(null)
          setHistory([])
        }
        return
      }
      // Don't overwrite in-progress first message with an empty server session
      if (busyRef.current) {
        setSessionId(activeSessionId)
        return
      }
      setLoadingChat(true)
      setError("")
      try {
        const detail = await api<ChatSession>(`/api/chat/sessions/${activeSessionId}/`)
        if (cancelled) return
        setSessionId(detail.id)
        setHistory(
          (detail.messages || []).map((m) => ({
            role: m.role,
            content: m.content,
            sources: m.sources,
          })),
        )
        if (detail.bucket && detail.bucket !== bucketId) {
          setQuery({ bucket: detail.bucket, session: detail.id })
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Could not load chat")
          setHistory([])
        }
      } finally {
        if (!cancelled) setLoadingChat(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [activeSessionId]) // eslint-disable-line react-hooks/exhaustive-deps

  async function ensureSession(): Promise<number> {
    if (sessionId) return sessionId
    if (!bucketId) throw new Error("Select an AI Bucket first")
    const s = await api<ChatSession>("/api/chat/sessions/", {
      method: "POST",
      body: JSON.stringify({ bucket_id: bucketId, title: "New chat" }),
    })
    // Keep session id in state only — do NOT put it in the URL yet.
    // Updating the URL here reloads an empty session and wipes the first message.
    setSessionId(s.id)
    return s.id
  }

  async function send(e?: FormEvent) {
    e?.preventDefault()
    const q = input.trim()
    if (!q || busy || !bucketId) return
    setInput("")
    setError("")
    setBusy(true)
    const nextHistory = [...history, { role: "user" as const, content: q }]
    setHistory(nextHistory)
    try {
      const sid = await ensureSession()
      const res = await api<{
        answer: string
        sources: AskSource[]
        session?: { id: number; title: string }
      }>("/api/ask/", {
        method: "POST",
        body: JSON.stringify({
          query: q,
          bucket_id: bucketId,
          session_id: sid,
          history: nextHistory.slice(0, -1).map((m) => ({
            role: m.role,
            content: m.content,
          })),
        }),
      })
      const finalSid = res.session?.id || sid
      setSessionId(finalSid)
      setHistory([
        ...nextHistory,
        { role: "assistant", content: res.answer, sources: res.sources || [] },
      ])
      // Sync URL after messages are on screen + persisted
      setQuery({ session: finalSid })
      void loadSessions()
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ask failed")
      setHistory((h) => h.slice(0, -1))
      setInput(q)
    } finally {
      setBusy(false)
    }
  }

  function newChat() {
    setHistory([])
    setSessionId(null)
    setError("")
    setQuery({ session: null })
  }

  const activeBucket = buckets.find((b) => b.id === bucketId)

  const isStudent = session?.membership?.role === "student"

  if (!buckets.length) {
    return (
      <div className="flex h-full items-center justify-center p-8 text-center text-muted-foreground">
        <div>
          <p className="font-medium text-foreground">No AI Buckets available</p>
          <p className="mt-1 text-sm">
            {isStudent
              ? "Ask your teacher to grant you access to an AI Bucket, then you can chat with its notes here."
              : "Create or get access to an AI Bucket to start chatting."}
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="flex h-full min-h-0 w-full">
      {/* History rail */}
      <aside className="flex w-64 shrink-0 flex-col border-r border-border/80 bg-white/90">
        <div className="space-y-3 border-b border-border/70 p-3">
          <Button type="button" className="w-full justify-start gap-2" onClick={newChat}>
            <MessageSquarePlus className="size-4" />
            New chat
          </Button>
          <div>
            <label className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
              AI Bucket
            </label>
            <select
              value={bucketId || ""}
              onChange={(e) => {
                const id = Number(e.target.value)
                setQuery({ bucket: id, session: null })
                setHistory([])
                setSessionId(null)
              }}
              className="w-full rounded-lg border border-input bg-transparent px-2.5 py-2 text-sm outline-none focus-visible:border-ring"
            >
              {buckets.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.name}
                </option>
              ))}
            </select>
          </div>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-2">
          <p className="px-2 pb-2 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
            History
          </p>
          {loadingSessions ? (
            <p className="px-2 text-xs text-muted-foreground">Loading…</p>
          ) : sessions.length ? (
            <ul className="space-y-0.5">
              {sessions.map((s) => (
                <li key={s.id}>
                  <button
                    type="button"
                    onClick={() => setQuery({ bucket: s.bucket, session: s.id })}
                    className={cn(
                      "w-full rounded-lg px-2.5 py-2 text-left transition",
                      activeSessionId === s.id
                        ? "bg-[#e6f4ef] text-[var(--brand)]"
                        : "hover:bg-muted text-foreground",
                    )}
                  >
                    <p className="truncate text-sm font-medium">
                      {s.title?.trim() || "Untitled chat"}
                    </p>
                    <p className="truncate text-[11px] text-muted-foreground">
                      {s.bucket_name || `Bucket #${s.bucket}`}
                    </p>
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="px-2 text-xs text-muted-foreground">No chats yet for this bucket.</p>
          )}
        </div>
      </aside>

      {/* Chat stage — full remaining width */}
      <section className="flex min-w-0 flex-1 flex-col bg-[#f3f6f8]">
        <header className="flex items-center justify-between gap-3 border-b border-border/70 bg-white/80 px-4 py-3">
          <div className="min-w-0">
            <h1 className="truncate font-display text-xl tracking-tight">
              {activeBucket?.name || "Chat"}
            </h1>
            <p className="text-xs text-muted-foreground">
              {isStudent
                ? "Ask questions from notes in your assigned AI Buckets"
                : "Grounded answers from indexed notes"}
              {sessionId ? ` · session #${sessionId}` : ""}
            </p>
          </div>
          <Button type="button" variant="outline" size="sm" onClick={newChat}>
            New chat
          </Button>
        </header>

        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-4 sm:px-6 lg:px-10">
          {loadingChat ? (
            <p className="text-sm text-muted-foreground">Loading chat…</p>
          ) : null}
          {!history.length && !busy && !loadingChat ? (
            <div className="mx-auto max-w-lg py-16 text-center text-sm text-muted-foreground">
              <p className="font-medium text-foreground">Ask anything from this AI Bucket</p>
              <p className="mt-2">Your chats are saved in History on the left.</p>
              <div className="mt-4 flex flex-wrap justify-center gap-2">
                {[
                  "Summarize the key topics",
                  "Give an example from the notes",
                  "What should I revise first?",
                ].map((q) => (
                  <button
                    key={q}
                    type="button"
                    className="rounded-full border border-border bg-white px-3 py-1.5 text-xs hover:border-[var(--brand)]"
                    onClick={() => setInput(q)}
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>
          ) : null}
          {history.map((m, i) => (
            <div
              key={i}
              className={cn("flex", m.role === "user" ? "justify-end" : "justify-start")}
            >
              <div
                className={cn(
                  "max-w-[min(48rem,92%)] rounded-2xl px-3.5 py-2.5 text-sm leading-relaxed",
                  m.role === "user"
                    ? "whitespace-pre-wrap bg-[#1e3a5f] text-white"
                    : "border border-border/80 bg-white text-foreground",
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

        {error ? <p className="px-4 pb-1 text-sm text-destructive sm:px-6">{error}</p> : null}
        <form
          onSubmit={send}
          className="flex gap-2 border-t border-border/70 bg-white/90 px-4 py-3 sm:px-6 lg:px-10"
        >
          <Input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask a question…"
            disabled={busy || !bucketId}
            className="h-11"
          />
          <Button type="submit" disabled={busy || !input.trim() || !bucketId} size="icon" className="size-11">
            <SendHorizontal className="size-4" />
          </Button>
        </form>
      </section>
    </div>
  )
}
