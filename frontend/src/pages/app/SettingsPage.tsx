import { useAuth } from "@/lib/auth"
import { Button } from "@/components/ui/button"

export function SettingsPage() {
  const { session, logout } = useAuth()
  if (!session?.school || !session.membership) return null

  const { school, user, membership, can_manage } = session
  const quotaGb = Math.round(Number(school.bucket_quota_bytes || 0) / (1024 ** 3)) || 1

  return (
    <div className="w-full max-w-3xl space-y-6">
      <div>
        <h1 className="font-display text-3xl tracking-tight">Settings</h1>
        <p className="mt-1 text-muted-foreground">School plan, invite code, and account.</p>
      </div>

      <section className="rounded-2xl border border-border/80 bg-white/80 p-5 space-y-3">
        <h2 className="font-medium">Account</h2>
        <Row label="Email" value={user.email || user.username} />
        <Row label="Role" value={membership.role_display} />
        <Row label="Organization" value={school.name} />
      </section>

      <section className="rounded-2xl border border-border/80 bg-white/80 p-5 space-y-3">
        <h2 className="font-medium">Plan</h2>
        <Row label="AI Buckets" value={`${school.max_buckets ?? "—"} max`} />
        <Row label="Size per bucket" value={`${quotaGb} GB`} />
        <Row label="User seats" value={String(school.max_users ?? 0)} />
        <Row label="Manager seats" value={String(school.max_managers ?? 0)} />
      </section>

      {can_manage ? (
        <section className="rounded-2xl border border-border/80 bg-white/80 p-5">
          <h2 className="font-medium">School join code</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Teachers and students use this code on the Join screen.
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
