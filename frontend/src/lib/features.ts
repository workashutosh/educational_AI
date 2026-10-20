/** Shared hooks + constants for feature pages (kept out of component files for fast refresh). */
import { useCallback, useEffect, useState } from "react"

import { api } from "@/lib/api"
import { useAuth } from "@/lib/auth"

export type Topic = { id: number; name: string; item_count?: number; source: string }

export const QTYPE_LABEL: Record<string, string> = {
  mcq: "MCQ",
  multi: "Multi-correct",
  brief: "Short answer",
  long: "Long answer",
  numeric: "Numerical",
}

export const HW_STATUS_TONE = {
  pending: "sky",
  overdue: "red",
  submitted: "amber",
  returned: "green",
  draft: "gray",
  published: "green",
  closed: "gray",
} as const

export function useTopics(bucketId: number | null) {
  const [topics, setTopics] = useState<Topic[]>([])
  const load = useCallback(async () => {
    if (!bucketId) return setTopics([])
    try {
      setTopics(await api<Topic[]>(`/api/question-bank/topics/?bucket_id=${bucketId}`))
    } catch {
      setTopics([])
    }
  }, [bucketId])
  useEffect(() => {
    void load()
  }, [load])
  return { topics, reload: load }
}

export function useRole() {
  const { session } = useAuth()
  const role = session?.membership?.role || ""
  return {
    role,
    isStudent: role === "student",
    isStaff: role === "admin" || role === "manager" || role === "teacher",
    isManager: role === "admin" || role === "manager",
    isAdmin: role === "admin",
  }
}
