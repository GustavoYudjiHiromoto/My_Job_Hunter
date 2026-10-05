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

M0/M1/M2/M3/M4/M5/M6/M7/M8: estrutura inicial, perfil profissional, experiências, formação, preferências, importação local de vagas de demonstração, coleta pública do Greenhouse e Lever, deduplicação conservadora entre fontes, recomendações ranqueadas com análise determinística de compatibilidade, histórico de coletas e alertas por e-mail para novas vagas compatíveis. IA adicional, outros canais e candidatura não estão implementados.

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

## M6: Lever

O adapter usa a [Postings API oficial do Lever](https://github.com/lever/postings-api) para listar vagas publicadas em cada site configurado. A listagem é paginada; o texto vem dos campos plain-text, complementado por listas estruturadas. O site Lever vira um nome de empresa aproximado, pois a resposta não fornece um campo canônico de nome empresarial. Faixas salariais permanecem desconhecidas no modelo normalizado porque a API informa períodos como anual ou por hora, e o modelo atual não armazena esse intervalo.

Configure os identificadores de sites separados por vírgula e a região global ou EU:

    $env:LEVER_SITES = "empresa_a,empresa_b"
    $env:LEVER_REGION = "global"
    uvicorn app.main:app --reload --app-dir backend

- POST /api/jobs/import-lever: coleta e importa os sites configurados, informando falhas parciais.
- Somente GET na lista pública é usado. O endpoint de candidatura do Lever não é chamado.
- A API não oferece busca textual geral; a coleta abrange os sites configurados.

## M7: monitoramento e histórico de coletas

O comando abaixo executa uma coleta das fontes configuradas e imprime uma linha JSON com o resultado. Execute-o a partir da pasta `backend`:

    ..\.venv\Scripts\python.exe -m app.cli import-jobs --source all

`--source` aceita `all`, `greenhouse` ou `lever`. Códigos de saída: 0 sucesso, 1 falha, 2 parcial, 3 execução ignorada porque outra estava ativa e 4 configuração ausente ou inválida. Os resultados são persistidos em `import_runs` e `import_run_sources`; a API `GET /api/jobs/import-runs/latest` e a interface mostram o resumo da última tentativa.

O CLI e os endpoints de importação Greenhouse/Lever compartilham uma trava local junto ao arquivo SQLite. Uma execução concorrente é registrada como `skipped`. Cada board/site é processado isoladamente; uma fonte que falha não invalida as fontes concluídas.

Uma vaga ausente é considerada fechada para aquela origem somente após duas coletas completas consecutivas do respectivo board/site. A vaga consolidada permanece aberta enquanto existir alguma origem ativa ou ainda não monitorada. Falhas e boards/sites não consultados não contam como ausência. Registros de demonstração não participam da reconciliação.

### Agendar no Windows

1. Configure `GREENHOUSE_BOARDS`, `LEVER_SITES`, `LEVER_REGION` e, se necessário, `DATABASE_URL` como variáveis persistentes do mesmo usuário do Windows que executará a tarefa. Uma variável definida somente com `$env:` em uma janela PowerShell não será herdada por execuções futuras.
2. Abra o Agendador de Tarefas e selecione **Criar Tarefa**.
3. Na guia **Geral**, escolha a conta com acesso ao projeto e ao banco SQLite.
4. Em **Disparadores**, crie uma execução diária e configure repetição a cada 6 horas.
5. Em **Ações**, selecione **Iniciar um programa**:
   - Programa/script: caminho absoluto para `.venv\Scripts\python.exe`;
   - Argumentos: `-m app.cli import-jobs --source all`;
   - Iniciar em: caminho absoluto da pasta `backend`.
6. Nas configurações, escolha **Não iniciar uma nova instância** se a tarefa já estiver em execução (`IgnoreNew`).
7. Execute a tarefa manualmente uma vez e confira o histórico de coletas no Job Hunter.

Se a máquina estiver desligada no horário, pode-se habilitar a opção para iniciar a tarefa assim que possível após um horário agendado ter sido perdido. As políticas de instâncias do Agendador estão documentadas pela [Microsoft](https://learn.microsoft.com/en-us/windows/win32/taskschd/taskschedulerschema-multipleinstancespolicy-settingstype-element).

## M8: alertas por e-mail

Os alertas são opcionais e desligados inicialmente. Na seção de vagas, informe o destinatário e o score mínimo (0–100) para ativá-los. Após uma coleta Greenhouse/Lever bem-sucedida ou parcial, o Job Hunter envia um resumo apenas das vagas novas, abertas, não excluídas pelas preferências e com score igual ou superior ao limite configurado. Atualizações e duplicatas já conhecidas não geram um novo alerta. Uma falha de envio fica no histórico de notificações e não altera o resultado da coleta. Não há repetição automática de e-mails cujo resultado ficou ambíguo.

Configure o SMTP no ambiente do backend; a senha nunca é retornada pela API nem incluída no histórico:

    $env:SMTP_HOST = "smtp.example.com"
    $env:SMTP_PORT = "587"
    $env:SMTP_SECURITY = "starttls"
    $env:SMTP_FROM = "job-hunter@example.com"
    $env:SMTP_USERNAME = "usuario" # opcional
    $env:SMTP_PASSWORD = "senha-de-aplicativo" # opcional, junto com SMTP_USERNAME

`SMTP_SECURITY` aceita `starttls` (padrão) ou `ssl`. Os testes usam um notifier falso e nunca enviam mensagens reais. O primeiro envio real deve ser validado manualmente com SMTP configurado, alertas habilitados, score mínimo explícito e uma coleta controlada.

## M4: deduplicação entre fontes

Uma vaga importada por outra fonte é associada à vaga existente quando há URL canônica idêntica ou correspondência exata de título, empresa e localização após normalização de caixa, acentos e pontuação. A assinatura textual exige localização; quando falta localização e não há URL comum, as vagas permanecem separadas. Correspondências ambíguas também não são consolidadas automaticamente. Cada origem mantém seu ID e URL originais, exibidos na interface.

## M5: compatibilidade e ranking

- GET /api/jobs/recommendations: retorna vagas abertas ordenadas por score e cobertura da análise.
- Filtros disponíveis: `min_score`, `location`, `workplace_type`, `status` (`open`, `closed` ou `all`) e `include_excluded`.
- O score determinístico usa cargos, localização, modalidade, nível, contrato, salário, habilidades do perfil e critérios obrigatórios, com pesos explícitos no serviço de análise.
- A comparação de habilidades usa o campo estruturado de habilidades e cargos das experiências; o texto livre do currículo não é interpretado automaticamente nesta versão.
- Campos ausentes aparecem como desconhecidos e não reduzem a cobertura. Critérios configurados como excluídos são identificados, recebem score zero e podem ser incluídos ou removidos do resultado.
- Os resultados são calculados sob demanda a partir do perfil e das vagas atuais; não são persistidos. A análise não usa IA nem infere competências ausentes do perfil.
