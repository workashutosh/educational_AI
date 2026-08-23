import { useEffect, useRef } from "react"

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
    .replace(/\[(\d+)\]/g, '<span class="font-semibold text-brand">[$1]</span>')
    .replace(/\n{2,}/g, "<br/>")
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

  return (
    <div className={cn("space-y-2", className)}>
      <div
        ref={ref}
        className="math-body text-sm leading-normal [&_code]:text-[0.85em]"
      />
      {sources?.length ? (
        <div className="flex flex-wrap gap-1.5 border-t border-border/50 pt-2">
          {sources.slice(0, 6).map((s, j) => (
            <span
              key={j}
              className="rounded-md bg-[#f7f9fd] px-1.5 py-0.5 text-[11px] text-muted-foreground"
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
