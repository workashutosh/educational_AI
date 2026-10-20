import { useCallback, useEffect, useState } from "react"
import { Loader2, UserPlus, Users } from "lucide-react"

import { EmptyState, ErrorText, Field, Loading, PageHeader, Pill, Section, Select, TextInput } from "@/components/app/ui"
import { Button } from "@/components/ui/button"
import { api, errorMessage, type MemberRow } from "@/lib/api"

type ParentRow = {
  id: number
  username: string
  email: string
  full_name: string
  phone: string
  is_active: boolean
  children: { student_id: number; name: string; relationship: string }[]
}

export function ParentsPage() {
  const [parents, setParents] = useState<ParentRow[] | null>(null)
  const [students, setStudents] = useState<MemberRow[]>([])
  const [error, setError] = useState("")
  const [form, setForm] = useState({ username: "", password: "", full_name: "", email: "", phone: "", relationship: "guardian" })
  const [childIds, setChildIds] = useState<number[]>([])
  const [busy, setBusy] = useState(false)
  const [showForm, setShowForm] = useState(false)

  const load = useCallback(async () => {
    try {
      const [p, s] = await Promise.all([
        api<ParentRow[]>("/api/parents/"),
        api<MemberRow[]>("/api/admin/members/?role=student"),
      ])
      setParents(p)
      setStudents(s)
    } catch (err) {
      setError(errorMessage(err))
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  async function create() {
    setBusy(true)
    setError("")
    try {
      await api("/api/parents/", { method: "POST", body: JSON.stringify({ ...form, student_ids: childIds }) })
      setForm({ username: "", password: "", full_name: "", email: "", phone: "", relationship: "guardian" })
      setChildIds([])
      setShowForm(false)
      await load()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  async function toggleActive(p: ParentRow) {
    await api(`/api/parents/${p.id}/`, { method: "PATCH", body: JSON.stringify({ is_active: !p.is_active }) })
    void load()
  }

  return (
    <div className="w-full max-w-4xl space-y-6">
      <PageHeader
        icon={Users}
        title="Parents"
        description="Parent logins see their child's released results, attendance, homework, and progress — read-only. They sign in on the normal login page."
        actions={<Button onClick={() => setShowForm((s) => !s)}><UserPlus className="size-4" /> Add parent</Button>}
      />
      <ErrorText>{error}</ErrorText>
      {showForm ? (
        <Section title="New parent login">
          <div className="grid gap-3 sm:grid-cols-3">
            <Field label="Username"><TextInput value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} /></Field>
            <Field label="Password" hint="At least 8 characters"><TextInput type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} /></Field>
            <Field label="Full name"><TextInput value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} /></Field>
            <Field label="Email" hint="For the weekly summary"><TextInput type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></Field>
            <Field label="Phone"><TextInput value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} /></Field>
            <Field label="Relationship">
              <Select value={form.relationship} onChange={(e) => setForm({ ...form, relationship: e.target.value })}>
                <option value="mother">Mother</option><option value="father">Father</option><option value="guardian">Guardian</option><option value="other">Other</option>
              </Select>
            </Field>
          </div>
          <Field label="Children">
            <div className="flex max-h-40 flex-wrap gap-1.5 overflow-y-auto">
              {students.map((s) => (
                <button
                  key={s.id}
                  type="button"
                  onClick={() => setChildIds((ids) => (ids.includes(s.id) ? ids.filter((i) => i !== s.id) : [...ids, s.id]))}
                  className={`rounded-full border px-2.5 py-1 text-xs ${childIds.includes(s.id) ? "border-brand bg-brand-soft text-brand" : "border-border bg-white"}`}
                >
                  {s.full_name || s.username}
                </button>
              ))}
            </div>
          </Field>
          <Button onClick={() => void create()} disabled={busy || !form.username || form.password.length < 8 || !childIds.length}>
            {busy ? <Loader2 className="size-4 animate-spin" /> : null} Create login
          </Button>
        </Section>
      ) : null}
      {!parents ? <Loading /> : !parents.length ? <EmptyState>No parent accounts yet.</EmptyState> : (
        <ul className="divide-y divide-border/60 rounded-2xl border border-border/80 bg-white/80">
          {parents.map((p) => (
            <li key={p.id} className="flex flex-wrap items-center justify-between gap-2 px-4 py-3 text-sm">
              <div>
                <p className="font-medium">{p.full_name || p.username} <span className="text-xs font-normal text-muted-foreground">@{p.username}</span></p>
                <p className="text-xs text-muted-foreground">
                  {p.children.map((c) => `${c.name} (${c.relationship})`).join(", ")}{p.email ? ` · ${p.email}` : ""}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <Pill tone={p.is_active ? "green" : "gray"}>{p.is_active ? "Active" : "Disabled"}</Pill>
                <Button size="xs" variant="outline" onClick={() => void toggleActive(p)}>{p.is_active ? "Disable" : "Enable"}</Button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
