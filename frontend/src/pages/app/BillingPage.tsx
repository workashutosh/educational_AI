import { useCallback, useEffect, useState } from "react"
import { CreditCard, Loader2 } from "lucide-react"

import { ErrorText, Field, Loading, PageHeader, Pill, Section, Select, Stat } from "@/components/app/ui"
import { Button } from "@/components/ui/button"
import { api, errorMessage, formatBytes, formatDate } from "@/lib/api"
import { useAuth } from "@/lib/auth"
import { useRole } from "@/lib/features"
import { cn } from "@/lib/utils"

type Plan = {
  code: string
  name: string
  price_inr_monthly: number
  is_paid: boolean
  max_buckets: number
  bucket_quota_bytes: number
  max_users: number
  max_managers: number
  monthly_ai_tokens: number
  features: string[]
}

type Subscription = {
  plan: Plan
  status: string
  current_period_end: string | null
  online_payments: boolean
  usage: { buckets: number; members: number }
}

type Payment = { id: number; plan_code: string; months: number; amount_paise: number; status: string; created_at: string; paid_at: string | null }

type Usage = {
  totals: { events: number; tokens: number; cost_usd: number; ocr_pages: number; transcription_minutes: number }
  by_feature: { feature: string; tokens: number; cost_usd: number; events: number }[]
  by_model: { model: string; tokens: number; cost_usd: number }[]
  daily: { date: string; tokens: number; cost_usd: number }[]
  top_members: { member_id: number; username: string; role: string; tokens: number; cost_usd: number }[]
  quota: { plan: string; monthly_ai_tokens: number; used_this_month: number; percent_used: number }
  cost_note: string
}

type RazorpayHandlerResponse = { razorpay_order_id: string; razorpay_payment_id: string; razorpay_signature: string }
declare global {
  interface Window {
    Razorpay?: new (options: Record<string, unknown>) => { open: () => void }
  }
}

function loadRazorpay(): Promise<void> {
  if (window.Razorpay) return Promise.resolve()
  return new Promise((resolve, reject) => {
    const s = document.createElement("script")
    s.src = "https://checkout.razorpay.com/v1/checkout.js"
    s.onload = () => resolve()
    s.onerror = () => reject(new Error("Could not load the payment window."))
    document.body.appendChild(s)
  })
}

const fmtTokens = (n: number) => (n >= 1_000_000 ? `${(n / 1_000_000).toFixed(1)}M` : n >= 1000 ? `${Math.round(n / 1000)}k` : String(n))

export function BillingPage() {
  const { isAdmin } = useRole()
  const { refresh } = useAuth()
  const [plans, setPlans] = useState<Plan[]>([])
  const [sub, setSub] = useState<Subscription | null>(null)
  const [payments, setPayments] = useState<Payment[]>([])
  const [months, setMonths] = useState(1)
  const [busy, setBusy] = useState("")
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")

  const load = useCallback(async () => {
    try {
      const [p, s, pay] = await Promise.all([
        api<{ plans: Plan[] }>("/api/billing/plans/"),
        api<Subscription>("/api/billing/subscription/"),
        api<Payment[]>("/api/billing/payments/"),
      ])
      setPlans(p.plans)
      setSub(s)
      setPayments(pay)
    } catch (err) {
      setError(errorMessage(err))
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  async function upgrade(plan: Plan) {
    setBusy(plan.code)
    setError("")
    try {
      const res = await api<{ checkout: Record<string, unknown> & { order_id: string } }>("/api/billing/checkout/", {
        method: "POST",
        body: JSON.stringify({ plan_code: plan.code, months }),
      })
      await loadRazorpay()
      const rzp = new window.Razorpay!({
        ...res.checkout,
        order_id: res.checkout.order_id,
        theme: { color: "#1e3a5f" },
        handler: async (r: RazorpayHandlerResponse) => {
          try {
            await api("/api/billing/verify/", { method: "POST", body: JSON.stringify(r) })
            setNotice(`Upgraded to ${plan.name}. New limits are active.`)
            await Promise.all([load(), refresh()])
          } catch (err) {
            setError(errorMessage(err))
          }
        },
        modal: { ondismiss: () => setBusy("") },
      })
      rzp.open()
    } catch (err) {
      setError(errorMessage(err))
      setBusy("")
    }
  }

  return (
    <div className="w-full space-y-6">
      <PageHeader icon={CreditCard} title="Billing & Usage" description="Your plan, payments, and how much AI your school is using." />
      {notice ? <p className="rounded-lg bg-brand-soft px-3 py-2 text-sm text-brand">{notice}</p> : null}
      <ErrorText>{error}</ErrorText>
      {!sub ? <Loading /> : (
        <>
          <Section
            title={<span className="flex items-center gap-2">Current plan: {sub.plan.name} <Pill tone={sub.plan.is_paid ? "green" : "gray"}>{sub.status}</Pill></span>}
            description={sub.current_period_end ? `Renews / expires ${formatDate(sub.current_period_end)}` : "No expiry"}
          >
            <div className="grid gap-3 sm:grid-cols-4">
              <Stat label="AI Buckets" value={`${sub.usage.buckets}/${sub.plan.max_buckets}`} />
              <Stat label="Seats" value={`${sub.usage.members}/${sub.plan.max_users || "∞"}`} />
              <Stat label="Per bucket" value={formatBytes(sub.plan.bucket_quota_bytes)} />
              <Stat label="AI tokens / month" value={sub.plan.monthly_ai_tokens ? fmtTokens(sub.plan.monthly_ai_tokens) : "∞"} />
            </div>
          </Section>

          <div className="flex items-end justify-between">
            <h2 className="font-medium">Plans</h2>
            {isAdmin && sub.online_payments ? (
              <Field label="Billing period">
                <Select value={months} onChange={(e) => setMonths(Number(e.target.value))} className="w-36">
                  <option value={1}>1 month</option><option value={3}>3 months</option><option value={6}>6 months</option><option value={12}>12 months</option>
                </Select>
              </Field>
            ) : null}
          </div>
          <div className="grid gap-3 md:grid-cols-3">
            {plans.map((p) => (
              <div key={p.code} className={cn("rounded-2xl border bg-white/80 p-5", p.code === sub.plan.code ? "border-brand" : "border-border/80")}>
                <p className="font-medium">{p.name}</p>
                <p className="mt-1 text-2xl font-semibold">{p.is_paid ? `₹${p.price_inr_monthly.toLocaleString("en-IN")}` : "Free"}<span className="text-sm font-normal text-muted-foreground">{p.is_paid ? " /month" : ""}</span></p>
                <ul className="mt-3 space-y-1 text-sm text-muted-foreground">
                  <li>{p.max_buckets} AI Buckets × {formatBytes(p.bucket_quota_bytes)}</li>
                  <li>{p.max_users || "Unlimited"} users · {p.max_managers || "Unlimited"} managers</li>
                  <li>{fmtTokens(p.monthly_ai_tokens)} AI tokens / month</li>
                  {p.features.map((f) => <li key={f}>✓ {f}</li>)}
                </ul>
                {p.code === sub.plan.code ? (
                  <p className="mt-4 text-sm font-medium text-brand">Current plan</p>
                ) : p.is_paid ? (
                  isAdmin ? (
                    sub.online_payments ? (
                      <Button className="mt-4 w-full" onClick={() => void upgrade(p)} disabled={!!busy}>
                        {busy === p.code ? <Loader2 className="size-4 animate-spin" /> : null} {sub.plan.is_paid ? "Switch" : "Upgrade"} — ₹{(p.price_inr_monthly * months).toLocaleString("en-IN")}
                      </Button>
                    ) : (
                      <p className="mt-4 text-xs text-muted-foreground">Online payments aren't set up yet — contact us to upgrade.</p>
                    )
                  ) : (
                    <p className="mt-4 text-xs text-muted-foreground">Ask your school admin to upgrade.</p>
                  )
                ) : null}
              </div>
            ))}
          </div>

          {payments.length ? (
            <Section title="Payments">
              <ul className="divide-y divide-border/60 text-sm">
                {payments.map((p) => (
                  <li key={p.id} className="flex items-center justify-between py-2">
                    <span>{p.plan_code} · {p.months} mo · ₹{(p.amount_paise / 100).toLocaleString("en-IN")}</span>
                    <span className="flex items-center gap-2 text-xs text-muted-foreground">{formatDate(p.paid_at || p.created_at)} <Pill tone={p.status === "paid" ? "green" : p.status === "failed" ? "red" : "gray"}>{p.status}</Pill></span>
                  </li>
                ))}
              </ul>
            </Section>
          ) : null}
          <UsageSection />
        </>
      )}
    </div>
  )
}

function UsageSection() {
  const [days, setDays] = useState(30)
  const [usage, setUsage] = useState<Usage | null>(null)

  useEffect(() => {
    api<Usage>(`/api/billing/usage/?days=${days}`).then(setUsage).catch(() => setUsage(null))
  }, [days])

  if (!usage) return null
  const maxDay = Math.max(1, ...usage.daily.map((d) => d.tokens))
  return (
    <Section
      title="AI usage"
      description={usage.cost_note}
      actions={
        <Select value={days} onChange={(e) => setDays(Number(e.target.value))} className="w-32">
          <option value={7}>7 days</option><option value={30}>30 days</option><option value={90}>90 days</option>
        </Select>
      }
    >
      <div className="grid gap-3 sm:grid-cols-4">
        <Stat label="This month" value={`${usage.quota.percent_used}%`} hint={`${fmtTokens(usage.quota.used_this_month)} of ${usage.quota.monthly_ai_tokens ? fmtTokens(usage.quota.monthly_ai_tokens) : "∞"} tokens`} />
        <Stat label="Tokens" value={fmtTokens(usage.totals.tokens)} hint={`${usage.totals.events} AI calls`} />
        <Stat label="OCR pages" value={usage.totals.ocr_pages} />
        <Stat label="Est. cost" value={`$${usage.totals.cost_usd.toFixed(2)}`} hint={`${usage.totals.transcription_minutes} min transcribed`} />
      </div>
      {usage.daily.length ? (
        <div className="flex h-28 items-end gap-0.5" aria-label="Daily tokens">
          {usage.daily.map((d) => (
            <div key={d.date} className="flex-1 rounded-t bg-brand/70" style={{ height: `${Math.max(2, (100 * d.tokens) / maxDay)}%` }} title={`${d.date}: ${fmtTokens(d.tokens)} tokens`} />
          ))}
        </div>
      ) : null}
      <div className="grid gap-4 md:grid-cols-2">
        <div>
          <p className="mb-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">By feature</p>
          <ul className="space-y-1 text-sm">
            {usage.by_feature.map((f) => (
              <li key={f.feature} className="flex justify-between"><span>{f.feature}</span><span className="tabular-nums text-muted-foreground">{fmtTokens(f.tokens)} · ${f.cost_usd.toFixed(2)}</span></li>
            ))}
          </ul>
        </div>
        <div>
          <p className="mb-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Top users</p>
          <ul className="space-y-1 text-sm">
            {usage.top_members.map((m) => (
              <li key={m.member_id} className="flex justify-between"><span>{m.username} <span className="text-xs text-muted-foreground">{m.role}</span></span><span className="tabular-nums text-muted-foreground">{fmtTokens(m.tokens)}</span></li>
            ))}
          </ul>
        </div>
      </div>
    </Section>
  )
}
