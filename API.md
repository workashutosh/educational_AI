# ClassKit API — guide for app developers

Everything the web app does goes through this JSON API, so a mobile app can be built against it without backend changes.

- **Interactive docs:** `GET /api/docs/` (Swagger UI)
- **OpenAPI 3 schema (for client codegen):** `GET /api/schema/`. Every operation has a stable, unique `operationId`, e.g. `assignmentDetailGet` or `paperExportGet`.
- **Versioned base path:** use **`/api/v1/`** in apps. It serves exactly the same views as `/api/`, which the web app uses, so old app builds keep working if `/api/` changes.

## Conventions

| Topic | Rule |
|---|---|
| Auth | `POST /api/v1/auth/login/ {username, password}` returns `{token, account_type, membership, school, buckets, parent, …}`. Send `Authorization: Token <token>` on every request. `username` may also be the account email. |
| Account types | `account_type`: `member` (admin / manager / teacher / student; see `membership.role`), `parent` (parent portal only), or `none`. |
| Session check | `GET /api/v1/auth/me/` returns the same payload as login. |
| Sign out | `POST /api/v1/auth/logout/` deletes the token. Also `DELETE /api/v1/engagement/devices/ {token}` to drop the push token. |
| Password | `POST /api/v1/auth/password/change/ {old_password, new_password}` returns a **new** token. Other devices are signed out. |
| 401 vs 403 | **401** means the token is missing or invalid: send the user to the login screen. **403** means signed in but not allowed for this role or bucket. |
| Errors | Every 4xx/5xx JSON body has a human-readable `detail`. Validation errors add `errors: {field: [messages]}`. AI-provider failures never leak provider details: 429 means "busy, retry" (or the school's monthly AI allowance is used up), 502 means the provider is down. |
| Pagination | Large lists (`question-bank/items`, `learning/doubts`) take `?limit=&offset=` and return `{count, limit, offset, next_offset, results}`. `next_offset` is `null` on the last page. Other lists are capped and return plain arrays. |
| Uploads | `multipart/form-data`. Field names: `file` (documents, recordings), `audio` (voice), `files` (repeat for each homework attachment), `attachment` (homework worksheet). |
| Downloads | Exports and attachments are binary responses with `Content-Disposition`. They need the auth header too, so download them with an authenticated request rather than a plain browser link. |
| Async jobs | These return `202` with a job object; poll its detail endpoint every 3–5 s until `status` is final: document indexing (`/documents/{id}/status/`), past-paper import (`/question-bank/import-jobs/{id}/`), lecture recordings (`/lectures/recordings/{id}/`). Homework AI grading: poll the submission until `ai_status != "pending"`. |
| Dates | ISO-8601 UTC. Send timezone-aware datetimes (e.g. `2026-10-21T09:30:00+05:30`). |
| Math | Text fields may contain LaTeX (`$…$`, `$$…$$`, `\ce{…}`). Render with KaTeX/MathJax. |

## Roles

`admin` and `manager` see every AI Bucket in the school. `teacher` and `student` only see buckets they have been granted. **Staff** below means admin, manager, or teacher. Parents can call only the `/parent/…` endpoints; every other endpoint returns 403 for them.

## Endpoint map (prefix `/api/v1/`)

### Core (existing)
- **Auth & onboarding:** `auth/login/`, `auth/me/`, `auth/logout/`, `auth/register/join/`, `auth/onboard/*`, `auth/password/change/`
- **Buckets & documents:** `buckets/`, `documents/` (GET, POST multipart), `documents/{id}/status/`, `documents/{id}/pages/{n}/` (PNG)
- **Chat:** `chat/sessions/`, `chat/sessions/{id}/`, `ask/`
  - `ask/` body: `{query, bucket_id, session_id, history, language}`.
  - `ask/` response includes `message_id` (use it for feedback) and `doubt_id`. `doubt_id` is set when a student's unanswered question was routed to teachers.
- **Languages:** `languages/` lists the supported answer languages (en, hi, mr, bn, ta, te, gu, kn, ml, pa, or, ur, as). `translate/` takes `{text, target_language}`.
- **Voice:** `speech/transcribe/` (multipart `audio`, optional `language`) returns `{text}`. Record with the native recorder (m4a/webm/ogg, under 10 MB).
- **Mock tests:** `mock-tests/…` (generate, assign, publish, start, submit, results, release)
- **Lectures:** `lectures/`, `lectures/{id}/room/`, `go-live/`, `end/`, Teams endpoints
- **Engagement:** `engagement/summary/`, `notifications/`, `micro-quizzes/`, `mastery/`, `preferences/`, `devices/`

### Question bank & papers (staff)
| Endpoint | Purpose |
|---|---|
| `question-bank/topics/?bucket_id=` · POST · `topics/{id}/` | Topics with item counts |
| `question-bank/topics/sync/` `{bucket_id}` | Create topics from note headings (no AI cost) |
| `question-bank/topics/tag-untagged/` `{bucket_id}` | Auto-tag bank items and old mock questions |
| `question-bank/items/` GET (filters: `bucket_id topic_id qtype difficulty source year q untagged`) · POST | Paginated bank; add a teacher-written question |
| `question-bank/items/{id}/` GET · PATCH · DELETE (archive; `?hard=1` deletes if unused) | |
| `question-bank/items/generate/` `{bucket_id, topic_id?, prompt?, difficulty, counts:{mcq,multi,brief,long,numeric}, use_past_papers}` | AI questions grounded in the notes |
| `question-bank/items/import-document/` `{document_id}` → 202 · `import-jobs/{id}/` | Extract questions from a past paper |
| `question-bank/items/import-mock-test/` `{mock_test_id}` | Copy a mock test into the bank |
| `question-bank/coverage/?bucket_id=` | Bank depth per topic, and how often each topic was tested |
| `question-bank/build-mock-test/` | Draft (or assigned + published) test from the bank, no AI |
| `question-bank/papers/` GET · POST `{bucket_id, title, sections:[{title,qtype,count,marks_each,instructions}], source_mode, difficulty_mix, topic_ids, …}` | Exam papers |
| `question-bank/papers/{id}/` GET · PATCH (`status: final` locks the paper) · DELETE | |
| `papers/{id}/sections/{sid}/refill/` · `papers/{id}/items/{iid}/` PATCH/DELETE · `…/swap/` | Edit a paper |
| `papers/{id}/export/?fmt=pdf\|docx&answers=0\|1` | Printable paper / answer key (`fmt`, not `format`) |
| `papers/{id}/to-mock-test/` | Turn a paper into a draft mock test |

### Learning
| Endpoint | Who | Purpose |
|---|---|---|
| `learning/decks/` GET · POST · `decks/generate/` · `decks/{id}/` · `decks/{id}/cards/` · `cards/{id}/` | all | Flashcard decks. Students' decks are always private. |
| `learning/study/?bucket_id&deck_id&limit` | all | Cards due now, then new cards |
| `learning/study/review/` `{card_id, button: again\|hard\|good\|easy}` or `{grade 0-5}` | all | Schedules the next review (SM-2) |
| `learning/study/stats/` | all | Reviews today and this week, plus per-bucket counts |
| `learning/doubts/` GET (`status`, `bucket_id`) · POST `{bucket_id, question, note, chat_message_id?}` | students: own; staff: their buckets | Doubt inbox |
| `learning/doubts/{id}/` · `…/answer/` `{answer, add_to_notes}` (staff) · `…/close/` | | `add_to_notes` indexes the Q&A as notes |
| `learning/feedback/` `{message_id, rating: 1\|-1, reason, comment, ask_teacher}` | all | 👍/👎 on an AI answer |
| `learning/feedback/summary/?bucket_id&days` | staff | Helpful rate, low-rated answers, retrieval-threshold hint |

### Homework
`homework/` GET/POST (multipart allowed) · `homework/{id}/` · `/assign/` · `/publish/` · `/close/` · `/attachment/` · `/submit/` (student, multipart `text_answer` + `files`) · `/submissions/` (staff roster) · `/release/` · `homework/submissions/{sid}/` · `/grade/ {score, feedback, release}` · `/regrade-ai/` · `/files/{fid}/`

### Analytics
`analytics/me/topics/?bucket_id` (student; only released results count) · `analytics/me/practice/` `{bucket_id, topic_ids?}` (student self-practice test) · `analytics/students/{id}/topics/` · `analytics/buckets/{id}/heatmap/` · `analytics/buckets/{id}/weak-topics/` · `analytics/remediate/` `{bucket_id, student_ids?, topic_ids?, question_count}` (staff)

### Attendance
`attendance/me/` (student) · `attendance/lectures/{id}/` GET/PUT `{records:[{student_id,status,note}]}` · `attendance/buckets/{id}/` · `attendance/students/{id}/`. Opening `lectures/{id}/room/` while a lecture is live marks the student present (late after 10 min). Ending the lecture marks absentees.

### Parents
- **Staff:** `parents/` GET · POST `{username, password, full_name, email, phone, student_ids, relationship}` · `parents/{id}/` PATCH · `parents/{id}/links/` POST · `parents/{id}/links/{student_id}/` DELETE
- **Parent accounts:** `parent/me/` · `parent/children/{student_id}/` (released results, attendance, streak, subjects, homework) · `parent/children/{id}/attendance/` · `parent/preferences/` PATCH `{weekly_email}`

### Billing & usage
`billing/plans/` (public) · `billing/subscription/` · `billing/checkout/` `{plan_code, months}` (admin) · `billing/verify/` · `billing/payments/` · `billing/usage/?days=` (admin/manager) · `billing/usage/schools/` (platform superuser) · `billing/webhook/razorpay/` (server-to-server)

**Mobile payment flow:**
1. Call `POST billing/checkout/`. It returns `checkout: {key_id, order_id, amount, currency, name, description, prefill}`.
2. Open the Razorpay Android/iOS SDK with those values.
3. On success, `POST billing/verify/ {razorpay_order_id, razorpay_payment_id, razorpay_signature}`.
4. If the app closes before step 3, the webhook still activates the plan.

### Push notifications
Register with `POST engagement/devices/ {token, platform: android|ios|web, app_version}` after login (this works for parents too). The server stores the tokens, but sending pushes (FCM/APNs) isn't built yet. In-app notifications are available at `engagement/notifications/`.
