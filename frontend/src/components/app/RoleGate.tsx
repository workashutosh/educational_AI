import type { ReactNode } from "react"
import { Navigate } from "react-router-dom"

import { useAuth } from "@/lib/auth"

/** Hide from students (teachers, managers, admins). */
export function StaffOnly({ children }: { children: ReactNode }) {
  const { session } = useAuth()
  if (session?.membership?.role === "student") {
    return <Navigate to="/app" replace />
  }
  return <>{children}</>
}

/** Admin or manager only (school ops, members, grants). */
export function ManagerOrAdmin({ children }: { children: ReactNode }) {
  const { session } = useAuth()
  if (!session?.can_manage) {
    return <Navigate to="/app" replace />
  }
  return <>{children}</>
}

/** Anyone who may create student logins (includes teachers). */
export function CanCreateStudents({ children }: { children: ReactNode }) {
  const { session } = useAuth()
  if (!session?.can_create_students) {
    return <Navigate to="/app" replace />
  }
  return <>{children}</>
}
