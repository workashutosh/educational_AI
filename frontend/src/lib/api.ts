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
  progress_message?: string
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
  /** Assistant message id for /api/learning/feedback/ */
  message_id?: number | null
  doubt_id?: number | null
  feedback?: 1 | -1 | null
  role: "user" | "assistant"
  content: string
  sources?: AskSource[]
  suggestions?: string[]
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
  full_access?: boolean
  bucket_ids?: number[]
}

export type AccessGrant = {
  member_id: number
  username: string
  email: string
  role: string
  granted_at: string
}

export type ParentChild = {
  student_id: number
  name: string
  relationship: string
}

export type ParentInfo = {
  id: number
  phone: string
  weekly_email: boolean
  children: ParentChild[]
}

export type Session = {
  token: string
  user: AuthUser
  /** member = school staff/student, parent = parent portal account */
  account_type?: "member" | "parent" | "none"
  parent?: ParentInfo | null
  membership: Membership | null
  school: School | null
  buckets: Bucket[]
  can_manage: boolean
  can_upload: boolean
  can_create_students?: boolean
  /** Roles this user may create via Members UI */
  creatable_roles?: string[]
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

/** Never show provider dumps, env vars, status codes, or admin setup hints in the UI. */
function sanitizeUserFacingError(message: string, status: number): string {
  const msg = (message || "").trim()
  const lower = msg.toLowerCase()
  const looksTechnical =
    lower.includes("rate limit") ||
    lower.includes("tokens per minute") ||
    lower.includes("groq") ||
    lower.includes("org_") ||
    lower.includes("service tier") ||
    lower.includes("ms_graph") ||
    lower.includes(".env") ||
    lower.includes("setup_teams") ||
    lower.includes("client_id") ||
    lower.includes("client_secret") ||
    lower.includes("tenant_id") ||
    lower.includes("traceback") ||
    lower.includes("status_code") ||
    /request failed\s*\(\d+\)/i.test(msg) ||
    (msg.includes('{"error"') && lower.includes("limit")) ||
    /api error\s*\(\d+\)/i.test(msg)

  if (looksTechnical || status === 429) {
    if (status === 429 || lower.includes("rate limit") || lower.includes("groq")) {
      return "The AI service is busy right now. Please wait a few seconds and try again."
    }
    return "Something went wrong. Please try again in a moment."
  }
  if (status >= 500) {
    return "Something went wrong. Please try again in a moment."
  }
  if (msg.length > 180) {
    return "Something went wrong. Please try again in a moment."
  }
  return msg || "Something went wrong. Please try again in a moment."
}

function parseError(data: unknown, status: number): Error {
  const err = (data || {}) as ApiError
  const fieldErrors = err.errors
    ? Object.entries(err.errors)
        .map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(" ") : String(v)}`)
        .join(" · ")
    : ""
  const raw = err.detail || fieldErrors || `Request failed (${status})`
  return new Error(sanitizeUserFacingError(raw, status))
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
export async function apiUpload<T>(
  path: string,
  form: FormData,
  method: "POST" | "PATCH" | "PUT" = "POST",
): Promise<T> {
  const auth = getToken()
  const res = await fetch(path, {
    method,
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

export function statusLabel(status: string, progressMessage?: string | null): string {
  const map: Record<string, string> = {
    queued: "Waiting…",
    parsing: "Reading…",
    indexing: "Crunching…",
    indexed: "Ready",
    duplicate: "Duplicate",
    failed: "Failed",
  }
  const base = map[status] || status
  const progress = (progressMessage || "").trim()
  if (progress && (status === "parsing" || status === "indexing")) {
    // e.g. "Reading… 4/16 pages" or "Crunching… 12/40 chunks"
    return `${base.replace(/…$/, "")} (${progress})`
  }
  return base
}

export function isPendingStatus(status: string): boolean {
  return ["queued", "parsing", "indexing"].includes(status)
}

/** Paginated list shape used by large collections (?limit=&offset=). */
export type Page<T> = {
  count: number
  limit: number
  offset: number
  next_offset: number | null
  results: T[]
}

/** Download an authenticated file (export, attachment) and save it. */
export async function downloadFile(path: string, fallbackName = "download") {
  const auth = getToken()
  const res = await fetch(path, {
    headers: auth ? { Authorization: `Token ${auth}` } : {},
  })
  if (!res.ok) {
    let data: unknown = null
    try {
      data = await res.json()
    } catch {
      data = null
    }
    throw parseError(data, res.status)
  }
  const blob = await res.blob()
  const disposition = res.headers.get("Content-Disposition") || ""
  const match = /filename="?([^";]+)"?/i.exec(disposition)
  triggerBlobDownload(blob, match?.[1]?.trim() || fallbackName)
}

/** Fetch an authenticated file as an object URL (audio players, image previews). */
export async function fetchObjectUrl(path: string): Promise<string> {
  const auth = getToken()
  const res = await fetch(path, { headers: auth ? { Authorization: `Token ${auth}` } : {} })
  if (!res.ok) throw parseError(null, res.status)
  return URL.createObjectURL(await res.blob())
}

export function errorMessage(err: unknown, fallback = "Something went wrong"): string {
  return err instanceof Error ? err.message : fallback
}

export function formatDate(value: string | null | undefined, withTime = false): string {
  if (!value) return "—"
  const d = new Date(value)
  return withTime
    ? d.toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })
    : d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" })
}
