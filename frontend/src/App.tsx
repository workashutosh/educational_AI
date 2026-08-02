import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom"

import { AppLayout } from "@/components/app/AppLayout"
import { AuthProvider, useAuth } from "@/lib/auth"
import { BucketDetailPage } from "@/pages/app/BucketDetailPage"
import { BucketsPage } from "@/pages/app/BucketsPage"
import { ChatPage } from "@/pages/app/ChatPage"
import { CreatePptPage } from "@/pages/app/CreatePptPage"
import { DashboardPage } from "@/pages/app/Dashboard"
import { SettingsPage } from "@/pages/app/SettingsPage"
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
            <Route path="buckets" element={<BucketsPage />} />
            <Route path="buckets/:bucketId" element={<BucketDetailPage />} />
            <Route path="chat" element={<ChatPage />} />
            <Route path="ppt" element={<CreatePptPage />} />
            <Route path="settings" element={<SettingsPage />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  )
}
