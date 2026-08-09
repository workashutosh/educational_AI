import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom"

import { AppLayout } from "@/components/app/AppLayout"
import { StaffOnly } from "@/components/app/RoleGate"
import { AuthProvider, useAuth } from "@/lib/auth"
import { BucketDetailPage } from "@/pages/app/BucketDetailPage"
import { BucketsPage } from "@/pages/app/BucketsPage"
import { ChatPage } from "@/pages/app/ChatPage"
import { CreatePptPage } from "@/pages/app/CreatePptPage"
import { DashboardPage } from "@/pages/app/Dashboard"
import { LectureRoomPage } from "@/pages/app/LectureRoomPage"
import { LecturesPage } from "@/pages/app/LecturesPage"
import { SettingsPage } from "@/pages/app/SettingsPage"
import { MicroQuizTakePage } from "@/pages/app/MicroQuizTakePage"
import { MockTestCreatePage } from "@/pages/app/MockTestCreatePage"
import { MockTestDetailPage } from "@/pages/app/MockTestDetailPage"
import { MockTestsPage } from "@/pages/app/MockTestsPage"
import { MockTestStudentResultPage } from "@/pages/app/MockTestStudentResultPage"
import { MockTestTakePage } from "@/pages/app/MockTestTakePage"
import { StudentsPage } from "@/pages/app/StudentsPage"
import { JoinPage } from "@/pages/Join"
import { LandingPage } from "@/pages/Landing"
import { LoginPage } from "@/pages/Login"
import { OnboardPage } from "@/pages/Onboard"

function ProtectedShell() {
  const { session, loading } = useAuth()
  if (loading) {
    return (
      <div className="flex min-h-svh items-center justify-center text-muted-foreground">
        Loading…
      </div>
    )
  }
  if (!session?.membership) {
    return <Navigate to="/login" replace />
  }
  return <AppLayout />
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<LandingPage />} />
          <Route path="/login" element={<LoginPage />} />
          <Route path="/onboard" element={<OnboardPage />} />
          <Route path="/join" element={<JoinPage />} />
          <Route path="/app" element={<ProtectedShell />}>
            <Route index element={<DashboardPage />} />
            <Route
              path="buckets"
              element={
                <StaffOnly>
                  <BucketsPage />
                </StaffOnly>
              }
            />
            <Route
              path="buckets/:bucketId"
              element={
                <StaffOnly>
                  <BucketDetailPage />
                </StaffOnly>
              }
            />
            <Route path="chat" element={<ChatPage />} />
            <Route path="lectures" element={<LecturesPage />} />
            <Route path="lectures/:lectureId" element={<LectureRoomPage />} />
            <Route
              path="ppt"
              element={
                <StaffOnly>
                  <CreatePptPage />
                </StaffOnly>
              }
            />
            <Route path="mock-tests" element={<MockTestsPage />} />
            <Route
              path="mock-tests/new"
              element={
                <StaffOnly>
                  <MockTestCreatePage />
                </StaffOnly>
              }
            />
            <Route path="mock-tests/:testId" element={<MockTestDetailPage />} />
            <Route path="mock-tests/:testId/take" element={<MockTestTakePage />} />
            <Route path="micro-quizzes/:quizId" element={<MicroQuizTakePage />} />
            <Route
              path="mock-tests/:testId/results/:studentId"
              element={
                <StaffOnly>
                  <MockTestStudentResultPage />
                </StaffOnly>
              }
            />
            <Route
              path="students"
              element={
                <StaffOnly>
                  <StudentsPage />
                </StaffOnly>
              }
            />
            <Route path="settings" element={<SettingsPage />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  )
}
