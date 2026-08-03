# Microsoft Teams setup (Lectures)

Education AI creates Teams meetings with **Microsoft Graph** Cloud Communications API:

```http
POST /users/{organizerId}/onlineMeetings
```

Docs: [Create onlineMeeting](https://learn.microsoft.com/en-us/graph/api/application-post-onlinemeetings)

## 1. Azure app registration

1. Entra ID → App registrations → New registration  
2. Certificates & secrets → create a **client secret**  
3. API permissions → Microsoft Graph → **Application** → `OnlineMeetings.ReadWrite.All`  
4. Grant **admin consent** for the tenant  

## 2. Application access policy (required for app-only)

Without this, Graph returns **403** even when `OnlineMeetings.ReadWrite.All` is consented:

> No application access policy found for this app … on the user

You need a **Microsoft 365 / Teams** admin (Entra Free alone is not enough for Teams PowerShell in many tenants).

On Windows PowerShell or PowerShell 7:

```powershell
Install-Module MicrosoftTeams -Scope CurrentUser -Force
Connect-MicrosoftTeams

# Use your Application (client) ID from the app registration
New-CsApplicationAccessPolicy `
  -Identity EduAI-Lectures `
  -AppIds "ac066d4c-6484-462c-b3e5-c0b2d43c13fb" `
  -Description "Education AI lectures"

# Grant to the organizer user's Object ID (MS_GRAPH_ORGANIZER_USER_ID)
Grant-CsApplicationAccessPolicy `
  -PolicyName EduAI-Lectures `
  -Identity "164cafb0-d4d0-4b6e-bf08-687e2a537144"

# Policy can take a few minutes to apply (sometimes up to ~30 min).
```

Tenant-wide (optional, more permissive):

```powershell
Grant-CsApplicationAccessPolicy -PolicyName EduAI-Lectures -Global
```

Docs: [Application access policy](https://learn.microsoft.com/en-us/graph/cloud-communication-online-meeting-application-access-policy)

## 3. Backend `.env`

```env
MS_GRAPH_TENANT_ID=<directory/tenant id>
MS_GRAPH_CLIENT_ID=<app client id>
MS_GRAPH_CLIENT_SECRET=<client secret>
MS_GRAPH_ORGANIZER_USER_ID=<organizer Entra object id or UPN>
```

Restart Django after saving.

## 4. Without Graph

Leave `MS_GRAPH_*` empty. Teachers can still create lectures and paste a Teams join URL manually; the lecture room (notes + AI) works either way.
