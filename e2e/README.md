# ClassKit E2E (Playwright)

API + UI checks for the Feature × Role matrix.

```bash
cd e2e
npm install
npx playwright install chromium

# Backend + frontend must be running (./dev.sh from repo root)
export E2E_ADMIN_USER='your-school-admin@email.com'
export E2E_ADMIN_PASS='your-password'
npm test
```
