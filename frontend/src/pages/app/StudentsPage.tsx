import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react"
import { Navigate } from "react-router-dom"
import { GraduationCap, Plus, Search, X } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { api, type MemberRow } from "@/lib/api"
import { useAuth } from "@/lib/auth"
import { cn } from "@/lib/utils"

const PAGE_SIZE = 10

export function StudentsPage() {
  const { session } = useAuth()
  const [students, setStudents] = useState<MemberRow[]>([])
  const [loading, setLoading] = useState(true)
  const [listError, setListError] = useState("")
  const [query, setQuery] = useState("")
  const [page, setPage] = useState(1)
  const [showForm, setShowForm] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setListError("")
    const fetchOnce = () => api<MemberRow[]>("/api/admin/members/?role=student")
    try {
      let rows: MemberRow[]
      try {
        rows = await fetchOnce()
      } catch (err) {
        // Dev server often returns 502 while Django auto-reloads — retry once.
        const msg = err instanceof Error ? err.message : ""
        if (!/502|failed to fetch|network/i.test(msg)) throw err
        await new Promise((r) => setTimeout(r, 800))
        rows = await fetchOnce()
      }
      setStudents(rows)
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Could not load students"
      setListError(
        /502/i.test(msg)
          ? "Backend was restarting — refresh in a moment."
          : msg,
      )
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (session?.can_create_students) void load()
  }, [session?.can_create_students, load])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return students
    return students.filter((s) => {
      const hay = `${s.full_name} ${s.username} ${s.email}`.toLowerCase()
      return hay.includes(q)
    })
  }, [students, query])

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  const safePage = Math.min(page, totalPages)
  const pageRows = filtered.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE)

  useEffect(() => {
    setPage(1)
  }, [query])

  if (!session?.membership) return null
  if (!session.can_create_students) {
    return <Navigate to="/app" replace />
  }

  const buckets = session.buckets || []

  return (
    <div className="w-full space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 font-display text-3xl tracking-tight">
            <GraduationCap className="size-7 text-brand" />
            Students
          </h1>
          <p className="mt-1 text-muted-foreground">
            Roster of student logins. Create accounts and share credentials with them.
          </p>
        </div>
        <Button
          onClick={() => setShowForm((v) => !v)}
          variant={showForm ? "outline" : "default"}
        >
          {showForm ? (
            <>
              <X className="size-4" data-icon="inline-start" />
              Close
            </>
          ) : (
            <>
              <Plus className="size-4" data-icon="inline-start" />
              Add student
            </>
          )}
        </Button>
      </div>

      {showForm ? (
        <CreateStudentForm
          buckets={buckets}
          onCreated={() => {
            void load()
            setShowForm(false)
          }}
          onCancel={() => setShowForm(false)}
        />
      ) : null}

      <section className="space-y-4">
        <div className="flex flex-wrap items-end gap-3">
          <div className="relative min-w-[16rem] flex-1">
            <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Filter by name, username, or email…"
              className="pl-9"
              aria-label="Filter students"
            />
          </div>
          <p className="pb-1 text-xs text-muted-foreground">
            {loading
              ? "Loading…"
              : `${filtered.length} of ${students.length} student${students.length === 1 ? "" : "s"}`}
          </p>
        </div>

        {listError ? <p className="text-sm text-destructive">{listError}</p> : null}

        <div className="overflow-x-auto rounded-2xl border border-border/80 bg-white/80">
          <table className="w-full min-w-[36rem] text-left text-sm">
            <thead className="border-b border-border/70 bg-brand-soft/40 text-xs tracking-wide text-muted-foreground uppercase">
              <tr>
                <th className="px-4 py-3 font-medium">Name</th>
                <th className="px-4 py-3 font-medium">Username</th>
                <th className="px-4 py-3 font-medium">Email</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={3} className="px-4 py-10 text-center text-muted-foreground">
                    Loading…
                  </td>
                </tr>
              ) : pageRows.length ? (
                pageRows.map((s) => (
                  <tr
                    key={s.id}
                    className="border-b border-border/50 last:border-0 hover:bg-brand-soft/25"
                  >
                    <td className="px-4 py-3 font-medium">
                      {s.full_name || "—"}
                    </td>
                    <td className="px-4 py-3 text-muted-foreground">@{s.username}</td>
                    <td className="px-4 py-3 text-muted-foreground">{s.email || "—"}</td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={3} className="px-4 py-10 text-center text-muted-foreground">
                    {query.trim()
                      ? "No students match this filter."
                      : "No students yet. Click Add student to create one."}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {!loading && filtered.length > 0 ? (
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-xs text-muted-foreground">
              Page {safePage} of {totalPages}
              {" · "}
              Showing {(safePage - 1) * PAGE_SIZE + 1}–
              {Math.min(safePage * PAGE_SIZE, filtered.length)}
            </p>
            <div className="flex items-center gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={safePage <= 1}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
              >
                Previous
              </Button>
              <div className="flex items-center gap-1">
                {Array.from({ length: totalPages }, (_, i) => i + 1)
                  .filter((n) => n === 1 || n === totalPages || Math.abs(n - safePage) <= 1)
                  .reduce<(number | "…")[]>((acc, n, idx, arr) => {
                    if (idx > 0 && n - (arr[idx - 1] as number) > 1) acc.push("…")
                    acc.push(n)
                    return acc
                  }, [])
                  .map((n, i) =>
                    n === "…" ? (
                      <span key={`e-${i}`} className="px-1 text-xs text-muted-foreground">
                        …
                      </span>
                    ) : (
                      <button
                        key={n}
                        type="button"
                        onClick={() => setPage(n)}
                        className={cn(
                          "flex size-8 items-center justify-center rounded-lg text-xs font-medium transition",
                          n === safePage
                            ? "bg-brand text-white"
                            : "text-muted-foreground hover:bg-muted",
                        )}
                      >
                        {n}
                      </button>
                    ),
                  )}
              </div>
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={safePage >= totalPages}
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              >
                Next
              </Button>
            </div>
          </div>
        ) : null}
      </section>
    </div>
  )
}

function CreateStudentForm({
  buckets,
  onCreated,
  onCancel,
}: {
  buckets: { id: number; name: string; grade_level: string }[]
  onCreated: () => void
  onCancel: () => void
}) {
  const [error, setError] = useState("")
  const [ok, setOk] = useState("")
  const [busy, setBusy] = useState(false)
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [fullName, setFullName] = useState("")
  const [email, setEmail] = useState("")
  const [bucketId, setBucketId] = useState("")

  async function createStudent(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError("")
    setOk("")
    try {
      const body: Record<string, unknown> = {
        username: username.trim(),
        password,
        full_name: fullName.trim(),
        email: email.trim(),
      }
      if (bucketId) body.bucket_id = Number(bucketId)
      const created = await api<MemberRow & { bucket_granted?: number | null }>(
        "/api/admin/students/",
        { method: "POST", body: JSON.stringify(body) },
      )
      setOk(
        `Created ${created.username}. Share username + password so they can sign in.`,
      )
      setUsername("")
      setPassword("")
      setFullName("")
      setEmail("")
      setBucketId("")
      onCreated()
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create student")
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="space-y-4 rounded-2xl border border-border/80 bg-white/80 p-5">
      <div className="flex items-center justify-between gap-2">
        <h2 className="font-medium">Add student</h2>
        <Button type="button" variant="ghost" size="sm" onClick={onCancel}>
          Cancel
        </Button>
      </div>
      <form
        onSubmit={createStudent}
        className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3"
      >
        <div className="space-y-1.5">
          <Label htmlFor="stu-user">Username</Label>
          <Input
            id="stu-user"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="off"
            required
            disabled={busy}
            placeholder="e.g. riya.class12"
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="stu-pass">Password</Label>
          <Input
            id="stu-pass"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="new-password"
            required
            minLength={8}
            disabled={busy}
            placeholder="Min. 8 characters"
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="stu-name">Full name (optional)</Label>
          <Input
            id="stu-name"
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
            disabled={busy}
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="stu-email">Email (optional)</Label>
          <Input
            id="stu-email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            disabled={busy}
          />
        </div>
        {buckets.length ? (
          <div className="space-y-1.5 sm:col-span-2 lg:col-span-1">
            <Label htmlFor="stu-bucket">Grant AI Bucket access (optional)</Label>
            <select
              id="stu-bucket"
              value={bucketId}
              onChange={(e) => setBucketId(e.target.value)}
              disabled={busy}
              className="flex h-9 w-full rounded-lg border border-input bg-transparent px-2.5 text-sm"
            >
              <option value="">None — grant later from the bucket Access tab</option>
              {buckets.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.name}
                  {b.grade_level ? ` · ${b.grade_level}` : ""}
                </option>
              ))}
            </select>
          </div>
        ) : null}
        <div className="flex items-end sm:col-span-2 lg:col-span-3">
          <Button
            type="submit"
            disabled={busy || !username.trim() || password.length < 8}
          >
            {busy ? "Creating…" : "Create student"}
          </Button>
        </div>
      </form>
      {error ? <p className="text-sm text-destructive">{error}</p> : null}
      {ok ? <p className="text-sm text-brand">{ok}</p> : null}
    </section>
  )
}
