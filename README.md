# Job Hunter

> Plataforma inteligente para agregação, deduplicação *cross-source*, recomendação determinística e triagem semântica de vagas de emprego.

[![Python](https://img.shields.io/badge/Python-3.13-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-19-61DAFB.svg)](https://react.dev/)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.7-3178C6.svg)](https://www.typescriptlang.org/)
[![Tests](https://img.shields.io/badge/Tests-111%20Passed-success.svg)](#-testes-e-qualidade-de-código)

---

## 🎯 Sobre o Projeto

O **Job Hunter** é uma aplicação *full-stack* desenvolvida para centralizar e otimizar a busca por oportunidades profissionais. O sistema automatiza desde a coleta em boards e agregadores de vagas até a análise de compatibilidade do perfil profissional, unificando duplicatas e classificando oportunidades com base em critérios objetivos e análise semântica via IA.

---

## ✨ Principais Funcionalidades

* **Agregação e Descoberta Multicanal:** Coleta de vagas em ATSs corporativos (**Greenhouse**, **Lever**) e provedores de busca pública/APIs (**Remotive**, **JSearch / OpenWeb Ninja**, **Jobicy**), respeitando limites de taxa e cotas.
* **Deduplicação *Cross-Source*:** Identifica a mesma oportunidade anunciada em múltiplos canais através de URLs canônicas e assinaturas normalizadas (título, empresa e localização), fundindo registros sem perder dados de proveniência.
* **Motor Determinístico de Ranking:** Algoritmo explicável de compatibilidade que pondera competências, cargos desejados, modalidade, localização, senioridade e pretensão salarial em uma escala de 0 a 100, detalhando pontos de aderência e ausências.
* **Triagem Semântica com IA (LLM):** Avaliação de relevância sob demanda com **GPT-4.1-mini** (OpenAI Responses API com *Structured Outputs*), contando com **cache local baseado em hash SHA-256** (perfil + vaga + modelo + versão de prompt) para evitar requisições redundantes e custos desnecessários.
* **Monitoramento & Reconciliação:** Detecta o encerramento de vagas após ausência consecutiva em múltiplos ciclos de coleta de uma mesma fonte.
* **Concorrência Segura (*File Locks*):** Controle de concorrência com travas de arquivo no sistema operacional (`msvcrt` no Windows / `fcntl` no Unix) para proteger a integridade do SQLite e evitar coletas duplicadas em paralelo.
* **Alertas por E-mail:** Envio automatizado de notificações via SMTP para oportunidades que atingem o score mínimo desejado.

---

## 🛠️ Tecnologias Utilizadas

* **Backend:** Python 3.13, FastAPI, SQLAlchemy 2, Pydantic v2, SQLite, HTTPX, Ruff.
* **Frontend:** React 19, TypeScript, Vite, CSS Modules / Styles puros.
* **Inteligência Artificial:** OpenAI API (`gpt-4.1-mini`) com Structured Outputs / JSON Schema estrito.
* **Testes Automatizados:** Pytest (Backend) e Vitest + React Testing Library (Frontend).

---

## 🚀 Como Executar Localmente

### Pré-requisitos
* **Python 3.13+**
* **Node.js 20.19+ ou 22.12+** e **npm**

### 1. Backend

No terminal (PowerShell no Windows ou Bash no Linux), a partir da raiz do repositório:

```powershell
# Criar e ativar o ambiente virtual
python -m venv .venv
.\.venv\Scripts\Activate.ps1    # No Linux/Mac: source .venv/bin/activate

# Instalar dependências
python -m pip install --upgrade pip
pip install -r backend/requirements.txt

# Iniciar o servidor da API
uvicorn app.main:app --reload --app-dir backend
```

A API estará disponível em `http://localhost:8000` e a documentação interativa OpenAPI/Swagger em `http://localhost:8000/docs`. O banco SQLite é inicializado automaticamente em `job_hunter.db`.

### 2. Frontend

Em outro terminal:

```powershell
cd frontend

# Instalar dependências
npm install

# Iniciar o servidor de desenvolvimento
npm run dev
```

Acesse a interface no navegador em `http://localhost:5173`. As chamadas para `/api/*` são roteadas automaticamente para o backend.

---

## ⚙️ Variáveis de Ambiente (Opcionais)

O sistema funciona localmente sem configurações obrigatórias adicionais. Para habilitar integrações externas específicas, configure as variáveis de ambiente antes de subir o backend:

| Variável | Descrição |
| :--- | :--- |
| `OPENAI_API_KEY` | Chave da OpenAI para habilitar a análise de relevância com IA. |
| `OPENAI_MODEL` | Modelo utilizado pela análise semântica (Padrão: `gpt-4.1-mini`). |
| `JSEARCH_API_KEY` | Chave da OpenWeb Ninja para descoberta de vagas via JSearch. |
| `GREENHOUSE_BOARDS` | Lista de tokens de boards Greenhouse separados por vírgula. |
| `LEVER_SITES` | Lista de identificadores de empresas no Lever separados por vírgula. |
| `SMTP_HOST` / `SMTP_PORT` | Configuração de servidor SMTP para notificações por e-mail. |
| `DATABASE_URL` | URL de conexão do banco (Padrão: `sqlite:///job_hunter.db`). |

---

## 🧪 Testes e Qualidade de Código

A aplicação possui uma suíte com **111 testes automatizados** cobrindo regras de negócio, adapters, persistência, deduplicação e interface.

```powershell
# Backend: Rodar testes unitários e de integração (94 testes)
python -m pytest backend/tests

# Backend: Análise estática de código com Ruff
python -m ruff check backend

# Frontend: Rodar testes de interface com Vitest (17 testes)
npm --prefix frontend test -- --run

# Frontend: Checagem estrita de tipos TypeScript
npm --prefix frontend run typecheck

# Frontend: Linting com ESLint
npm --prefix frontend run lint
```

---

## 🗺️ Histórico de Marcos e Evolução

O projeto foi construído incrementalmente através de marcos estruturados de desenvolvimento (M0 a M9). Para detalhes sobre a arquitetura de cada etapa e decisões de implementação, consulte o [Histórico de Marcos](docs/MILESTONES.md).
