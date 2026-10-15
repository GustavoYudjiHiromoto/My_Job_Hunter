# Histórico de Marcos e Evolução (M0 a M9)

Este documento preserva o histórico de especificações e decisões técnicas de cada etapa de desenvolvimento do **Job Hunter**.

---

## M0/M1: Estrutura Inicial e Perfil Profissional
* Definição da arquitetura básica (FastAPI + React).
* Modelagem do perfil profissional (`ProfessionalProfile`), experiências, formação acadêmica e preferências de carreira.

---

## M2: Vagas de Demonstração e Contrato Canônico
A seção Vagas na interface importa uma pequena lista fictícia para validar o modelo comum. A importação é idempotente para o par fonte + identificador externo e não faz requisições a sites de emprego.
* `POST /api/jobs/import-fixture`: importa ou atualiza os registros do fixture local.
* `GET /api/jobs`: lista vagas com seus registros de origem.
* `GET /api/jobs/{id}`: retorna uma vaga e suas origens.

---

## M3: Greenhouse (ATS)
O adapter consulta a Job Board API oficial do Greenhouse, que disponibiliza vagas publicadas por board e não exige autenticação para requisições GET. Ele usa o endpoint público de listagem com conteúdo, mantém o URL original, converte a descrição HTML em texto e ignora prospect posts. Campos que a resposta não informa permanecem desconhecidos.
* `GREENHOUSE_BOARDS`: tokens de boards separados por vírgula.
* `POST /api/jobs/import-greenhouse`: coleta os boards configurados e importa/atualiza as vagas.

---

## M4: Deduplicação Cross-Source
Uma vaga importada por outra fonte é associada à vaga existente quando há URL canônica idêntica ou correspondência exata de título, empresa e localização após normalização de caixa, acentos e pontuação. A assinatura textual exige localização; quando falta localização e não há URL comum, as vagas permanecem separadas. Correspondências ambíguas também não são consolidadas automaticamente. Cada origem mantém seu ID e URL originais.

---

## M5: Compatibilidade e Ranking Determinístico
* `GET /api/jobs/recommendations`: retorna vagas abertas ordenadas por score e cobertura da análise.
* Filtros disponíveis: `min_score`, `location`, `workplace_type`, `status` (`open`, `closed` ou `all`) e `include_excluded`.
* O score determinístico usa cargos, localização, modalidade, nível, contrato, salário, habilidades do perfil e critérios obrigatórios, com pesos explícitos no serviço de análise.
* A comparação de habilidades usa o campo estruturado de habilidades e cargos das experiências.

---

## M6: Lever (ATS)
O adapter usa a Postings API oficial do Lever para listar vagas publicadas em cada site configurado. A listagem é paginada; o texto vem dos campos plain-text, complementado por listas estruturadas.
* `LEVER_SITES`: identificadores separados por vírgula.
* `LEVER_REGION`: `global` ou `eu`.
* `POST /api/jobs/import-lever`: coleta e importa os sites configurados.

---

## M7: Monitoramento, Histórico de Coletas e Trava Concorrente
* CLI de coleta: `python -m app.cli import-jobs --source all`.
* Bloqueio concorrente via lock local no arquivo SQLite (`job_hunter.db.import.lock`).
* Reconciliação conservadora: uma vaga ausente é considerada fechada para aquela origem somente após **duas coletas completas consecutivas** do respectivo board/site.

---

## M8: Alertas por E-mail
* Envio automatizado de resumo por e-mail via SMTP após coletas bem-sucedidas.
* Alerta apenas para vagas novas, abertas, não excluídas pelas preferências e com score igual ou superior ao limite configurado.

---

## M9: Descoberta Multicanal e Avaliação por IA
* **Descoberta:** Remotive, JSearch (OpenWeb Ninja) e Jobicy com respeito a cotas e rate limits.
* **Avaliação Semântica por IA:** OpenAI `gpt-4.1-mini` via Structured Outputs para análise em lotes de 10 vagas, com cache local baseado em hash SHA-256 (perfil + vaga + modelo + versão de prompt).
