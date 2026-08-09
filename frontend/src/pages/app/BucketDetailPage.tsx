import { useCallback, useEffect, useRef, useState, type FormEvent } from "react"
import { Link, useParams, useSearchParams } from "react-router-dom"
import {
  ArrowLeft,
  FileQuestion,
  Loader2,
  MessageSquareText,
  Presentation,
  Upload,
} from "lucide-react"

import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import {
  api,
  apiUpload,
  formatBytes,
  isPendingStatus,
  statusLabel,
  type AccessGrant,
  type Bucket,
  type DocumentKind,
  type DocumentRow,
  type MemberRow,
} from "@/lib/api"
import { useAuth } from "@/lib/auth"
import { cn } from "@/lib/utils"

type Tab = "notes" | "papers" | "access"

export function BucketDetailPage() {
  const { bucketId } = useParams()
  const [searchParams, setSearchParams] = useSearchParams()
  const { session } = useAuth()
  const id = Number(bucketId)
  const tabParam = searchParams.get("tab")
  const tab: Tab =
    tabParam === "papers" || tabParam === "access" ? tabParam : "notes"

  const [bucket, setBucket] = useState<Bucket | null>(null)
  const [error, setError] = useState("")
  const [loading, setLoading] = useState(true)

  const setTab = (t: Tab) => {
    setSearchParams(t === "notes" ? {} : { tab: t })
  }

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      setLoading(true)
      setError("")
      try {
        const buckets = await api<Bucket[]>("/api/buckets/")
        const found = buckets.find((b) => b.id === id) || null
        if (!cancelled) {
          setBucket(found)
          if (!found) setError("AI Bucket not found or you don’t have access.")
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load")
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [id])

  if (loading) {
    return <p className="text-muted-foreground">Loading AI Bucket…</p>
  }

  if (!bucket) {
    return (
      <div className="space-y-3">
        <p className="text-destructive">{error || "Not found"}</p>
        <Link to="/app/buckets" className="text-sm font-medium text-brand">
          ← Back to AI Buckets
        </Link>
      </div>
    )
  }

  return (
    <div className="flex h-full min-h-[calc(100svh-5rem)] w-full flex-col">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <Link
            to="/app/buckets"
            className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-brand"
          >
            <ArrowLeft className="size-3.5" /> AI Buckets
          </Link>
          <h1 className="mt-1 font-display text-3xl tracking-tight">{bucket.name}</h1>
          <p className="text-sm text-muted-foreground">
            {bucket.grade_level || "No grade"} · AI Bucket #{bucket.id}
          </p>
          <BucketInvestmentStrip bucketId={bucket.id} />
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Link
            to={`/app/chat?bucket=${bucket.id}`}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border/80 bg-white px-3 py-1.5 text-sm text-muted-foreground hover:border-brand hover:text-brand"
          >
            <MessageSquareText className="size-3.5" />
            Chat
          </Link>
          <Link
            to={`/app/ppt?bucket=${bucket.id}`}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border/80 bg-white px-3 py-1.5 text-sm text-muted-foreground hover:border-brand hover:text-brand"
          >
            <Presentation className="size-3.5" />
            Create PPT
          </Link>
          <div className="flex gap-1 rounded-xl border border-border/80 bg-white/80 p-1">
            {(
              [
                ["notes", "Notes"],
                ["papers", "Question papers"],
                ...(session?.can_manage ? ([["access", "Access"]] as const) : []),
              ] as const
            ).map(([key, label]) => (
              <button
                key={key}
                type="button"
                onClick={() => setTab(key as Tab)}
                className={cn(
                  "rounded-lg px-3 py-1.5 text-sm font-medium transition",
                  tab === key
                    ? "bg-brand text-white"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {error ? <p className="mb-2 text-sm text-destructive">{error}</p> : null}

      <div className="min-h-0 flex-1">
        {tab === "notes" ? (
          <DocsPanel
            bucketId={bucket.id}
            canUpload={!!session?.can_upload}
            kind="notes"
            title="Notes"
            subtitle="Teaching material · PDF, DOCX, PPTX · used for chat & PPT"
            empty="No notes yet."
          />
        ) : null}
        {tab === "papers" ? (
          <DocsPanel
            bucketId={bucket.id}
            canUpload={!!session?.can_upload}
            kind="question_paper"
            title="Previous year question papers"
            subtitle="Past exam papers · indexed for mock-test generation"
            empty="No question papers yet."
            icon
          />
        ) : null}
        {tab === "access" && session?.can_manage ? <AccessPanel bucketId={bucket.id} /> : null}
      </div>
    </div>
  )
}

function DocsPanel({
  bucketId,
  canUpload,
  kind,
  title,
  subtitle,
  empty,
  icon,
}: {
  bucketId: number
  canUpload: boolean
  kind: DocumentKind
  title: string
  subtitle: string
  empty: string
  icon?: boolean
}) {
  const [docs, setDocs] = useState<DocumentRow[]>([])
  const [error, setError] = useState("")
  const [uploading, setUploading] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)
  const pollRef = useRef<number | null>(null)

  const load = useCallback(async () => {
    const rows = await api<DocumentRow[]>(
      `/api/documents/?bucket_id=${bucketId}&kind=${kind}`,
    )
    setDocs(rows)
    return rows
  }, [bucketId, kind])

  useEffect(() => {
    void load().catch((err) =>
      setError(err instanceof Error ? err.message : "Could not load documents"),
    )
  }, [load])

  useEffect(() => {
    const pending = docs.some((d) => isPendingStatus(d.status))
    if (!pending) {
      if (pollRef.current) window.clearInterval(pollRef.current)
      pollRef.current = null
      return
    }
    pollRef.current = window.setInterval(() => {
      void load().catch(() => undefined)
    }, 2500)
    return () => {
      if (pollRef.current) window.clearInterval(pollRef.current)
    }
  }, [docs, load])

  async function onUpload(file: File) {
    setUploading(true)
    setError("")
    try {
      const form = new FormData()
      form.append("file", file)
      form.append("bucket_id", String(bucketId))
      form.append("kind", kind)
      await apiUpload<DocumentRow>("/api/documents/", form)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed")
    } finally {
      setUploading(false)
      if (fileRef.current) fileRef.current.value = ""
    }
  }

  return (
    <div className="flex h-full min-h-[28rem] flex-col rounded-2xl border border-border/80 bg-white/80">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border/70 px-4 py-3">
        <div>
          <p className="flex items-center gap-1.5 font-medium">
            {icon ? <FileQuestion className="size-4 text-brand" /> : null}
            {title}
          </p>
          <p className="text-xs text-muted-foreground">{subtitle}</p>
        </div>
        {canUpload ? (
          <>
            <input
              ref={fileRef}
              type="file"
              className="hidden"
              accept=".pdf,.docx,.pptx,application/pdf"
              onChange={(e) => {
                const f = e.target.files?.[0]
                if (f) void onUpload(f)
              }}
            />
            <Button
              type="button"
              disabled={uploading}
              onClick={() => fileRef.current?.click()}
            >
              <Upload className="size-4" data-icon="inline-start" />
              {uploading ? "Uploading…" : "Upload"}
            </Button>
          </>
        ) : null}
      </div>
      {error ? <p className="px-4 pt-3 text-sm text-destructive">{error}</p> : null}
      {docs.some((d) => d.status === "queued") &&
      !docs.some((d) => d.status === "parsing" || d.status === "indexing") ? (
        <p className="border-b border-border/60 bg-amber-50/80 px-4 py-2 text-xs text-amber-900">
          Waiting for the indexer. Status moves Waiting → Reading → Crunching →{" "}
          <span className="font-medium text-brand">Ready</span> when a file is
          fully processed. Keep Redis + Celery worker running.
        </p>
      ) : null}
      <div className="flex-1 overflow-y-auto p-4">
        {docs.length ? (
          <ul className="space-y-2">
            {docs.map((d) => (
              <li
                key={d.id}
                className="flex items-center justify-between gap-3 rounded-xl border border-border/70 bg-[#f7f9fd]/80 px-3 py-2.5"
              >
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">{d.original_filename}</p>
                  <p className="text-xs text-muted-foreground">
                    {formatBytes(d.byte_size)}
                    {d.page_count != null ? ` · ${d.page_count} pages` : ""}
                    {d.error_message ? ` · ${d.error_message}` : ""}
                  </p>
                </div>
                <StatusPill status={d.status} />
              </li>
            ))}
          </ul>
        ) : (
          <p className="py-10 text-center text-sm text-muted-foreground">
            {empty}
            {canUpload ? " Upload a file to get started." : ""}
          </p>
        )}
      </div>
    </div>
  )
}

function StatusPill({ status }: { status: string }) {
  const pending = isPendingStatus(status)
  const tone =
    status === "indexed"
      ? "bg-brand-soft text-brand"
      : status === "failed"
        ? "bg-red-50 text-destructive"
        : status === "duplicate"
          ? "bg-amber-50 text-amber-800"
          : status === "indexing"
            ? "bg-sky-50 text-sky-800"
            : status === "parsing"
              ? "bg-violet-50 text-violet-800"
              : "bg-muted text-muted-foreground"
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium",
        tone,
      )}
    >
      {pending ? <Loader2 className="size-3 animate-spin" /> : null}
      {statusLabel(status)}
    </span>
  )
}

function AccessPanel({ bucketId }: { bucketId: number }) {
  const [members, setMembers] = useState<MemberRow[]>([])
  const [grants, setGrants] = useState<AccessGrant[]>([])
  const [memberId, setMemberId] = useState("")
  const [error, setError] = useState("")
  const [busy, setBusy] = useState(false)

  async function load() {
    const [m, g] = await Promise.all([
      api<MemberRow[]>("/api/admin/members/"),
      api<AccessGrant[]>(`/api/admin/buckets/${bucketId}/access/`),
    ])
    setMembers(m.filter((x) => x.role === "teacher" || x.role === "student"))
    setGrants(g)
  }

  useEffect(() => {
    void load().catch((err) =>
      setError(err instanceof Error ? err.message : "Could not load access"),
    )
  }, [bucketId])

  async function grant(e: FormEvent) {
    e.preventDefault()
    if (!memberId) return
    setBusy(true)
    setError("")
    try {
      await api(`/api/admin/buckets/${bucketId}/grant/`, {
        method: "POST",
        body: JSON.stringify({ member_id: Number(memberId) }),
      })
      setMemberId("")
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : "Grant failed")
    } finally {
      setBusy(false)
    }
  }

  async function revoke(mid: number) {
    setBusy(true)
    setError("")
    try {
      await api(`/api/admin/buckets/${bucketId}/grant/${mid}/`, { method: "DELETE" })
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : "Revoke failed")
    } finally {
      setBusy(false)
    }
  }

  const grantedIds = new Set(grants.map((g) => g.member_id))
  const grantable = members.filter((m) => !grantedIds.has(m.id))

  return (
    <div className="space-y-4 rounded-2xl border border-border/80 bg-white/80 p-4">
      <div>
        <p className="font-medium">Access</p>
        <p className="text-sm text-muted-foreground">
          Teachers and students need an explicit grant for this AI Bucket.
        </p>
      </div>

      <form onSubmit={grant} className="flex flex-wrap items-end gap-2">
        <div className="min-w-[200px] flex-1 space-y-1.5">
          <Label htmlFor="member">Member</Label>
          <select
            id="member"
            className="flex h-9 w-full rounded-lg border border-input bg-transparent px-2.5 text-sm"
            value={memberId}
            onChange={(e) => setMemberId(e.target.value)}
          >
            <option value="">Select…</option>
            {grantable.map((m) => (
              <option key={m.id} value={m.id}>
                {m.username} ({m.role_display})
              </option>
            ))}
          </select>
        </div>
        <Button type="submit" disabled={busy || !memberId}>
          Grant access
        </Button>
      </form>

      {error ? <p className="text-sm text-destructive">{error}</p> : null}

      <ul className="space-y-2">
        {grants.length ? (
          grants.map((g) => (
            <li
              key={g.member_id}
              className="flex items-center justify-between rounded-xl border border-border/70 px-3 py-2 text-sm"
            >
              <div>
                <p className="font-medium">{g.username}</p>
                <p className="text-xs text-muted-foreground">
                  {g.role} · {g.email}
                </p>
              </div>
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={busy}
                onClick={() => void revoke(g.member_id)}
              >
                Revoke
              </Button>
            </li>
          ))
        ) : (
          <p className="text-sm text-muted-foreground">No grants yet.</p>
        )}
      </ul>
    </div>
  )
}

function BucketInvestmentStrip({ bucketId }: { bucketId: number }) {
  const [summary, setSummary] = useState("")
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const data = await api<{ summary: string }>(
          `/api/engagement/buckets/${bucketId}/investment/`,
        )
        if (!cancelled) setSummary(data.summary || "")
      } catch {
        if (!cancelled) setSummary("")
      }
    })()
    return () => {
      cancelled = true
    }
  }, [bucketId])
  if (!summary) return null
  return <p className="mt-2 text-xs text-muted-foreground">{summary}</p>
}
