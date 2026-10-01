# Notas para agentes de desenvolvimento

- Backend: `apps/api` (FastAPI, Python 3.13). Venv na raiz: `.venv`. Instalar: `.venv\Scripts\python.exe -m pip install -r apps/api/requirements.lock.txt`.
- Rodar API: `.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --app-dir apps/api`.
- Testes: `.venv\Scripts\python.exe -m pytest -q` (raiz; config em `pyproject.toml`, `pythonpath = apps/api`). Sem chamadas pagas.
- Frontend: `apps/web` (Next 16). `npm ci`, `npm run dev`, `npm run typecheck`, `npm run build`.
- Tipos do frontend: `cd apps/api && python -m app.export_openapi` depois `cd apps/web && npm run gen:types`. Commitar `lib/api-types.ts` e `apps/api/openapi.json`.
- Contratos Pydantic herdam de `ContractModel` (schema de saida com defaults obrigatorios) — manter ao criar modelos novos.
- Dinheiro: `Money` (Decimal, string no JSON); no banco, inteiros nano-USD (`app/budget/prices.py`).
- Migracoes: Alembic em `apps/api/alembic` (aplicadas no startup). Nova migracao: editar `app/storage/models.py` e criar revisao em `alembic/versions`.
- Smoke: `scripts/smoke_mock.py` (in-process), `scripts/smoke_real.py` (exige credencial + `--confirm-spend`), `scripts/ui_smoke.mjs` (Playwright).
- Ambiente Windows sem Git Bash: shell padrao e PowerShell 5.1 (sem `&&`, sem heredoc). Node/Git portateis em `%LOCALAPPDATA%\Programs`.
