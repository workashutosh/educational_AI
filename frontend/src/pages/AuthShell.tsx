import type { ReactNode } from "react"
import { Link, useNavigate } from "react-router-dom"

import { Button } from "@/components/ui/button"

export function AuthShell({
  brand = "Education AI",
  title,
  subtitle,
  children,
  footer,
  wide = false,
}: {
  brand?: string
  title: string
  subtitle?: string
  children: ReactNode
  footer?: ReactNode
  /** Wider form column (e.g. plan / bucket picker). */
  wide?: boolean
}) {
  const navigate = useNavigate()
  const leftW = wide ? "lg:w-[60%]" : "lg:w-[70%]"
  const rightW = wide ? "lg:w-[40%]" : "lg:w-[30%]"
  const maxW = wide ? "max-w-md" : "max-w-sm"

  return (
    <div className="flex min-h-svh w-full flex-col bg-[#f3f6f8] lg:flex-row">
      <aside
        className={`relative h-44 w-full shrink-0 overflow-hidden sm:h-56 lg:h-auto lg:min-h-svh ${leftW}`}
      >
        <img
          src="/auth-panel.jpg"
          alt=""
          className="absolute inset-0 h-full w-full object-cover"
        />
        <div
          aria-hidden
          className="absolute inset-0 bg-gradient-to-t from-[#0b6e4f]/60 via-[#1a2332]/20 to-transparent"
        />
        <div className="absolute inset-x-0 bottom-0 p-5 text-white lg:p-10">
          <p className="font-display text-2xl tracking-tight lg:text-3xl">Education AI</p>
          <p className="mt-1 hidden max-w-md text-base leading-relaxed text-white/85 sm:block">
            Notes that answer back — grounded in what your school actually teaches.
          </p>
        </div>
      </aside>

      <section
        className={`flex w-full flex-1 flex-col justify-center overflow-y-auto px-5 py-8 lg:h-svh lg:px-8 xl:px-10 ${rightW}`}
      >
        <div className={`mx-auto w-full ${maxW}`}>
          <Link
            to="/"
            className="mb-5 inline-block font-display text-sm tracking-[0.14em] uppercase text-[var(--brand)]"
          >
            {brand}
          </Link>
          <h1 className="font-display text-3xl tracking-tight text-foreground">{title}</h1>
          {subtitle ? (
            <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{subtitle}</p>
          ) : null}
          <div className="mt-6 space-y-4">{children}</div>
          {footer ? (
            <div className="mt-5 text-center text-sm text-muted-foreground">{footer}</div>
          ) : null}
          <div className="mt-3 flex justify-center">
            <Button variant="link" onClick={() => navigate("/")}>
              Back to home
            </Button>
          </div>
        </div>
      </section>
    </div>
  )
}
