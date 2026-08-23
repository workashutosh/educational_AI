import { useState, type FormEvent } from "react"
import { Link, Navigate, useNavigate } from "react-router-dom"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { api, type Session } from "@/lib/api"
import { useAuth } from "@/lib/auth"
import { AuthShell } from "@/pages/AuthShell"

export function JoinPage() {
  const { session, setSession, loading } = useAuth()
  const navigate = useNavigate()
  const [form, setForm] = useState({
    join_code: "",
    role: "teacher",
    full_name: "",
    username: "",
    email: "",
    password: "",
    password_confirm: "",
  })
  const [error, setError] = useState("")
  const [submitting, setSubmitting] = useState(false)

  if (!loading && session?.membership) {
    return <Navigate to="/app" replace />
  }

  function set(field: string, value: string) {
    setForm((prev) => ({ ...prev, [field]: value }))
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setError("")
    setSubmitting(true)
    try {
      const data = await api<Session>("/api/auth/register/join/", {
        method: "POST",
        body: JSON.stringify({
          ...form,
          join_code: form.join_code.trim().toUpperCase(),
        }),
        token: null,
      })
      setSession(data)
      navigate("/app")
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not join school")
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <AuthShell
      title="Join your school"
      subtitle="Ask your admin for the join code. Teachers upload after bucket access is granted."
      footer={
        <div className="flex flex-wrap items-center justify-center gap-x-3 gap-y-1">
          <Link className="underline underline-offset-2" to="/onboard">
            Create school
          </Link>
          <span className="text-white/30">·</span>
          <Link className="underline underline-offset-2" to="/login">
            Sign in
          </Link>
        </div>
      }
    >
      <form className="space-y-3.5" onSubmit={onSubmit}>
        <div className="space-y-1.5">
          <Label htmlFor="join_code">School join code</Label>
          <Input
            id="join_code"
            value={form.join_code}
            onChange={(e) => set("join_code", e.target.value.toUpperCase())}
            placeholder="8-character code"
            className="uppercase tracking-wider"
            required
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="role">I am a</Label>
          <select
            id="role"
            className="flex h-9 w-full rounded-lg border border-input bg-transparent px-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
            value={form.role}
            onChange={(e) => set("role", e.target.value)}
          >
            <option value="teacher">Teacher</option>
            <option value="student">Student</option>
          </select>
        </div>
        <Field label="Your name" id="full_name" value={form.full_name} onChange={set} />
        <Field label="Username" id="username" value={form.username} onChange={set} autoComplete="username" required />
        <Field label="Email" id="email" type="email" value={form.email} onChange={set} autoComplete="email" required />
        <Field label="Password" id="password" type="password" value={form.password} onChange={set} autoComplete="new-password" required />
        <Field label="Confirm password" id="password_confirm" type="password" value={form.password_confirm} onChange={set} autoComplete="new-password" required />
        {error ? <p className="text-sm text-destructive">{error}</p> : null}
        <Button className="w-full" type="submit" disabled={submitting}>
          {submitting ? "Creating account…" : "Create account"}
        </Button>
      </form>
    </AuthShell>
  )
}

function Field({
  label,
  id,
  value,
  onChange,
  type = "text",
  autoComplete,
  required,
}: {
  label: string
  id: string
  value: string
  onChange: (id: string, value: string) => void
  type?: string
  autoComplete?: string
  required?: boolean
}) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        type={type}
        value={value}
        autoComplete={autoComplete}
        required={required}
        onChange={(e) => onChange(id, e.target.value)}
      />
    </div>
  )
}
