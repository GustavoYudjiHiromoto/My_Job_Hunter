import type { Education, Experience, Preference, ProfessionalProfile } from './types'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch('/api/profile' + path, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  })
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    const detail = body?.detail
    throw new Error(typeof detail === 'string' ? detail : 'Não foi possível salvar. Confira os dados e tente novamente.')
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export const api = {
  profile: () => request<ProfessionalProfile>(''),
  saveProfile: (data: object) => request<ProfessionalProfile>('', { method: 'PUT', body: JSON.stringify(data) }),
  addExperience: (data: object) => request<Experience>('/experiences', { method: 'POST', body: JSON.stringify(data) }),
  deleteExperience: (id: number) => request<void>('/experiences/' + id, { method: 'DELETE' }),
  addEducation: (data: object) => request<Education>('/education', { method: 'POST', body: JSON.stringify(data) }),
  deleteEducation: (id: number) => request<void>('/education/' + id, { method: 'DELETE' }),
  savePreference: (data: object) => request<Preference>('/preferences', { method: 'PUT', body: JSON.stringify(data) }),
}
