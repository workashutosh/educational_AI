import { expect, test, type APIRequestContext } from "@playwright/test"

const API = process.env.E2E_API_URL || "http://127.0.0.1:8000"

async function login(request: APIRequestContext, username: string, password: string) {
  const res = await request.post(`${API}/api/auth/login/`, {
    data: { username, password },
  })
  expect(res.ok(), await res.text()).toBeTruthy()
  return res.json() as Promise<{
    token: string
    membership: { role: string }
    can_manage: boolean
    can_upload: boolean
    can_create_students: boolean
    creatable_roles?: string[]
    buckets: { id: number; name: string }[]
  }>
}

test.describe("RBAC API matrix", () => {
  const adminUser = process.env.E2E_ADMIN_USER || ""
  const adminPass = process.env.E2E_ADMIN_PASS || ""

  test.skip(!adminUser || !adminPass, "Set E2E_ADMIN_USER / E2E_ADMIN_PASS to run")

  test("admin can create teacher/student and grant bucket access", async ({ request }) => {
    const admin = await login(request, adminUser, adminPass)
    expect(admin.membership.role).toBe("admin")
    expect(admin.can_manage).toBe(true)
    expect(admin.creatable_roles || []).toEqual(
      expect.arrayContaining(["admin", "manager", "teacher", "student"]),
    )

    // Ensure a bucket exists
    let bucketId = admin.buckets[0]?.id
    if (!bucketId) {
      const b = await request.post(`${API}/api/admin/buckets/`, {
        headers: { Authorization: `Token ${admin.token}` },
        data: { name: `E2E Bucket ${Date.now()}`, grade_level: "XII" },
      })
      expect(b.ok(), await b.text()).toBeTruthy()
      bucketId = (await b.json()).id
    }

    const stamp = Date.now()
    const teacherUser = `e2e_teacher_${stamp}`
    const studentUser = `e2e_student_${stamp}`

    const teacherRes = await request.post(`${API}/api/admin/members/create/`, {
      headers: { Authorization: `Token ${admin.token}` },
      data: {
        role: "teacher",
        username: teacherUser,
        password: "testpass123",
        full_name: "E2E Teacher",
        bucket_ids: [bucketId],
      },
    })
    expect(teacherRes.ok(), await teacherRes.text()).toBeTruthy()
    const teacher = await teacherRes.json()
    expect(teacher.role).toBe("teacher")
    expect(teacher.bucket_ids).toContain(bucketId)

    const studentRes = await request.post(`${API}/api/admin/members/create/`, {
      headers: { Authorization: `Token ${admin.token}` },
      data: {
        role: "student",
        username: studentUser,
        password: "testpass123",
        full_name: "E2E Student",
        bucket_ids: [],
      },
    })
    expect(studentRes.ok(), await studentRes.text()).toBeTruthy()
    const student = await studentRes.json()

    // Grant student the bucket
    const grant = await request.put(`${API}/api/admin/members/${student.id}/access/`, {
      headers: { Authorization: `Token ${admin.token}` },
      data: { bucket_ids: [bucketId] },
    })
    expect(grant.ok(), await grant.text()).toBeTruthy()
    const granted = await grant.json()
    expect(granted.bucket_ids).toContain(bucketId)

    // Teacher cannot create admin
    const teacherSession = await login(request, teacherUser, "testpass123")
    expect(teacherSession.membership.role).toBe("teacher")
    expect(teacherSession.can_manage).toBe(false)
    expect(teacherSession.can_upload).toBe(true)
    const forbidden = await request.post(`${API}/api/admin/members/create/`, {
      headers: { Authorization: `Token ${teacherSession.token}` },
      data: {
        role: "admin",
        username: `e2e_bad_${stamp}`,
        password: "testpass123",
      },
    })
    expect(forbidden.status()).toBe(403)

    // Teacher can create student
    const okStudent = await request.post(`${API}/api/admin/members/create/`, {
      headers: { Authorization: `Token ${teacherSession.token}` },
      data: {
        role: "student",
        username: `e2e_st2_${stamp}`,
        password: "testpass123",
        bucket_ids: [bucketId],
      },
    })
    expect(okStudent.ok(), await okStudent.text()).toBeTruthy()

    // Student cannot upload / ppt
    const studentSession = await login(request, studentUser, "testpass123")
    expect(studentSession.can_upload).toBe(false)
    const ppt = await request.post(`${API}/api/generate-pptx/`, {
      headers: { Authorization: `Token ${studentSession.token}` },
      data: { bucket_id: bucketId, prompt: "Matrices", slide_count: 3 },
    })
    expect([403, 401]).toContain(ppt.status())

    // Student cannot create buckets
    const bucketCreate = await request.post(`${API}/api/admin/buckets/`, {
      headers: { Authorization: `Token ${studentSession.token}` },
      data: { name: "Nope", grade_level: "" },
    })
    expect(bucketCreate.status()).toBe(403)
  })
})

test.describe("Members UI (admin)", () => {
  const adminUser = process.env.E2E_ADMIN_USER || ""
  const adminPass = process.env.E2E_ADMIN_PASS || ""

  test.skip(!adminUser || !adminPass, "Set E2E_ADMIN_USER / E2E_ADMIN_PASS to run")

  test("admin sees Members nav and create form roles", async ({ page }) => {
    await page.goto("/login")
    await page.getByLabel(/username/i).fill(adminUser)
    await page.getByLabel(/password/i).fill(adminPass)
    await page.getByRole("button", { name: /sign in/i }).click()
    await expect(page).toHaveURL(/\/app/)

    await expect(page.getByRole("link", { name: "Members" })).toBeVisible()
    await page.getByRole("link", { name: "Members" }).click()
    await expect(page).toHaveURL(/\/app\/members/)
    await expect(page.getByRole("heading", { name: "Members" })).toBeVisible()

    await page.getByRole("button", { name: /add member/i }).click()
    const roleSelect = page.locator("#role")
    await expect(roleSelect).toBeVisible()
    await expect(roleSelect.locator("option")).toHaveCount(4)
  })
})
