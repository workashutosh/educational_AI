/** Lecture room add-ons: recordings → transcript/summary, and the attendance roster. */
import { useCallback, useEffect, useState } from "react"
import { Loader2, Mic, Play, Trash2, Upload } from "lucide-react"

import { ErrorText, Pill, Section, Select } from "@/components/app/ui"
import { RichAnswer } from "@/components/chat/RichAnswer"
import { Button } from "@/components/ui/button"
import { api, apiUpload, errorMessage, fetchObjectUrl, formatBytes, formatDate } from "@/lib/api"

type Recording = {
  id: number
  original_filename: string
  byte_size: number
  status: string
  status_display: string
  error_message: string
  duration_seconds: number
  summary: string
  key_points: string[]
  audio_url: string
  created_at: string
  transcript?: string
}

const PENDING = new Set(["queued", "transcribing", "summarizing", "indexing"])

export function LectureRecordings({ lectureId, canManage }: { lectureId: number; canManage: boolean }) {
  const [rows, setRows] = useState<Recording[]>([])
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState("")
  const [open, setOpen] = useState<Recording | null>(null)
  const [audioSrc, setAudioSrc] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      setRows(await api<Recording[]>(`/api/lectures/${lectureId}/recordings/`))
    } catch (err) {
      setError(errorMessage(err))
    }
  }, [lectureId])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    if (!rows.some((r) => PENDING.has(r.status))) return
    const t = window.setInterval(() => void load(), 5000)
    return () => window.clearInterval(t)
  }, [rows, load])

  useEffect(() => () => { if (audioSrc) URL.revokeObjectURL(audioSrc) }, [audioSrc])

  async function upload(file: File) {
    setUploading(true)
    setError("")
    const fd = new FormData()
    fd.set("file", file)
    try {
      await apiUpload(`/api/lectures/${lectureId}/recordings/`, fd)
      await load()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setUploading(false)
    }
  }

  async function show(rec: Recording) {
    if (open?.id === rec.id) return setOpen(null)
    setOpen(await api<Recording>(`/api/lectures/recordings/${rec.id}/`))
  }

  async function play(rec: Recording) {
    try {
      setAudioSrc(await fetchObjectUrl(rec.audio_url))
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  async function remove(rec: Recording) {
    await api(`/api/lectures/recordings/${rec.id}/`, { method: "DELETE" })
    setOpen(null)
    void load()
  }

  if (!canManage && !rows.length) return null

  return (
    <Section
      title={<span className="flex items-center gap-2"><Mic className="size-4" /> Recordings</span>}
      description="Upload the class audio — it's transcribed, summarized, and added to this AI Bucket's notes so students can ask about it."
      actions={
        canManage ? (
          <label className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-border bg-white px-3 py-1.5 text-sm hover:border-brand">
            {uploading ? <Loader2 className="size-3.5 animate-spin" /> : <Upload className="size-3.5" />}
            Upload recording
            <input type="file" accept="audio/*,video/mp4,video/webm" className="hidden" disabled={uploading}
              onChange={(e) => { const f = e.target.files?.[0]; if (f) void upload(f); e.target.value = "" }} />
          </label>
        ) : null
      }
    >
      <ErrorText>{error}</ErrorText>
      {audioSrc ? <audio src={audioSrc} controls autoPlay className="w-full" /> : null}
      <ul className="space-y-2">
        {rows.map((r) => (
          <li key={r.id} className="rounded-xl border border-border/70 bg-white p-3 text-sm">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="font-medium">{r.original_filename}</span>
              <span className="flex items-center gap-2 text-xs text-muted-foreground">
                {formatBytes(r.byte_size)}
                {r.duration_seconds ? ` · ${Math.round(r.duration_seconds / 60)} min` : ""} · {formatDate(r.created_at)}
                {PENDING.has(r.status) ? (
                  <span className="flex items-center gap-1"><Loader2 className="size-3 animate-spin" />{r.status_display}…</span>
                ) : (
                  <Pill tone={r.status === "done" ? "green" : "red"}>{r.status_display}</Pill>
                )}
              </span>
            </div>
            {r.error_message ? <p className="mt-1 text-xs text-destructive">{r.error_message}</p> : null}
            {r.key_points.length ? (
              <ul className="mt-2 list-disc pl-5 text-sm">{r.key_points.map((k) => <li key={k}>{k}</li>)}</ul>
            ) : null}
            {r.status === "done" ? (
              <div className="mt-2 flex flex-wrap gap-1">
                <Button size="xs" variant="outline" onClick={() => void show(r)}>{open?.id === r.id ? "Hide" : "Summary & transcript"}</Button>
                <Button size="xs" variant="outline" onClick={() => void play(r)}><Play className="size-3" /> Play</Button>
                {canManage ? <Button size="xs" variant="ghost" onClick={() => void remove(r)}><Trash2 className="size-3" /></Button> : null}
              </div>
            ) : null}
            {open?.id === r.id ? (
              <div className="mt-3 space-y-3">
                {open.summary ? <div className="rounded-lg bg-[#f7f9fd] p-3"><RichAnswer content={open.summary} /></div> : null}
                <details>
                  <summary className="cursor-pointer text-xs text-muted-foreground">Full transcript</summary>
                  <p className="mt-2 max-h-72 overflow-y-auto whitespace-pre-wrap text-xs leading-relaxed">{open.transcript}</p>
                </details>
              </div>
            ) : null}
          </li>
        ))}
      </ul>
    </Section>
  )
}

type RosterRow = { student_id: number; name: string; status: string; source: string | null; first_seen_at: string | null; note: string }
type Roster = { counts: Record<string, number>; students: RosterRow[] }

export function LectureAttendance({ lectureId }: { lectureId: number }) {
  const [roster, setRoster] = useState<Roster | null>(null)
  const [error, setError] = useState("")

  const load = useCallback(async () => {
    try {
      setRoster(await api<Roster>(`/api/attendance/lectures/${lectureId}/`))
    } catch (err) {
      setError(errorMessage(err))
    }
  }, [lectureId])

  useEffect(() => {
    void load()
    const t = window.setInterval(() => void load(), 15000)
    return () => window.clearInterval(t)
  }, [load])

  async function mark(studentId: number, status: string) {
    try {
      setRoster(
        await api<Roster>(`/api/attendance/lectures/${lectureId}/`, {
          method: "PUT",
          body: JSON.stringify({ records: [{ student_id: studentId, status }] }),
        }),
      )
    } catch (err) {
      setError(errorMessage(err))
    }
  }

  if (!roster) return null
  return (
    <Section
      title="Attendance"
      description={`Auto-marked when students open this room while it's live · ${Object.entries(roster.counts).map(([k, v]) => `${v} ${k}`).join(" · ") || "no students"}`}
    >
      <ErrorText>{error}</ErrorText>
      <ul className="grid gap-x-6 gap-y-1.5 text-sm sm:grid-cols-2">
        {roster.students.map((s) => (
          <li key={s.student_id} className="flex items-center justify-between gap-2">
            <span className="truncate">
              {s.name}
              {s.first_seen_at ? <span className="text-xs text-muted-foreground"> · {formatDate(s.first_seen_at, true)}</span> : null}
            </span>
            <Select value={s.status} onChange={(e) => void mark(s.student_id, e.target.value)} className="w-28 py-1 text-xs">
              {s.status === "unmarked" ? <option value="unmarked">Unmarked</option> : null}
              <option value="present">Present</option>
              <option value="late">Late</option>
              <option value="absent">Absent</option>
              <option value="excused">Excused</option>
            </Select>
          </li>
        ))}
      </ul>
    </Section>
  )
}
