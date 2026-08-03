import { useEffect, useState } from "react"
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom"
import {
  BookOpen,
  ClipboardList,
  GraduationCap,
  LayoutDashboard,
  LogOut,
  MessageSquareText,
  PanelLeftClose,
  PanelLeftOpen,
  Presentation,
  Settings2,
  Sparkles,
  Video,
  type LucideIcon,
} from "lucide-react"

import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { useAuth } from "@/lib/auth"

const SIDEBAR_KEY = "education_ai_sidebar_collapsed"

type NavItem = {
  to: string
  end: boolean
  label: string
  icon: LucideIcon
  requiresCreateStudents?: boolean
  /** When true, hidden from student accounts */
  staffOnly?: boolean
  /** Student-facing label override */
  studentLabel?: string
}

const nav: NavItem[] = [
  { to: "/app", end: true, label: "Home", icon: LayoutDashboard },
  { to: "/app/buckets", end: false, label: "AI Buckets", icon: BookOpen, staffOnly: true },
  {
    to: "/app/chat",
    end: false,
    label: "Chat",
    studentLabel: "AI Chat",
    icon: MessageSquareText,
  },
  { to: "/app/ppt", end: false, label: "Create PPT", icon: Presentation, staffOnly: true },
  {
    to: "/app/lectures",
    end: false,
    label: "Lectures",
    studentLabel: "My Lectures",
    icon: Video,
  },
  {
    to: "/app/mock-tests",
    end: false,
    label: "Mock Tests",
    studentLabel: "My Tests",
    icon: ClipboardList,
  },
  {
    to: "/app/students",
    end: false,
    label: "Students",
    icon: GraduationCap,
    requiresCreateStudents: true,
    staffOnly: true,
  },
  { to: "/app/settings", end: false, label: "Settings", icon: Settings2 },
]

export function AppLayout() {
  const { session, logout } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const school = session?.school
  const isStudent = session?.membership?.role === "student"
  const workspace =
    location.pathname.startsWith("/app/chat") ||
    (!isStudent && location.pathname.startsWith("/app/ppt"))
  const items = nav
    .filter((item) => {
      if (isStudent && item.staffOnly) return false
      if (item.requiresCreateStudents && !session?.can_create_students) return false
      return true
    })
    .map((item) => ({
      ...item,
      label: isStudent && item.studentLabel ? item.studentLabel : item.label,
    }))

  const [collapsed, setCollapsed] = useState(() => {
    try {
      return localStorage.getItem(SIDEBAR_KEY) === "1"
    } catch {
      return false
    }
  })

  useEffect(() => {
    try {
      localStorage.setItem(SIDEBAR_KEY, collapsed ? "1" : "0")
    } catch {
      /* ignore */
    }
  }, [collapsed])

  return (
    <div className="flex h-svh overflow-hidden bg-[#f3f6f8]">
      <aside
        className={cn(
          "hidden shrink-0 flex-col border-r border-border/80 bg-white/90 py-4 transition-[width] duration-200 ease-out md:flex",
          collapsed ? "w-[4.25rem] px-2" : "w-56 px-3",
        )}
      >
        <div className={cn("mb-4 flex items-start gap-2", collapsed ? "flex-col items-center" : "px-1")}>
          <div className={cn("min-w-0", collapsed ? "text-center" : "flex-1")}>
            <p
              className={cn(
                "flex items-center gap-2 font-display tracking-tight text-[var(--brand)]",
                collapsed ? "justify-center text-base" : "text-lg",
              )}
              title="Education AI"
            >
              <Sparkles className="size-4 shrink-0" />
              {!collapsed ? <span>Education AI</span> : null}
            </p>
            {!collapsed ? (
              <p className="mt-1 truncate text-xs text-muted-foreground">{school?.name}</p>
            ) : null}
          </div>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="size-8 shrink-0 text-muted-foreground"
            onClick={() => setCollapsed((c) => !c)}
            title={collapsed ? "Expand sidebar" : "Minimize sidebar"}
            aria-label={collapsed ? "Expand sidebar" : "Minimize sidebar"}
          >
            {collapsed ? <PanelLeftOpen className="size-4" /> : <PanelLeftClose className="size-4" />}
          </Button>
        </div>

        <nav className="flex flex-1 flex-col gap-0.5">
          {items.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              title={item.label}
              className={({ isActive }) =>
                cn(
                  "flex items-center rounded-lg py-2 text-sm font-medium transition",
                  collapsed ? "justify-center px-2" : "gap-2.5 px-3",
                  isActive
                    ? "bg-[#e6f4ef] text-[var(--brand)]"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground",
                )
              }
            >
              <item.icon className="size-4 shrink-0" />
              {!collapsed ? <span>{item.label}</span> : null}
            </NavLink>
          ))}
        </nav>

        <div className="mt-auto space-y-2 border-t border-border/70 pt-3">
          {!collapsed ? (
            <p className="truncate px-2 text-xs text-muted-foreground">
              {session?.user.email || session?.user.username}
              <br />
              <span className="text-foreground/80">{session?.membership?.role_display}</span>
            </p>
          ) : null}
          <Button
            variant="outline"
            size={collapsed ? "icon" : "default"}
            className={cn(collapsed ? "mx-auto size-9" : "w-full justify-start gap-2")}
            title="Sign out"
            onClick={() => {
              void logout().then(() => navigate("/login"))
            }}
          >
            <LogOut className="size-4" />
            {!collapsed ? "Sign out" : null}
          </Button>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between gap-3 border-b border-border/80 bg-white/70 px-3 py-2.5 md:hidden">
          <p className="font-display text-base text-[var(--brand)]">Education AI</p>
          <div className="flex gap-0.5 overflow-x-auto">
            {items.map((item) => (
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
                title={item.label}
              >
                <item.icon className="size-4" />
              </NavLink>
            ))}
          </div>
        </header>
        <main
          className={cn(
            "min-h-0 flex-1",
            workspace ? "overflow-hidden" : "overflow-y-auto px-4 py-5 sm:px-5",
          )}
        >
          <Outlet />
        </main>
      </div>
    </div>
  )
}
