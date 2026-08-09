import { useEffect, useState } from "react"

import { useAuth } from "@/lib/auth"
import { Button } from "@/components/ui/button"
import { api } from "@/lib/api"

type Prefs = {
  email_digests: boolean
  leaderboard_visible: boolean
}

export function SettingsPage() {
  const { session, logout } = useAuth()
  const [prefs, setPrefs] = useState<Prefs | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const p = await api<Prefs>("/api/engagement/preferences/")
        if (!cancelled) setPrefs(p)
      } catch {
        if (!cancelled) setPrefs({ email_digests: true, leaderboard_visible: true })
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  async function savePrefs(next: Prefs) {
    setSaving(true)
    setPrefs(next)
    try {
      const p = await api<Prefs>("/api/engagement/preferences/", {
        method: "PATCH",
        body: JSON.stringify(next),
      })
      setPrefs(p)
    } catch {
      /* keep optimistic */
    } finally {
      setSaving(false)
    }
  }

  if (!session?.school || !session.membership) return null

  const { school, user, membership, can_manage } = session
  const quotaGb = Math.round(Number(school.bucket_quota_bytes || 0) / (1024 ** 3)) || 1
  const isStudent = membership.role === "student"

  return (
    <div className="w-full max-w-3xl space-y-6">
      <div>
        <h1 className="font-display text-3xl tracking-tight">Settings</h1>
        <p className="mt-1 text-muted-foreground">School plan, invites, and notifications.</p>
      </div>

      <section className="rounded-2xl border border-border/80 bg-white/80 p-5 space-y-3">
        <h2 className="font-medium">Account</h2>
        <Row label="Email" value={user.email || user.username} />
        <Row label="Role" value={membership.role_display} />
        <Row label="Organization" value={school.name} />
      </section>

      <section className="rounded-2xl border border-border/80 bg-white/80 p-5 space-y-4">
        <h2 className="font-medium">Notifications</h2>
        <label className="flex items-start gap-3 text-sm">
          <input
            type="checkbox"
            className="mt-1"
            checked={!!prefs?.email_digests}
            disabled={!prefs || saving}
            onChange={(e) =>
              prefs &&
              void savePrefs({ ...prefs, email_digests: e.target.checked })
            }
          />
          <span>
            Email digests
            <span className="block text-xs text-muted-foreground">
              {isStudent
                ? "Weekly summary of streaks, open tests, and quick checks."
                : "Daily summary of class follow-ups and time saved."}
            </span>
          </span>
        </label>
        {isStudent ? (
          <label className="flex items-start gap-3 text-sm">
            <input
              type="checkbox"
              className="mt-1"
              checked={!!prefs?.leaderboard_visible}
              disabled={!prefs || saving}
              onChange={(e) =>
                prefs &&
                void savePrefs({
                  ...prefs,
                  leaderboard_visible: e.target.checked,
                })
              }
            />
            <span>
              Appear on class leaderboards
              <span className="block text-xs text-muted-foreground">
                Only when your teacher turns on a test leaderboard. Others still
                see anonymous ranks.
              </span>
            </span>
          </label>
        ) : null}
      </section>

      <section className="rounded-2xl border border-border/80 bg-white/80 p-5 space-y-3">
        <h2 className="font-medium">Plan</h2>
        <Row label="AI Buckets" value={`${school.max_buckets ?? "—"} max`} />
        <Row label="Size per bucket" value={`${quotaGb} GB`} />
        <Row
          label="User seats"
          value={school.max_users ? String(school.max_users) : "Unlimited"}
        />
        <Row label="Manager seats" value={String(school.max_managers ?? 0)} />
      </section>

      {can_manage ? (
        <section className="rounded-2xl border border-border/80 bg-white/80 p-5">
          <h2 className="font-medium">School join code</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Teachers and students can also self-join with this code.
          </p>
          <p className="mt-4 font-mono text-3xl tracking-[0.2em] text-foreground">
            {school.join_code || "—"}
          </p>
        </section>
      ) : null}

      <Button
        variant="outline"
        onClick={() => {
          void logout()
        }}
      >
        Sign out
      </Button>
    </div>
  )
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-4 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-medium text-foreground">{value}</span>
    </div>
  )
}
