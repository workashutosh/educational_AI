import { useEffect, useState, type FormEvent } from "react"
import { Link } from "react-router-dom"
import { Plus } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { api, type Bucket } from "@/lib/api"
import { useAuth } from "@/lib/auth"

export function BucketsPage() {
  const { session, refresh } = useAuth()
  const [buckets, setBuckets] = useState<Bucket[]>(session?.buckets || [])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [showCreate, setShowCreate] = useState(false)
  const [name, setName] = useState("")
  const [grade, setGrade] = useState("")
  const [creating, setCreating] = useState(false)

  const canManage = !!session?.can_manage
  const maxBuckets = session?.school?.max_buckets ?? 5

  async function load() {
    setLoading(true)
    setError("")
    try {
      const rows = await api<Bucket[]>("/api/buckets/")
      setBuckets(rows)
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load AI Buckets")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function createBucket(e: FormEvent) {
    e.preventDefault()
    setCreating(true)
    setError("")
    try {
      await api<Bucket>("/api/admin/buckets/", {
        method: "POST",
        body: JSON.stringify({ name: name.trim(), grade_level: grade.trim() }),
      })
      setName("")
      setGrade("")
      setShowCreate(false)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create AI Bucket")
    } finally {
      setCreating(false)
    }
  }

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="font-display text-3xl tracking-tight">AI Buckets</h1>
          <p className="mt-1 text-muted-foreground">
            Subject spaces for notes, retrieval, and grounded Q&amp;A.
            {canManage ? ` · ${buckets.length}/${maxBuckets} used` : ""}
          </p>
        </div>
        {canManage ? (
          <Button onClick={() => setShowCreate((v) => !v)}>
            <Plus className="size-4" data-icon="inline-start" />
            New AI Bucket
          </Button>
        ) : null}
      </div>

      {showCreate ? (
        <form
          onSubmit={createBucket}
          className="rounded-2xl border border-border/80 bg-white/80 p-4 space-y-3"
        >
          <p className="text-sm font-medium">Create AI Bucket</p>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="bucket-name">Name</Label>
              <Input
                id="bucket-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. Mathematics"
                required
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="bucket-grade">Grade / level</Label>
              <Input
                id="bucket-grade"
                value={grade}
                onChange={(e) => setGrade(e.target.value)}
                placeholder="e.g. Class 12"
              />
            </div>
          </div>
          <div className="flex gap-2">
            <Button type="submit" disabled={creating || !name.trim()}>
              {creating ? "Creating…" : "Create"}
            </Button>
            <Button type="button" variant="outline" onClick={() => setShowCreate(false)}>
              Cancel
            </Button>
          </div>
        </form>
      ) : null}

      {error ? <p className="text-sm text-destructive">{error}</p> : null}

      {loading ? (
        <p className="text-muted-foreground">Loading AI Buckets…</p>
      ) : buckets.length ? (
        <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {buckets.map((b) => (
            <li key={b.id}>
              <Link
                to={`/app/buckets/${b.id}`}
                className="flex h-full flex-col rounded-2xl border border-border/80 bg-white/80 p-5 transition hover:border-[var(--brand)] hover:bg-[#e6f4ef]/50"
              >
                <div className="mb-4 flex h-12 w-10 items-end justify-center rounded-md border-2 border-[var(--brand)]/40 bg-[#e6f4ef]/80">
                  <div className="mb-1 h-6 w-7 rounded-sm bg-[var(--brand)]/35" />
                </div>
                <p className="font-medium">{b.name}</p>
                <p className="mt-1 text-sm text-muted-foreground">
                  {b.grade_level || "No grade"} · #{b.id}
                </p>
                <p className="mt-auto pt-4 text-sm font-medium text-[var(--brand)]">Open →</p>
              </Link>
            </li>
          ))}
        </ul>
      ) : (
        <div className="rounded-2xl border border-dashed border-border bg-white/60 p-8 text-center text-sm text-muted-foreground">
          {canManage
            ? "Create your first AI Bucket to start uploading notes."
            : "No AI Buckets yet. Ask an admin to grant you access."}
        </div>
      )}
    </div>
  )
}
