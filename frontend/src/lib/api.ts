export type AuthUser = {
  id: number
  username: string
  email: string
  full_name: string
}

export type Membership = {
  id: number
  role: string
  role_display: string
}

export type School = {
  id: number
  name: string
  join_code: string | null
  max_buckets?: number
  bucket_quota_bytes?: number
  max_users?: number
  max_managers?: number
  onboarding_complete?: boolean
}

export type Bucket = {
  id: number
  name: string
  grade_level: string
  school?: number
  is_archived?: boolean
}

export type DocumentKind = "notes" | "question_paper"

export type DocumentRow = {
  id: number
  bucket: number
  uploaded_by: number | null
  original_filename: string
  file_hash: string
  byte_size: number | null
  content_type: string
  kind?: DocumentKind
  status: string
  error_message: string
  page_count: number | null
  duplicate_of: number | null
  created_at: string
  processed_at: string | null
}

export type AskSource = {
  index?: number
  document_id?: number
  document_filename?: string
  heading_path?: string[] | string
  page_ref?: string
  page_start?: number | null
  page_end?: number | null
  image_url?: string | null
  text?: string
  score?: number
}

export type ChatMessage = {
  id?: number
  role: "user" | "assistant"
  content: string
  sources?: AskSource[]
  retrieval_query?: string
  model?: string
  created_at?: string
}

export type ChatSession = {
  id: number
  bucket: number
  bucket_name?: string
  member: number
  title: string
  created_at: string
  updated_at: string
  messages?: ChatMessage[]
}

export type MemberRow = {
  id: number
  username: string
  email: string
  full_name: string
  role: string
  role_display: string
}

export type AccessGrant = {
  member_id: number
  username: string
  email: string
  role: string
  granted_at: string
}

export type Session = {
  token: string
  user: AuthUser
  membership: Membership | null
  school: School | null
  buckets: Bucket[]
  can_manage: boolean
  can_upload: boolean
  can_create_students?: boolean
}

const TOKEN_KEY = "education_ai_token"
const SESSION_KEY = "education_ai_session"

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function loadSession(): Session | null {
  const raw = localStorage.getItem(SESSION_KEY)
  if (!raw) return null
  try {
    return JSON.parse(raw) as Session
  } catch {
    return null
  }
}

export function saveSession(session: Session) {
  localStorage.setItem(TOKEN_KEY, session.token)
  localStorage.setItem(SESSION_KEY, JSON.stringify(session))
}

export function clearSession() {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(SESSION_KEY)
}

type ApiError = {
  detail?: string
  errors?: Record<string, string[]>
}

function parseError(data: unknown, status: number): Error {
  const err = (data || {}) as ApiError
  const fieldErrors = err.errors
    ? Object.entries(err.errors)
        .map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(" ") : String(v)}`)
        .join(" · ")
    : ""
  return new Error(err.detail || fieldErrors || `Request failed (${status})`)
}

export async function api<T>(
  path: string,
  options: RequestInit & { token?: string | null } = {},
): Promise<T> {
  const { token, headers, ...rest } = options
  const auth = token === undefined ? getToken() : token
  const res = await fetch(path, {
    ...rest,
    headers: {
      "Content-Type": "application/json",
      ...(auth ? { Authorization: `Token ${auth}` } : {}),
      ...headers,
    },
  })

  const text = await res.text()
  let data: unknown = null
  if (text) {
    try {
      data = JSON.parse(text)
    } catch {
      data = { detail: text }
    }
  }

  if (!res.ok) throw parseError(data, res.status)
  return data as T
}

/** Multipart upload — do not set Content-Type (browser sets boundary). */
export async function apiUpload<T>(path: string, form: FormData): Promise<T> {
  const auth = getToken()
  const res = await fetch(path, {
    method: "POST",
    headers: {
      ...(auth ? { Authorization: `Token ${auth}` } : {}),
    },
    body: form,
  })
  const text = await res.text()
  let data: unknown = null
  if (text) {
    try {
      data = JSON.parse(text)
    } catch {
      data = { detail: text }
    }
  }
  if (!res.ok) throw parseError(data, res.status)
  return data as T
}

/** Binary download (e.g. generated PPTX). */
export async function apiDownload(
  path: string,
  options: RequestInit & { token?: string | null } = {},
): Promise<{ blob: Blob; filename: string }> {
  const { token, headers, ...rest } = options
  const auth = token === undefined ? getToken() : token
  const res = await fetch(path, {
    ...rest,
    headers: {
      "Content-Type": "application/json",
      ...(auth ? { Authorization: `Token ${auth}` } : {}),
      ...headers,
    },
  })

  if (!res.ok) {
    const text = await res.text()
    let data: unknown = null
    if (text) {
      try {
        data = JSON.parse(text)
      } catch {
        data = { detail: text }
      }
    }
    throw parseError(data, res.status)
  }

  const blob = await res.blob()
  const disposition = res.headers.get("Content-Disposition") || ""
  const match = /filename="?([^";]+)"?/i.exec(disposition)
  const filename = match?.[1]?.trim() || "download.bin"
  return { blob, filename }
}

export function triggerBlobDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement("a")
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

export function formatBytes(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "—"
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / (1024 * 1024)).toFixed(1)} MB`
}

export function statusLabel(status: string): string {
  const map: Record<string, string> = {
    queued: "Waiting…",
    parsing: "Reading…",
    indexing: "Crunching…",
    indexed: "Ready",
    duplicate: "Duplicate",
    failed: "Failed",
  }
  return map[status] || status
}

export function isPendingStatus(status: string): boolean {
  return ["queued", "parsing", "indexing"].includes(status)
}
