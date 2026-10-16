import { useState, type ChangeEvent, type FormEvent } from 'react'
import { api } from './api'
import type { ResumeImportDraft } from './types'

type Section = 'professional_summary' | 'skills' | 'languages' | 'resume_text' | 'experiences' | 'education'
const sectionLabels: Record<Section, string> = {
  professional_summary: 'Resumo profissional', skills: 'Competências', languages: 'Idiomas',
  resume_text: 'Texto do currículo', experiences: 'Experiências', education: 'Formação',
}

export default function ResumeImportPanel({ onApplied }: { onApplied: () => Promise<void> }) {
  const [file, setFile] = useState<File | null>(null)
  const [consent, setConsent] = useState(false)
  const [draft, setDraft] = useState<ResumeImportDraft | null>(null)
  const [sections, setSections] = useState<Section[]>(Object.keys(sectionLabels) as Section[])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  function updateScalar(field: 'professional_summary' | 'skills' | 'languages' | 'resume_text', value: string) {
    setDraft((current) => current && { ...current, [field]: value })
  }

  function toggleSection(section: Section) {
    setSections((current) => current.includes(section) ? current.filter((item) => item !== section) : [...current, section])
  }

  async function createPreview(event: FormEvent) {
    event.preventDefault()
    if (!file || !consent) return
    setBusy(true); setError(''); setNotice(''); setDraft(null)
    try {
      setDraft(await api.previewResumeImport(file, consent))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Não foi possível preparar a prévia.')
    } finally { setBusy(false) }
  }

  async function applyDraft() {
    if (!draft || sections.length === 0) return
    setBusy(true); setError(''); setNotice('')
    try {
      const result = await api.applyResumeImport(draft, sections)
      await onApplied()
      setNotice(`Importação salva. ${result.experiences_added} experiências e ${result.education_added} formações adicionadas.`)
      setDraft(null); setFile(null); setConsent(false)
      const input = document.getElementById('resume-pdf') as HTMLInputElement | null
      if (input) input.value = ''
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Não foi possível salvar a importação.')
    } finally { setBusy(false) }
  }

  function updateExperience(index: number, field: string, value: string | boolean | null) {
    setDraft((current) => current && ({ ...current, experiences: current.experiences.map((item, i) => i === index ? { ...item, [field]: value } : item) }))
  }
  function updateEducation(index: number, field: string, value: string | number | null) {
    setDraft((current) => current && ({ ...current, education: current.education.map((item, i) => i === index ? { ...item, [field]: value } : item) }))
  }

  return <section className="panel resume-import-panel">
    <div className="section-heading"><div className="section-icon">PDF</div><div><p className="eyebrow">IMPORTAÇÃO ASSISTIDA</p><h2>Preencher pelo currículo</h2></div></div>
    <p className="resume-import-intro">Extraímos o texto localmente e usamos o OpenRouter para montar uma prévia editável. Nada é salvo no perfil até você confirmar.</p>
    <form className="resume-upload-form" onSubmit={createPreview}>
      <label>Arquivo PDF<input id="resume-pdf" type="file" accept="application/pdf,.pdf" onChange={(event: ChangeEvent<HTMLInputElement>) => { setFile(event.target.files?.[0] ?? null); setConsent(false); setDraft(null) }} /></label>
      <label className="resume-consent"><input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} />Autorizo enviar o texto extraído do currículo ao OpenRouter para análise.</label>
      <small>O arquivo não é guardado pelo app. PDFs digitalizados que precisam de OCR não são suportados. O provedor de IA processará os dados enviados conforme a configuração da sua conta.</small>
      <button className="button secondary" type="submit" disabled={!file || !consent || busy}>{busy ? 'Analisando currículo…' : 'Gerar prévia'}</button>
    </form>
    {error && <p className="resume-feedback error" role="alert">{error}</p>}
    {notice && <p className="resume-feedback success" role="status">{notice}</p>}
    {draft && <div className="resume-draft" aria-label="Prévia editável do currículo">
      <h3>Revise e edite os dados antes de salvar</h3>
      <fieldset className="resume-sections"><legend>Seções para salvar</legend>{(Object.keys(sectionLabels) as Section[]).map((section) => <label key={section}><input type="checkbox" checked={sections.includes(section)} onChange={() => toggleSection(section)} />{sectionLabels[section]}</label>)}</fieldset>
      <label>Resumo profissional<textarea rows={3} value={draft.professional_summary} onChange={(event) => updateScalar('professional_summary', event.target.value)} /></label>
      <label>Competências<textarea rows={3} value={draft.skills} onChange={(event) => updateScalar('skills', event.target.value)} /></label>
      <label>Idiomas<textarea rows={2} value={draft.languages} onChange={(event) => updateScalar('languages', event.target.value)} /></label>
      <label>Texto extraído do currículo<textarea rows={7} value={draft.resume_text} onChange={(event) => updateScalar('resume_text', event.target.value)} /></label>
      <div className="resume-draft-list"><h4>Experiências ({draft.experiences.length})</h4>{draft.experiences.map((item, index) => <details key={index}><summary>{item.role || 'Cargo não informado'} · {item.company || 'Empresa não informada'}</summary><div className="form-grid compact-form">
        <label>Cargo<input value={item.role} onChange={(event) => updateExperience(index, 'role', event.target.value)} /></label><label>Empresa<input value={item.company} onChange={(event) => updateExperience(index, 'company', event.target.value)} /></label>
        <label>Localização<input value={item.location} onChange={(event) => updateExperience(index, 'location', event.target.value)} /></label><label>Início<input type="date" value={item.start_date ?? ''} onChange={(event) => updateExperience(index, 'start_date', event.target.value || null)} /></label>
        <label>Fim<input type="date" value={item.end_date ?? ''} onChange={(event) => updateExperience(index, 'end_date', event.target.value || null)} /></label><label className="check-label"><input type="checkbox" checked={item.is_current} onChange={(event) => updateExperience(index, 'is_current', event.target.checked)} />Atual</label>
        <label className="full-width">Descrição<textarea rows={3} value={item.description} onChange={(event) => updateExperience(index, 'description', event.target.value)} /></label>
        <button type="button" className="button secondary full-width" onClick={() => setDraft((current) => current && ({ ...current, experiences: current.experiences.filter((_, i) => i !== index) }))}>Remover esta experiência da prévia</button>
      </div></details>)}</div>
      <div className="resume-draft-list"><h4>Formação ({draft.education.length})</h4>{draft.education.map((item, index) => <details key={index}><summary>{item.degree || 'Curso não informado'} · {item.institution || 'Instituição não informada'}</summary><div className="form-grid compact-form">
        <label>Instituição<input value={item.institution} onChange={(event) => updateEducation(index, 'institution', event.target.value)} /></label><label>Grau / curso<input value={item.degree} onChange={(event) => updateEducation(index, 'degree', event.target.value)} /></label>
        <label className="full-width">Área de estudo<input value={item.field_of_study} onChange={(event) => updateEducation(index, 'field_of_study', event.target.value)} /></label>
        <label>Ano de início<input type="number" min="1900" max="2200" value={item.start_year ?? ''} onChange={(event) => updateEducation(index, 'start_year', event.target.value ? Number(event.target.value) : null)} /></label><label>Ano final<input type="number" min="1900" max="2200" value={item.end_year ?? ''} onChange={(event) => updateEducation(index, 'end_year', event.target.value ? Number(event.target.value) : null)} /></label>
        <button type="button" className="button secondary full-width" onClick={() => setDraft((current) => current && ({ ...current, education: current.education.filter((_, i) => i !== index) }))}>Remover esta formação da prévia</button>
      </div></details>)}</div>
      <button className="button primary" type="button" disabled={busy || sections.length === 0} onClick={() => void applyDraft()}>{busy ? 'Salvando…' : 'Confirmar e salvar no perfil'}</button>
    </div>}
  </section>
}
