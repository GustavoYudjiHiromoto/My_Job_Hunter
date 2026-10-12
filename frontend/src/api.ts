import type { Education, EmailNotification, Experience, GreenhouseImportResult, ImportRun, Job, JobRecommendation, LeverImportResult, NotificationSettings, Preference, ProfessionalProfile, RecommendationFilters } from './types'

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
  jobs: () => fetch('/api/jobs').then(async (response) => {
    if (!response.ok) throw new Error('Não foi possível carregar as vagas.')
    return response.json() as Promise<Job[]>
  }),
  recommendations: (filters: RecommendationFilters = {}) => {
    const params = new URLSearchParams()
    Object.entries(filters).forEach(([key, value]) => {
      if (value !== undefined && value !== '') params.set(key, String(value))
    })
    return fetch('/api/jobs/recommendations?' + params.toString()).then(async (response) => {
      if (!response.ok) throw new Error('Não foi possível carregar as recomendações.')
      return response.json() as Promise<JobRecommendation[]>
    })
  },
  latestImportRun: () => fetch('/api/jobs/import-runs/latest').then(async (response) => {
    if (!response.ok) throw new Error('Não foi possível consultar o histórico de coletas.')
    const result: unknown = await response.json()
    return result && typeof result === 'object' && 'id' in result && 'started_at' in result
      ? result as ImportRun
      : null
  }),
  latestDiscoveryRun: () => fetch('/api/jobs/discovery-runs/latest').then(async (response) => {
    if (!response.ok) throw new Error('Não foi possível consultar o histórico de descoberta.')
    const result: unknown = await response.json()
    return result && typeof result === 'object' && 'id' in result && 'started_at' in result
      ? result as ImportRun
      : null
  }),
  discoverJobs: () => fetch('/api/jobs/discover', { method: 'POST' }).then(async (response) => {
    if (!response.ok) {
      const body = await response.json().catch(() => null)
      throw new Error(typeof body?.detail === 'string' ? body.detail : 'Não foi possível descobrir vagas.')
    }
    return response.json() as Promise<ImportRun>
  }),
  notificationSettings: () => fetch('/api/notifications/settings').then(async (response) => {
    if (!response.ok) throw new Error('Não foi possível carregar as configurações de alertas.')
    return response.json() as Promise<NotificationSettings>
  }),
  saveNotificationSettings: (data: Pick<NotificationSettings, 'enabled' | 'recipient_email' | 'minimum_score'>) => fetch('/api/notifications/settings', {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data),
  }).then(async (response) => {
    if (!response.ok) {
      const body = await response.json().catch(() => null)
      throw new Error(typeof body?.detail === 'string' ? body.detail : 'Não foi possível salvar as configurações de alertas.')
    }
    return response.json() as Promise<NotificationSettings>
  }),
  notificationHistory: () => fetch('/api/notifications').then(async (response) => {
    if (!response.ok) throw new Error('Não foi possível carregar o histórico de e-mails.')
    return response.json() as Promise<EmailNotification[]>
  }),
  importFixture: () => fetch('/api/jobs/import-fixture', { method: 'POST' }).then(async (response) => {
    if (!response.ok) throw new Error('Não foi possível importar as vagas de demonstração.')
    return response.json() as Promise<{ created: number; updated: number; total: number }>
  }),
  importGreenhouse: () => fetch('/api/jobs/import-greenhouse', { method: 'POST' }).then(async (response) => {
    if (!response.ok) {
      const body = await response.json().catch(() => null)
      throw new Error(typeof body?.detail === 'string' ? body.detail : 'Não foi possível importar as vagas do Greenhouse.')
    }
    return response.json() as Promise<GreenhouseImportResult>
  }),
  importLever: () => fetch('/api/jobs/import-lever', { method: 'POST' }).then(async (response) => {
    if (!response.ok) {
      const body = await response.json().catch(() => null)
      throw new Error(typeof body?.detail === 'string' ? body.detail : 'Não foi possível importar as vagas do Lever.')
    }
    return response.json() as Promise<LeverImportResult>
  }),
}
