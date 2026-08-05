# Frontend (React + TypeScript + TailwindCSS)

## Run

1. Install dependencies
   - `npm install`
   - 若证书问题导致失败，可临时执行：`npm install --strict-ssl=false --registry=https://registry.npmjs.org`
2. Start dev server
   - `npm run dev`
3. Open browser
   - `http://localhost:5173`

## Build

- `npm run build`
- `npm run typecheck`

## API

- Default API base URL: `http://localhost:8000/api/v1`
- Optional env override:
  - copy `.env.example` to `.env`
  - update `VITE_API_BASE_URL`
