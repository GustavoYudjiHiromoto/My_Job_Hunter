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

export interface GreenhouseImportResult {
  source: 'greenhouse'
  boards_configured: number
  boards_succeeded: number
  created: number
  updated: number
  total: number
  errors: Array<{ board_token: string; message: string }>
}

export const emptyPreference: Preference = {
  desired_titles: '',
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
