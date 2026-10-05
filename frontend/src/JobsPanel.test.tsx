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

describe('lista de vagas M2', () => {
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
      return Promise.resolve({ ok: true, json: async () => jobs })
    }))
  })

  it('mostra os dados normalizados e a origem original', async () => {
    render(<JobsPanel />)

    expect(await screen.findByRole('heading', { name: 'Pessoa Desenvolvedora Backend Júnior' })).toBeInTheDocument()
    expect(screen.getByText('Remuneração não informada')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Ver origem ↗' })).toHaveAttribute(
      'href',
      'https://example.com/jobs/demo-001',
    )
    expect(screen.getByText('DEMONSTRAÇÃO')).toBeInTheDocument()
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
})
