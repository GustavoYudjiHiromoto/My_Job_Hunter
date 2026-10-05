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
    source: 'fixture',
    external_id: 'demo-001',
    source_url: 'https://example.com/jobs/demo-001',
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
}]

describe('recomendações de vagas M5', () => {
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn().mockImplementation((url: string, options?: RequestInit) => {
      if (url === '/api/jobs/import-fixture' && options?.method === 'POST') {
        return Promise.resolve({
          ok: true,
          json: async () => ({ created: 1, updated: 0, total: 1 }),
        })
      }
      if (url === '/api/jobs/import-greenhouse' && options?.method === 'POST') {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            source: 'greenhouse',
            boards_configured: 1,
            boards_succeeded: 1,
            created: 2,
            updated: 0,
            total: 2,
            errors: [],
          }),
        })
      }
      if (url === '/api/jobs/import-lever' && options?.method === 'POST') {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            source: 'lever',
            sites_configured: 1,
            sites_succeeded: 1,
            created: 1,
            updated: 1,
            total: 2,
            errors: [],
          }),
        })
      }
      if (url === '/api/jobs/import-runs/latest') {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            id: 7,
            requested_source: 'all',
            status: 'partial',
            started_at: '2026-10-04T12:00:00Z',
            finished_at: '2026-10-04T12:01:00Z',
            created: 3,
            updated: 1,
            total: 4,
            error: null,
            sources: [
              { source: 'greenhouse', scope: 'acme', status: 'succeeded', created: 3, updated: 1, total: 4, error: null },
              { source: 'lever', scope: 'unavailable', status: 'failed', created: 0, updated: 0, total: 0, error: 'HTTP 503' },
            ],
          }),
        })
      }
      if (typeof url === 'string' && url.startsWith('/api/jobs/recommendations')) {
        return Promise.resolve({ ok: true, json: async () => recommendations })
      }
      return Promise.resolve({ ok: true, json: async () => jobs })
    }))
  })

  it('mostra score, explicação e a origem original', async () => {
    render(<JobsPanel />)

    expect(await screen.findByRole('heading', { name: 'Pessoa Desenvolvedora Backend Júnior' })).toBeInTheDocument()
    expect(screen.getByText('Remuneração não informada')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Ver origem DEMONSTRAÇÃO ↗' })).toHaveAttribute(
      'href',
      'https://example.com/jobs/demo-001',
    )
    expect(screen.getByText('DEMONSTRAÇÃO')).toBeInTheDocument()
    expect(screen.getByText('82%')).toBeInTheDocument()
    expect(screen.getByText('Habilidade Python encontrada.')).toBeInTheDocument()
    expect(screen.getByText('Faixa salarial anunciada está fora da preferência.')).toBeInTheDocument()
  })

  it('mostra o estado agregado e o resultado de cada fonte da última coleta', async () => {
    render(<JobsPanel />)

    expect(await screen.findByLabelText('Última coleta')).toHaveTextContent('parcial')
    expect(screen.getByLabelText('Última coleta')).toHaveTextContent('greenhouse / acme: ok')
    expect(screen.getByLabelText('Última coleta')).toHaveTextContent('lever / unavailable: falhou')
  })

  it('importa o fixture e informa o resultado', async () => {
    const user = userEvent.setup()
    render(<JobsPanel />)
    await screen.findByRole('heading', { name: 'Pessoa Desenvolvedora Backend Júnior' })

    await user.click(screen.getByRole('button', { name: /Carregar demonstração/ }))

    await waitFor(() => expect(fetch).toHaveBeenCalledWith('/api/jobs/import-fixture', { method: 'POST' }))
    expect(await screen.findByRole('status')).toHaveTextContent('1 novas · 0 atualizadas · 1 no arquivo')
  })

  it('aciona a importação do Greenhouse e apresenta o resumo', async () => {
    const user = userEvent.setup()
    render(<JobsPanel />)
    await screen.findByRole('heading', { name: 'Pessoa Desenvolvedora Backend Júnior' })

    await user.click(screen.getByRole('button', { name: /Importar Greenhouse/ }))

    await waitFor(() => expect(fetch).toHaveBeenCalledWith('/api/jobs/import-greenhouse', { method: 'POST' }))
    expect(await screen.findByRole('status')).toHaveTextContent('Greenhouse: 2 novas · 0 atualizadas · 2 vagas de 1/1 boards')
  })

  it('aciona a importação do Lever e apresenta o resumo', async () => {
    const user = userEvent.setup()
    render(<JobsPanel />)
    await screen.findByRole('heading', { name: 'Pessoa Desenvolvedora Backend Júnior' })

    await user.click(screen.getByRole('button', { name: /Importar Lever/ }))

    await waitFor(() => expect(fetch).toHaveBeenCalledWith('/api/jobs/import-lever', { method: 'POST' }))
    expect(await screen.findByRole('status')).toHaveTextContent('Lever: 1 novas · 1 atualizadas · 2 vagas de 1/1 sites')
  })

  it('mostra um link para cada origem associada à vaga', async () => {
    jobs[0].sources.push({
      source: 'greenhouse',
      external_id: 'company:123',
      source_url: 'https://boards.greenhouse.io/company/jobs/123',
      collected_at: '2026-10-04T12:00:00Z',
    })

    try {
      render(<JobsPanel />)

      expect(await screen.findByRole('link', { name: 'Ver origem DEMONSTRAÇÃO ↗' })).toHaveAttribute(
        'href',
        'https://example.com/jobs/demo-001',
      )
      expect(screen.getByRole('link', { name: 'Ver origem GREENHOUSE ↗' })).toHaveAttribute(
        'href',
        'https://boards.greenhouse.io/company/jobs/123',
      )
    } finally {
      jobs[0].sources.pop()
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
      '/api/jobs/recommendations?min_score=60&location=S%C3%A3o+Paulo&workplace_type=remote&include_excluded=true',
    ))
  })
})
