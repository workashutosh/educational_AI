import { useCallback, useEffect, useState, type FormEvent } from "react"
import { Link, Navigate, useSearchParams } from "react-router-dom"
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

type TeamsStatus = {
  configured: boolean
  oauth_ready: boolean
  connected: boolean
  ms_upn?: string
  display_name?: string
}

function toLocalInputValue(d: Date) {
  const pad = (n: number) => String(n).padStart(2, "0")
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export function LecturesPage() {
  const { session } = useAuth()
  const isStudent = session?.membership?.role === "student"
  const buckets = session?.buckets || []
  const [searchParams, setSearchParams] = useSearchParams()

  const [rows, setRows] = useState<LectureRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [banner, setBanner] = useState("")
  const [showForm, setShowForm] = useState(false)
  const [teams, setTeams] = useState<TeamsStatus | null>(null)
  const [busy, setBusy] = useState(false)
  const [connecting, setConnecting] = useState(false)

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

  const loadTeams = useCallback(async () => {
    if (isStudent) return
    try {
      const r = await api<TeamsStatus>("/api/lectures/teams/status/")
      setTeams(r)
      if (r.connected) setCreateTeams(true)
    } catch {
      setTeams(null)
    }
  }, [isStudent])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    void loadTeams()
  }, [loadTeams])

  useEffect(() => {
    const teamsParam = searchParams.get("teams")
    if (!teamsParam) return
    if (teamsParam === "connected") {
      setBanner("Microsoft account connected. New lectures can create Teams links automatically.")
      void loadTeams()
    } else if (teamsParam === "error") {
      setError("Couldn’t connect Microsoft. Please try again in a moment.")
    }
    setSearchParams({}, { replace: true })
  }, [searchParams, setSearchParams, loadTeams])

  async function connectMicrosoft() {
    setConnecting(true)
    setError("")
    try {
      const r = await api<{ authorize_url: string }>("/api/lectures/teams/connect/")
      window.location.href = r.authorize_url
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start Microsoft login")
      setConnecting(false)
    }
  }

  async function disconnectMicrosoft() {
    setBusy(true)
    setError("")
    try {
      await api("/api/lectures/teams/disconnect/", { method: "POST" })
      setTeams((t) => (t ? { ...t, connected: false, ms_upn: "", display_name: "" } : t))
      setBanner("Microsoft account disconnected.")
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not disconnect")
    } finally {
      setBusy(false)
    }
  }

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

  const msConnected = !!teams?.connected
  const oauthReady = !!teams?.oauth_ready

  return (
    <div className="w-full space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 font-display text-3xl tracking-tight">
            <Video className="size-7 text-brand" />
            {isStudent ? "My Lectures" : "Lectures"}
          </h1>
          <p className="mt-1 text-muted-foreground">
            {isStudent
              ? "Join class meetings and use AI with the lecture notes."
              : "Connect Microsoft once, then create lectures with Teams links from here."}
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
        <div
          className={cn(
            "flex flex-wrap items-center justify-between gap-3 rounded-xl border px-3 py-3 text-sm",
            msConnected
              ? "border-emerald-200 bg-emerald-50/80 text-emerald-950"
              : "border-amber-200 bg-amber-50/80 text-amber-950",
          )}
        >
          <div className="min-w-0 flex-1">
            {msConnected ? (
              <>
                <p className="font-medium">Microsoft connected</p>
                <p className="text-xs opacity-90">
                  Meetings will be created as{" "}
                  {teams?.display_name || teams?.ms_upn || "your account"}.
                  {teams?.ms_upn ? ` (${teams.ms_upn})` : ""}
                </p>
              </>
            ) : oauthReady ? (
              <>
                <p className="font-medium">Connect Microsoft to create meeting links</p>
                <p className="text-xs opacity-90">
                  Sign in with a work/school account that has Teams. Then new lectures
                  get a join URL automatically — no paste.
                </p>
              </>
            ) : (
              <>
                <p className="font-medium">Teams auto-links aren’t available yet</p>
                <p className="text-xs opacity-90">
                  You can still create lectures and paste a Teams meeting link manually.
                </p>
              </>
            )}
          </div>
          <div className="flex flex-wrap gap-2">
            {msConnected ? (
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={busy}
                onClick={() => void disconnectMicrosoft()}
              >
                Disconnect
              </Button>
            ) : oauthReady ? (
              <Button
                type="button"
                size="sm"
                disabled={connecting}
                onClick={() => void connectMicrosoft()}
              >
                {connecting ? (
                  <>
                    <Loader2 className="size-4 animate-spin" data-icon="inline-start" />
                    Opening Microsoft…
                  </>
                ) : (
                  "Connect Microsoft"
                )}
              </Button>
            ) : null}
          </div>
        </div>
      ) : null}

      {banner ? (
        <p className="rounded-xl border border-emerald-200 bg-emerald-50/80 px-3 py-2 text-sm text-emerald-950">
          {banner}
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
                disabled={busy || !msConnected}
                className="mt-1"
              />
              <span>
                Create Teams meeting link from ClassKit
                <span className="block text-xs text-muted-foreground">
                  {msConnected
                    ? "Uses your connected Microsoft account (recommended)."
                    : "Connect Microsoft above first — then this creates the join URL for you."}
                </span>
              </span>
            </label>
            {!msConnected ? (
              <div className="space-y-1.5 sm:col-span-2">
                <Label htmlFor="lec-url">Teams join URL (fallback only)</Label>
                <Input
                  id="lec-url"
                  type="url"
                  value={manualUrl}
                  onChange={(e) => setManualUrl(e.target.value)}
                  disabled={busy}
                  placeholder="https://teams.microsoft.com/l/meetup-join/..."
                  required={!createTeams}
                />
              </div>
            ) : null}
          </div>
          <Button
            type="submit"
            disabled={busy || !buckets.length || (createTeams && !msConnected && !manualUrl.trim())}
          >
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
                className="block rounded-2xl border border-border/80 bg-white/80 p-4 transition hover:border-brand"
              >
                <div className="flex items-start justify-between gap-2">
                  <p className="font-medium">{l.title}</p>
                  <StatusBadge status={l.status} />
                </div>
                <p className="mt-1 text-xs text-muted-foreground">
                  {l.bucket_name} · {formatWhen(l.starts_at)}
                </p>
                {l.teams_join_url ? (
                  <p className="mt-2 text-xs text-brand">Teams link ready</p>
                ) : l.teams_error ? (
                  <p className="mt-2 text-xs text-amber-800">
                    No meeting link yet — connect Microsoft and create one from the lecture.
                  </p>
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
            : "No lectures yet. Connect Microsoft, then create a lecture with a Teams link."}
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
          : "bg-brand-soft text-brand"
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
