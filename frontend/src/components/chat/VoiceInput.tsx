/** Record a voice question in the browser and turn it into text via /api/speech/transcribe/. */
import { useRef, useState } from "react"
import { Loader2, Mic, Square } from "lucide-react"

import { Button } from "@/components/ui/button"
import { apiUpload } from "@/lib/api"

const MAX_SECONDS = 120

export function VoiceInput({
  language,
  onText,
  disabled,
}: {
  language: string
  onText: (text: string) => void
  disabled?: boolean
}) {
  const [state, setState] = useState<"idle" | "recording" | "working">("idle")
  const [error, setError] = useState("")
  const recorder = useRef<MediaRecorder | null>(null)
  const timer = useRef<number | null>(null)

  if (typeof window === "undefined" || !("MediaRecorder" in window) || !navigator.mediaDevices) return null

  async function start() {
    setError("")
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const mime = MediaRecorder.isTypeSupported("audio/webm") ? "audio/webm" : ""
      const rec = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined)
      const chunks: Blob[] = []
      rec.ondataavailable = (e) => e.data.size && chunks.push(e.data)
      rec.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop())
        if (timer.current) window.clearTimeout(timer.current)
        setState("working")
        const type = rec.mimeType || "audio/webm"
        const ext = type.includes("ogg") ? "ogg" : type.includes("mp4") ? "m4a" : "webm"
        const fd = new FormData()
        fd.set("audio", new Blob(chunks, { type }), `question.${ext}`)
        if (language && language !== "en") fd.set("language", language)
        try {
          const res = await apiUpload<{ text: string }>("/api/speech/transcribe/", fd)
          if (res.text.trim()) onText(res.text.trim())
          else setError("Didn't catch that — try again.")
        } catch (err) {
          setError(err instanceof Error ? err.message : "Voice input failed")
        } finally {
          setState("idle")
        }
      }
      recorder.current = rec
      rec.start()
      setState("recording")
      timer.current = window.setTimeout(() => rec.state === "recording" && rec.stop(), MAX_SECONDS * 1000)
    } catch {
      setError("Microphone permission is needed for voice questions.")
    }
  }

  return (
    <div className="relative">
      <Button
        type="button"
        variant={state === "recording" ? "destructive" : "outline"}
        size="icon"
        className="size-11 shrink-0"
        disabled={disabled || state === "working"}
        title={state === "recording" ? "Stop and transcribe" : "Ask by voice"}
        onClick={() => (state === "recording" ? recorder.current?.stop() : void start())}
      >
        {state === "working" ? <Loader2 className="size-4 animate-spin" /> : state === "recording" ? <Square className="size-4" /> : <Mic className="size-4" />}
      </Button>
      {error ? <p className="absolute bottom-12 right-0 w-56 rounded bg-white p-1 text-xs text-destructive shadow">{error}</p> : null}
    </div>
  )
}
