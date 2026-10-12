import { useEffect, useState, type FormEvent } from 'react'
import { api } from './api'
import JobsPanel from './JobsPanel'
import { emptyPreference, type ProfessionalProfile } from './types'

const emptyProfile: ProfessionalProfile = {
  id: 0, full_name: '', email: '', professional_summary: '', resume_text: '',
  skills: '', languages: '', experiences: [], education: [], preference: null,
}

function value(form: FormData, key: string) {
  return String(form.get(key) ?? '').trim()
}

export default function App() {
  const [profile, setProfile] = useState(emptyProfile)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const refresh = async () => setProfile(await api.profile())
  useEffect(() => {
    api.profile().then(setProfile).catch((reason: Error) => setError(reason.message)).finally(() => setLoading(false))
  }, [])

  async function run(action: () => Promise<unknown>, message: string) {
    setError('')
    setNotice('')
    try {
      await action()
      await refresh()
      setNotice(message)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Ocorreu um erro inesperado.')
    }
  }

  function saveProfile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    return run(() => api.saveProfile({
      full_name: value(form, 'full_name'), email: value(form, 'email'),
      professional_summary: value(form, 'professional_summary'), resume_text: value(form, 'resume_text'),
      skills: value(form, 'skills'), languages: value(form, 'languages'),
    }), 'Perfil salvo.')
  }

  function addExperience(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const element = event.currentTarget
    const form = new FormData(element)
    const isCurrent = form.has('is_current')
    return run(async () => {
      await api.addExperience({
        company: value(form, 'company'), role: value(form, 'role'), location: value(form, 'location'),
        description: value(form, 'description'), start_date: value(form, 'start_date') || null,
        end_date: isCurrent ? null : value(form, 'end_date') || null, is_current: isCurrent,
      })
      element.reset()
    }, 'Experiência adicionada.')
  }

  function addEducation(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const element = event.currentTarget
    const form = new FormData(element)
    return run(async () => {
      await api.addEducation({
        institution: value(form, 'institution'), degree: value(form, 'degree'),
        field_of_study: value(form, 'field_of_study'),
        start_year: value(form, 'start_year') ? Number(value(form, 'start_year')) : null,
        end_year: value(form, 'end_year') ? Number(value(form, 'end_year')) : null,
      })
      element.reset()
    }, 'Formação adicionada.')
  }

  function savePreferences(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    return run(() => api.savePreference({
      desired_titles: value(form, 'desired_titles'), desired_locations: value(form, 'desired_locations'),
      search_keywords: value(form, 'search_keywords'), search_areas: value(form, 'search_areas'),
      work_modes: value(form, 'work_modes'), seniority: value(form, 'seniority'),
      employment_types: value(form, 'employment_types'),
      minimum_salary: value(form, 'minimum_salary') ? Number(value(form, 'minimum_salary')) : null,
      maximum_salary: value(form, 'maximum_salary') ? Number(value(form, 'maximum_salary')) : null,
      salary_currency: value(form, 'salary_currency') || 'BRL',
      must_have: value(form, 'must_have'), excluded_criteria: value(form, 'excluded_criteria'),
    }), 'Preferências salvas.')
  }

  const preference = profile.preference ?? emptyPreference
  if (loading) return <main className="loading">Carregando seu perfil…</main>

  return (
    <main className="page-shell">
      <header className="topbar"><a className="brand" href="#top"><span className="brand-mark">J</span> job hunter</a><nav className="topnav"><a href="#profile">Perfil</a><a href="#jobs">Vagas</a></nav><span className="phase-label"><i /> Seu espaço profissional</span></header>
      <section className="hero" id="top">
        <div><p className="eyebrow">M1 · SEU PONTO DE PARTIDA</p><h1>Um perfil claro.<br /><span>Oportunidades melhores.</span></h1><p className="hero-description">Reúna sua trajetória e o que você procura. Este perfil será a base das recomendações nos próximos marcos.</p></div>
        <div className="hero-orbit" aria-hidden="true"><div className="orbit orbit-one" /><div className="orbit orbit-two" /><div className="orbit-core">J<span>H</span></div><b className="orbit-star star-one">✳</b><b className="orbit-star star-two">✳</b></div>
      </section>
      {(error || notice) && <div className={error ? 'feedback error' : 'feedback success'} role="status">{error || notice}</div>}
      <div className="content-grid">
        <div className="main-column">
          <section className="panel" id="profile">
            <div className="section-heading"><div className="section-icon">01</div><div><p className="eyebrow">QUEM É VOCÊ</p><h2>Perfil profissional</h2></div></div>
            <form onSubmit={saveProfile} className="form-grid">
              <label>Nome completo<input name="full_name" defaultValue={profile.full_name} placeholder="Como devemos chamar você?" /></label>
              <label>E-mail<input name="email" type="email" defaultValue={profile.email} placeholder="voce@email.com" /></label>
              <label className="full-width">Resumo profissional<textarea name="professional_summary" rows={3} defaultValue={profile.professional_summary} placeholder="Conte um pouco sobre sua experiência e objetivos." /></label>
              <label className="full-width">Tecnologias e competências <small>Uma por linha ou separadas por vírgula</small><textarea name="skills" rows={3} defaultValue={profile.skills} placeholder="Python, React, SQL…" /></label>
              <label className="full-width">Idiomas <small>Inclua seu nível, se quiser</small><input name="languages" defaultValue={profile.languages} placeholder="Português (nativo), Inglês (avançado)" /></label>
              <label className="full-width">Currículo em texto <small>Cole o conteúdo para manter tudo organizado</small><textarea name="resume_text" rows={5} defaultValue={profile.resume_text} placeholder="Experiências, projetos, resultados…" /></label>
              <div className="form-actions full-width"><button className="button primary" type="submit">Salvar perfil <span>↗</span></button></div>
            </form>
          </section>

          <section className="panel">
            <div className="section-heading"><div className="section-icon">02</div><div><p className="eyebrow">SUA TRAJETÓRIA</p><h2>Experiências</h2></div><span className="count-pill">{profile.experiences.length}</span></div>
            <div className="entries">
              {profile.experiences.map((item) => <article className="entry" key={item.id}><div className="entry-marker" /><div className="entry-body"><h3>{item.role}</h3><p>{item.company}{item.location ? ' · ' + item.location : ''}</p><span className="entry-date">{item.start_date || 'Início não informado'} — {item.is_current ? 'Atual' : item.end_date || 'Atual'}</span>{item.description && <p className="entry-description">{item.description}</p>}</div><button className="icon-button" type="button" aria-label={'Remover experiência ' + item.role} onClick={() => run(() => api.deleteExperience(item.id), 'Experiência removida.')}>×</button></article>)}
              {profile.experiences.length === 0 && <p className="empty-state">Sua experiência profissional aparecerá aqui.</p>}
            </div>
            <details className="add-details"><summary>＋ Adicionar experiência</summary><form onSubmit={addExperience} className="form-grid compact-form">
              <label>Cargo<input name="role" required placeholder="Desenvolvedor(a)" /></label><label>Empresa<input name="company" required placeholder="Nome da empresa" /></label>
              <label>Localização<input name="location" placeholder="Cidade, estado ou remoto" /></label><label>Início<input name="start_date" type="date" /></label>
              <label>Fim<input name="end_date" type="date" /></label><label className="check-label"><input name="is_current" type="checkbox" /> Trabalho aqui atualmente</label>
              <label className="full-width">Descrição<textarea name="description" rows={3} placeholder="Responsabilidades e resultados" /></label>
              <div className="form-actions full-width"><button className="button secondary" type="submit">Adicionar experiência</button></div>
            </form></details>
          </section>

          <section className="panel">
            <div className="section-heading"><div className="section-icon">03</div><div><p className="eyebrow">SUA FORMAÇÃO</p><h2>Educação</h2></div><span className="count-pill">{profile.education.length}</span></div>
            <div className="entries">
              {profile.education.map((item) => <article className="entry" key={item.id}><div className="entry-marker education-marker" /><div className="entry-body"><h3>{item.degree}{item.field_of_study ? ' · ' + item.field_of_study : ''}</h3><p>{item.institution}</p><span className="entry-date">{item.start_year || '—'} — {item.end_year || 'Em andamento'}</span></div><button className="icon-button" type="button" aria-label={'Remover formação ' + item.degree} onClick={() => run(() => api.deleteEducation(item.id), 'Formação removida.')}>×</button></article>)}
              {profile.education.length === 0 && <p className="empty-state">Sua formação aparecerá aqui.</p>}
            </div>
            <details className="add-details"><summary>＋ Adicionar formação</summary><form onSubmit={addEducation} className="form-grid compact-form">
              <label>Instituição<input name="institution" required placeholder="Universidade ou escola" /></label><label>Grau / curso<input name="degree" required placeholder="Bacharelado, técnico…" /></label>
              <label className="full-width">Área de estudo<input name="field_of_study" placeholder="Ciência da Computação" /></label>
              <label>Ano de início<input name="start_year" type="number" min="1900" max="2200" /></label><label>Ano de conclusão<input name="end_year" type="number" min="1900" max="2200" /></label>
              <div className="form-actions full-width"><button className="button secondary" type="submit">Adicionar formação</button></div>
            </form></details>
          </section>
        </div>
        <aside className="side-column">
          <section className="panel preferences-panel">
            <div className="section-heading"><div className="section-icon preference-icon">04</div><div><p className="eyebrow">O QUE VOCÊ PROCURA</p><h2>Preferências</h2></div></div>
            <p className="aside-intro">Defina seus próximos passos. Você pode ajustar tudo quando quiser.</p>
            <form onSubmit={savePreferences} className="stack-form">
              <label>Cargos desejados <small>Um por linha</small><textarea name="desired_titles" rows={3} defaultValue={preference.desired_titles} placeholder={'Engenheiro(a) de software\nDesenvolvedor(a) backend'} /></label>
              <label>Áreas de busca <small>Uma por linha; exemplo: Engenharia de software</small><textarea name="search_areas" rows={2} defaultValue={preference.search_areas} placeholder={'Engenharia de software\nDados'} /></label>
              <label>Palavras-chave de busca <small>Uma por linha; não usamos seu currículo ou resumo para criar consultas</small><textarea name="search_keywords" rows={3} defaultValue={preference.search_keywords} placeholder={'Python\nSQL\nBackend'} /></label>
              <label>Localizações <small>Uma por linha</small><textarea name="desired_locations" rows={2} defaultValue={preference.desired_locations} placeholder="São Paulo, SP · Remoto" /></label>
              <label>Modalidade preferida<select name="work_modes" defaultValue={preference.work_modes}><option value="">Selecione</option><option value="Remoto">Remoto</option><option value="Híbrido">Híbrido</option><option value="Presencial">Presencial</option><option value="Indiferente">Indiferente</option></select></label>
              <label>Nível desejado<select name="seniority" defaultValue={preference.seniority}><option value="">Selecione</option><option>Estágio</option><option>Júnior</option><option>Pleno</option><option>Sênior</option><option>Especialista</option><option>Liderança</option><option>Indiferente</option></select></label>
              <label>Tipo de contrato<input name="employment_types" defaultValue={preference.employment_types} placeholder="CLT, PJ, estágio…" /></label>
              <div className="salary-fields"><label>Salário mínimo<input name="minimum_salary" type="number" min="0" defaultValue={preference.minimum_salary ?? ''} placeholder="0" /></label><label>Máximo<input name="maximum_salary" type="number" min="0" defaultValue={preference.maximum_salary ?? ''} placeholder="0" /></label></div>
              <label>Moeda<input name="salary_currency" maxLength={3} defaultValue={preference.salary_currency} /></label>
              <label>Critérios essenciais <small>Uma competência ou condição por linha</small><textarea name="must_have" rows={3} defaultValue={preference.must_have} placeholder="Ex.: trabalho remoto" /></label>
              <label>O que prefere evitar<textarea name="excluded_criteria" rows={2} defaultValue={preference.excluded_criteria} placeholder="Ex.: viagens frequentes" /></label>
              <button className="button primary full-button" type="submit">Salvar preferências <span>↗</span></button>
            </form>
          </section>
          <div className="privacy-note"><span aria-hidden="true">✳</span><p><strong>Seu perfil, suas escolhas.</strong><br />Seus dados ficam armazenados localmente neste MVP.</p></div>
        </aside>
      </div>
      <JobsPanel />
      <footer className="footer"><span>job hunter <b>·</b> M0 + M7</span><span>Feito para encontrar o próximo passo.</span></footer>
    </main>
  )
}
