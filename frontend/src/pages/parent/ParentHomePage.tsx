import { useEffect, useState } from "react"
import { useNavigate } from "react-router-dom"
import { CalendarCheck, Flame, LogOut } from "lucide-react"

import { BrandLogo } from "@/components/BrandLogo"
import { AccuracyBar, EmptyState, ErrorText, Loading, Pill, Section, Stat } from "@/components/app/ui"
import { Button } from "@/components/ui/button"
import { api, errorMessage, formatDate } from "@/lib/api"
import { useAuth } from "@/lib/auth"
import { cn } from "@/lib/utils"

type Overview = {
  student_id: number
  name: string
  school_name: string
  streak: { current_streak: number; longest_streak: number }
  subjects: { bucket_id: number; bucket_name: string; score: number; tests_taken: number }[]
  attendance: {
    total: number
    attended: number
    percent: number | null
    recent: { lecture_id: number; lecture_title: string; bucket_name: string; starts_at: string; status: string }[]
  }
  test_results: { test_id: number; title: string; bucket_name: string; submitted_at: string; released: boolean; score: number | null; max_score: number | null; percent: number | null }[]
  pending_tests: { test_id: number; title: string; bucket_name: string }[]
  homework: { assignment_id: number; title: string; bucket_name: string; due_at: string | null; status: string; score: number | null; max_marks: number }[]
}

const ATT_TONE: Record<string, "green" | "amber" | "red" | "sky"> = { present: "green", late: "amber", absent: "red", excused: "sky" }

export function ParentHomePage() {
  const { session, logout, setSession } = useAuth()
  const navigate = useNavigate()
  const children = session?.parent?.children || []
  const [childId, setChildId] = useState<number | null>(children[0]?.student_id ?? null)
  const [data, setData] = useState<Overview | null>(null)
  const [error, setError] = useState("")
  const [weekly, setWeekly] = useState(session?.parent?.weekly_email ?? true)

  useEffect(() => {
    if (!childId) return
    setData(null)
    api<Overview>(`/api/parent/children/${childId}/`).then(setData).catch((e) => setError(errorMessage(e)))
  }, [childId])

  async function toggleWeekly(next: boolean) {
    setWeekly(next)
    try {
      const parent = await api<NonNullable<typeof session>["parent"]>("/api/parent/preferences/", {
        method: "PATCH",
        body: JSON.stringify({ weekly_email: next }),
      })
      if (session && parent) setSession({ ...session, parent })
    } catch {
      setWeekly(!next)
    }
  }

  return (
    <div className="min-h-svh bg-background">
      <header className="flex items-center justify-between border-b border-border/80 bg-white/80 px-4 py-3">
        <div className="flex items-center gap-3">
          <BrandLogo to={false} size={28} wordmarkClassName="text-lg text-brand" />
          <span className="hidden text-sm text-muted-foreground sm:inline">{session?.school?.name} · Parent</span>
        </div>
        <Button variant="outline" size="sm" onClick={() => void logout().then(() => navigate("/login"))}>
          <LogOut className="size-3.5" /> Sign out
        </Button>
      </header>

      <main className="mx-auto w-full max-w-4xl space-y-6 px-4 py-6">
        {children.length > 1 ? (
          <div className="flex flex-wrap gap-2">
            {children.map((c) => (
              <button
                key={c.student_id}
                type="button"
                onClick={() => setChildId(c.student_id)}
                className={cn("rounded-full border px-3 py-1.5 text-sm", c.student_id === childId ? "border-brand bg-brand-soft text-brand" : "border-border bg-white")}
              >
                {c.name}
              </button>
            ))}
          </div>
        ) : null}
        <ErrorText>{error}</ErrorText>
        {!children.length ? <EmptyState>No children are linked to this account yet. Please contact the school.</EmptyState> : null}
        {childId && !data && !error ? <Loading /> : null}

        {data ? (
          <>
            <div>
              <h1 className="font-display text-3xl tracking-tight">{data.name}</h1>
              <p className="text-muted-foreground">{data.school_name}</p>
            </div>
            <div className="grid gap-3 sm:grid-cols-3">
              <Stat label="Attendance (90 days)" value={data.attendance.percent == null ? "—" : `${data.attendance.percent}%`} hint={`${data.attendance.attended}/${data.attendance.total} lectures`} />
              <Stat label="Study streak" value={<span className="flex items-center gap-1"><Flame className="size-5 text-orange-500" />{data.streak.current_streak}</span>} hint={`Best: ${data.streak.longest_streak} days`} />
              <Stat label="Tests not started" value={data.pending_tests.length} />
            </div>

            <Section title="Subjects">
              {!data.subjects.length ? <p className="text-sm text-muted-foreground">No subject activity yet.</p> : (
                <ul className="space-y-2">
                  {data.subjects.map((s) => (
                    <li key={s.bucket_id} className="flex items-center justify-between gap-3 text-sm">
                      <span>{s.bucket_name}</span>
                      <AccuracyBar value={s.score} />
                    </li>
                  ))}
                </ul>
              )}
            </Section>

            <Section title="Test results" description="Shown once the teacher releases them.">
              {!data.test_results.length ? <p className="text-sm text-muted-foreground">No tests submitted yet.</p> : (
                <ul className="divide-y divide-border/60 text-sm">
                  {data.test_results.map((t) => (
                    <li key={t.test_id} className="flex items-center justify-between gap-2 py-2">
                      <span>{t.title} <span className="text-xs text-muted-foreground">· {t.bucket_name} · {formatDate(t.submitted_at)}</span></span>
                      {t.released ? <span className="font-medium">{t.score}/{t.max_score} ({t.percent}%)</span> : <Pill tone="amber">Being reviewed</Pill>}
                    </li>
                  ))}
                </ul>
              )}
              {data.pending_tests.length ? (
                <p className="text-sm text-amber-700">Not started: {data.pending_tests.map((t) => t.title).join(", ")}</p>
              ) : null}
            </Section>

            {data.homework.length ? (
              <Section title="Homework">
                <ul className="divide-y divide-border/60 text-sm">
                  {data.homework.map((h) => (
                    <li key={h.assignment_id} className="flex items-center justify-between gap-2 py-2">
                      <span>{h.title} <span className="text-xs text-muted-foreground">· {h.bucket_name}{h.due_at ? ` · due ${formatDate(h.due_at)}` : ""}</span></span>
                      <span className="flex items-center gap-2">
                        {h.score != null ? <span className="font-medium">{h.score}/{h.max_marks}</span> : null}
                        <Pill tone={h.status === "returned" ? "green" : h.status === "overdue" ? "red" : h.status === "submitted" ? "amber" : "sky"}>{h.status}</Pill>
                      </span>
                    </li>
                  ))}
                </ul>
              </Section>
            ) : null}

            <Section title={<span className="flex items-center gap-2"><CalendarCheck className="size-4" /> Recent lectures</span>}>
              {!data.attendance.recent.length ? <p className="text-sm text-muted-foreground">No lectures recorded yet.</p> : (
                <ul className="divide-y divide-border/60 text-sm">
                  {data.attendance.recent.slice(0, 10).map((r) => (
                    <li key={r.lecture_id} className="flex items-center justify-between py-1.5">
                      <span>{r.lecture_title} <span className="text-xs text-muted-foreground">· {r.bucket_name} · {formatDate(r.starts_at)}</span></span>
                      <Pill tone={ATT_TONE[r.status] || "gray"}>{r.status}</Pill>
                    </li>
                  ))}
                </ul>
              )}
            </Section>

            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={weekly} onChange={(e) => void toggleWeekly(e.target.checked)} />
              Email me a weekly summary
            </label>
          </>
        ) : null}
      </main>
    </div>
  )
}
