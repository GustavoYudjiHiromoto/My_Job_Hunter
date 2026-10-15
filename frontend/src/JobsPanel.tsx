import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { api } from './api'
import type { EmailNotification, ImportRun, Job, JobRecommendation, NotificationSettings, RecommendationFilters } from './types'

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

const DISCOVERY_SOURCES = new Set(['remotive', 'jsearch', 'jobicy'])

function importStatus(status: ImportRun['status']) {
  return ({
    pending: 'aguardando',
    running: 'em andamento',
    succeeded: 'concluída',
    partial: 'parcial',
    failed: 'falhou',
    skipped: 'ignorada: outra coleta estava ativa',
    interrupted: 'interrompida',
  })[status]
}

function sourceStatus(status: ImportRun['sources'][number]['status']) {
  return ({ pending: 'pendente', succeeded: 'ok', failed: 'falhou', skipped: 'ignorada' })[status]
}

export default function JobsPanel() {
  const [recommendations, setRecommendations] = useState<JobRecommendation[]>([])
  const [latestDiscoveryRun, setLatestDiscoveryRun] = useState<ImportRun | null>(null)
  const [loading, setLoading] = useState(true)
  const [discoveringJobs, setDiscoveringJobs] = useState(false)
  const [analyzingAI, setAnalyzingAI] = useState(false)
  const [aiFilter, setAiFilter] = useState('all')
  const [aiMessage, setAiMessage] = useState('')
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [location, setLocation] = useState('')
  const [workplaceType, setWorkplaceType] = useState('')
  const [minScore, setMinScore] = useState('0')
  const [includeExcluded, setIncludeExcluded] = useState(true)
  const [includeIneligible, setIncludeIneligible] = useState(false)
  const [notificationSettings, setNotificationSettings] = useState<NotificationSettings>({ enabled: false, recipient_email: '', minimum_score: null, smtp_configured: false })
  const [notificationHistory, setNotificationHistory] = useState<EmailNotification[]>([])
  const [notificationScore, setNotificationScore] = useState('')
  const [savingNotifications, setSavingNotifications] = useState(false)
  const [notificationMessage, setNotificationMessage] = useState('')
  const appliedFilters = useRef<RecommendationFilters>({})
  const recommendationsRequest = useRef(0)

  const loadRecommendations = useCallback(async (filters: RecommendationFilters = appliedFilters.current) => {
    const requestId = ++recommendationsRequest.current
    setError('')
    try {
      const result = await api.recommendations(filters)
      if (requestId === recommendationsRequest.current) setRecommendations(result)
    } catch (reason) {
      if (requestId === recommendationsRequest.current) {
        setError(reason instanceof Error ? reason.message : 'Erro ao carregar recomendações.')
      }
    } finally {
      if (requestId === recommendationsRequest.current) setLoading(false)
    }
  }, [])

  const loadLatestDiscoveryRun = useCallback(async () => {
    try {
      setLatestDiscoveryRun(await api.latestDiscoveryRun())
    } catch {
      setLatestDiscoveryRun(null)
    }
  }, [])

  const loadNotifications = useCallback(async () => {
    try {
      const [settings, history] = await Promise.all([api.notificationSettings(), api.notificationHistory()])
      setNotificationSettings(settings)
      setNotificationScore(settings.minimum_score == null ? '' : String(settings.minimum_score))
      setNotificationHistory(history)
    } catch (reason) {
      setNotificationMessage(reason instanceof Error ? reason.message : 'Erro ao carregar alertas.')
    }
  }, [])

  useEffect(() => {
    void loadRecommendations({})
  }, [loadRecommendations])

  useEffect(() => {
    void loadLatestDiscoveryRun()
  }, [loadLatestDiscoveryRun])

  useEffect(() => {
    void loadNotifications()
  }, [loadNotifications])

  useEffect(() => {
    if (!discoveringJobs) return
    const interval = window.setInterval(() => {
      if (document.visibilityState === 'visible') {
        void loadLatestDiscoveryRun()
      }
    }, 1500)
    return () => window.clearInterval(interval)
  }, [discoveringJobs, loadLatestDiscoveryRun])

  useEffect(() => {
    function refreshWhenVisible() {
      if (document.visibilityState === 'visible') {
        void loadLatestDiscoveryRun()
        void loadRecommendations()
        void loadNotifications()
      }
    }
    window.addEventListener('focus', refreshWhenVisible)
    document.addEventListener('visibilitychange', refreshWhenVisible)
    return () => {
      window.removeEventListener('focus', refreshWhenVisible)
      document.removeEventListener('visibilitychange', refreshWhenVisible)
    }
  }, [loadLatestDiscoveryRun, loadRecommendations, loadNotifications])

  async function discoverJobs() {
    setDiscoveringJobs(true)
    setError('')
    setMessage('')
    setLatestDiscoveryRun(null)
    try {
      const run = await api.discoverJobs()
      setLatestDiscoveryRun(run)
      await loadRecommendations()
      if (run.total === 0) {
        setMessage('Busca concluída sem vagas retornadas. Confira abaixo o estado e o motivo de cada fonte.')
      } else if (run.status === 'succeeded') {
        setMessage(`Descoberta concluída: ${run.created} novas, ${run.updated} atualizadas.`)
      } else if (run.status === 'partial') {
        setMessage(`Descoberta parcialmente concluída: ${run.created} novas, ${run.updated} atualizadas.`)
      } else {
        setError(run.error || 'A descoberta não foi concluída.')
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Erro ao descobrir vagas.')
      await loadLatestDiscoveryRun()
    } finally {
      setDiscoveringJobs(false)
    }
  }

  async function analyzeJobsWithAI() {
    setAnalyzingAI(true)
    setAiMessage('')
    setError('')
    try {
      const result = await api.analyzeJobsWithAI()
      await loadRecommendations()
      const failureMessage = result.failed ? ` ${result.failed} falharam e podem ser tentadas novamente.` : ''
      const remainingMessage = result.remaining ? ` Restam ${result.remaining} para próximos lotes.` : ''
      setAiMessage(`${result.analyzed} analisadas com IA.${remainingMessage}${failureMessage}`)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Erro ao analisar vagas com IA.')
    } finally {
      setAnalyzingAI(false)
    }
  }

  async function saveNotifications(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setSavingNotifications(true)
    setNotificationMessage('')
    try {
      const settings = await api.saveNotificationSettings({
        enabled: notificationSettings.enabled,
        recipient_email: notificationSettings.recipient_email.trim(),
        minimum_score: notificationScore === '' ? null : Number(notificationScore),
      })
      setNotificationSettings(settings)
      setNotificationScore(settings.minimum_score == null ? '' : String(settings.minimum_score))
      setNotificationMessage('Configurações de alertas salvas.')
    } catch (reason) {
      setNotificationMessage(reason instanceof Error ? reason.message : 'Erro ao salvar configurações.')
    } finally {
      setSavingNotifications(false)
    }
  }

  async function applyFilters(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const filters: RecommendationFilters = {
      min_score: Number(minScore) || 0,
      location: location.trim() || undefined,
      workplace_type: workplaceType || undefined,
      include_excluded: includeExcluded,
      include_ineligible: includeIneligible,
    }
    appliedFilters.current = filters
    setLoading(true)
    await loadRecommendations(filters)
  }

  const visibleRecommendations = recommendations.filter((recommendation) =>
    recommendation.job.sources.some((source) => DISCOVERY_SOURCES.has(source.source)),
  )
  const filteredRecommendations = visibleRecommendations.filter((recommendation) => {
    const assessment = recommendation.ai_analysis
    if (aiFilter === 'unanalysed') return !assessment
    return aiFilter === 'all' || assessment?.classification === aiFilter
  })

  return (
    <section className="jobs-section" id="jobs">
      <div className="jobs-intro">
        <div><p className="eyebrow">M5 · COMPATIBILIDADE</p><h2>Vagas recomendadas para você.</h2><p>O score atual é determinístico. A avaliação por IA é opcional, separada e pode errar.</p></div>
        <div className="job-actions">
          <button className="button primary" type="button" onClick={discoverJobs} disabled={discoveringJobs}>
            {discoveringJobs ? 'Buscando vagas…' : 'Descobrir vagas'} <span>↗</span>
          </button>
          <button className="button secondary" type="button" onClick={analyzeJobsWithAI} disabled={analyzingAI}>
            {analyzingAI ? 'Analisando…' : 'Analisar próximas 10 com IA'}
          </button>
          <small>A análise é manual, pode consumir créditos da API e não altera o score atual.</small>
        </div>
      </div>
      {discoveringJobs && <div className="discovery-progress" role="status" aria-live="polite">
        <strong>Busca em andamento</strong>
        <span>Consultando Remotive, JSearch (se configurado e dentro do limite) e Jobicy (respeitando o intervalo entre consultas).</span>
        {latestDiscoveryRun?.status === 'running' && <span>Execução #{latestDiscoveryRun.id}: {latestDiscoveryRun.sources.length
          ? latestDiscoveryRun.sources.map((item) => `${item.source}: ${sourceStatus(item.status)}`).join(' · ')
          : 'preparando as fontes'}.</span>}
        {!latestDiscoveryRun && <span>Preparando e registrando a execução…</span>}
      </div>}
      {latestDiscoveryRun && <div className="import-run-summary" aria-label="Última descoberta">
        <div><strong>Última descoberta #{latestDiscoveryRun.id}</strong><span>{importStatus(latestDiscoveryRun.status)} · {new Intl.DateTimeFormat('pt-BR', { dateStyle: 'short', timeStyle: 'short' }).format(new Date(latestDiscoveryRun.started_at))}</span></div>
        <span>{latestDiscoveryRun.created} novas · {latestDiscoveryRun.updated} atualizadas · {latestDiscoveryRun.total} resultados</span>
        {latestDiscoveryRun.sources.map((item) => <span key={item.source + item.scope} className={item.status === 'failed' ? 'source-run failed' : 'source-run'}>{item.source} / {item.scope}: {sourceStatus(item.status)}{item.error ? ` — ${item.error}` : ''}</span>)}
        {latestDiscoveryRun.error && <span className="source-run failed">{latestDiscoveryRun.error}</span>}
      </div>}
      <section className="notification-panel" aria-labelledby="notification-heading">
        <div><p className="eyebrow">M8 · ALERTAS</p><h3 id="notification-heading">Receba novas vagas por e-mail.</h3><p>O alerta considera apenas vagas novas dessa coleta que atinjam o score configurado.</p></div>
        <form className="notification-form" onSubmit={(event) => void saveNotifications(event)}>
          <label className="notification-toggle"><input type="checkbox" checked={notificationSettings.enabled} onChange={(event) => setNotificationSettings({ ...notificationSettings, enabled: event.target.checked })} />Ativar alertas por e-mail</label>
          <label>E-mail de destino<input type="email" maxLength={254} value={notificationSettings.recipient_email} onChange={(event) => setNotificationSettings({ ...notificationSettings, recipient_email: event.target.value })} placeholder="voce@exemplo.com" /></label>
          <label>Score mínimo (0–100)<input type="number" min="0" max="100" value={notificationScore} onChange={(event) => setNotificationScore(event.target.value)} placeholder="Defina o limite" /></label>
          <button className="button secondary" type="submit" disabled={savingNotifications}>{savingNotifications ? 'Salvando…' : 'Salvar alertas'}</button>
        </form>
        <p className="smtp-hint">{notificationSettings.smtp_configured ? 'SMTP configurado no backend.' : 'Para envio, configure SMTP_HOST, SMTP_PORT, SMTP_FROM e opcionalmente SMTP_USERNAME/SMTP_PASSWORD no ambiente do backend. As credenciais não são exibidas na interface.'}</p>
        {notificationMessage && <p className="notification-message" role="status">{notificationMessage}</p>}
        <div className="notification-history"><strong>Histórico de envios</strong>{notificationHistory.length === 0 ? <p>Nenhum e-mail enviado ainda.</p> : notificationHistory.map((item) => <div className="notification-entry" key={item.id}><span>{item.status === 'sent' ? 'Enviado' : item.status === 'failed' ? 'Falhou' : item.status} · {item.jobs.length} vaga(s) · score mínimo {item.minimum_score}</span><small>{new Intl.DateTimeFormat('pt-BR', { dateStyle: 'short', timeStyle: 'short' }).format(new Date(item.created_at))} · {item.recipient_email}</small>{item.error && <small className="notification-error">{item.error}</small>}<ul>{item.jobs.map((job) => <li key={job.job_id}><a href={job.source_url} target="_blank" rel="noreferrer">{job.title} — {job.company}</a> ({job.score}%)</li>)}</ul></div>)}</div>
      </section>
      {message && <div className="feedback success" role="status">{message}</div>}
      {aiMessage && <div className="feedback success" role="status">{aiMessage}</div>}
      {error && <div className="feedback error" role="alert">{error}</div>}
      <form className="recommendation-filters" onSubmit={(event) => void applyFilters(event)}>
        <label>Score mínimo<input type="number" min="0" max="100" value={minScore} onChange={(event) => setMinScore(event.target.value)} /></label>
        <label>Localização<input value={location} onChange={(event) => setLocation(event.target.value)} placeholder="Ex.: São Paulo" /></label>
        <label>Modalidade<select value={workplaceType} onChange={(event) => setWorkplaceType(event.target.value)}><option value="">Todas</option><option value="remote">Remota</option><option value="hybrid">Híbrida</option><option value="onsite">Presencial</option></select></label>
        <label className="filter-check"><input type="checkbox" checked={includeExcluded} onChange={(event) => setIncludeExcluded(event.target.checked)} />Incluir vagas com critérios excluídos</label>
        <label className="filter-check"><input type="checkbox" checked={includeIneligible} onChange={(event) => setIncludeIneligible(event.target.checked)} />Incluir vagas fora do pré-filtro (para revisão)</label>
        <label>Relevância IA<select value={aiFilter} onChange={(event) => setAiFilter(event.target.value)}><option value="all">Todas</option><option value="relevant">Relevantes</option><option value="maybe">Talvez</option><option value="not_relevant">Pouco relevantes</option><option value="unanalysed">Ainda não analisadas</option></select></label>
        <button className="button secondary" type="submit">Aplicar filtros</button>
      </form>
      {loading ? <p className="jobs-empty">Calculando compatibilidade…</p> : filteredRecommendations.length === 0 ? (
        <div className="jobs-empty"><span>✳</span><h3>Nenhuma vaga elegível para estes filtros.</h3><p>As vagas coletadas continuam salvas. Confira se localização, modalidade e área estão configuradas como deseja ou marque “Incluir vagas fora do pré-filtro” para ver os motivos. Anúncios antigos de Greenhouse, Lever e demonstração permanecem no histórico.</p></div>
      ) : (
        <div className="jobs-list">
          {filteredRecommendations.map((recommendation) => {
            const { job } = recommendation
            const sources = job.sources.filter((item) => DISCOVERY_SOURCES.has(item.source))
            const source = sources[0]
            return <article className={'job-card recommendation-card' + (recommendation.excluded ? ' excluded' : '')} key={job.id}>
              <div className="job-card-top">
                <div className="job-source-badges">{sources.map((item) => <span key={item.source + item.external_id} className="source-badge">{sourceLabel(item.source)}</span>)}</div>
                <span className={recommendation.excluded ? 'job-status excluded-label' : 'match-score'}>{recommendation.excluded ? 'Critério excluído' : `${recommendation.score}%`}</span>
              </div>
              <div className="job-card-main"><div><h3>{job.title}</h3><p className="job-company">{job.company}</p></div></div>
              <div className="recommendation-coverage">Cobertura da análise: {recommendation.coverage}%</div>
              {recommendation.ai_analysis && <section className="ai-assessment" aria-label="Avaliação de relevância por IA">
                <div><strong>Relevância IA · {recommendation.ai_analysis.score}%</strong><span className={'ai-classification ' + recommendation.ai_analysis.classification}>{({ relevant: 'Relevante', maybe: 'Talvez relevante', not_relevant: 'Pouco relevante' })[recommendation.ai_analysis.classification]}</span></div>
                <p>{recommendation.ai_analysis.rationale}</p>
                {recommendation.ai_analysis.strengths.length > 0 && <p><b>Compatibilidades:</b> {recommendation.ai_analysis.strengths.join(' · ')}</p>}
                {recommendation.ai_analysis.gaps.length > 0 && <p><b>Lacunas:</b> {recommendation.ai_analysis.gaps.join(' · ')}</p>}
                {recommendation.ai_analysis.unknowns.length > 0 && <p><b>Não informado:</b> {recommendation.ai_analysis.unknowns.join(' · ')}</p>}
              </section>}
              {recommendation.eligibility_status && recommendation.eligibility_status !== 'eligible' && <p className="feedback warning">{recommendation.eligibility_status === 'needs_review' ? 'Precisa de revisão' : 'Fora do pré-filtro'}: {recommendation.eligibility_reason}</p>}
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
              <div className="job-card-bottom"><span>{publishedLabel(job.published_at)}</span><span>{sources.length > 1 ? `${sources.length} origens` : `Origem: ${source.source} · ${source.external_id}`}</span></div>
              <div className="job-source-links">{sources.map((item) => <a key={item.source + item.external_id} className="source-link" href={item.source_url} target="_blank" rel="noreferrer">Ver origem {sourceLabel(item.source)} ↗</a>)}</div>
              <details className="job-description"><summary>Ver descrição</summary><p>{job.description || 'A fonte não informou uma descrição para esta vaga.'}</p></details>
            </article>
          })}
        </div>
      )}
    </section>
  )
}
