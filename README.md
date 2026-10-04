# Job Hunter

Aplicação pessoal para organizar perfil e preferências profissionais e, em marcos futuros, coletar e analisar vagas.

## Requisitos

- Python 3.13
- Node.js 20.19+ ou 22.12+
- npm

## Backend

No PowerShell, na raiz do projeto:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r backend/requirements.txt
uvicorn app.main:app --reload --app-dir backend
```

O backend fica em http://localhost:8000; documentação interativa em /docs. O SQLite é criado em job_hunter.db na raiz do projeto (ou no caminho de DATABASE_URL).

```powershell
python -m pytest backend/tests
python -m ruff check backend
```

## Frontend

```powershell
cd frontend
npm install
npm run dev
```

```powershell
npm run test
npm run typecheck
npm run lint
```

O frontend usa /api como prefixo; o servidor de desenvolvimento encaminha as chamadas para http://localhost:8000.

## Escopo atual

M0/M1: estrutura inicial, perfil profissional, experiências, formação e preferências. Adaptadores de fontes e providers de IA são apenas pontos de extensão. Coleta de vagas, ranking, deduplicação, notificações e candidatura não estão implementados.
