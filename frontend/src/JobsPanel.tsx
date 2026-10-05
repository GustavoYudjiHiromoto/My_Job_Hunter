import { useEffect, useState } from 'react'
import { api } from './api'
import type { Job } from './types'

function salaryLabel(job: Job) {
  if (job.salary_min == null && job.salary_max == null) return 'Remuneração não informada'
  const currency = job.salary_currency || 'BRL'
  const format = (amount: number) => new Intl.NumberFormat('pt-BR', {
    style: 'currency',
    currency,
    maximumFractionDigits: 0,
  }).format(amount)
  if (job.salary_min != null && job.salary_max != null) return format(job.salary_min) + ' – ' + format(job.salary_max)
  return format(job.salary_min ?? job.salary_max!)
}

function publishedLabel(value: string | null) {
  if (!value) return 'Data de publicação não informada'
  return 'Publicada em ' + new Intl.DateTimeFormat('pt-BR', { dateStyle: 'medium' }).format(new Date(value))
}

export default function JobsPanel() {
  const [jobs, setJobs] = useState<Job[]>([])
  const [loading, setLoading] = useState(true)
  const [importing, setImporting] = useState(false)
  const [importingGreenhouse, setImportingGreenhouse] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')

  async function loadJobs() {
    setError('')
    try {
      setJobs(await api.jobs())
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Erro ao carregar as vagas.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadJobs()
  }, [])

  async function importFixture() {
    setImporting(true)
    setError('')
    setMessage('')
    try {
      const result = await api.importFixture()
      await loadJobs()
      setMessage(result.created + ' novas · ' + result.updated + ' atualizadas · ' + result.total + ' no arquivo')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Erro ao importar vagas.')
    } finally {
      setImporting(false)
    }
  }

  async function importGreenhouse() {
    setImportingGreenhouse(true)
    setError('')
    setMessage('')
    try {
      const result = await api.importGreenhouse()
      await loadJobs()
      setMessage(
        'Greenhouse: ' + result.created + ' novas · ' + result.updated + ' atualizadas · ' +
        result.total + ' vagas de ' + result.boards_succeeded + '/' + result.boards_configured + ' boards',
      )
      if (result.errors.length > 0) {
        setError(result.errors.map((item) => item.board_token + ': ' + item.message).join(' · '))
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Erro ao importar vagas do Greenhouse.')
    } finally {
      setImportingGreenhouse(false)
    }
  }

  return (
    <section className="jobs-section" id="jobs">
      <div className="jobs-intro">
        <div><p className="eyebrow">M3 · FONTES DE VAGAS</p><h2>Vagas em um só lugar.</h2><p>Veja anúncios dos boards configurados e exemplos fictícios para demonstração.</p></div>
        <div className="job-actions">
          <button className="button primary" type="button" onClick={importGreenhouse} disabled={importingGreenhouse}>
            {importingGreenhouse ? 'Consultando Greenhouse…' : 'Importar Greenhouse'} <span>↗</span>
          </button>
          <button className="button secondary" type="button" onClick={importFixture} disabled={importing}>
            {importing ? 'Importando…' : 'Carregar demonstração'} <span>↓</span>
          </button>
          <small>Configure GREENHOUSE_BOARDS no ambiente do backend.</small>
        </div>
      </div>
      {message && <div className="feedback success" role="status">{message}</div>}
      {error && <div className="feedback error" role="alert">{error}</div>}
      {loading ? <p className="jobs-empty">Carregando vagas…</p> : jobs.length === 0 ? (
        <div className="jobs-empty"><span>✳</span><h3>A lista está pronta para receber vagas.</h3><p>Carregue os exemplos para ver o contrato M2 funcionando de ponta a ponta.</p></div>
      ) : (
        <div className="jobs-list">
          {jobs.map((job) => {
            const source = job.sources[0]
            return <article className="job-card" key={job.id}>
              <div className="job-card-top"><span className={source.source === 'fixture' ? 'demo-badge' : 'demo-badge greenhouse-badge'}>{source.source === 'fixture' ? 'DEMONSTRAÇÃO' : 'GREENHOUSE'}</span><span className={job.status === 'open' ? 'job-status open' : 'job-status'}>{job.status === 'open' ? 'Aberta' : job.status === 'closed' ? 'Encerrada' : 'Status desconhecido'}</span></div>
              <div className="job-card-main"><div><h3>{job.title}</h3><p className="job-company">{job.company}</p></div><a className="source-link" href={source.source_url} target="_blank" rel="noreferrer">Ver origem ↗</a></div>
              <div className="job-meta">
                {job.location && <span>⌖ {job.location}</span>}
                {job.workplace_type && <span>{job.workplace_type}</span>}
                {job.seniority && <span>{job.seniority}</span>}
                {job.employment_type && <span>{job.employment_type}</span>}
                <span>{salaryLabel(job)}</span>
              </div>
              <div className="job-card-bottom"><span>{publishedLabel(job.published_at)}</span><span>Origem: {source.source} · {source.external_id}</span></div>
              <details className="job-description"><summary>Ver descrição</summary><p>{job.description || 'A fonte não informou uma descrição para esta vaga.'}</p></details>
            </article>
          })}
        </div>
      )}
    </section>
  )
}
