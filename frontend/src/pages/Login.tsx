import { useState, type FormEvent } from "react"
import { Link, Navigate, useNavigate } from "react-router-dom"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { api, type Session } from "@/lib/api"
import { useAuth } from "@/lib/auth"
import { AuthShell } from "@/pages/AuthShell"

export function LoginPage() {
  const { session, setSession, loading } = useAuth()
  const navigate = useNavigate()
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [error, setError] = useState("")
  const [submitting, setSubmitting] = useState(false)

  if (!loading && session?.membership) {
    return <Navigate to="/app" replace />
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setError("")
    setSubmitting(true)
    try {
      const data = await api<Session>("/api/auth/login/", {
        method: "POST",
        body: JSON.stringify({ username, password }),
        token: null,
      })
      setSession(data)
      navigate(data.account_type === "parent" && !data.membership ? "/parent" : "/app")
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign in failed")
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <AuthShell
      title="Log in"
      subtitle="Teachers, managers, students, and school admins use the same login."
      footer={
        <div className="flex flex-wrap items-center justify-center gap-x-3 gap-y-1">
          <Link className="underline underline-offset-2" to="/onboard">
            Create school
          </Link>
          <span className="text-white/30">·</span>
          <Link className="underline underline-offset-2" to="/join">
            Join with code
          </Link>
        </div>
      }
    >
      <form className="space-y-4" onSubmit={onSubmit}>
        <div className="space-y-2">
          <Label htmlFor="username">Username or email</Label>
          <Input
            id="username"
            autoComplete="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
            placeholder="Phone number / email address"
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="password">Password</Label>
          <Input
            id="password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            placeholder="Password"
          />
        </div>
        {error ? <p className="text-sm text-destructive">{error}</p> : null}
        <Button className="w-full" size="lg" type="submit" disabled={submitting}>
          {submitting ? "Signing in…" : "Log in"}
        </Button>
      </form>
    </AuthShell>
  )
}
