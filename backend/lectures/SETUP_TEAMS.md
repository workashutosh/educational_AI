# Microsoft Teams setup (Lectures)

ClassKit creates Teams meeting links **from the app** after a teacher clicks
**Connect Microsoft** (delegated Graph). No paste required.

```http
POST /me/onlineMeetings
```

This does **not** need Teams application access policy (that only applies to app-only).

## Recommended: Connect Microsoft (delegated)

### 1. Azure app registration

1. Entra ID → App registrations → your app (or create one)
2. **Authentication** → Add a platform → **Web**
   - Redirect URI (exact):
     `http://127.0.0.1:8000/api/lectures/teams/callback/`
3. **Supported account types**: prefer  
   *Accounts in any organizational directory (multitenant)*  
   so teachers can sign in with a school/work account that actually has **Teams**
4. Certificates & secrets → create a **client secret** (copy the **Value**, not the Secret ID)
5. API permissions → Microsoft Graph → **Delegated**:
   - `OnlineMeetings.ReadWrite`
   - `User.Read`
   - `offline_access` (usually included via OAuth scopes)
6. Click **Grant admin consent** if your tenant requires it

### 2. Backend `.env`

```env
MS_GRAPH_TENANT_ID=<directory/tenant id>
MS_GRAPH_CLIENT_ID=<app client id>
MS_GRAPH_CLIENT_SECRET=<client secret Value>
MS_GRAPH_REDIRECT_URI=http://127.0.0.1:8000/api/lectures/teams/callback/
MS_GRAPH_OAUTH_TENANT=organizations
```

`MS_GRAPH_ORGANIZER_USER_ID` is optional for this flow (used only for app-only fallback).

Restart Django after saving.

### 3. In the product

1. Open **Lectures**
2. Click **Connect Microsoft**
3. Sign in with a **work/school** account that can create Teams meetings
4. Create a lecture with “Create Teams meeting link” checked — join URL is filled automatically

### Important: Teams license

Your Entra Free directory alone often has **no Teams**. Sign in during Connect with an
account from a Microsoft 365 / school tenant that includes Teams. Personal MSA
accounts generally cannot create Graph online meetings.

---

## Optional: App-only (needs M365 Teams admin)

```http
POST /users/{organizerId}/onlineMeetings
```

Requires Application permission `OnlineMeetings.ReadWrite.All` **and** a Teams
[application access policy](https://learn.microsoft.com/en-us/graph/cloud-communication-online-meeting-application-access-policy).
Entra Free tenants usually cannot create that policy — use **Connect Microsoft** instead.

```powershell
Install-Module MicrosoftTeams -Scope CurrentUser -Force
Connect-MicrosoftTeams
New-CsApplicationAccessPolicy -Identity EduAI-Lectures -AppIds "<CLIENT_ID>" -Description "ClassKit"
Grant-CsApplicationAccessPolicy -PolicyName EduAI-Lectures -Identity "<ORGANIZER_OBJECT_ID>"
```

```env
MS_GRAPH_ORGANIZER_USER_ID=<organizer Entra object id>
```

---

## Docs

- [Create onlineMeeting](https://learn.microsoft.com/en-us/graph/api/application-post-onlinemeetings)
- [OnlineMeetings.ReadWrite (delegated)](https://learn.microsoft.com/en-us/graph/permissions-reference#onlinemeetingsreadwrite)
