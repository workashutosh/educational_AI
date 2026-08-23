import type { ReactNode } from "react"
import { Link, useNavigate } from "react-router-dom"

import authHeroUrl from "@/assets/auth-hero.jpg"
import { BrandLogo } from "@/components/BrandLogo"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

/** Left-panel wallpaper for login / join / onboard (DeepSeek-style auth). */
export const AUTH_HERO_IMAGE = authHeroUrl

export function AuthShell({
  title,
  subtitle,
  children,
  footer,
  wide = false,
  heroTitle = "Making Learning Easy",
  heroSubtitle = "Notes that answer back — grounded in what your school actually teaches.",
}: {
  title: string
  subtitle?: string
  children: ReactNode
  footer?: ReactNode
  /** Wider form column (e.g. plan / bucket picker). */
  wide?: boolean
  heroTitle?: string
  heroSubtitle?: string
}) {
  const navigate = useNavigate()
  const leftW = wide ? "lg:w-[45%]" : "lg:w-[42%]"
  const rightW = wide ? "lg:w-[55%]" : "lg:w-[58%]"
  const maxW = wide ? "max-w-lg" : "max-w-[22rem]"

  return (
    <div className={cn("auth-dark flex min-h-svh w-full flex-col bg-black lg:flex-row")}>
      <aside
        className={cn(
          "relative h-48 w-full shrink-0 overflow-hidden sm:h-56 lg:h-auto lg:min-h-svh",
          leftW,
        )}
      >
        <img
          src={AUTH_HERO_IMAGE}
          alt=""
          className="absolute inset-0 h-full w-full object-cover object-center"
        />
        <div
          aria-hidden
          className="absolute inset-0 bg-gradient-to-t from-black/70 via-black/25 to-black/10"
        />
        <div className="absolute inset-x-0 bottom-0 p-6 text-white lg:p-10 xl:p-12">
          <BrandLogo
            to={false}
            size={36}
            className="text-white"
            wordmarkClassName="text-xl tracking-tight text-white lg:text-2xl"
          />
          <h2 className="mt-6 max-w-md font-display text-2xl leading-tight tracking-tight text-white sm:text-3xl lg:text-4xl">
            {heroTitle}
          </h2>
          <p className="mt-3 hidden max-w-sm text-sm leading-relaxed text-white/75 sm:block lg:text-base">
            {heroSubtitle}
          </p>
        </div>
      </aside>

      <section
        className={cn(
          "flex w-full flex-1 flex-col justify-center overflow-y-auto bg-black px-6 py-10 lg:h-svh lg:px-12 xl:px-16",
          rightW,
        )}
      >
        <div className={cn("mx-auto w-full", maxW)}>
          <div className="mb-8 flex justify-center lg:justify-start">
            <BrandLogo
              size={32}
              wordmarkClassName="text-lg text-white"
              className="text-white"
            />
          </div>
          <h1 className="text-center text-2xl font-semibold tracking-tight text-white lg:text-left">
            {title}
          </h1>
          {subtitle ? (
            <p className="mt-2 text-center text-sm leading-relaxed text-white/55 lg:text-left">
              {subtitle}
            </p>
          ) : null}
          <div className="mt-8 space-y-4">{children}</div>
          {footer ? (
            <div className="mt-6 text-center text-sm text-white/55">{footer}</div>
          ) : null}
          <div className="mt-4 flex justify-center">
            <Button
              variant="link"
              className="text-white/50 hover:text-white"
              onClick={() => navigate("/")}
            >
              Back to home
            </Button>
          </div>
          <p className="mt-8 text-center text-xs text-white/35">
            By continuing you agree to ClassKit’s{" "}
            <Link to="/" className="underline underline-offset-2 hover:text-white/60">
              Terms
            </Link>{" "}
            &{" "}
            <Link to="/" className="underline underline-offset-2 hover:text-white/60">
              Privacy
            </Link>
            .
          </p>
        </div>
      </section>
    </div>
  )
}
