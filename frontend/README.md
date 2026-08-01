# Frontend

Vite + React + TypeScript + [shadcn/ui](https://ui.shadcn.com) (base-nova).

```bash
npm install
npm run dev      # http://127.0.0.1:5173
npm run build
```

Dev server proxies `/api`, `/accounts`, and `/admin` to `http://127.0.0.1:8000`.

```bash
# add components (use project-local npm cache if global cache has permission issues)
npm_config_cache=../.npm-cache npx --yes shadcn@4.15.0 add card
```
