import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { api } from './api'
import type { Job, JobRecommendation, RecommendationFilters } from './types'

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

function sourceLabel(source: string) {
  return source === 'fixture' ? 'DEMONSTRAÇÃO' : source.toUpperCase()
}

export default function JobsPanel() {
  const [recommendations, setRecommendations] = useState<JobRecommendation[]>([])
  const [loading, setLoading] = useState(true)
  const [importing, setImporting] = useState(false)
  const [importingGreenhouse, setImportingGreenhouse] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [location, setLocation] = useState('')
  const [workplaceType, setWorkplaceType] = useState('')
  const [minScore, setMinScore] = useState('0')
  const [includeExcluded, setIncludeExcluded] = useState(true)
  const appliedFilters = useRef<RecommendationFilters>({})

  const loadRecommendations = useCallback(async (filters: RecommendationFilters = appliedFilters.current) => {
    setError('')
    try {
      setRecommendations(await api.recommendations(filters))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Erro ao carregar recomendações.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadRecommendations({})
  }, [loadRecommendations])

  async function applyFilters(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const filters: RecommendationFilters = {
      min_score: Number(minScore) || 0,
      location: location.trim() || undefined,
      workplace_type: workplaceType || undefined,
      include_excluded: includeExcluded,
    }
    appliedFilters.current = filters
    setLoading(true)
    await loadRecommendations(filters)
  }

  async function importFixture() {
    setImporting(true)
    setError('')
    setMessage('')
    try {
      const result = await api.importFixture()
      await loadRecommendations()
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
      await loadRecommendations()
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
        <div><p className="eyebrow">M5 · COMPATIBILIDADE</p><h2>Vagas recomendadas para você.</h2><p>Uma análise explicável compara suas preferências e habilidades com cada anúncio.</p></div>
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
      <form className="recommendation-filters" onSubmit={(event) => void applyFilters(event)}>
        <label>Score mínimo<input type="number" min="0" max="100" value={minScore} onChange={(event) => setMinScore(event.target.value)} /></label>
        <label>Localização<input value={location} onChange={(event) => setLocation(event.target.value)} placeholder="Ex.: São Paulo" /></label>
        <label>Modalidade<select value={workplaceType} onChange={(event) => setWorkplaceType(event.target.value)}><option value="">Todas</option><option value="remote">Remota</option><option value="hybrid">Híbrida</option><option value="onsite">Presencial</option></select></label>
        <label className="filter-check"><input type="checkbox" checked={includeExcluded} onChange={(event) => setIncludeExcluded(event.target.checked)} />Incluir vagas com critérios excluídos</label>
        <button className="button secondary" type="submit">Aplicar filtros</button>
      </form>
      {loading ? <p className="jobs-empty">Calculando compatibilidade…</p> : recommendations.length === 0 ? (
        <div className="jobs-empty"><span>✳</span><h3>Nenhuma recomendação para estes filtros.</h3><p>Importe vagas ou ajuste os filtros e suas preferências.</p></div>
      ) : (
        <div className="jobs-list">
          {recommendations.map((recommendation) => {
            const { job } = recommendation
            const source = job.sources[0]
            return <article className={'job-card recommendation-card' + (recommendation.excluded ? ' excluded' : '')} key={job.id}>
              <div className="job-card-top">
                <div className="job-source-badges">{job.sources.map((item) => <span key={item.source + item.external_id} className={item.source === 'fixture' ? 'demo-badge' : 'demo-badge greenhouse-badge'}>{sourceLabel(item.source)}</span>)}</div>
                <span className={recommendation.excluded ? 'job-status excluded-label' : 'match-score'}>{recommendation.excluded ? 'Critério excluído' : `${recommendation.score}%`}</span>
              </div>
              <div className="job-card-main"><div><h3>{job.title}</h3><p className="job-company">{job.company}</p></div></div>
              <div className="recommendation-coverage">Cobertura da análise: {recommendation.coverage}%</div>
              <div className="job-meta">
                {job.location && <span>⌖ {job.location}</span>}
                {job.workplace_type && <span>{job.workplace_type}</span>}
                {job.seniority && <span>{job.seniority}</span>}
                {job.employment_type && <span>{job.employment_type}</span>}
                <span>{salaryLabel(job)}</span>
              </div>
              <div className="match-explanation">
                <div><strong>Pontos fortes</strong>{recommendation.strengths.length ? <ul>{recommendation.strengths.map((item) => <li key={item}>{item}</li>)}</ul> : <p>Não identificados com os dados disponíveis.</p>}</div>
                <div><strong>Gaps e incertezas</strong>{recommendation.gaps.length ? <ul>{recommendation.gaps.map((item) => <li key={item}>{item}</li>)}</ul> : <p>Nenhum gap identificado.</p>}</div>
              </div>
              <details className="job-description"><summary>Ver critérios da análise</summary><ul className="criteria-list">{recommendation.criteria.map((criterion) => <li key={criterion.key}><b>{criterion.label}</b> · {criterion.points}/{criterion.weight} pts · {criterion.result === 'unknown' ? 'Sem dados' : criterion.result === 'match' ? 'Compatível' : criterion.result === 'partial' ? 'Parcial' : 'Divergente'} · {criterion.explanation}</li>)}</ul></details>
              <div className="job-card-bottom"><span>{publishedLabel(job.published_at)}</span><span>{job.sources.length > 1 ? `${job.sources.length} origens` : `Origem: ${source.source} · ${source.external_id}`}</span></div>
              <div className="job-source-links">{job.sources.map((item) => <a key={item.source + item.external_id} className="source-link" href={item.source_url} target="_blank" rel="noreferrer">Ver origem {sourceLabel(item.source)} ↗</a>)}</div>
              <details className="job-description"><summary>Ver descrição</summary><p>{job.description || 'A fonte não informou uma descrição para esta vaga.'}</p></details>
            </article>
          })}
        </div>
      )}
    </section>
  )
}
