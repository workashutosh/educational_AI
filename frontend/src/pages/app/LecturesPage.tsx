import { useCallback, useEffect, useState, type FormEvent } from "react"
import { Link, Navigate } from "react-router-dom"
import { Loader2, Plus, Video } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { api } from "@/lib/api"
import { useAuth } from "@/lib/auth"
import { cn } from "@/lib/utils"

type LectureRow = {
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
}

function toLocalInputValue(d: Date) {
  const pad = (n: number) => String(n).padStart(2, "0")
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export function LecturesPage() {
  const { session } = useAuth()
  const isStudent = session?.membership?.role === "student"
  const buckets = session?.buckets || []

  const [rows, setRows] = useState<LectureRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [showForm, setShowForm] = useState(false)
  const [teamsOk, setTeamsOk] = useState(false)
  const [busy, setBusy] = useState(false)

  const [bucketId, setBucketId] = useState(String(buckets[0]?.id || ""))
  const [title, setTitle] = useState("")
  const [description, setDescription] = useState("")
  const [startsAt, setStartsAt] = useState(() => {
    const d = new Date()
    d.setMinutes(d.getMinutes() + 15)
    return toLocalInputValue(d)
  })
  const [endsAt, setEndsAt] = useState(() => {
    const d = new Date()
    d.setMinutes(d.getMinutes() + 75)
    return toLocalInputValue(d)
  })
  const [createTeams, setCreateTeams] = useState(true)
  const [manualUrl, setManualUrl] = useState("")

  const load = useCallback(async () => {
    setLoading(true)
    setError("")
    try {
      const list = await api<LectureRow[]>("/api/lectures/")
      setRows(list)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load lectures")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    if (isStudent) return
    void api<{ configured: boolean }>("/api/lectures/teams/status/")
      .then((r) => setTeamsOk(!!r.configured))
      .catch(() => setTeamsOk(false))
  }, [isStudent])

  async function create(e: FormEvent) {
    e.preventDefault()
    if (!bucketId || !title.trim()) return
    setBusy(true)
    setError("")
    try {
      const created = await api<LectureRow>("/api/lectures/", {
        method: "POST",
        body: JSON.stringify({
          bucket_id: Number(bucketId),
          title: title.trim(),
          description: description.trim(),
          starts_at: new Date(startsAt).toISOString(),
          ends_at: new Date(endsAt).toISOString(),
          create_teams_meeting: createTeams,
          teams_join_url: manualUrl.trim(),
        }),
      })
      setShowForm(false)
      setTitle("")
      setDescription("")
      setManualUrl("")
      await load()
      window.location.href = `/app/lectures/${created.id}`
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create lecture")
    } finally {
      setBusy(false)
    }
  }

  if (!session?.membership) return null

  return (
    <div className="w-full space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 font-display text-3xl tracking-tight">
            <Video className="size-7 text-[var(--brand)]" />
            {isStudent ? "My Lectures" : "Lectures"}
          </h1>
          <p className="mt-1 text-muted-foreground">
            {isStudent
              ? "Join class meetings and use AI with the lecture notes."
              : "Create a Teams meeting, open the lecture room with notes + AI assist."}
          </p>
        </div>
        {!isStudent ? (
          <Button
            onClick={() => setShowForm((v) => !v)}
            variant={showForm ? "outline" : "default"}
          >
            {showForm ? (
              "Cancel"
            ) : (
              <>
                <Plus className="size-4" data-icon="inline-start" />
                New lecture
              </>
            )}
          </Button>
        ) : null}
      </div>

      {!isStudent ? (
        <p
          className={cn(
            "rounded-xl border px-3 py-2 text-sm",
            teamsOk
              ? "border-[#cfe8dc] bg-[#e6f4ef]/60 text-[var(--brand)]"
              : "border-amber-200 bg-amber-50/80 text-amber-900",
          )}
        >
          {teamsOk
            ? "Microsoft Teams (Graph) is configured — new lectures can auto-create a join link."
            : "Teams Graph is not configured yet. You can still create lectures and paste a Teams join URL, or set MS_GRAPH_* in backend .env."}
        </p>
      ) : null}

      {error ? <p className="text-sm text-destructive">{error}</p> : null}

      {showForm && !isStudent ? (
        <form
          onSubmit={create}
          className="space-y-4 rounded-2xl border border-border/80 bg-white/80 p-5"
        >
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5 sm:col-span-2">
              <Label htmlFor="lec-title">Title</Label>
              <Input
                id="lec-title"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                required
                disabled={busy}
                placeholder="e.g. Integrals — revision lecture"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="lec-bucket">AI Bucket (notes)</Label>
              <select
                id="lec-bucket"
                value={bucketId}
                onChange={(e) => setBucketId(e.target.value)}
                disabled={busy}
                required
                className="flex h-9 w-full rounded-lg border border-input bg-transparent px-2.5 text-sm"
              >
                {buckets.map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.name}
                    {b.grade_level ? ` · ${b.grade_level}` : ""}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-1.5 sm:col-span-2">
              <Label htmlFor="lec-desc">Description (optional)</Label>
              <textarea
                id="lec-desc"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                rows={2}
                disabled={busy}
                className="flex w-full rounded-lg border border-input bg-transparent px-2.5 py-2 text-sm"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="lec-start">Starts</Label>
              <Input
                id="lec-start"
                type="datetime-local"
                value={startsAt}
                onChange={(e) => setStartsAt(e.target.value)}
                required
                disabled={busy}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="lec-end">Ends</Label>
              <Input
                id="lec-end"
                type="datetime-local"
                value={endsAt}
                onChange={(e) => setEndsAt(e.target.value)}
                required
                disabled={busy}
              />
            </div>
            <label className="flex items-start gap-2 text-sm sm:col-span-2">
              <input
                type="checkbox"
                checked={createTeams}
                onChange={(e) => setCreateTeams(e.target.checked)}
                disabled={busy}
                className="mt-1"
              />
              <span>
                Create Microsoft Teams meeting via Graph
                <span className="block text-xs text-muted-foreground">
                  Requires Azure app + OnlineMeetings.ReadWrite.All. Uncheck to paste a
                  link only.
                </span>
              </span>
            </label>
            <div className="space-y-1.5 sm:col-span-2">
              <Label htmlFor="lec-url">Teams join URL (optional / fallback)</Label>
              <Input
                id="lec-url"
                type="url"
                value={manualUrl}
                onChange={(e) => setManualUrl(e.target.value)}
                disabled={busy}
                placeholder="https://teams.microsoft.com/l/meetup-join/..."
              />
            </div>
          </div>
          <Button type="submit" disabled={busy || !buckets.length}>
            {busy ? (
              <>
                <Loader2 className="size-4 animate-spin" data-icon="inline-start" />
                Creating…
              </>
            ) : (
              "Create lecture"
            )}
          </Button>
          {!buckets.length ? (
            <p className="text-sm text-muted-foreground">
              Create or get access to an AI Bucket first.
            </p>
          ) : null}
        </form>
      ) : null}

      {loading ? (
        <p className="text-sm text-muted-foreground">Loading lectures…</p>
      ) : rows.length ? (
        <ul className="grid gap-3 lg:grid-cols-2">
          {rows.map((l) => (
            <li key={l.id}>
              <Link
                to={`/app/lectures/${l.id}`}
                className="block rounded-2xl border border-border/80 bg-white/80 p-4 transition hover:border-[var(--brand)]"
              >
                <div className="flex items-start justify-between gap-2">
                  <p className="font-medium">{l.title}</p>
                  <StatusBadge status={l.status} />
                </div>
                <p className="mt-1 text-xs text-muted-foreground">
                  {l.bucket_name} · {formatWhen(l.starts_at)}
                </p>
                {l.teams_join_url ? (
                  <p className="mt-2 text-xs text-[var(--brand)]">Teams link ready</p>
                ) : l.teams_error ? (
                  <p className="mt-2 text-xs text-amber-800">Teams: {l.teams_error}</p>
                ) : (
                  <p className="mt-2 text-xs text-muted-foreground">No join link yet</p>
                )}
              </Link>
            </li>
          ))}
        </ul>
      ) : (
        <p className="rounded-2xl border border-dashed border-border/80 py-12 text-center text-sm text-muted-foreground">
          {isStudent
            ? "No lectures assigned yet."
            : "No lectures yet. Create one to open a Teams meeting with notes + AI."}
        </p>
      )}
    </div>
  )
}

function StatusBadge({ status }: { status: string }) {
  const tone =
    status === "live"
      ? "bg-red-50 text-red-700"
      : status === "ended"
        ? "bg-muted text-muted-foreground"
        : status === "cancelled"
          ? "bg-amber-50 text-amber-800"
          : "bg-[#e6f4ef] text-[var(--brand)]"
  return (
    <span className={cn("rounded-full px-2 py-0.5 text-[11px] font-medium capitalize", tone)}>
      {status}
    </span>
  )
}

function formatWhen(iso: string) {
  try {
    return new Date(iso).toLocaleString(undefined, {
      dateStyle: "medium",
      timeStyle: "short",
    })
  } catch {
    return iso
  }
}

/** Students without bucket access should not hit create — page is shared. */
export function LecturesPageGate() {
  const { session } = useAuth()
  if (!session?.membership) return <Navigate to="/login" replace />
  return <LecturesPage />
}
