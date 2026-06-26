import { create } from 'zustand'
import type {
  JobInfo,
  ProcessType,
  ReviewResult,
  RuleListResponse,
  UploadMeta,
  UserRule,
} from './types'

interface AppState {
  process: ProcessType
  setProcess: (p: ProcessType) => void

  rules: RuleListResponse | null
  setRules: (r: RuleListResponse | null) => void

  userRules: UserRule[]
  setUserRules: (rs: UserRule[]) => void

  uploads: UploadMeta[]
  setUploads: (us: UploadMeta[]) => void

  jobId: string | null
  setJobId: (id: string | null) => void

  jobStatus: JobInfo['status'] | 'idle'
  setJobStatus: (s: JobInfo['status'] | 'idle') => void

  progress: string[]
  appendProgress: (msg: string) => void
  resetProgress: () => void

  /** 三段式 loading：parse / batch / merge */
  stage: 'idle' | 'parse' | 'batch' | 'merge' | 'done' | 'failed'
  setStage: (s: AppState['stage']) => void

  result: ReviewResult | null
  setResult: (r: ReviewResult | null) => void

  /** 筛选 */
  filterRisks: Set<'高风险' | '中风险' | '低风险'>
  toggleRisk: (r: '高风险' | '中风险' | '低风险') => void
  setFilterRisks: (s: Set<'高风险' | '中风险' | '低风险'>) => void
}

export const useStore = create<AppState>((set, get) => ({
  process: 'pre_report',
  setProcess: (p) => set({ process: p }),

  rules: null,
  setRules: (r) => set({ rules: r }),

  userRules: [],
  setUserRules: (rs) => set({ userRules: rs }),

  uploads: [],
  setUploads: (us) => set({ uploads: us }),

  jobId: null,
  setJobId: (id) => set({ jobId: id }),

  jobStatus: 'idle',
  setJobStatus: (s) => set({ jobStatus: s }),

  progress: [],
  appendProgress: (msg) => set({ progress: [...get().progress, msg] }),
  resetProgress: () => set({ progress: [] }),

  stage: 'idle',
  setStage: (s) => set({ stage: s }),

  result: null,
  setResult: (r) => set({ result: r }),

  filterRisks: new Set(['高风险', '中风险', '低风险']),
  toggleRisk: (r) => {
    const s = new Set(get().filterRisks)
    if (s.has(r)) s.delete(r)
    else s.add(r)
    set({ filterRisks: s })
  },
  setFilterRisks: (s) => set({ filterRisks: s }),
}))
