import { useEffect, useRef } from "react"

import { getToken } from "@/lib/api"
import type { AskSource } from "@/lib/api"
import { cn } from "@/lib/utils"

declare global {
  interface Window {
    katex?: unknown
    renderMathInElement?: (
      el: HTMLElement,
      opts: {
        delimiters: { left: string; right: string; display: boolean }[]
        throwOnError: boolean
        trust: boolean
      },
    ) => void
  }
}

function escapeHtml(s: string) {
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
}

/** Escape prose but keep LaTeX delimiters intact for KaTeX auto-render. */
function formatAnswerHtml(text: string) {
  const chunks: string[] = []
  const protected_ = String(text).replace(
    /(\$\$[\s\S]+?\$\$|\$[^$\n]+?\$|\\\[[\s\S]+?\\\]|\\\([\s\S]+?\\\))/g,
    (m) => {
      chunks.push(m)
      return `\u0000MATH${chunks.length - 1}\u0000`
    },
  )
  let html = escapeHtml(protected_)
  // light markdown: **bold**, `code`, line breaks, bullets
  html = html
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/`([^`]+)`/g, "<code class='rounded bg-muted px-1'>$1</code>")
    .replace(/^### (.+)$/gm, "<h4 class='mt-2 font-semibold'>$1</h4>")
    .replace(/^## (.+)$/gm, "<h3 class='mt-2 font-semibold'>$1</h3>")
    .replace(/^# (.+)$/gm, "<h3 class='mt-2 font-semibold'>$1</h3>")
    .replace(/^[-*] (.+)$/gm, "<li class='ml-4 list-disc'>$1</li>")
    .replace(/\[(\d+)\]/g, '<span class="font-semibold text-[var(--brand)]">[$1]</span>')
    .replace(/\n{2,}/g, "<br/><br/>")
    .replace(/\n/g, "<br/>")
  html = html.replace(/\u0000MATH(\d+)\u0000/g, (_, i) => chunks[Number(i)])
  return html
}

function typesetMath(el: HTMLElement) {
  const attempt = (n: number) => {
    if (typeof window.renderMathInElement === "function" && window.katex) {
      try {
        window.renderMathInElement(el, {
          delimiters: [
            { left: "$$", right: "$$", display: true },
            { left: "\\[", right: "\\]", display: true },
            { left: "$", right: "$", display: false },
            { left: "\\(", right: "\\)", display: false },
          ],
          throwOnError: false,
          trust: true,
        })
      } catch {
        /* ignore malformed fragments */
      }
      return
    }
    if (n < 40) window.setTimeout(() => attempt(n + 1), 50)
  }
  attempt(0)
}

function AuthPageImage({
  url,
  label,
}: {
  url: string
  label: string
}) {
  const imgRef = useRef<HTMLImageElement>(null)

  useEffect(() => {
    let revoked: string | null = null
    let cancelled = false
    ;(async () => {
      try {
        const token = getToken()
        const res = await fetch(url, {
          headers: token ? { Authorization: `Token ${token}` } : {},
        })
        if (!res.ok || cancelled) return
        const blob = await res.blob()
        const obj = URL.createObjectURL(blob)
        revoked = obj
        if (imgRef.current) imgRef.current.src = obj
      } catch {
        /* ignore */
      }
    })()
    return () => {
      cancelled = true
      if (revoked) URL.revokeObjectURL(revoked)
    }
  }, [url])

  return (
    <figure className="overflow-hidden rounded-xl border border-border/70 bg-[#f7faf8]">
      <img
        ref={imgRef}
        alt={label}
        className="max-h-72 w-full object-contain bg-white"
      />
      <figcaption className="truncate px-2 py-1 text-[11px] text-muted-foreground">
        {label}
      </figcaption>
    </figure>
  )
}

export function RichAnswer({
  content,
  sources,
  className,
}: {
  content: string
  sources?: AskSource[]
  className?: string
}) {
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const el = ref.current
    if (!el) return
    el.innerHTML = formatAnswerHtml(content)
    typesetMath(el)
  }, [content])

  const images = (sources || []).filter(
    (s) => s.image_url && s.document_id && s.page_start,
  )
  // de-dupe by document+page
  const seen = new Set<string>()
  const uniqueImages = images.filter((s) => {
    const key = `${s.document_id}:${s.page_start}`
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })

  return (
    <div className={cn("space-y-3", className)}>
      <div
        ref={ref}
        className="text-sm leading-relaxed [&_.katex-display]:my-3 [&_.katex-display]:overflow-x-auto [&_code]:text-[0.85em]"
      />
      {uniqueImages.length ? (
        <div className="space-y-2 border-t border-border/50 pt-2">
          <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
            From your notes
          </p>
          <div className="grid gap-2 sm:grid-cols-2">
            {uniqueImages.slice(0, 4).map((s) => (
              <AuthPageImage
                key={`${s.document_id}-${s.page_start}`}
                url={s.image_url!}
                label={`${s.document_filename || "Note"}${s.page_ref ? ` · ${s.page_ref}` : ""}`}
              />
            ))}
          </div>
        </div>
      ) : null}
      {sources?.length ? (
        <div className="flex flex-wrap gap-1.5 border-t border-border/50 pt-2">
          {sources.slice(0, 6).map((s, j) => (
            <span
              key={j}
              className="rounded-md bg-[#f7faf8] px-1.5 py-0.5 text-[11px] text-muted-foreground"
            >
              [{s.index ?? j + 1}] {s.document_filename || `doc ${s.document_id}`}
              {s.page_ref ? ` · ${s.page_ref}` : ""}
            </span>
          ))}
        </div>
      ) : null}
    </div>
  )
}
