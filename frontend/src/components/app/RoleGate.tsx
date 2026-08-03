import type { ReactNode } from "react"
import { Navigate } from "react-router-dom"

import { useAuth } from "@/lib/auth"

/** Renders children only for non-student members; students go to My Tests. */
export function StaffOnly({ children }: { children: ReactNode }) {
  const { session } = useAuth()
  if (session?.membership?.role === "student") {
    return <Navigate to="/app/mock-tests" replace />
  }
  return <>{children}</>
}
