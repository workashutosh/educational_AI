import {
  useEffect,
  useState,
  type Dispatch,
  type FormEvent,
  type SetStateAction,
} from "react"
import { Link, Navigate, useNavigate } from "react-router-dom"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { api, type Session } from "@/lib/api"
import { useAuth } from "@/lib/auth"
import { AuthShell } from "@/pages/AuthShell"

type Step = 1 | 2 | 3

const DEFAULT_MAX_BUCKETS = 5
const DEFAULT_BUCKET_GB = 1

export function OnboardPage() {
  const { session, setSession, loading } = useAuth()
  const navigate = useNavigate()
  const [step, setStep] = useState<Step>(1)
  const [pendingId, setPendingId] = useState<number | null>(null)
  const [setupToken, setSetupToken] = useState("")
  const [maskedEmail, setMaskedEmail] = useState("")
  const [otp, setOtp] = useState("")
  const [resendAfter, setResendAfter] = useState(0)
  const [error, setError] = useState("")
  const [submitting, setSubmitting] = useState(false)

  const [form, setForm] = useState({
    organization_name: "",
    contact_phone: "",
    email: "",
    country_region: "",
    privacy_consent: false,
    password: "",
    password_confirm: "",
  })

  const [plan, setPlan] = useState({
    max_buckets: DEFAULT_MAX_BUCKETS,
    bucket_quota_gb: DEFAULT_BUCKET_GB,
    max_users: 0,
    max_managers: 0,
  })

  useEffect(() => {
    if (resendAfter <= 0) return
    const t = window.setTimeout(() => setResendAfter((n) => Math.max(0, n - 1)), 1000)
    return () => window.clearTimeout(t)
  }, [resendAfter])

  if (!loading && session?.membership) {
    return <Navigate to="/app" replace />
  }

  function setField(field: string, value: string | boolean) {
    setForm((prev) => ({ ...prev, [field]: value }))
  }

  async function startOnboard(e: FormEvent) {
    e.preventDefault()
    setError("")
    if (!form.privacy_consent) {
      setError("Please accept the data privacy consent to continue.")
      return
    }
    setSubmitting(true)
    try {
      const data = await api<{
        pending_id: number
        email: string
        resend_after: number
      }>("/api/auth/onboard/start/", {
        method: "POST",
        body: JSON.stringify(form),
        token: null,
      })
      setPendingId(data.pending_id)
      setMaskedEmail(data.email)
      setResendAfter(data.resend_after || 60)
      setOtp("")
      setSetupToken("")
      setStep(2)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start onboarding")
    } finally {
      setSubmitting(false)
    }
  }

  async function verifyOtp(e: FormEvent) {
    e.preventDefault()
    if (pendingId == null) return
    setError("")
    setSubmitting(true)
    try {
      const data = await api<{ setup_token: string }>("/api/auth/onboard/verify-otp/", {
        method: "POST",
        body: JSON.stringify({ pending_id: pendingId, otp: otp.trim() }),
        token: null,
      })
      setSetupToken(data.setup_token)
      setStep(3)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Invalid verification code")
    } finally {
      setSubmitting(false)
    }
  }

  async function resendOtp() {
    if (pendingId == null || resendAfter > 0) return
    setError("")
    setSubmitting(true)
    try {
      const data = await api<{ resend_after: number }>("/api/auth/onboard/resend-otp/", {
        method: "POST",
        body: JSON.stringify({ pending_id: pendingId }),
        token: null,
      })
      setResendAfter(data.resend_after || 60)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not resend code")
    } finally {
      setSubmitting(false)
    }
  }

  async function completeOnboard(skip: boolean) {
    if (!setupToken) return
    setError("")
    setSubmitting(true)
    try {
      const body = skip
        ? { setup_token: setupToken, skip: true }
        : {
            setup_token: setupToken,
            skip: false,
            max_buckets: Number(plan.max_buckets) || DEFAULT_MAX_BUCKETS,
            bucket_quota_gb: Number(plan.bucket_quota_gb) || DEFAULT_BUCKET_GB,
            max_users: Number(plan.max_users) || 0,
            max_managers: Number(plan.max_managers) || 0,
          }
      const data = await api<Session>("/api/auth/onboard/complete/", {
        method: "POST",
        body: JSON.stringify(body),
        token: null,
      })
      setSession(data)
      navigate("/app")
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not complete onboarding")
    } finally {
      setSubmitting(false)
    }
  }

  const stepLabel =
    step === 1 ? "Organization details" : step === 2 ? "Email verification" : "AI Buckets"

  return (
    <AuthShell
      brand="Onboarding"
      title={stepLabel}
      wide={step === 3}
      subtitle={
        step === 1
          ? "Step 1 of 3 — Tell us about your university or organization."
          : step === 2
            ? `Step 2 of 3 — Enter the 6-digit code sent to ${maskedEmail}.`
            : "Step 3 of 3 — Tap AI Buckets to choose how many subject spaces you need."
      }
      footer={
        <>
          Already registered?{" "}
          <Link className="font-medium text-[var(--brand)]" to="/login">
            Sign in
          </Link>
          {" · "}
          Joining?{" "}
          <Link className="font-medium text-[var(--brand)]" to="/join">
            Join with code
          </Link>
        </>
      }
    >
      <div className="mb-4 flex gap-2">
        {[1, 2, 3].map((n) => (
          <div
            key={n}
            className={`h-1.5 flex-1 rounded-full ${n <= step ? "bg-[var(--brand)]" : "bg-border"}`}
          />
        ))}
      </div>

      {step === 1 ? (
        <form className="space-y-3.5" onSubmit={startOnboard}>
          <Field
            label="University / organization name"
            id="organization_name"
            value={form.organization_name}
            onChange={setField}
            required
          />
          <Field
            label="Contact number"
            id="contact_phone"
            value={form.contact_phone}
            onChange={setField}
            required
          />
          <Field
            label="Email"
            id="email"
            type="email"
            value={form.email}
            onChange={setField}
            autoComplete="email"
            required
          />
          <Field
            label="Country / region"
            id="country_region"
            value={form.country_region}
            onChange={setField}
            required
          />
          <Field
            label="Password"
            id="password"
            type="password"
            value={form.password}
            onChange={setField}
            autoComplete="new-password"
            required
          />
          <Field
            label="Confirm password"
            id="password_confirm"
            type="password"
            value={form.password_confirm}
            onChange={setField}
            autoComplete="new-password"
            required
          />
          <label className="flex items-start gap-2 text-sm text-muted-foreground">
            <input
              type="checkbox"
              className="mt-1"
              checked={form.privacy_consent}
              onChange={(e) => setField("privacy_consent", e.target.checked)}
              required
            />
            <span>
              I agree to the data privacy policy and consent to processing of my information.
            </span>
          </label>
          {error ? <p className="text-sm text-destructive">{error}</p> : null}
          <Button className="w-full" type="submit" disabled={submitting}>
            {submitting ? "Sending code…" : "Continue"}
          </Button>
        </form>
      ) : null}

      {step === 2 ? (
        <form className="space-y-3.5" onSubmit={verifyOtp}>
          <div className="space-y-1.5">
            <Label htmlFor="otp">Verification code</Label>
            <Input
              id="otp"
              inputMode="numeric"
              pattern="[0-9]{6}"
              maxLength={6}
              value={otp}
              onChange={(e) => setOtp(e.target.value.replace(/\D/g, "").slice(0, 6))}
              placeholder="6-digit code"
              className="text-center text-lg tracking-[0.3em]"
              required
            />
          </div>
          {error ? <p className="text-sm text-destructive">{error}</p> : null}
          <Button className="w-full" type="submit" disabled={submitting || otp.length !== 6}>
            {submitting ? "Verifying…" : "Verify email"}
          </Button>
          <Button
            type="button"
            variant="outline"
            className="w-full"
            disabled={submitting || resendAfter > 0}
            onClick={() => void resendOtp()}
          >
            {resendAfter > 0 ? `Resend code in ${resendAfter}s` : "Resend code"}
          </Button>
          <Button type="button" variant="ghost" className="w-full" onClick={() => setStep(1)}>
            Back
          </Button>
        </form>
      ) : null}

      {step === 3 ? (
        <BucketPlanStep
          plan={plan}
          setPlan={setPlan}
          error={error}
          submitting={submitting}
          onContinue={() => void completeOnboard(false)}
          onSkip={() => void completeOnboard(true)}
          onBack={() => setStep(2)}
        />
      ) : null}
    </AuthShell>
  )
}

function Field({
  label,
  id,
  value,
  onChange,
  type = "text",
  placeholder,
  autoComplete,
  required,
}: {
  label: string
  id: string
  value: string
  onChange: (id: string, value: string | boolean) => void
  type?: string
  placeholder?: string
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
        placeholder={placeholder}
        autoComplete={autoComplete}
        required={required}
        onChange={(e) => onChange(id, e.target.value)}
      />
    </div>
  )
}

type PlanState = {
  max_buckets: number
  bucket_quota_gb: number
  max_users: number
  max_managers: number
}

const FREE_BUCKET_SLOTS = 5
const SIZE_OPTIONS_GB = [1] as const

function BucketPlanStep({
  plan,
  setPlan,
  error,
  submitting,
  onContinue,
  onSkip,
  onBack,
}: {
  plan: PlanState
  setPlan: Dispatch<SetStateAction<PlanState>>
  error: string
  submitting: boolean
  onContinue: () => void
  onSkip: () => void
  onBack: () => void
}) {
  const count = Math.min(Math.max(plan.max_buckets, 1), FREE_BUCKET_SLOTS)

  return (
    <div className="space-y-5">
      <div>
        <div className="mb-2 flex items-end justify-between gap-2">
          <p className="text-sm font-medium text-foreground">AI Buckets</p>
          <p className="text-xs text-muted-foreground">
            {count} selected · {plan.bucket_quota_gb} GB each
          </p>
        </div>
        <div className="grid grid-cols-3 gap-2.5">
          {Array.from({ length: FREE_BUCKET_SLOTS }, (_, i) => {
            const n = i + 1
            const active = n <= count
            return (
              <button
                key={n}
                type="button"
                onClick={() => setPlan((p) => ({ ...p, max_buckets: n }))}
                className={`group relative flex flex-col items-center rounded-xl border px-2 py-3 transition ${
                  active
                    ? "border-[var(--brand)] bg-[#e6f4ef] shadow-sm"
                    : "border-border/80 bg-white/70 hover:border-[var(--brand)]/40"
                }`}
                aria-pressed={active}
                aria-label={`${n} AI Bucket${n === 1 ? "" : "s"}`}
              >
                <BucketIcon filled={active} fillRatio={plan.bucket_quota_gb / 5} />
                <span
                  className={`mt-1.5 text-xs font-medium ${
                    active ? "text-[var(--brand)]" : "text-muted-foreground"
                  }`}
                >
                  AI Bucket {n}
                </span>
              </button>
            )
          })}
          <button
            type="button"
            disabled
            title="Paid upgrade coming soon"
            className="flex flex-col items-center rounded-xl border border-dashed border-border/90 bg-muted/40 px-2 py-3 opacity-70"
          >
            <BucketIcon filled={false} dashed />
            <span className="mt-1.5 text-xs font-medium text-muted-foreground">+ Paid</span>
          </button>
        </div>
        <p className="mt-2 text-xs text-muted-foreground">
          Free plan includes up to {FREE_BUCKET_SLOTS} AI Buckets. Tap one to set your count.
        </p>
      </div>

      <div>
        <p className="mb-2 text-sm font-medium text-foreground">Size per AI Bucket</p>
        <div className="flex flex-wrap gap-2">
          {SIZE_OPTIONS_GB.map((gb) => {
            const active = plan.bucket_quota_gb === gb
            return (
              <button
                key={gb}
                type="button"
                onClick={() => setPlan((p) => ({ ...p, bucket_quota_gb: gb }))}
                className={`rounded-full px-3.5 py-1.5 text-sm font-medium transition ${
                  active
                    ? "bg-[var(--brand)] text-white"
                    : "border border-border bg-white text-muted-foreground hover:border-[var(--brand)]/50"
                }`}
              >
                {gb} GB
              </button>
            )
          })}
          <button
            type="button"
            disabled
            className="cursor-not-allowed rounded-full border border-dashed border-border px-3.5 py-1.5 text-sm text-muted-foreground opacity-60"
          >
            More (Paid)
          </button>
        </div>
      </div>

      <div className="space-y-2.5 rounded-xl border border-border/80 bg-white/70 p-3">
        <p className="text-sm font-medium text-foreground">Seats</p>
        <SeatStepper
          label="Users"
          value={plan.max_users}
          onChange={(v) => setPlan((p) => ({ ...p, max_users: v }))}
        />
        <SeatStepper
          label="Managers"
          value={plan.max_managers}
          onChange={(v) => setPlan((p) => ({ ...p, max_managers: v }))}
        />
      </div>

      {error ? <p className="text-sm text-destructive">{error}</p> : null}

      <div className="space-y-2">
        <Button className="w-full" type="button" disabled={submitting} onClick={onContinue}>
          {submitting
            ? "Finishing…"
            : `Continue with ${count} AI Bucket${count === 1 ? "" : "s"}`}
        </Button>
        <Button type="button" variant="outline" className="w-full" disabled={submitting} onClick={onSkip}>
          Skip for now
        </Button>
        <Button type="button" variant="ghost" className="w-full" onClick={onBack}>
          Back
        </Button>
      </div>
    </div>
  )
}

function SeatStepper({
  label,
  value,
  onChange,
}: {
  label: string
  value: number
  onChange: (v: number) => void
}) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-sm text-muted-foreground">{label}</span>
      <div className="flex items-center gap-2">
        <button
          type="button"
          className="flex size-8 items-center justify-center rounded-lg border border-border bg-white text-lg leading-none hover:bg-muted"
          onClick={() => onChange(Math.max(0, value - 1))}
          aria-label={`Decrease ${label}`}
        >
          −
        </button>
        <span className="w-8 text-center text-sm font-semibold tabular-nums">{value}</span>
        <button
          type="button"
          className="flex size-8 items-center justify-center rounded-lg border border-border bg-white text-lg leading-none hover:bg-muted"
          onClick={() => onChange(Math.min(999, value + 1))}
          aria-label={`Increase ${label}`}
        >
          +
        </button>
      </div>
    </div>
  )
}

function BucketIcon({
  filled,
  fillRatio = 0.35,
  dashed = false,
}: {
  filled: boolean
  fillRatio?: number
  dashed?: boolean
}) {
  const fillH = Math.max(0.15, Math.min(0.85, fillRatio))
  const stroke = filled ? "#0b6e4f" : dashed ? "#94a3b8" : "#8a9aab"
  const liquid = filled ? "#0b6e4f" : "#cbd5e1"

  return (
    <svg viewBox="0 0 64 72" className="h-14 w-12" aria-hidden>
      {/* rim */}
      <ellipse cx="32" cy="12" rx="22" ry="7" fill="none" stroke={stroke} strokeWidth="2.5" />
      {/* body */}
      <path
        d="M10 14 C10 14 8 52 14 62 C18 68 46 68 50 62 C56 52 54 14 54 14"
        fill="none"
        stroke={stroke}
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeDasharray={dashed ? "4 3" : undefined}
      />
      {/* liquid fill */}
      {!dashed ? (
        <path
          d={`M14 ${62 - fillH * 40} C18 ${58 - fillH * 36} 46 ${58 - fillH * 36} 50 ${62 - fillH * 40} C52 ${50} 52 40 52 28 L12 28 C12 40 12 50 14 ${62 - fillH * 40} Z`}
          fill={liquid}
          opacity={filled ? 0.35 : 0.12}
          className="transition-all duration-300"
        />
      ) : (
        <text x="32" y="42" textAnchor="middle" fill={stroke} fontSize="18" fontWeight="600">
          +
        </text>
      )}
      {/* handle */}
      <path
        d="M18 20 C12 24 12 34 18 38"
        fill="none"
        stroke={stroke}
        strokeWidth="2.2"
        strokeLinecap="round"
        strokeDasharray={dashed ? "3 3" : undefined}
      />
    </svg>
  )
}
