import { useCallback, useEffect, useState } from "react"
import { Link, useNavigate, useSearchParams } from "react-router-dom"
import { Layers, Loader2, Plus, Sparkles, Trash2 } from "lucide-react"

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
  Stat,
  TextInput,
} from "@/components/app/ui"
import { RichAnswer } from "@/components/chat/RichAnswer"
import { Button, buttonVariants } from "@/components/ui/button"
import { api, errorMessage, type DocumentRow } from "@/lib/api"
import { useAuth } from "@/lib/auth"
import { useRole, useTopics } from "@/lib/features"
import { cn } from "@/lib/utils"

type Deck = {
  id: number
  bucket: number
  bucket_name: string
  title: string
  visibility: "bucket" | "private"
  owner_name: string
  card_count: number
  can_edit: boolean
  progress: { total: number; seen: number; learned: number; to_study: number } | null
}

type StudyCard = { id: number; deck_id: number; deck_title: string; front: string; back: string; state: "new" | "review" }
type Queue = { due_count: number; new_count: number; cards: StudyCard[] }

export function FlashcardsPage() {
  const { session } = useAuth()
  const { isStaff } = useRole()
  const [bucketId, setBucketId] = useState<number | null>(null)
  const [decks, setDecks] = useState<Deck[] | null>(null)
  const [stats, setStats] = useState<{ reviews_today: number; reviews_7d: number } | null>(null)
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState("")

  const load = useCallback(async () => {
    try {
      const q = bucketId ? `?bucket_id=${bucketId}` : ""
      const [d, s] = await Promise.all([
        api<Deck[]>(`/api/learning/decks/${q}`),
        api<{ reviews_today: number; reviews_7d: number }>("/api/learning/study/stats/"),
      ])
      setDecks(d)
      setStats(s)
    } catch (err) {
      setError(errorMessage(err))
    }
  }, [bucketId])

  useEffect(() => {
    void load()
  }, [load])

  async function remove(deck: Deck) {
    await api(`/api/learning/decks/${deck.id}/`, { method: "DELETE" })
    void load()
  }

  const toStudy = decks?.reduce((s, d) => s + (d.progress?.to_study || 0), 0) || 0

  return (
    <div className="w-full space-y-6">
      <PageHeader
        icon={Layers}
        title="Flashcards"
        description="Spaced repetition: cards come back just before you'd forget them. A few minutes a day keeps your streak going."
        actions={
          <>
            <Button variant="outline" onClick={() => setCreating((c) => !c)} disabled={!session?.buckets?.length}>
              <Sparkles className="size-4" /> New deck
            </Button>
            <Link to={`/app/flashcards/study${bucketId ? `?bucket=${bucketId}` : ""}`} className={cn(buttonVariants())}>
              Study now{toStudy ? ` (${toStudy})` : ""}
            </Link>
          </>
        }
      />
      <ErrorText>{error}</ErrorText>
      {stats ? (
        <div className="grid max-w-xl grid-cols-3 gap-3">
          <Stat label="Reviewed today" value={stats.reviews_today} />
          <Stat label="This week" value={stats.reviews_7d} />
          <Stat label="To study" value={toStudy} />
        </div>
      ) : null}
      {creating ? <CreateDeck shared={isStaff} onDone={() => { setCreating(false); void load() }} /> : null}

      <Field label="AI Bucket"><BucketSelect value={bucketId} onChange={setBucketId} allowAll className="max-w-xs" /></Field>
      {!decks ? <Loading /> : !decks.length ? (
        <EmptyState>No decks yet. Generate one from your notes in a few seconds.</EmptyState>
      ) : (
        <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {decks.map((d) => (
            <li key={d.id} className="rounded-2xl border border-border/80 bg-white/80 p-4">
              <div className="flex items-start justify-between gap-2">
                <p className="font-medium leading-snug">{d.title}</p>
                <Pill tone={d.visibility === "bucket" ? "green" : "gray"}>{d.visibility === "bucket" ? "Shared" : "Private"}</Pill>
              </div>
              <p className="mt-1 text-xs text-muted-foreground">{d.bucket_name} · {d.card_count} cards · by {d.owner_name || "—"}</p>
              {d.progress ? (
                <div className="mt-3 h-2 overflow-hidden rounded-full bg-muted">
                  <div className="h-full bg-brand" style={{ width: `${d.progress.total ? (100 * d.progress.learned) / d.progress.total : 0}%` }} />
                </div>
              ) : null}
              <div className="mt-3 flex items-center justify-between">
                <span className="text-xs text-muted-foreground">{d.progress?.learned || 0} learned · {d.progress?.to_study || 0} to study</span>
                <div className="flex gap-1">
                  {d.can_edit ? (
                    <Button size="icon-sm" variant="ghost" onClick={() => void remove(d)} title="Delete deck"><Trash2 className="size-3.5" /></Button>
                  ) : null}
                  <Link to={`/app/flashcards/study?deck=${d.id}`} className={cn(buttonVariants({ size: "sm" }))}>Study</Link>
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function CreateDeck({ shared, onDone }: { shared: boolean; onDone: () => void }) {
  const { session } = useAuth()
  const [bucketId, setBucketId] = useState<number | null>(session?.buckets?.[0]?.id ?? null)
  const { topics } = useTopics(shared ? bucketId : null)
  const [docs, setDocs] = useState<DocumentRow[]>([])
  const [mode, setMode] = useState<"ai" | "manual">("ai")
  const [form, setForm] = useState({ prompt: "", title: "", topic_id: "", document_id: "", count: 15, visibility: "bucket" })
  const [cards, setCards] = useState([{ front: "", back: "" }])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")

  useEffect(() => {
    if (!bucketId) return
    api<DocumentRow[]>(`/api/documents/?bucket_id=${bucketId}&kind=notes&status=indexed`).then(setDocs).catch(() => setDocs([]))
  }, [bucketId])

  async function save() {
    setBusy(true)
    setError("")
    try {
      if (mode === "ai") {
        await api("/api/learning/decks/generate/", {
          method: "POST",
          body: JSON.stringify({
            bucket_id: bucketId,
            prompt: form.prompt,
            title: form.title,
            count: form.count,
            topic_id: form.topic_id ? Number(form.topic_id) : null,
            document_id: form.document_id ? Number(form.document_id) : null,
            visibility: form.visibility,
          }),
        })
      } else {
        await api("/api/learning/decks/", {
          method: "POST",
          body: JSON.stringify({ bucket_id: bucketId, title: form.title, visibility: form.visibility, cards: cards.filter((c) => c.front.trim() && c.back.trim()) }),
        })
      }
      onDone()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Section
      title="New deck"
      actions={
        <Select value={mode} onChange={(e) => setMode(e.target.value as "ai" | "manual")} className="w-44">
          <option value="ai">Generate with AI</option>
          <option value="manual">Write my own</option>
        </Select>
      }
    >
      <div className="grid gap-3 sm:grid-cols-3">
        <Field label="AI Bucket"><BucketSelect value={bucketId} onChange={setBucketId} /></Field>
        <Field label="Title"><TextInput value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} placeholder={mode === "ai" ? "Optional — AI names it" : ""} /></Field>
        {shared ? (
          <Field label="Who can study it">
            <Select value={form.visibility} onChange={(e) => setForm({ ...form, visibility: e.target.value })}>
              <option value="bucket">Everyone in this AI Bucket</option>
              <option value="private">Only me</option>
            </Select>
          </Field>
        ) : null}
      </div>
      {mode === "ai" ? (
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="Topic / instructions"><TextInput value={form.prompt} onChange={(e) => setForm({ ...form, prompt: e.target.value })} placeholder="e.g. Key formulas of electrostatics" /></Field>
          <Field label="…or one document">
            <Select value={form.document_id} onChange={(e) => setForm({ ...form, document_id: e.target.value })}>
              <option value="">Any notes</option>
              {docs.map((d) => <option key={d.id} value={d.id}>{d.original_filename}</option>)}
            </Select>
          </Field>
          {shared && topics.length ? (
            <Field label="Topic tag">
              <Select value={form.topic_id} onChange={(e) => setForm({ ...form, topic_id: e.target.value })}>
                <option value="">None</option>
                {topics.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
              </Select>
            </Field>
          ) : (
            <Field label="Cards"><TextInput type="number" min={3} max={40} value={form.count} onChange={(e) => setForm({ ...form, count: Number(e.target.value) })} /></Field>
          )}
        </div>
      ) : (
        <div className="space-y-2">
          {cards.map((c, i) => (
            <div key={i} className="grid gap-2 sm:grid-cols-2">
              <TextInput placeholder="Front" value={c.front} onChange={(e) => setCards(cards.map((x, j) => (j === i ? { ...x, front: e.target.value } : x)))} />
              <TextInput placeholder="Back" value={c.back} onChange={(e) => setCards(cards.map((x, j) => (j === i ? { ...x, back: e.target.value } : x)))} />
            </div>
          ))}
          <Button variant="outline" size="sm" onClick={() => setCards([...cards, { front: "", back: "" }])}><Plus className="size-3.5" /> Card</Button>
        </div>
      )}
      <ErrorText>{error}</ErrorText>
      <Button onClick={() => void save()} disabled={busy || !bucketId || (mode === "ai" ? !form.prompt.trim() && !form.document_id && !form.topic_id : !form.title.trim())}>
        {busy ? <Loader2 className="size-4 animate-spin" /> : null} Create deck
      </Button>
    </Section>
  )
}

export function FlashcardStudyPage() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const deck = params.get("deck")
  const bucket = params.get("bucket")
  const [queue, setQueue] = useState<Queue | null>(null)
  const [index, setIndex] = useState(0)
  const [flipped, setFlipped] = useState(false)
  const [reviewed, setReviewed] = useState(0)
  const [error, setError] = useState("")

  const load = useCallback(async () => {
    const q = new URLSearchParams({ limit: "30" })
    if (deck) q.set("deck_id", deck)
    if (bucket) q.set("bucket_id", bucket)
    try {
      setQueue(await api<Queue>(`/api/learning/study/?${q}`))
      setIndex(0)
      setFlipped(false)
    } catch (err) {
      setError(errorMessage(err))
    }
  }, [deck, bucket])

  useEffect(() => {
    void load()
  }, [load])

  const card = queue?.cards[index]

  async function grade(button: "again" | "hard" | "good" | "easy") {
    if (!card) return
    try {
      await api("/api/learning/study/review/", { method: "POST", body: JSON.stringify({ card_id: card.id, button }) })
    } catch (err) {
      setError(errorMessage(err))
      return
    }
    setReviewed((r) => r + 1)
    setFlipped(false)
    if (queue && index + 1 >= queue.cards.length) void load()
    else setIndex((i) => i + 1)
  }

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (!card) return
      if (e.key === " ") { e.preventDefault(); setFlipped((f) => !f) }
      if (flipped && ["1", "2", "3", "4"].includes(e.key)) {
        void grade((["again", "hard", "good", "easy"] as const)[Number(e.key) - 1])
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  })

  return (
    <div className="mx-auto w-full max-w-2xl space-y-5">
      <div className="flex items-center justify-between">
        <Button variant="ghost" onClick={() => navigate("/app/flashcards")}>← Decks</Button>
        <p className="text-sm text-muted-foreground">{reviewed} reviewed this session</p>
      </div>
      <ErrorText>{error}</ErrorText>
      {!queue ? <Loading /> : !card ? (
        <EmptyState>
          All caught up! 🎉 Nothing is due right now.
          <div className="mt-3"><Link to="/app/flashcards" className={cn(buttonVariants({ size: "sm", variant: "outline" }))}>Back to decks</Link></div>
        </EmptyState>
      ) : (
        <>
          <p className="text-center text-xs text-muted-foreground">
            {card.deck_title} · {card.state === "new" ? "New card" : "Review"} · {index + 1}/{queue.cards.length}
          </p>
          <button
            type="button"
            onClick={() => setFlipped((f) => !f)}
            className="flex min-h-64 w-full flex-col items-center justify-center rounded-3xl border border-border/80 bg-white p-8 text-center shadow-sm transition hover:border-brand"
          >
            <div className="text-lg"><RichAnswer content={card.front} /></div>
            {flipped ? (
              <div className="mt-6 w-full border-t border-border/70 pt-6 text-base text-brand"><RichAnswer content={card.back} /></div>
            ) : (
              <p className="mt-6 text-xs text-muted-foreground">Tap or press Space to reveal</p>
            )}
          </button>
          {flipped ? (
            <div className="grid grid-cols-4 gap-2">
              {([["again", "Again", "bg-red-50 text-red-700"], ["hard", "Hard", "bg-amber-50 text-amber-800"], ["good", "Good", "bg-brand-soft text-brand"], ["easy", "Easy", "bg-sky-50 text-sky-800"]] as const).map(([key, label, tone], i) => (
                <button key={key} type="button" onClick={() => void grade(key)} className={cn("rounded-xl px-3 py-3 text-sm font-medium", tone)}>
                  {label}<span className="block text-[10px] opacity-70">{i + 1}</span>
                </button>
              ))}
            </div>
          ) : null}
        </>
      )}
    </div>
  )
}
