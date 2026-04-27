# sales_forecast

## Backend (FastAPI + Chronos)

```bash
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

## Frontend (React + Tailwind + Recharts)

```bash
cd frontend
npm install
npm run dev
```

Frontend runs on `http://localhost:5173` and calls backend API at `http://localhost:8000`.
