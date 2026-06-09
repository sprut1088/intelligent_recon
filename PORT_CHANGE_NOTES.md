# Port Change Notes

This build uses the requested ports:

- FastAPI backend: `8090`
- React/Vite frontend: `8181`

## Local backend

```bash
cd backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8090
```

Open API docs at: `http://localhost:8090/docs`

## Local frontend

```bash
cd frontend
npm install
npm run dev
```

Open UI at: `http://localhost:8181`

The frontend default API base URL is now `http://127.0.0.1:8090`.

## Docker

```bash
docker compose up --build
```

- Backend: `http://localhost:8090`
- Frontend: `http://localhost:8181`
