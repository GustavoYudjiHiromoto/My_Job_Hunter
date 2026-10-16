export interface Experience {
  id: number
  company: string
  role: string
  location: string
  description: string
  start_date: string | null
  end_date: string | null
  is_current: boolean
}

export interface Education {
  id: number
  institution: string
  degree: string
  field_of_study: string
  start_year: number | null
  end_year: number | null
}

export interface Preference {
  desired_titles: string
  search_keywords: string
  search_areas: string
  desired_locations: string
  work_modes: string
  seniority: string
  employment_types: string
  minimum_salary: number | null
  maximum_salary: number | null
  salary_currency: string
  must_have: string
  excluded_criteria: string
}

export interface ProfessionalProfile {
  id: number
  full_name: string
  email: string
  professional_summary: string
  resume_text: string
  skills: string
  languages: string
  experiences: Experience[]
  education: Education[]
  preference: Preference | null
}

export interface ResumeExperienceDraft {
  company: string
  role: string
  location: string
  description: string
  start_date: string | null
  end_date: string | null
  is_current: boolean
}

export interface ResumeEducationDraft {
  institution: string
  degree: string
  field_of_study: string
  start_year: number | null
  end_year: number | null
}

export interface ResumeImportDraft {
  professional_summary: string
  skills: string
  languages: string
  experiences: ResumeExperienceDraft[]
  education: ResumeEducationDraft[]
  resume_text: string
}

export interface JobSource {
  source: string
  external_id: string
  source_url: string
  collected_at: string
}

export interface Job {
  id: number
  title: string
  company: string
  description: string
  location: string | null
  workplace_type: string | null
  seniority: string | null
  employment_type: string | null
  salary_min: number | null
  salary_max: number | null
  salary_currency: string | null
  published_at: string | null
  status: string
  created_at: string
  sources: JobSource[]
}

export interface MatchCriterion {
  key: string
  label: string
  result: 'match' | 'mismatch' | 'partial' | 'unknown'
  weight: number
  points: number
  explanation: string
}

export interface JobRecommendation {
  job: Job
  score: number
  coverage: number
  excluded: boolean
  strengths: string[]
  gaps: string[]
  criteria: MatchCriterion[]
  eligibility_status?: 'eligible' | 'rejected' | 'needs_review' | null
  eligibility_reason?: string | null
  ai_analysis?: AIJobAnalysis | null
}

export interface AIJobAnalysis {
  classification: 'relevant' | 'maybe' | 'not_relevant'
  score: number
  rationale: string
  strengths: string[]
  gaps: string[]
  unknowns: string[]
  model: string
  analyzed_at: string
}

export interface AIAnalysisBatch {
  analyzed: number
  remaining: number
  failed: number
  limit: number
  items: AIAnalysisBatchItem[]
}

export interface AIAnalysisBatchItem {
  job_id: number
  title: string
  company: string
  classification: AIJobAnalysis['classification']
  score: number
  rationale: string
  strengths: string[]
  gaps: string[]
  unknowns: string[]
}

export interface RecommendationFilters {
  min_score?: number
  location?: string
  workplace_type?: string
  status?: 'open' | 'closed' | 'all'
  include_excluded?: boolean
  include_ineligible?: boolean
}

export interface GreenhouseImportResult {
  source: 'greenhouse'
  boards_configured: number
  boards_succeeded: number
  created: number
  updated: number
  total: number
  errors: Array<{ board_token: string; message: string }>
}

export interface LeverImportResult {
  source: 'lever'
  sites_configured: number
  sites_succeeded: number
  created: number
  updated: number
  total: number
  errors: Array<{ site: string; message: string }>
}

export interface ImportRunSource {
  source: 'greenhouse' | 'lever' | 'remotive' | 'adzuna' | 'jsearch' | 'jobicy'
  scope: string
  status: 'pending' | 'succeeded' | 'failed' | 'skipped'
  created: number
  updated: number
  total: number
  error: string | null
}

export interface ImportRun {
  id: number
  requested_source: 'all' | 'greenhouse' | 'lever' | 'discovery'
  status: 'pending' | 'running' | 'succeeded' | 'partial' | 'failed' | 'skipped' | 'interrupted'
  started_at: string
  finished_at: string | null
  created: number
  updated: number
  total: number
  error: string | null
  sources: ImportRunSource[]
}

export interface NotificationSettings {
  enabled: boolean
  recipient_email: string
  minimum_score: number | null
  smtp_configured: boolean
}

export interface EmailNotification {
  id: number
  import_run_id: number
  recipient_email: string
  minimum_score: number
  status: 'pending' | 'sending' | 'sent' | 'failed'
  jobs: Array<{ job_id: number; title: string; company: string; score: number; source_url: string }>
  error: string | null
  created_at: string
  sent_at: string | null
}

export const emptyPreference: Preference = {
  desired_titles: '',
  search_keywords: '',
  search_areas: '',
  desired_locations: '',
  work_modes: '',
  seniority: '',
  employment_types: '',
  minimum_salary: null,
  maximum_salary: null,
  salary_currency: 'BRL',
  must_have: '',
  excluded_criteria: '',
}
