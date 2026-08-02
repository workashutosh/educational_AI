import { useEffect, useState, type FormEvent } from "react"
import { useSearchParams } from "react-router-dom"
import {
  ChevronLeft,
  ChevronRight,
  Download,
  Loader2,
  Presentation,
} from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { api, apiDownload, triggerBlobDownload } from "@/lib/api"
import { useAuth } from "@/lib/auth"
import { cn } from "@/lib/utils"

type PptSlide = {
  heading: string
  bullets: string[]
  notes?: string
}

type PptOutline = {
  title: string
  slides: PptSlide[]
  slide_count: number
  prompt: string
}

export function CreatePptPage() {
  const { session } = useAuth()
  const buckets = session?.buckets || []
  const [searchParams, setSearchParams] = useSearchParams()
  const bucketId = Number(searchParams.get("bucket") || buckets[0]?.id || 0) || null

  const [prompt, setPrompt] = useState("")
  const [slideCount, setSlideCount] = useState(8)
  const [busy, setBusy] = useState(false)
  const [downloading, setDownloading] = useState(false)
  const [error, setError] = useState("")
  const [outline, setOutline] = useState<PptOutline | null>(null)
  const [slideIndex, setSlideIndex] = useState(0)
  const [doneName, setDoneName] = useState("")

  useEffect(() => {
    if (!bucketId && buckets[0]) {
      setSearchParams({ bucket: String(buckets[0].id) }, { replace: true })
    }
  }, [bucketId, buckets, setSearchParams])

  async function generate(e: FormEvent) {
    e.preventDefault()
    const text = prompt.trim()
    if (!text || busy || !bucketId) return
    setBusy(true)
    setError("")
    setDoneName("")
    setOutline(null)
    setSlideIndex(0)
    try {
      const res = await api<PptOutline>("/api/generate-pptx/", {
        method: "POST",
        body: JSON.stringify({
          bucket_id: bucketId,
          prompt: text,
          slide_count: slideCount,
        }),
      })
      setOutline(res)
      setSlideIndex(0)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not generate PPT")
    } finally {
      setBusy(false)
    }
  }

  async function download() {
    if (!outline || downloading || !bucketId) return
    setDownloading(true)
    setError("")
    try {
      const { blob, filename } = await apiDownload("/api/generate-pptx/download/", {
        method: "POST",
        body: JSON.stringify({
          bucket_id: bucketId,
          title: outline.title,
          slides: outline.slides,
        }),
      })
      triggerBlobDownload(blob, filename)
      setDoneName(filename)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not download PPT")
    } finally {
      setDownloading(false)
    }
  }

  const previewSlides = outline
    ? [
        {
          kind: "title" as const,
          heading: outline.title,
          bullets: ["Generated from your AI Bucket notes"],
        },
        ...outline.slides.map((s) => ({
          kind: "content" as const,
          heading: s.heading,
          bullets: s.bullets,
        })),
      ]
    : []
  const current = previewSlides[slideIndex]
  const activeBucket = buckets.find((b) => b.id === bucketId)

  if (!buckets.length) {
    return (
      <div className="flex h-full items-center justify-center p-8 text-center text-muted-foreground">
        <div>
          <p className="font-medium text-foreground">No AI Buckets yet</p>
          <p className="mt-1 text-sm">Create an AI Bucket and index notes before generating a PPT.</p>
        </div>
      </div>
    )
  }

  return (
    <div className="flex h-full min-h-0 w-full flex-col">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-border/70 bg-white/90 px-4 py-3 sm:px-6">
        <div className="min-w-0">
          <h1 className="flex items-center gap-2 font-display text-xl tracking-tight">
            <Presentation className="size-5 text-[var(--brand)]" />
            Create PPT
          </h1>
          <p className="text-xs text-muted-foreground">
            Preview from indexed notes, then download when you’re ready
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Label htmlFor="ppt-bucket" className="sr-only">
            AI Bucket
          </Label>
          <select
            id="ppt-bucket"
            value={bucketId || ""}
            onChange={(e) => {
              setOutline(null)
              setDoneName("")
              setSearchParams({ bucket: e.target.value }, { replace: true })
            }}
            className="min-w-[12rem] rounded-lg border border-input bg-transparent px-2.5 py-2 text-sm outline-none focus-visible:border-ring"
          >
            {buckets.map((b) => (
              <option key={b.id} value={b.id}>
                {b.name}
              </option>
            ))}
          </select>
        </div>
      </header>

      <div className="grid min-h-0 flex-1 lg:grid-cols-[minmax(18rem,24rem)_1fr]">
        {/* Controls */}
        <div className="overflow-y-auto border-b border-border/70 bg-white/80 p-4 sm:p-5 lg:border-b-0 lg:border-r">
          <p className="mb-3 text-xs text-muted-foreground">
            Using <span className="font-medium text-foreground">{activeBucket?.name}</span>
          </p>
          <form onSubmit={generate} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="ppt-prompt">Prompt</Label>
              <textarea
                id="ppt-prompt"
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                disabled={busy}
                rows={6}
                placeholder="e.g. Create a PPT on Calculus chapter 2"
                className="w-full resize-y rounded-xl border border-input bg-transparent px-3 py-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="ppt-slides">Number of slides</Label>
              <div className="flex flex-wrap items-center gap-2">
                <Input
                  id="ppt-slides"
                  type="number"
                  min={3}
                  max={15}
                  value={slideCount}
                  disabled={busy}
                  onChange={(e) => {
                    const n = Number(e.target.value)
                    if (Number.isNaN(n)) return
                    setSlideCount(Math.min(15, Math.max(3, n)))
                  }}
                  className="w-20"
                />
                {[5, 8, 10, 12].map((n) => (
                  <button
                    key={n}
                    type="button"
                    disabled={busy}
                    onClick={() => setSlideCount(n)}
                    className={cn(
                      "rounded-lg border px-2.5 py-1 text-xs font-medium transition",
                      slideCount === n
                        ? "border-[var(--brand)] bg-[#e6f4ef] text-[var(--brand)]"
                        : "border-border/80 text-muted-foreground hover:border-border",
                    )}
                  >
                    {n}
                  </button>
                ))}
              </div>
            </div>
            <Button type="submit" disabled={busy || !prompt.trim()} className="w-full gap-2">
              {busy ? <Loader2 className="size-4 animate-spin" /> : <Presentation className="size-4" />}
              {busy ? "Generating…" : outline ? "Regenerate preview" : "Generate preview"}
            </Button>
          </form>
          {error ? <p className="mt-3 text-sm text-destructive">{error}</p> : null}
          {doneName ? (
            <p className="mt-3 text-sm text-[var(--brand)]">Downloaded {doneName}</p>
          ) : null}
        </div>

        {/* Preview stage — full remaining width */}
        <div className="flex min-h-0 min-w-0 flex-col overflow-y-auto bg-[#f3f6f8] p-4 sm:p-6">
          {!outline && !busy ? (
            <div className="flex flex-1 items-center justify-center rounded-2xl border border-dashed border-border/80 bg-white/50 text-center text-sm text-muted-foreground">
              <div className="px-6 py-16">
                <Presentation className="mx-auto mb-3 size-8 text-[var(--brand)]/50" />
                <p className="font-medium text-foreground">Slide preview</p>
                <p className="mt-1">Generate a preview to browse slides here at full width.</p>
              </div>
            </div>
          ) : null}

          {busy ? (
            <div className="flex flex-1 items-center justify-center text-sm text-muted-foreground">
              <Loader2 className="mr-2 size-4 animate-spin" />
              Gathering notes and drafting slides…
            </div>
          ) : null}

          {outline && current ? (
            <div className="mx-auto flex w-full max-w-5xl flex-col gap-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <p className="font-medium">{outline.title}</p>
                  <p className="text-xs text-muted-foreground">
                    {outline.slide_count} content slides · title slide in preview
                  </p>
                </div>
                <div className="flex gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      setOutline(null)
                      setSlideIndex(0)
                      setDoneName("")
                    }}
                  >
                    Clear
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    className="gap-2"
                    disabled={downloading}
                    onClick={() => void download()}
                  >
                    {downloading ? (
                      <Loader2 className="size-4 animate-spin" />
                    ) : (
                      <Download className="size-4" />
                    )}
                    {downloading ? "Preparing…" : "Download .pptx"}
                  </Button>
                </div>
              </div>

              <div className="overflow-hidden rounded-xl border border-border/80 bg-gradient-to-br from-[#f7faf8] to-[#eef5f1] shadow-sm">
                <div className="aspect-[16/9] p-6 sm:p-10 lg:p-12">
                  {current.kind === "title" ? (
                    <div className="flex h-full flex-col justify-center">
                      <p className="font-display text-3xl tracking-tight text-[var(--brand)] sm:text-4xl">
                        {current.heading}
                      </p>
                      <p className="mt-4 text-base text-muted-foreground">{current.bullets[0]}</p>
                    </div>
                  ) : (
                    <div className="flex h-full flex-col">
                      <h3 className="font-display text-2xl tracking-tight text-[var(--brand)] sm:text-3xl">
                        {current.heading}
                      </h3>
                      <ul className="mt-6 space-y-3 overflow-y-auto text-base text-foreground/90 sm:text-lg">
                        {current.bullets.map((b, i) => (
                          <li key={i} className="flex gap-3">
                            <span className="mt-2 size-2 shrink-0 rounded-full bg-[var(--brand)]" />
                            <span>{b}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
                <div className="flex items-center justify-between border-t border-border/60 bg-white/70 px-3 py-2">
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    disabled={slideIndex <= 0}
                    onClick={() => setSlideIndex((i) => Math.max(0, i - 1))}
                  >
                    <ChevronLeft className="size-4" />
                    Prev
                  </Button>
                  <p className="text-xs text-muted-foreground">
                    Slide {slideIndex + 1} of {previewSlides.length}
                  </p>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    disabled={slideIndex >= previewSlides.length - 1}
                    onClick={() =>
                      setSlideIndex((i) => Math.min(previewSlides.length - 1, i + 1))
                    }
                  >
                    Next
                    <ChevronRight className="size-4" />
                  </Button>
                </div>
              </div>

              <div className="flex gap-2 overflow-x-auto pb-1">
                {previewSlides.map((s, i) => (
                  <button
                    key={i}
                    type="button"
                    onClick={() => setSlideIndex(i)}
                    className={cn(
                      "w-32 shrink-0 rounded-lg border px-2 py-2 text-left transition",
                      i === slideIndex
                        ? "border-[var(--brand)] bg-[#e6f4ef]"
                        : "border-border/70 bg-white/60 hover:border-border",
                    )}
                  >
                    <p className="text-[10px] text-muted-foreground">
                      {s.kind === "title" ? "Title" : `Slide ${i}`}
                    </p>
                    <p className="mt-0.5 line-clamp-2 text-[11px] font-medium leading-snug">
                      {s.heading}
                    </p>
                  </button>
                ))}
              </div>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  )
}
