import { useCallback, useEffect, useRef, useState } from "react"
import { Link } from "react-router-dom"
import { Bell } from "lucide-react"

import { Button } from "@/components/ui/button"
import { api } from "@/lib/api"
import { cn } from "@/lib/utils"

export type EngagementNotification = {
  id: number
  kind: string
  title: string
  body: string
  link_path: string
  is_read: boolean
  created_at: string
}

export function NotificationBell() {
  const [open, setOpen] = useState(false)
  const [items, setItems] = useState<EngagementNotification[]>([])
  const [unread, setUnread] = useState(0)
  const ref = useRef<HTMLDivElement>(null)

  const load = useCallback(async () => {
    try {
      const rows = await api<EngagementNotification[]>("/api/engagement/notifications/")
      setItems(rows)
      setUnread(rows.filter((n) => !n.is_read).length)
    } catch {
      /* ignore */
    }
  }, [])

  useEffect(() => {
    void load()
    const t = window.setInterval(() => void load(), 60000)
    return () => window.clearInterval(t)
  }, [load])

  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (!ref.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener("mousedown", onDoc)
    return () => document.removeEventListener("mousedown", onDoc)
  }, [])

  async function markRead(id: number) {
    try {
      await api(`/api/engagement/notifications/${id}/read/`, { method: "POST" })
      await load()
    } catch {
      /* ignore */
    }
  }

  async function markAll() {
    try {
      await api("/api/engagement/notifications/read-all/", { method: "POST" })
      await load()
    } catch {
      /* ignore */
    }
  }

  return (
    <div className="relative" ref={ref}>
      <Button
        type="button"
        variant="ghost"
        size="icon"
        className="relative size-9"
        aria-label="Notifications"
        onClick={() => {
          setOpen((v) => !v)
          void load()
        }}
      >
        <Bell className="size-4" />
        {unread > 0 ? (
          <span className="absolute right-1 top-1 flex size-4 items-center justify-center rounded-full bg-brand text-[10px] font-medium text-white">
            {unread > 9 ? "9+" : unread}
          </span>
        ) : null}
      </Button>
      {open ? (
        <div className="absolute left-0 z-50 mt-2 w-[min(22rem,calc(100vw-2rem))] overflow-hidden rounded-xl border border-border/80 bg-white shadow-lg md:left-full md:ml-1 md:mt-0 md:top-0">
          <div className="flex items-center justify-between border-b border-border/70 px-3 py-2">
            <p className="text-sm font-medium">Notifications</p>
            {unread ? (
              <button
                type="button"
                className="text-xs text-brand"
                onClick={() => void markAll()}
              >
                Mark all read
              </button>
            ) : null}
          </div>
          <ul className="max-h-80 overflow-y-auto">
            {items.length ? (
              items.map((n) => (
                <li key={n.id}>
                  <Link
                    to={n.link_path || "/app"}
                    onClick={() => {
                      setOpen(false)
                      if (!n.is_read) void markRead(n.id)
                    }}
                    className={cn(
                      "block px-3 py-2.5 text-sm transition hover:bg-muted/60",
                      !n.is_read && "bg-brand-soft/40",
                    )}
                  >
                    <p className="font-medium leading-snug">{n.title}</p>
                    {n.body ? (
                      <p className="mt-0.5 text-xs text-muted-foreground line-clamp-2">
                        {n.body}
                      </p>
                    ) : null}
                  </Link>
                </li>
              ))
            ) : (
              <li className="px-3 py-6 text-center text-sm text-muted-foreground">
                You’re all caught up.
              </li>
            )}
          </ul>
        </div>
      ) : null}
    </div>
  )
}
