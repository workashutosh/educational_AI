import { Link, useNavigate } from "react-router-dom"

import { BrandLogo } from "@/components/BrandLogo"
import { Button } from "@/components/ui/button"

export function LandingPage() {
  const navigate = useNavigate()

  return (
    <div className="relative min-h-svh overflow-hidden">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 -z-10"
        style={{
          background:
            "radial-gradient(ellipse 80% 55% at 12% 18%, #d6e4f9 0%, transparent 55%), radial-gradient(ellipse 60% 50% at 88% 8%, #d4e0ec 0%, transparent 50%), linear-gradient(180deg, #eef3fb 0%, #f7f8f6 45%, #e8ecf4 100%)",
        }}
      />
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 bottom-0 -z-10 h-[42vh] opacity-70"
        style={{
          backgroundImage:
            "url(\"data:image/svg+xml,%3Csvg width='60' height='60' viewBox='0 0 60 60' xmlns='http://www.w3.org/2000/svg'%3E%3Cg fill='none' fill-rule='evenodd'%3E%3Cg fill='%230058db' fill-opacity='0.05'%3E%3Cpath d='M36 34v-4h-2v4h-4v2h4v4h2v-4h4v-2h-4zm0-30V0h-2v4h-4v2h4v4h2V6h4V4h-4zM6 34v-4H4v4H0v2h4v4h2v-4h4v-2H6zM6 4V0H4v4H0v2h4v4h2V6h4V4H6z'/%3E%3C/g%3E%3C/g%3E%3C/svg%3E\")",
        }}
      />

      <header className="mx-auto flex w-full max-w-5xl items-center justify-between px-6 pt-6">
        <BrandLogo size={32} wordmarkClassName="text-lg text-brand" />
        <Button variant="ghost" onClick={() => navigate("/login")}>
          Sign in
        </Button>
      </header>

      <main className="mx-auto flex min-h-[calc(100svh-5rem)] w-full max-w-5xl flex-col justify-center px-6 pb-16 pt-10">
        <div className="max-w-2xl">
          <div className="flex flex-col gap-5">
            <BrandLogo to={false} withWordmark={false} size={72} />
            <h1 className="font-display text-5xl leading-[1.05] tracking-tight text-foreground sm:text-6xl md:text-7xl">
              ClassKit
            </h1>
          </div>
          <p className="mt-5 max-w-xl font-display text-2xl leading-snug text-foreground/85 sm:text-3xl">
            Making Learning Easy
          </p>
          <p className="mt-4 max-w-md text-base leading-relaxed text-muted-foreground sm:text-lg">
            Teachers upload class notes. Students and staff ask questions grounded in what was taught.
          </p>
          <div className="mt-9 flex flex-wrap gap-3">
            <Button size="lg" onClick={() => navigate("/onboard")}>
              Create your school
            </Button>
            <Button size="lg" variant="outline" onClick={() => navigate("/join")}>
              Join with code
            </Button>
          </div>
          <p className="mt-6 text-sm text-muted-foreground">
            Already have an account?{" "}
            <Link className="font-medium text-brand" to="/login">
              Sign in
            </Link>
          </p>
        </div>
      </main>
    </div>
  )
}
