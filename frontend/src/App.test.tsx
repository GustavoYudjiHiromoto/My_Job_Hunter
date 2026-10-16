import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from './App'

const profile = {
  id: 1, full_name: 'Joana Lima', email: 'joana@example.com', professional_summary: '',
  resume_text: '', skills: 'Python', languages: 'Português', experiences: [], education: [], preference: null,
}

describe('perfil profissional', () => {
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn().mockImplementation((url: string, options?: RequestInit) => Promise.resolve({
      ok: true,
      status: 200,
      json: async () => url === '/api/profile/preferences' && options?.method === 'PUT'
        ? JSON.parse(String(options.body))
        : url === '/api/notifications/settings'
        ? { enabled: false, recipient_email: '', minimum_score: null, smtp_configured: false }
        : url === '/api/notifications' || url.startsWith('/api/jobs/recommendations') || url === '/api/jobs'
          ? []
          : profile,
    })))
  })

  it('carrega e exibe perfil, formação e preferências', async () => {
    render(<App />)
    expect(await screen.findByDisplayValue('Joana Lima')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Preferências' })).toBeInTheDocument()
    expect(screen.getByText('Sua formação aparecerá aqui.')).toBeInTheDocument()
  })

  it('salva preferências no endpoint do perfil', async () => {
    const user = userEvent.setup()
    render(<App />)
    await screen.findByDisplayValue('Joana Lima')
    await user.type(document.querySelector('[name="desired_titles"]') as HTMLTextAreaElement, 'Engenheira backend')
    await user.type(document.querySelector('[name="search_keywords"]') as HTMLTextAreaElement, 'Python')
    await user.type(document.querySelector('[name="search_areas"]') as HTMLTextAreaElement, 'Dados')
    await user.click(screen.getByRole('button', { name: /Salvar preferências/ }))
    await waitFor(() => expect(fetch).toHaveBeenCalledWith('/api/profile/preferences', expect.objectContaining({ method: 'PUT' })))
    const saveCall = vi.mocked(fetch).mock.calls.find(([url]) => url === '/api/profile/preferences')
    expect(JSON.parse(String(saveCall?.[1]?.body))).toMatchObject({ search_keywords: 'Python', search_areas: 'Dados' })
    const feedback = await within(screen.getByRole('heading', { name: 'Preferências' }).closest('section')!).findByRole('status')
    expect(feedback).toHaveTextContent('Preferências salvas.')
    expect(feedback.closest('.preferences-panel')).not.toBeNull()
    expect(screen.getByRole('button', { name: /Salvar preferências/ })).toBeEnabled()
  })

  it('mostra erro de salvamento junto às preferências e libera o botão', async () => {
    vi.stubGlobal('fetch', vi.fn().mockImplementation((url: string, options?: RequestInit) => Promise.resolve({
      ok: !(url === '/api/profile/preferences' && options?.method === 'PUT'),
      status: url === '/api/profile/preferences' ? 500 : 200,
      json: async () => url === '/api/profile/preferences'
        ? { detail: 'Não foi possível salvar as preferências.' }
        : url === '/api/notifications/settings'
          ? { enabled: false, recipient_email: '', minimum_score: null, smtp_configured: false }
          : url === '/api/notifications' || url.startsWith('/api/jobs/recommendations') || url === '/api/jobs'
            ? []
            : profile,
    })))
    const user = userEvent.setup()
    render(<App />)
    await screen.findByDisplayValue('Joana Lima')

    await user.click(screen.getByRole('button', { name: /Salvar preferências/ }))

    const feedback = await screen.findByRole('alert')
    expect(feedback).toHaveTextContent('Não foi possível salvar as preferências.')
    expect(feedback.closest('.preferences-panel')).not.toBeNull()
    expect(screen.getByRole('button', { name: /Salvar preferências/ })).toBeEnabled()
  })

  it('gera prévia editável somente com consentimento e salva seções confirmadas', async () => {
    let profileAfterApply = profile
    const draft = {
      professional_summary: 'Resumo extraído', skills: 'Python', languages: 'Português', resume_text: 'Texto do CV',
      experiences: [{ company: 'Acme', role: 'Dev', location: '', description: '', start_date: null, end_date: null, is_current: false }],
      education: [],
    }
    vi.stubGlobal('fetch', vi.fn().mockImplementation((url: string, options?: RequestInit) => {
      if (url === '/api/profile/resume-import/apply') {
        const body = JSON.parse(String(options?.body))
        profileAfterApply = { ...profile, professional_summary: body.draft.professional_summary }
      }
      return Promise.resolve({
        ok: true, status: 200,
        json: async () => url === '/api/profile/resume-import/preview' ? draft
          : url === '/api/profile/resume-import/apply' ? { saved_sections: ['skills'], experiences_added: 0, education_added: 0 }
            : url === '/api/jobs' || url.startsWith('/api/jobs/recommendations') || url === '/api/notifications' ? []
            : profileAfterApply,
      })
    }))
    const user = userEvent.setup()
    render(<App />)
    await screen.findByDisplayValue('Joana Lima')
    const file = new File(['%PDF-test'], 'curriculo.pdf', { type: 'application/pdf' })
    await user.upload(screen.getByLabelText('Arquivo PDF'), file)
    const previewButton = screen.getByRole('button', { name: 'Gerar prévia' })
    expect(previewButton).toBeDisabled()
    await user.click(screen.getByLabelText(/Autorizo enviar o texto extraído/))
    await user.click(previewButton)
    expect(await screen.findByRole('heading', { name: 'Revise e edite os dados antes de salvar' })).toBeInTheDocument()
    const preview = screen.getByLabelText('Prévia editável do currículo')
    const summary = within(preview).getByRole('textbox', { name: 'Resumo profissional' }) as HTMLTextAreaElement
    await user.clear(summary)
    await user.type(summary, 'Resumo revisado')
    await user.click(within(preview).getByRole('checkbox', { name: 'Competências' }))
    await user.click(screen.getByRole('button', { name: 'Confirmar e salvar no perfil' }))
    await waitFor(() => expect(fetch).toHaveBeenCalledWith('/api/profile/resume-import/apply', expect.objectContaining({ method: 'PUT' })))
    const applyCall = vi.mocked(fetch).mock.calls.find(([url]) => url === '/api/profile/resume-import/apply')
    const body = JSON.parse(String(applyCall?.[1]?.body))
    expect(body.sections).not.toContain('skills')
    expect(body.draft.professional_summary).toBe('Resumo revisado')
    expect(document.querySelector('#profile [name="professional_summary"]')).toHaveValue('Resumo revisado')
    expect(await screen.findByRole('status')).toHaveTextContent('Importação salva.')
  })
})
