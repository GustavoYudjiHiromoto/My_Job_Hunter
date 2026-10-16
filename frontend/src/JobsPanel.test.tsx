import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import JobsPanel from './JobsPanel'

const jobs = [{
  id: 1,
  title: 'Pessoa Desenvolvedora Backend Júnior',
  company: 'Nuvem Clara',
  description: 'Desenvolvimento de APIs com Python.',
  location: null,
  workplace_type: null,
  seniority: null,
  employment_type: null,
  salary_min: null,
  salary_max: null,
  salary_currency: null,
  published_at: null,
  status: 'open',
  created_at: '2026-10-04T12:00:00Z',
  sources: [{
    source: 'remotive',
    external_id: 'remotive-001',
    source_url: 'https://remotive.com/remote-jobs/software-dev/backend-developer-9876',
    collected_at: '2026-10-04T12:00:00Z',
  }],
}]

const recommendations = [{
  job: jobs[0],
  score: 82,
  coverage: 80,
  excluded: false,
  strengths: ['Cargo compatível com backend.', 'Habilidade Python encontrada.'],
  gaps: ['Faixa salarial anunciada está fora da preferência.'],
  criteria: [{ key: 'title', label: 'Cargo desejado', result: 'match', weight: 20, points: 20, explanation: 'Cargo compatível.' }],
  ai_analysis: {
    classification: 'relevant', score: 93, rationale: 'Tecnologias centrais e nível são compatíveis.',
    strengths: ['Python'], gaps: [], unknowns: ['Salário não informado'], model: 'fake-model',
    analyzed_at: '2026-10-12T12:00:00Z',
  },
}]
let activeRecommendations = recommendations

const variedAIRecommendations = [
  {
    ...recommendations[0], job: { ...jobs[0], id: 3, title: 'Vaga pouco relevante' }, score: 99,
    ai_analysis: { ...recommendations[0].ai_analysis, classification: 'not_relevant' as const, score: 12 },
  },
  {
    ...recommendations[0], job: { ...jobs[0], id: 2, title: 'Vaga talvez relevante' }, score: 96,
    ai_analysis: { ...recommendations[0].ai_analysis, classification: 'maybe' as const, score: 61 },
  },
  recommendations[0],
]

describe('recomendações de vagas M5', () => {
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  beforeEach(() => {
    localStorage.clear()
    activeRecommendations = recommendations
    vi.stubGlobal('fetch', vi.fn().mockImplementation((url: string, options?: RequestInit) => {
      if (url === '/api/notifications/settings') return Promise.resolve({ ok: true, json: async () => ({ enabled: false, recipient_email: '', minimum_score: null, smtp_configured: false }) })
      if (url === '/api/notifications') return Promise.resolve({ ok: true, json: async () => [] })
      if (url === '/api/jobs/discovery-runs/latest') {
        return Promise.resolve({ ok: true, json: async () => null })
      }
      if (url === '/api/jobs/discover' && options?.method === 'POST') {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            id: 8,
            requested_source: 'discovery',
            status: 'succeeded',
            started_at: '2026-10-11T12:00:00Z',
            finished_at: '2026-10-11T12:00:01Z',
            created: 1,
            updated: 0,
            total: 1,
            error: null,
            sources: [{ source: 'remotive', scope: 'remote', status: 'succeeded', created: 1, updated: 0, total: 1, error: null }],
          }),
        })
      }
      if (url === '/api/jobs/ai-analysis' && options?.method === 'POST') {
        return Promise.resolve({ ok: true, json: async () => ({
          analyzed: 1, remaining: 0, failed: 0, limit: 10,
          items: [{ job_id: 1, title: jobs[0].title, company: jobs[0].company,
            classification: 'relevant', score: 93, rationale: 'Tecnologias centrais e nível são compatíveis.',
            strengths: ['Python'], gaps: [], unknowns: ['Salário não informado'] }],
        }) })
      }
      if (typeof url === 'string' && url.startsWith('/api/jobs/recommendations')) {
        return Promise.resolve({ ok: true, json: async () => activeRecommendations })
      }
      return Promise.resolve({ ok: true, json: async () => jobs })
    }))
  })

  it('mostra score, explicação e a origem original', async () => {
    render(<JobsPanel />)

    expect(await screen.findByRole('heading', { name: 'Pessoa Desenvolvedora Backend Júnior' })).toBeInTheDocument()
    expect(screen.getByText('Remuneração não informada')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Ver origem REMOTIVE ↗' })).toHaveAttribute(
      'href',
      'https://remotive.com/remote-jobs/software-dev/backend-developer-9876',
    )
    expect(screen.getByText('REMOTIVE')).toBeInTheDocument()
    expect(screen.getByText('82%')).toBeInTheDocument()
    expect(screen.getByText('Habilidade Python encontrada.')).toBeInTheDocument()
    expect(screen.getByText('Faixa salarial anunciada está fora da preferência.')).toBeInTheDocument()
    expect(screen.getByText('Relevância IA · 93%')).toBeInTheDocument()
    expect(screen.getByText('82%')).toBeInTheDocument()
    expect(screen.getByText('Tecnologias centrais e nível são compatíveis.')).toBeInTheDocument()
  })

  it('dispara análise de IA manual e informa o lote processado', async () => {
    let finishAnalysis: (() => void) | undefined
    const pendingAnalysis = new Promise<void>((resolve) => { finishAnalysis = resolve })
    const mockedFetch = vi.mocked(fetch)
    const originalFetch = mockedFetch.getMockImplementation()!
    mockedFetch.mockImplementation((url, options) => {
      if (url === '/api/jobs/ai-analysis' && options?.method === 'POST') {
        return pendingAnalysis.then(() => new Response(JSON.stringify({
          analyzed: 1, remaining: 0, failed: 0, limit: 10,
          items: [{ job_id: 1, title: jobs[0].title, company: jobs[0].company,
            classification: 'relevant', score: 93, rationale: 'Tecnologias centrais e nível são compatíveis.',
            strengths: ['Python'], gaps: [], unknowns: ['Salário não informado'] }],
        }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
      }
      return originalFetch(url, options)
    })
    const user = userEvent.setup()
    render(<JobsPanel />)
    await screen.findByRole('heading', { name: 'Pessoa Desenvolvedora Backend Júnior' })

    await user.click(screen.getByRole('button', { name: 'Analisar próximas 10 com IA' }))

    await waitFor(() => expect(fetch).toHaveBeenCalledWith('/api/jobs/ai-analysis', { method: 'POST' }))
    expect(screen.getByText('O backend está analisando até 10 vagas sequencialmente. As conclusões aparecem aqui quando o lote terminar; não feche nem atualize a página.')).toBeInTheDocument()
    finishAnalysis?.()
    expect(await screen.findByText('Lote concluído: 1 relevantes, 0 talvez relevantes e 0 pouco relevantes.')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'O que a IA concluiu' })).toBeInTheDocument()
    expect(screen.getAllByText('Tecnologias centrais e nível são compatíveis.')).toHaveLength(2)
    expect(screen.getAllByText((_content, element) => element?.textContent === 'Compatibilidades: Python')).toHaveLength(2)
  })

  it('ordena por classificação e score de IA sem alterar a ordem determinística inicial', async () => {
    activeRecommendations = variedAIRecommendations
    const user = userEvent.setup()
    const { container } = render(<JobsPanel />)
    await screen.findByRole('heading', { name: 'Pessoa Desenvolvedora Backend Júnior' })
    const cardTitles = () => Array.from(container.querySelectorAll('.jobs-list .recommendation-card h3'))
      .map((heading) => heading.textContent)

    expect(cardTitles()).toEqual([
      'Vaga pouco relevante', 'Vaga talvez relevante', 'Pessoa Desenvolvedora Backend Júnior',
    ])
    await user.selectOptions(screen.getByLabelText('Ordenar por'), 'ai')
    expect(cardTitles()).toEqual([
      'Pessoa Desenvolvedora Backend Júnior', 'Vaga talvez relevante', 'Vaga pouco relevante',
    ])
    expect(localStorage.getItem('my-job-hunter.ai-sort-order')).toBe('ai')
  })

  it('oculta pouco relevantes de forma reversível e mantém preferência entre montagens', async () => {
    activeRecommendations = variedAIRecommendations
    const user = userEvent.setup()
    const firstMount = render(<JobsPanel />)
    await screen.findByRole('heading', { name: 'Pessoa Desenvolvedora Backend Júnior' })
    const hideControl = screen.getByLabelText('Ocultar pouco relevantes pela IA')

    await user.click(hideControl)
    expect(firstMount.container.querySelectorAll('.jobs-list .recommendation-card')).toHaveLength(2)
    expect(localStorage.getItem('my-job-hunter.hide-low-ai-relevance')).toBe('true')
    await user.selectOptions(screen.getByLabelText('Relevância IA'), 'not_relevant')
    expect(screen.getByRole('heading', { name: 'Vaga pouco relevante' })).toBeInTheDocument()

    firstMount.unmount()
    const secondMount = render(<JobsPanel />)
    await screen.findByRole('heading', { name: 'Pessoa Desenvolvedora Backend Júnior' })
    expect(screen.getByLabelText('Ocultar pouco relevantes pela IA')).toBeChecked()
    expect(secondMount.container.querySelectorAll('.jobs-list .recommendation-card')).toHaveLength(2)
  })

  it('aciona a descoberta Remotive e mostra o resultado', async () => {
    const user = userEvent.setup()
    render(<JobsPanel />)
    await screen.findByRole('heading', { name: 'Pessoa Desenvolvedora Backend Júnior' })

    await user.click(screen.getByRole('button', { name: /Descobrir vagas/ }))

    await waitFor(() => expect(fetch).toHaveBeenCalledWith('/api/jobs/discover', { method: 'POST' }))
    expect(await screen.findByRole('status')).toHaveTextContent('Descoberta concluída: 1 novas, 0 atualizadas.')
  })

  it('mostra feedback enquanto a busca está rodando e atualiza o estado das fontes', async () => {
    let finishDiscovery: (() => void) | undefined
    let discoveryStarted = false
    const runningRun = {
      id: 11, requested_source: 'discovery', status: 'running', started_at: '2026-10-11T12:00:00Z',
      finished_at: null, created: 0, updated: 0, total: 0, error: null,
      sources: [{ source: 'remotive', scope: 'remote', status: 'pending', created: 0, updated: 0, total: 0, error: null }],
    }
    const completedRun = {
      ...runningRun, status: 'succeeded', finished_at: '2026-10-11T12:00:02Z',
      sources: [{ ...runningRun.sources[0], status: 'succeeded' }],
    }
    const pendingResponse = new Promise<void>((resolve) => { finishDiscovery = resolve })
    vi.stubGlobal('fetch', vi.fn().mockImplementation((url: string, options?: RequestInit) => {
      if (url === '/api/notifications/settings') return Promise.resolve({ ok: true, json: async () => ({ enabled: false, recipient_email: '', minimum_score: null, smtp_configured: false }) })
      if (url === '/api/notifications') return Promise.resolve({ ok: true, json: async () => [] })
      if (url === '/api/jobs/discovery-runs/latest') return Promise.resolve({ ok: true, json: async () => discoveryStarted ? runningRun : null })
      if (url === '/api/jobs/discover' && options?.method === 'POST') {
        discoveryStarted = true
        return pendingResponse.then(() => ({ ok: true, json: async () => completedRun }))
      }
      if (typeof url === 'string' && url.startsWith('/api/jobs/recommendations')) return Promise.resolve({ ok: true, json: async () => recommendations })
      return Promise.resolve({ ok: true, json: async () => jobs })
    }))
    const user = userEvent.setup()
    render(<JobsPanel />)

    await user.click(await screen.findByRole('button', { name: /Descobrir vagas/ }))

    expect(screen.getByRole('status')).toHaveTextContent('Busca em andamento')
    expect(screen.getByRole('status')).toHaveTextContent('JSearch (se configurado e dentro do limite)')
    await waitFor(
      () => expect(screen.getByRole('status')).toHaveTextContent(/Execução #11: remotive: pendente/),
      { timeout: 3000 },
    )
    expect(screen.getByRole('button', { name: /Buscando vagas/ })).toBeDisabled()

    finishDiscovery?.()
    expect(await screen.findByLabelText('Última descoberta')).toHaveTextContent('remotive / remote: ok')
  })

  it('explica quando o backend falha antes de registrar a descoberta', async () => {
    vi.stubGlobal('fetch', vi.fn().mockImplementation((url: string, options?: RequestInit) => {
      if (url === '/api/notifications/settings') return Promise.resolve({ ok: true, json: async () => ({ enabled: false, recipient_email: '', minimum_score: null, smtp_configured: false }) })
      if (url === '/api/notifications') return Promise.resolve({ ok: true, json: async () => [] })
      if (url === '/api/jobs/discovery-runs/latest') return Promise.resolve({ ok: true, json: async () => null })
      if (url === '/api/jobs/discover' && options?.method === 'POST') return Promise.resolve({ ok: false, status: 500, json: async () => ({}) })
      if (typeof url === 'string' && url.startsWith('/api/jobs/recommendations')) return Promise.resolve({ ok: true, json: async () => recommendations })
      return Promise.resolve({ ok: true, json: async () => jobs })
    }))
    const user = userEvent.setup()
    render(<JobsPanel />)

    await user.click(await screen.findByRole('button', { name: /Descobrir vagas/ }))

    expect(await screen.findByRole('alert')).toHaveTextContent('O backend falhou ao executar a busca (HTTP 500).')
    expect(screen.queryByLabelText('Última descoberta')).not.toBeInTheDocument()
  })

  it('remove da interface importações manuais que não fazem parte da busca M9', async () => {
    render(<JobsPanel />)
    await screen.findByRole('heading', { name: 'Pessoa Desenvolvedora Backend Júnior' })

    expect(screen.queryByRole('button', { name: /Importar Greenhouse/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Importar Lever/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Carregar demonstração/ })).not.toBeInTheDocument()
  })

  it('explica quando JSearch e Jobicy são ignorados', async () => {
    vi.stubGlobal('fetch', vi.fn().mockImplementation((url: string, options?: RequestInit) => {
      if (url === '/api/notifications/settings') return Promise.resolve({ ok: true, json: async () => ({ enabled: false, recipient_email: '', minimum_score: null, smtp_configured: false }) })
      if (url === '/api/notifications') return Promise.resolve({ ok: true, json: async () => [] })
      if (url === '/api/jobs/discovery-runs/latest') return Promise.resolve({ ok: true, json: async () => null })
      if (url === '/api/jobs/discover' && options?.method === 'POST') return Promise.resolve({ ok: true, json: async () => ({
        id: 9, requested_source: 'discovery', status: 'succeeded', started_at: '2026-10-11T12:00:00Z',
        finished_at: '2026-10-11T12:00:01Z', created: 0, updated: 0, total: 0, error: null,
        sources: [
          { source: 'remotive', scope: 'remote', status: 'succeeded', created: 0, updated: 0, total: 0, error: null },
          { source: 'jsearch', scope: 'br', status: 'skipped', created: 0, updated: 0, total: 0, error: 'JSEARCH_API_KEY não configurada.' },
          { source: 'jobicy', scope: 'brazil', status: 'skipped', created: 0, updated: 0, total: 0, error: 'Cooldown ativo.' },
        ],
      }) })
      if (typeof url === 'string' && url.startsWith('/api/jobs/recommendations')) return Promise.resolve({ ok: true, json: async () => recommendations })
      return Promise.resolve({ ok: true, json: async () => jobs })
    }))
    const user = userEvent.setup()
    render(<JobsPanel />)
    await user.click(await screen.findByRole('button', { name: /Descobrir vagas/ }))
    const summary = await screen.findByLabelText('Última descoberta')
    expect(summary).toHaveTextContent('jsearch / br: ignorada — JSEARCH_API_KEY não configurada.')
    expect(summary).toHaveTextContent('jobicy / brazil: ignorada — Cooldown ativo.')
    expect(screen.getByRole('status')).toHaveTextContent('Busca concluída sem vagas retornadas.')
  })

  it('mostra erros por provider sem ocultar sucesso parcial nem resultados válidos', async () => {
    vi.stubGlobal('fetch', vi.fn().mockImplementation((url: string, options?: RequestInit) => {
      if (url === '/api/notifications/settings') return Promise.resolve({ ok: true, json: async () => ({ enabled: false, recipient_email: '', minimum_score: null, smtp_configured: false }) })
      if (url === '/api/notifications') return Promise.resolve({ ok: true, json: async () => [] })
      if (url === '/api/jobs/discovery-runs/latest') return Promise.resolve({ ok: true, json: async () => null })
      if (url === '/api/jobs/discover' && options?.method === 'POST') return Promise.resolve({ ok: true, json: async () => ({
        id: 10, requested_source: 'discovery', status: 'partial', started_at: '2026-10-11T12:00:00Z',
        finished_at: '2026-10-11T12:00:01Z', created: 1, updated: 0, total: 1, error: null,
        sources: [
          { source: 'remotive', scope: 'remote', status: 'succeeded', created: 1, updated: 0, total: 1, error: null },
          { source: 'jsearch', scope: 'br', status: 'succeeded', created: 0, updated: 0, total: 0, error: 'Uma consulta JSearch falhou: HTTP 429.' },
          { source: 'jobicy', scope: 'brazil', status: 'failed', created: 0, updated: 0, total: 0, error: 'Jobicy retornou HTTP 503.' },
        ],
      }) })
      if (typeof url === 'string' && url.startsWith('/api/jobs/recommendations')) return Promise.resolve({ ok: true, json: async () => recommendations })
      return Promise.resolve({ ok: true, json: async () => jobs })
    }))
    const user = userEvent.setup()
    render(<JobsPanel />)

    await user.click(await screen.findByRole('button', { name: /Descobrir vagas/ }))

    const summary = await screen.findByLabelText('Última descoberta')
    expect(summary).toHaveTextContent('parcial')
    expect(summary).toHaveTextContent('1 novas · 0 atualizadas · 1 resultados')
    expect(summary).toHaveTextContent('remotive / remote: ok')
    expect(summary).not.toHaveTextContent('remotive / remote: ok —')
    expect(summary).toHaveTextContent('jsearch / br: ok — Uma consulta JSearch falhou: HTTP 429.')
    expect(summary).toHaveTextContent('jobicy / brazil: falhou — Jobicy retornou HTTP 503.')
    expect(await screen.findByRole('heading', { name: 'Pessoa Desenvolvedora Backend Júnior' })).toBeInTheDocument()
  })

  it('mostra origens atuais e oculta Greenhouse em uma vaga deduplicada', async () => {
    jobs[0].sources.push({
      source: 'greenhouse',
      external_id: 'legacy:123',
      source_url: 'https://boards.greenhouse.io/company/jobs/123',
      collected_at: '2026-10-04T12:00:00Z',
    })

    try {
      render(<JobsPanel />)

      expect(await screen.findByRole('link', { name: 'Ver origem REMOTIVE ↗' })).toHaveAttribute(
        'href',
        'https://remotive.com/remote-jobs/software-dev/backend-developer-9876',
      )
      expect(screen.queryByRole('link', { name: 'Ver origem GREENHOUSE ↗' })).not.toBeInTheDocument()
      expect(screen.queryByText('GREENHOUSE')).not.toBeInTheDocument()
    } finally {
      jobs[0].sources.pop()
    }
  })

  it.each(['fixture', 'greenhouse', 'lever'])('não exibe anúncios antigos da origem %s', async (sourceName) => {
    const originalSource = jobs[0].sources[0].source
    jobs[0].sources[0].source = sourceName
    try {
      render(<JobsPanel />)

      expect(await screen.findByText(/Anúncios antigos de Greenhouse, Lever e demonstração permanecem/)).toBeInTheDocument()
      expect(screen.queryByText(sourceName.toUpperCase())).not.toBeInTheDocument()
    } finally {
      jobs[0].sources[0].source = originalSource
    }
  })

  it('aplica os filtros de score, localização e modalidade na consulta', async () => {
    const user = userEvent.setup()
    render(<JobsPanel />)
    await screen.findByRole('heading', { name: 'Pessoa Desenvolvedora Backend Júnior' })

    await user.clear(screen.getByLabelText('Score mínimo'))
    await user.type(screen.getByLabelText('Score mínimo'), '60')
    await user.type(screen.getByLabelText('Localização'), 'São Paulo')
    await user.selectOptions(screen.getByLabelText('Modalidade'), 'remote')
    await user.click(screen.getByRole('button', { name: 'Aplicar filtros' }))

    await waitFor(() => expect(fetch).toHaveBeenCalledWith(
      '/api/jobs/recommendations?min_score=60&location=S%C3%A3o+Paulo&workplace_type=remote&include_excluded=true&include_ineligible=false',
    ))
  })

  it('ignora respostas antigas de recomendações que chegam fora de ordem', async () => {
    let resolveFirst: ((response: { ok: boolean; json: () => Promise<unknown> }) => void) | undefined
    let resolveSecond: ((response: { ok: boolean; json: () => Promise<unknown> }) => void) | undefined
    let recommendationCalls = 0
    const latest = [{
      ...recommendations[0],
      job: { ...jobs[0], id: 2, title: 'Resposta mais recente' },
    }]
    vi.stubGlobal('fetch', vi.fn().mockImplementation((url: string) => {
      if (url === '/api/notifications/settings') return Promise.resolve({ ok: true, json: async () => ({ enabled: false, recipient_email: '', minimum_score: null, smtp_configured: false }) })
      if (url === '/api/notifications') return Promise.resolve({ ok: true, json: async () => [] })
      if (url === '/api/jobs/discovery-runs/latest') return Promise.resolve({ ok: true, json: async () => null })
      if (typeof url === 'string' && url.startsWith('/api/jobs/recommendations')) {
        recommendationCalls += 1
        return new Promise((resolve) => {
          if (recommendationCalls === 1) resolveFirst = resolve
          else resolveSecond = resolve
        })
      }
      return Promise.resolve({ ok: true, json: async () => jobs })
    }))
    render(<JobsPanel />)
    await waitFor(() => expect(recommendationCalls).toBe(1))

    window.dispatchEvent(new Event('focus'))
    await waitFor(() => expect(recommendationCalls).toBe(2))
    resolveSecond?.({ ok: true, json: async () => latest })
    expect(await screen.findByRole('heading', { name: 'Resposta mais recente' })).toBeInTheDocument()
    resolveFirst?.({ ok: true, json: async () => recommendations })

    await waitFor(() => expect(screen.getByRole('heading', { name: 'Resposta mais recente' })).toBeInTheDocument())
    expect(screen.queryByRole('heading', { name: 'Pessoa Desenvolvedora Backend Júnior' })).not.toBeInTheDocument()
  })
})
