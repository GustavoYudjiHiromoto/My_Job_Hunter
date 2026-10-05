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

M0/M1/M2/M3/M4/M5: estrutura inicial, perfil profissional, experiências, formação, preferências, importação local de vagas de demonstração, coleta pública do Greenhouse, deduplicação conservadora entre fontes e recomendações ranqueadas com análise determinística de compatibilidade. IA, notificações e candidatura não estão implementadas.

## M2: vagas de demonstração

A seção Vagas na interface importa uma pequena lista fictícia para validar o modelo comum. A importação é idempotente para o par fonte + identificador externo e não faz requisições a sites de emprego.

- POST /api/jobs/import-fixture: importa ou atualiza os registros do fixture local.
- GET /api/jobs: lista vagas com seus registros de origem.
- GET /api/jobs/{id}: retorna uma vaga e suas origens.

Os links do fixture usam example.com e não são anúncios reais. A interface marca esses itens como demonstração.

## M3: Greenhouse

O adapter consulta a Job Board API oficial do Greenhouse, que disponibiliza vagas publicadas por board e não exige autenticação para requisições GET. Ele usa o endpoint público de listagem com conteúdo, mantém o URL original, converte a descrição HTML em texto e ignora prospect posts. Campos que a resposta não informa permanecem desconhecidos. Consulte a [documentação oficial da Job Board API](https://docs.greenhouse.io/job-board.html).

Configure um ou mais tokens de boards separados por vírgula antes de iniciar o backend. O token é a parte final do URL do job board Greenhouse:

    $env:GREENHOUSE_BOARDS = "empresa_a,empresa_b"
    uvicorn app.main:app --reload --app-dir backend

- POST /api/jobs/import-greenhouse: coleta os boards configurados e importa/atualiza as vagas.
- Cada board é processado separadamente; uma falha parcial é relatada sem descartar os boards que responderam.
- A interface permite acionar a importação manualmente. Nenhuma candidatura é enviada.

## M4: deduplicação entre fontes

Uma vaga importada por outra fonte é associada à vaga existente quando há URL canônica idêntica ou correspondência exata de título, empresa e localização após normalização de caixa, acentos e pontuação. A assinatura textual exige localização; quando falta localização e não há URL comum, as vagas permanecem separadas. Correspondências ambíguas também não são consolidadas automaticamente. Cada origem mantém seu ID e URL originais, exibidos na interface.

## M5: compatibilidade e ranking

- GET /api/jobs/recommendations: retorna vagas abertas ordenadas por score e cobertura da análise.
- Filtros disponíveis: `min_score`, `location`, `workplace_type`, `status` (`open`, `closed` ou `all`) e `include_excluded`.
- O score determinístico usa cargos, localização, modalidade, nível, contrato, salário, habilidades do perfil e critérios obrigatórios, com pesos explícitos no serviço de análise.
- A comparação de habilidades usa o campo estruturado de habilidades e cargos das experiências; o texto livre do currículo não é interpretado automaticamente nesta versão.
- Campos ausentes aparecem como desconhecidos e não reduzem a cobertura. Critérios configurados como excluídos são identificados, recebem score zero e podem ser incluídos ou removidos do resultado.
- Os resultados são calculados sob demanda a partir do perfil e das vagas atuais; não são persistidos. A análise não usa IA nem infere competências ausentes do perfil.
