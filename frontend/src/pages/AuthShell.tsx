import type { ReactNode } from "react"
import { useNavigate } from "react-router-dom"

import { BrandLogo } from "@/components/BrandLogo"
import { Button } from "@/components/ui/button"

const AUTH_PANEL_IMAGE =
  "https://i.pinimg.com/736x/30/41/7d/30417d9aeb0f64beba68227a1fd34726.jpg"

export function AuthShell({
  title,
  subtitle,
  children,
  footer,
  wide = false,
}: {
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
    <div className="flex min-h-svh w-full flex-col bg-background lg:flex-row">
      <aside
        className={`relative h-44 w-full shrink-0 overflow-hidden sm:h-56 lg:h-auto lg:min-h-svh ${leftW}`}
      >
        <img
          src={AUTH_PANEL_IMAGE}
          alt=""
          className="absolute inset-0 h-full w-full object-cover object-center"
        />
        <div
          aria-hidden
          className="absolute inset-0 bg-gradient-to-t from-[#121826]/75 via-[#121826]/10 to-transparent"
        />
        <div className="absolute inset-x-0 bottom-0 p-5 text-white lg:p-10">
          <BrandLogo
            to={false}
            size={40}
            className="text-white"
            wordmarkClassName="text-2xl tracking-tight text-white lg:text-3xl"
          />
          <p className="mt-2 hidden max-w-md text-base leading-relaxed text-white/85 sm:block">
            Making Learning Easy
          </p>
        </div>
      </aside>

      <section
        className={`flex w-full flex-1 flex-col justify-center overflow-y-auto px-5 py-8 lg:h-svh lg:px-8 xl:px-10 ${rightW}`}
      >
        <div className={`mx-auto w-full ${maxW}`}>
          <div className="mb-5">
            <BrandLogo size={28} wordmarkClassName="text-base text-brand" />
          </div>
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
