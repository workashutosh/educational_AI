import { useEffect, useState } from "react"
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom"
import {
  BarChart3,
  BookCheck,
  BookOpen,
  ClipboardList,
  CreditCard,
  Database,
  FileText,
  HelpCircle,
  Layers,
  UsersRound,
  GraduationCap,
  LayoutDashboard,
  LogOut,
  MessageSquareText,
  PanelLeftClose,
  PanelLeftOpen,
  Presentation,
  Settings2,
  Users,
  Video,
  type LucideIcon,
} from "lucide-react"

import { BrandLogo } from "@/components/BrandLogo"
import { Button } from "@/components/ui/button"
import { NotificationBell } from "@/components/app/NotificationBell"
import { cn } from "@/lib/utils"
import { useAuth } from "@/lib/auth"

const SIDEBAR_KEY = "education_ai_sidebar_collapsed"

type NavItem = {
  to: string
  end: boolean
  label: string
  icon: LucideIcon
  /** admin | manager | teacher | student — omit = all roles */
  roles?: string[]
  /** Student-facing label override */
  studentLabel?: string
}

const nav: NavItem[] = [
  { to: "/app", end: true, label: "Home", icon: LayoutDashboard },
  {
    to: "/app/buckets",
    end: false,
    label: "AI Buckets",
    icon: BookOpen,
    roles: ["admin", "manager", "teacher"],
  },
  {
    to: "/app/chat",
    end: false,
    label: "Chat",
    studentLabel: "AI Chat",
    icon: MessageSquareText,
  },
  {
    to: "/app/ppt",
    end: false,
    label: "Create PPT",
    icon: Presentation,
    roles: ["admin", "manager", "teacher"],
  },
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
    to: "/app/homework",
    end: false,
    label: "Homework",
    studentLabel: "My Homework",
    icon: BookCheck,
  },
  { to: "/app/flashcards", end: false, label: "Flashcards", icon: Layers },
  {
    to: "/app/doubts",
    end: false,
    label: "Doubts",
    studentLabel: "My Doubts",
    icon: HelpCircle,
  },
  {
    to: "/app/insights",
    end: false,
    label: "Insights",
    studentLabel: "My Progress",
    icon: BarChart3,
  },
  {
    to: "/app/question-bank",
    end: false,
    label: "Question Bank",
    icon: Database,
    roles: ["admin", "manager", "teacher"],
  },
  {
    to: "/app/papers",
    end: false,
    label: "Question Papers",
    icon: FileText,
    roles: ["admin", "manager", "teacher"],
  },
  {
    to: "/app/members",
    end: false,
    label: "Members",
    icon: Users,
    roles: ["admin", "manager"],
  },
  {
    to: "/app/students",
    end: false,
    label: "Students",
    icon: GraduationCap,
    roles: ["teacher"],
  },
  {
    to: "/app/parents",
    end: false,
    label: "Parents",
    icon: UsersRound,
    roles: ["admin", "manager", "teacher"],
  },
  {
    to: "/app/billing",
    end: false,
    label: "Billing & Usage",
    icon: CreditCard,
    roles: ["admin", "manager"],
  },
  { to: "/app/settings", end: false, label: "Settings", icon: Settings2 },
]

export function AppLayout() {
  const { session, logout } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const school = session?.school
  const role = session?.membership?.role || ""
  const isStudent = role === "student"
  const workspace =
    location.pathname.startsWith("/app/chat") ||
    (!isStudent && location.pathname.startsWith("/app/ppt"))
  const items = nav
    .filter((item) => {
      if (!item.roles) return true
      return item.roles.includes(role)
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
    <div className="fixed inset-0 flex overflow-hidden bg-background">
      <aside
        className={cn(
          "hidden shrink-0 flex-col border-r border-border/80 bg-white/90 py-4 transition-[width] duration-200 ease-out md:flex",
          collapsed ? "w-[4.25rem] px-2" : "w-56 px-3",
        )}
      >
        <div className={cn("mb-4 flex items-start gap-1", collapsed ? "flex-col items-center" : "px-1")}>
          <div className={cn("min-w-0", collapsed ? "text-center" : "flex-1")}>
            <BrandLogo
              to={false}
              withWordmark={!collapsed}
              size={collapsed ? 28 : 30}
              className={cn(collapsed ? "justify-center" : "", "text-brand")}
              wordmarkClassName={collapsed ? "text-base" : "text-lg"}
            />
            {!collapsed ? (
              <p className="mt-1 truncate text-xs text-muted-foreground">{school?.name}</p>
            ) : null}
          </div>
          <div className={cn("flex shrink-0 items-center", collapsed ? "flex-col gap-1" : "gap-0.5")}>
            <NotificationBell />
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="size-8 text-muted-foreground"
              onClick={() => setCollapsed((c) => !c)}
              title={collapsed ? "Expand sidebar" : "Minimize sidebar"}
              aria-label={collapsed ? "Expand sidebar" : "Minimize sidebar"}
            >
              {collapsed ? <PanelLeftOpen className="size-4" /> : <PanelLeftClose className="size-4" />}
            </Button>
          </div>
        </div>

        <nav className="flex min-h-0 flex-1 flex-col gap-0.5 overflow-y-auto">
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
                    ? "bg-brand-soft text-brand"
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

      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        <header className="flex shrink-0 items-center justify-between gap-3 border-b border-border/80 bg-white/70 px-3 py-2.5 md:hidden">
          <BrandLogo to={false} size={26} wordmarkClassName="text-base text-brand" />
          <div className="flex items-center gap-1">
            <NotificationBell />
            <div className="flex gap-0.5 overflow-x-auto">
              {items.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.end}
                  className={({ isActive }) =>
                    cn(
                      "rounded-lg p-2",
                      isActive ? "bg-brand-soft text-brand" : "text-muted-foreground",
                    )
                  }
                  title={item.label}
                >
                  <item.icon className="size-4" />
                </NavLink>
              ))}
            </div>
          </div>
        </header>
        <main
          className={cn(
            // h-0 + flex-1 gives the pane a definite height (critical for chat fill)
            "relative h-0 min-h-0 flex-1",
            workspace
              ? "overflow-hidden"
              : "overflow-y-auto px-4 py-5 sm:px-5",
          )}
        >
          <Outlet />
        </main>
      </div>
    </div>
  )
}
