import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
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
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true, status: 200, json: async () => profile,
    }))
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
    await user.click(screen.getByRole('button', { name: /Salvar preferências/ }))
    await waitFor(() => expect(fetch).toHaveBeenCalledWith('/api/profile/preferences', expect.objectContaining({ method: 'PUT' })))
  })
})
