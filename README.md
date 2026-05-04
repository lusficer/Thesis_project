# eCommerce Smart DSS

Decision Support System for inventory and pricing optimization.

## Core features

- Product-level DSS analysis (forecast, inventory action, dynamic pricing)
- Portfolio statistics dashboard
- PM report generation with n8n + LLM narrative
- Recompute forecasts for active products

## Project folders

```text
Thesis_project/
├── app/                         # FastAPI backend
│   ├── api/                     # REST endpoints
│   ├── core/                    # DSS logic and models
│   └── services/                # cache/recompute services
├── frontend/                    # Next.js frontend
│   └── src/app/                 # app routes (dss, statistics, products, ...)
├── alembic/                     # DB migrations
├── docker-compose.yml           # n8n container
├── Thesis_workflow_n8n.json     # n8n workflow to import
├── requirements.txt             # Python dependencies
└── run.py                       # backend launcher
```

## Prerequisites

- Python 3.9+
- Node.js 18+ and npm
- Docker + Docker Compose (for n8n)

## First-time setup

From project root:

```bash
pip install -r requirements.txt
cd frontend && npm install && cd ..
alembic upgrade head
```

## Run locally

### 1) Backend

```bash
python run.py --reload
```

- API: `http://localhost:8000/api`
- Docs: `http://localhost:8000/docs`

### 2) Frontend

In a second terminal:

```bash
cd frontend
npm run dev
```

- UI: `http://localhost:3000`
- Frontend env file: `frontend/.env.local`
  - `NEXT_PUBLIC_API_URL=http://localhost:8000/api`

## n8n Docker setup (first run)

1. Start n8n:

```bash
docker-compose up -d
```

2. Open `http://localhost:5678` and create a local admin account.
3. Import workflow from file: `Thesis_workflow_n8n.json`.
4. Open node **Google Gemini Chat Model**, create credential, add API key, then activate the workflow.

> Security note: This repository does not include any API keys.

## n8n webhook used by backend

Default:

`http://localhost:5678/webhook/pm-report`

Optional override:

```bash
export N8N_WEBHOOK_URL="http://localhost:5678/webhook/your-path"
```

## Useful commands

```bash
python run.py
cd frontend && npm run build
docker-compose down
```
