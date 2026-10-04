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

M0/M1/M2: estrutura inicial, perfil profissional, experiências, formação, preferências e importação local de vagas de demonstração. O adapter de fixture exercita o contrato de coleta; adapters para fontes externas, ranking, deduplicação, notificações e candidatura não estão implementados.

## M2: vagas de demonstração

A seção Vagas na interface importa uma pequena lista fictícia para validar o modelo comum. A importação é idempotente para o par fonte + identificador externo e não faz requisições a sites de emprego.

- POST /api/jobs/import-fixture: importa ou atualiza os registros do fixture local.
- GET /api/jobs: lista vagas com seus registros de origem.
- GET /api/jobs/{id}: retorna uma vaga e suas origens.

Os links do fixture usam example.com e não são anúncios reais. A interface marca esses itens como demonstração. O contrato canônico e a interface JobAdapter ficam prontos para um adapter oficial em M3.
