import { NavLink, Outlet, useNavigate } from "react-router-dom"
import { BookOpen, LayoutDashboard, LogOut, Settings2, Sparkles } from "lucide-react"

import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { useAuth } from "@/lib/auth"

const nav = [
  { to: "/app", end: true, label: "Home", icon: LayoutDashboard },
  { to: "/app/buckets", end: false, label: "AI Buckets", icon: BookOpen },
  { to: "/app/settings", end: false, label: "Settings", icon: Settings2 },
]

export function AppLayout() {
  const { session, logout } = useAuth()
  const navigate = useNavigate()
  const school = session?.school

  return (
    <div className="flex min-h-svh bg-[#f3f6f8]">
      <aside className="hidden w-60 shrink-0 flex-col border-r border-border/80 bg-white/80 px-4 py-6 md:flex">
        <div className="mb-8 px-2">
          <p className="flex items-center gap-2 font-display text-lg tracking-tight text-[var(--brand)]">
            <Sparkles className="size-4" />
            Education AI
          </p>
          <p className="mt-1 truncate text-xs text-muted-foreground">{school?.name}</p>
        </div>
        <nav className="flex flex-1 flex-col gap-1">
          {nav.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium transition",
                  isActive
                    ? "bg-[#e6f4ef] text-[var(--brand)]"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground",
                )
              }
            >
              <item.icon className="size-4" />
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="mt-auto space-y-2 border-t border-border/70 pt-4">
          <p className="truncate px-2 text-xs text-muted-foreground">
            {session?.user.email || session?.user.username}
            <br />
            <span className="text-foreground/80">{session?.membership?.role_display}</span>
          </p>
          <Button
            variant="outline"
            className="w-full justify-start gap-2"
            onClick={() => {
              void logout().then(() => navigate("/login"))
            }}
          >
            <LogOut className="size-4" />
            Sign out
          </Button>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between gap-3 border-b border-border/80 bg-white/70 px-4 py-3 md:hidden">
          <p className="font-display text-base text-[var(--brand)]">Education AI</p>
          <div className="flex gap-1">
            {nav.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  cn(
                    "rounded-lg p-2",
                    isActive ? "bg-[#e6f4ef] text-[var(--brand)]" : "text-muted-foreground",
                  )
                }
              >
                <item.icon className="size-4" />
              </NavLink>
            ))}
          </div>
        </header>
        <main className="flex-1 overflow-y-auto px-4 py-6 sm:px-6 lg:px-8">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
