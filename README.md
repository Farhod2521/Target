# TargetologAI backend (FastAPI)

```bash
uv sync
cp .env.example .env
uv run alembic stamp 0001        # mavjud Django bazasi; bo'sh baza uchun: alembic upgrade head
uv run uvicorn app.main:app --reload
```

API hujjati: http://localhost:8000/docs

Arxitektura, modullar va ko'chirish holati: [docs/ARXITEKTURA.md](docs/ARXITEKTURA.md)
