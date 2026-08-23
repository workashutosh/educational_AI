import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react"
import { Navigate } from "react-router-dom"
import { Plus, Search, Users, X } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { api, type Bucket, type MemberRow } from "@/lib/api"
import { useAuth } from "@/lib/auth"
import { cn } from "@/lib/utils"

const ROLE_TABS = [
  { id: "all", label: "All" },
  { id: "admin", label: "Admins" },
  { id: "manager", label: "Managers" },
  { id: "teacher", label: "Teachers" },
  { id: "student", label: "Students" },
] as const

const ROLE_LABEL: Record<string, string> = {
  admin: "Admin",
  manager: "Manager",
  teacher: "Teacher",
  student: "Student",
}

export function MembersPage() {
  const { session } = useAuth()
  const [members, setMembers] = useState<MemberRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [query, setQuery] = useState("")
  const [roleTab, setRoleTab] = useState<string>("all")
  const [showForm, setShowForm] = useState(false)
  const [editing, setEditing] = useState<MemberRow | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError("")
    try {
      const rows = await api<MemberRow[]>("/api/admin/members/")
      setMembers(rows)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load members")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (session?.can_manage) void load()
  }, [session?.can_manage, load])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    return members.filter((m) => {
      if (roleTab !== "all" && m.role !== roleTab) return false
      if (!q) return true
      return `${m.full_name} ${m.username} ${m.email} ${m.role}`.toLowerCase().includes(q)
    })
  }, [members, query, roleTab])

  if (!session?.membership) return null
  if (!session.can_manage) {
    return <Navigate to="/app/students" replace />
  }

  const creatable = session.creatable_roles?.length
    ? session.creatable_roles
    : session.membership.role === "admin"
      ? ["admin", "manager", "teacher", "student"]
      : ["teacher", "student"]

  const schoolBuckets = session.buckets || []

  return (
    <div className="w-full space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 font-display text-3xl tracking-tight">
            <Users className="size-7 text-brand" />
            Members
          </h1>
          <p className="mt-1 text-muted-foreground">
            Create admins, managers, teachers, and students. Grant AI Bucket access per person.
          </p>
        </div>
        <Button onClick={() => setShowForm((v) => !v)} variant={showForm ? "outline" : "default"}>
          {showForm ? (
            <>
              <X className="size-4" data-icon="inline-start" />
              Close
            </>
          ) : (
            <>
              <Plus className="size-4" data-icon="inline-start" />
              Add member
            </>
          )}
        </Button>
      </div>

      {showForm ? (
        <CreateMemberForm
          creatableRoles={creatable}
          buckets={schoolBuckets}
          onCreated={() => {
            void load()
            setShowForm(false)
          }}
          onCancel={() => setShowForm(false)}
        />
      ) : null}

      {editing ? (
        <GrantBucketsPanel
          member={editing}
          buckets={schoolBuckets}
          onClose={() => setEditing(null)}
          onSaved={(updated) => {
            setMembers((prev) =>
              prev.map((m) => (m.id === updated.id ? { ...m, ...updated } : m)),
            )
            setEditing(null)
          }}
        />
      ) : null}

      <div className="flex flex-wrap gap-2">
        {ROLE_TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setRoleTab(t.id)}
            className={cn(
              "rounded-full px-3 py-1 text-sm font-medium transition",
              roleTab === t.id
                ? "bg-brand text-white"
                : "border border-border bg-white text-muted-foreground hover:border-brand/40",
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="relative max-w-md">
        <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          className="pl-8"
          placeholder="Search name, username, email…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>

      {error ? <p className="text-sm text-destructive">{error}</p> : null}
      {loading ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-border/80 bg-white">
          <table className="w-full min-w-[640px] text-left text-sm">
            <thead className="border-b border-border/70 bg-brand-soft/40 text-xs uppercase tracking-wide text-muted-foreground">
              <tr>
                <th className="px-3 py-2.5 font-medium">Name</th>
                <th className="px-3 py-2.5 font-medium">Username</th>
                <th className="px-3 py-2.5 font-medium">Role</th>
                <th className="px-3 py-2.5 font-medium">AI Buckets</th>
                <th className="px-3 py-2.5 font-medium" />
              </tr>
            </thead>
            <tbody>
              {filtered.map((m) => (
                <tr key={m.id} className="border-b border-border/50 last:border-0">
                  <td className="px-3 py-2.5">
                    <p className="font-medium">{m.full_name || "—"}</p>
                    <p className="text-xs text-muted-foreground">{m.email || "—"}</p>
                  </td>
                  <td className="px-3 py-2.5 font-mono text-xs">{m.username}</td>
                  <td className="px-3 py-2.5">
                    <span className="rounded-full bg-brand-soft px-2 py-0.5 text-xs font-medium text-brand">
                      {m.role_display || ROLE_LABEL[m.role] || m.role}
                    </span>
                  </td>
                  <td className="px-3 py-2.5 text-muted-foreground">
                    {m.full_access || m.role === "admin" || m.role === "manager"
                      ? "All buckets"
                      : `${(m.bucket_ids || []).length} granted`}
                  </td>
                  <td className="px-3 py-2.5 text-right">
                    {m.role === "teacher" || m.role === "student" ? (
                      <Button type="button" size="sm" variant="outline" onClick={() => setEditing(m)}>
                        Grant access
                      </Button>
                    ) : (
                      <span className="text-xs text-muted-foreground">Full access</span>
                    )}
                  </td>
                </tr>
              ))}
              {filtered.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-3 py-8 text-center text-muted-foreground">
                    No members match.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function CreateMemberForm({
  creatableRoles,
  buckets,
  onCreated,
  onCancel,
}: {
  creatableRoles: string[]
  buckets: Bucket[]
  onCreated: () => void
  onCancel: () => void
}) {
  const [form, setForm] = useState({
    role: creatableRoles.includes("teacher") ? "teacher" : creatableRoles[0] || "student",
    full_name: "",
    username: "",
    email: "",
    password: "",
    bucket_ids: [] as number[],
  })
  const [error, setError] = useState("")
  const [busy, setBusy] = useState(false)
  const needsBuckets = form.role === "teacher" || form.role === "student"

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setError("")
    setBusy(true)
    try {
      await api("/api/admin/members/create/", {
        method: "POST",
        body: JSON.stringify({
          role: form.role,
          full_name: form.full_name.trim(),
          username: form.username.trim(),
          email: form.email.trim(),
          password: form.password,
          bucket_ids: needsBuckets ? form.bucket_ids : [],
        }),
      })
      onCreated()
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create member")
    } finally {
      setBusy(false)
    }
  }

  function toggleBucket(id: number) {
    setForm((p) => ({
      ...p,
      bucket_ids: p.bucket_ids.includes(id)
        ? p.bucket_ids.filter((x) => x !== id)
        : [...p.bucket_ids, id],
    }))
  }

  return (
    <form
      onSubmit={onSubmit}
      className="space-y-3 rounded-xl border border-border/80 bg-white p-4 shadow-sm"
    >
      <p className="text-sm font-medium">New member</p>
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1.5 sm:col-span-2">
          <Label htmlFor="role">Role</Label>
          <select
            id="role"
            className="flex h-9 w-full rounded-lg border border-input bg-transparent px-2.5 text-sm"
            value={form.role}
            onChange={(e) => setForm((p) => ({ ...p, role: e.target.value }))}
          >
            {creatableRoles.map((r) => (
              <option key={r} value={r}>
                {ROLE_LABEL[r] || r}
              </option>
            ))}
          </select>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="full_name">Full name</Label>
          <Input
            id="full_name"
            value={form.full_name}
            onChange={(e) => setForm((p) => ({ ...p, full_name: e.target.value }))}
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="username">Username</Label>
          <Input
            id="username"
            required
            value={form.username}
            onChange={(e) => setForm((p) => ({ ...p, username: e.target.value }))}
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="email">Email</Label>
          <Input
            id="email"
            type="email"
            value={form.email}
            onChange={(e) => setForm((p) => ({ ...p, email: e.target.value }))}
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="password">Password</Label>
          <Input
            id="password"
            type="password"
            required
            minLength={8}
            value={form.password}
            onChange={(e) => setForm((p) => ({ ...p, password: e.target.value }))}
          />
        </div>
      </div>

      {needsBuckets ? (
        <div className="space-y-2">
          <Label>Grant AI Buckets (optional now — you can edit later)</Label>
          {buckets.length === 0 ? (
            <p className="text-xs text-muted-foreground">No buckets yet — create one under AI Buckets.</p>
          ) : (
            <div className="flex flex-wrap gap-2">
              {buckets.map((b) => {
                const on = form.bucket_ids.includes(b.id)
                return (
                  <button
                    key={b.id}
                    type="button"
                    onClick={() => toggleBucket(b.id)}
                    className={cn(
                      "rounded-full border px-3 py-1 text-xs font-medium",
                      on
                        ? "border-brand bg-brand-soft text-brand"
                        : "border-border text-muted-foreground hover:border-brand/40",
                    )}
                  >
                    {b.name}
                    {b.grade_level ? ` · ${b.grade_level}` : ""}
                  </button>
                )
              })}
            </div>
          )}
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">
          Admins and managers automatically see every AI Bucket — no grants needed.
        </p>
      )}

      {error ? <p className="text-sm text-destructive">{error}</p> : null}
      <div className="flex gap-2">
        <Button type="submit" disabled={busy}>
          {busy ? "Creating…" : "Create member"}
        </Button>
        <Button type="button" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </form>
  )
}

function GrantBucketsPanel({
  member,
  buckets,
  onClose,
  onSaved,
}: {
  member: MemberRow
  buckets: Bucket[]
  onClose: () => void
  onSaved: (m: MemberRow) => void
}) {
  const [selected, setSelected] = useState<number[]>(member.bucket_ids || [])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")

  useEffect(() => {
    setSelected(member.bucket_ids || [])
  }, [member])

  async function save() {
    setBusy(true)
    setError("")
    try {
      const res = await api<{ bucket_ids: number[] }>(
        `/api/admin/members/${member.id}/access/`,
        {
          method: "PUT",
          body: JSON.stringify({ bucket_ids: selected }),
        },
      )
      onSaved({ ...member, bucket_ids: res.bucket_ids || selected, full_access: false })
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not update access")
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-3 rounded-xl border border-brand/30 bg-brand-soft/30 p-4">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="font-medium">
            Grant AI Buckets — {member.full_name || member.username}
          </p>
          <p className="text-xs text-muted-foreground">
            {ROLE_LABEL[member.role]} · only checked buckets will be accessible
          </p>
        </div>
        <Button type="button" size="sm" variant="ghost" onClick={onClose}>
          <X className="size-4" />
        </Button>
      </div>
      <div className="flex flex-wrap gap-2">
        {buckets.map((b) => {
          const on = selected.includes(b.id)
          return (
            <button
              key={b.id}
              type="button"
              onClick={() =>
                setSelected((prev) =>
                  on ? prev.filter((x) => x !== b.id) : [...prev, b.id],
                )
              }
              className={cn(
                "rounded-full border px-3 py-1 text-xs font-medium",
                on
                  ? "border-brand bg-white text-brand"
                  : "border-border bg-white/60 text-muted-foreground",
              )}
            >
              {b.name}
            </button>
          )
        })}
      </div>
      {error ? <p className="text-sm text-destructive">{error}</p> : null}
      <Button type="button" disabled={busy} onClick={() => void save()}>
        {busy ? "Saving…" : "Save access"}
      </Button>
    </div>
  )
}
