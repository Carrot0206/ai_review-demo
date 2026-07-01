import { create } from 'zustand'
import type {
  BatchLog,
  Issue,
  JobInfo,
  ProcessType,
  ReviewResult,
  RuleListResponse,
  UploadMeta,
  UserRule,
} from './types'

type JobStatus = JobInfo['status'] | 'idle'
type Stage = 'idle' | 'parse' | 'batch' | 'merge' | 'done' | 'failed'

type ByProcess<T> = Record<ProcessType, T>

const PROCESSES: ProcessType[] = ['pre_report', 'initial']
function initByProcess<T>(value: T): ByProcess<T> {
  return PROCESSES.reduce((acc, p) => {
    acc[p] = value
    return acc
  }, {} as ByProcess<T>)
}

interface AppState {
  process: ProcessType
  setProcess: (p: ProcessType) => void

  rules: RuleListResponse | null
  setRules: (r: RuleListResponse | null) => void

  userRules: UserRule[]
  setUserRules: (rs: UserRule[]) => void

  uploads: UploadMeta[]
  setUploads: (us: UploadMeta[]) => void

  /** 每个流程独立保留审核结果 / 任务 / 进度,切换流程互不影响 */
  resultByProcess: ByProcess<ReviewResult | null>
  setResult: (r: ReviewResult | null, process?: ProcessType) => void

  /** O6 流式累积：每批返回时追加 issues + batch_log（done 时由最终合并结果覆盖） */
  appendBatchIssues: (
    payload: { batch: BatchLog; issues: Issue[] },
    process?: ProcessType,
  ) => void

  /** 已完成批次数（用于 X/N 进度展示） */
  batchProgressByProcess: ByProcess<{ done: number; total: number }>
  setBatchTotal: (total: number, process?: ProcessType) => void
  resetBatchProgress: (process?: ProcessType) => void

  jobIdByProcess: ByProcess<string | null>
  setJobId: (id: string | null, process?: ProcessType) => void

  jobStatusByProcess: ByProcess<JobStatus>
  setJobStatus: (s: JobStatus, process?: ProcessType) => void

  progressByProcess: ByProcess<string[]>
  appendProgress: (msg: string, process?: ProcessType) => void
  resetProgress: (process?: ProcessType) => void

  /** 三段式 loading:parse / batch / merge */
  stageByProcess: ByProcess<Stage>
  setStage: (s: Stage, process?: ProcessType) => void

  /** 材料片段裁剪开关：按流程保留，关闭时完全沿用原始全文材料逻辑 */
  materialSliceByProcess: ByProcess<boolean>
  setMaterialSlice: (enabled: boolean, process?: ProcessType) => void

  /** 清除指定流程(默认当前流程)的全部审核状态 */
  clearReviewState: (process?: ProcessType) => void

  /** 左侧字段与右侧问题卡片联动选中态 */
  selectedIssueIdByProcess: ByProcess<string | null>
  selectedIssueNonceByProcess: ByProcess<number>
  selectedFieldLocationByProcess: ByProcess<string | null>
  setSelectedIssue: (issueId: string | null, process?: ProcessType) => void
  clearSelectedIssue: (process?: ProcessType) => void
  setSelectedFieldLocation: (location: string | null, process?: ProcessType) => void

  /** 筛选(全局共享) */
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

  resultByProcess: initByProcess<ReviewResult | null>(null),
  setResult: (r, process) => {
    const key = process ?? get().process
    set((s) => ({ resultByProcess: { ...s.resultByProcess, [key]: r } }))
  },

  appendBatchIssues: ({ batch, issues }, process) => {
    const key = process ?? get().process
    set((s) => {
      const prev = s.resultByProcess[key]
      // 累积容器（首批到达时初始化）
      const base: ReviewResult =
        prev ?? {
          summary: {
            registration_type:
              key === 'pre_report' ? '事前报告' : '初始登记',
            total_issues: 0,
            high_risk_count: 0,
            medium_risk_count: 0,
            low_risk_count: 0,
          },
          issues: [],
          human_review_items: [],
          batch_logs: [],
        }

      // 按 rule_id+issue_summary 简单去重，避免短期内重复展示
      const seen = new Set(
        base.issues.map((i) => `${i.rule_id}||${i.issue_summary}`),
      )
      const merged: Issue[] = [...base.issues]
      for (let idx = 0; idx < issues.length; idx++) {
        const it = issues[idx]
        const k = `${it.rule_id}||${it.issue_summary}`
        if (seen.has(k)) continue
        seen.add(k)
        // 给临时 issue 编号，避免 React key 冲突
        merged.push({
          ...it,
          issue_id: it.issue_id || `TMP-${batch.batch_id}-${idx}`,
        })
      }

      // 重新统计 summary
      const hi = merged.filter((i) => i.risk_level === '高风险').length
      const mi = merged.filter((i) => i.risk_level === '中风险').length
      const lo = merged.filter((i) => i.risk_level === '低风险').length

      const batchLogs = [...base.batch_logs, batch]

      const next: ReviewResult = {
        ...base,
        issues: merged,
        batch_logs: batchLogs,
        summary: {
          ...base.summary,
          total_issues: merged.length,
          high_risk_count: hi,
          medium_risk_count: mi,
          low_risk_count: lo,
        },
      }

      const bp = s.batchProgressByProcess[key]
      return {
        resultByProcess: { ...s.resultByProcess, [key]: next },
        batchProgressByProcess: {
          ...s.batchProgressByProcess,
          [key]: { done: bp.done + 1, total: bp.total },
        },
      }
    })
  },

  batchProgressByProcess: initByProcess<{ done: number; total: number }>({
    done: 0,
    total: 0,
  }),
  setBatchTotal: (total, process) => {
    const key = process ?? get().process
    set((s) => ({
      batchProgressByProcess: {
        ...s.batchProgressByProcess,
        [key]: { ...s.batchProgressByProcess[key], total },
      },
    }))
  },
  resetBatchProgress: (process) => {
    const key = process ?? get().process
    set((s) => ({
      batchProgressByProcess: {
        ...s.batchProgressByProcess,
        [key]: { done: 0, total: 0 },
      },
    }))
  },

  jobIdByProcess: initByProcess<string | null>(null),
  setJobId: (id, process) => {
    const key = process ?? get().process
    set((s) => ({ jobIdByProcess: { ...s.jobIdByProcess, [key]: id } }))
  },

  jobStatusByProcess: initByProcess<JobStatus>('idle'),
  setJobStatus: (st, process) => {
    const key = process ?? get().process
    set((s) => ({ jobStatusByProcess: { ...s.jobStatusByProcess, [key]: st } }))
  },

  progressByProcess: initByProcess<string[]>([]),
  appendProgress: (msg, process) => {
    const key = process ?? get().process
    set((s) => ({
      progressByProcess: {
        ...s.progressByProcess,
        [key]: [...(s.progressByProcess[key] || []), msg],
      },
    }))
  },
  resetProgress: (process) => {
    const key = process ?? get().process
    set((s) => ({ progressByProcess: { ...s.progressByProcess, [key]: [] } }))
  },

  stageByProcess: initByProcess<Stage>('idle'),
  setStage: (st, process) => {
    const key = process ?? get().process
    set((s) => ({ stageByProcess: { ...s.stageByProcess, [key]: st } }))
  },

  materialSliceByProcess: initByProcess<boolean>(false),
  setMaterialSlice: (enabled, process) => {
    const key = process ?? get().process
    set((s) => ({
      materialSliceByProcess: {
        ...s.materialSliceByProcess,
        [key]: enabled,
      },
    }))
  },

  clearReviewState: (process) => {
    const key = process ?? get().process
    set((s) => ({
      resultByProcess: { ...s.resultByProcess, [key]: null },
      jobIdByProcess: { ...s.jobIdByProcess, [key]: null },
      jobStatusByProcess: { ...s.jobStatusByProcess, [key]: 'idle' },
      stageByProcess: { ...s.stageByProcess, [key]: 'idle' },
      progressByProcess: { ...s.progressByProcess, [key]: [] },
      batchProgressByProcess: {
        ...s.batchProgressByProcess,
        [key]: { done: 0, total: 0 },
      },
      selectedIssueIdByProcess: { ...s.selectedIssueIdByProcess, [key]: null },
      selectedIssueNonceByProcess: { ...s.selectedIssueNonceByProcess, [key]: 0 },
      selectedFieldLocationByProcess: { ...s.selectedFieldLocationByProcess, [key]: null },
    }))
  },

  selectedIssueIdByProcess: initByProcess<string | null>(null),
  selectedIssueNonceByProcess: initByProcess<number>(0),
  selectedFieldLocationByProcess: initByProcess<string | null>(null),
  setSelectedIssue: (issueId, process) => {
    const key = process ?? get().process
    set((s) => ({
      selectedIssueIdByProcess: {
        ...s.selectedIssueIdByProcess,
        [key]: issueId,
      },
      selectedIssueNonceByProcess: {
        ...s.selectedIssueNonceByProcess,
        [key]: s.selectedIssueNonceByProcess[key] + 1,
      },
    }))
  },
  clearSelectedIssue: (process) => {
    const key = process ?? get().process
    set((s) => ({
      selectedIssueIdByProcess: {
        ...s.selectedIssueIdByProcess,
        [key]: null,
      },
      selectedIssueNonceByProcess: {
        ...s.selectedIssueNonceByProcess,
        [key]: s.selectedIssueNonceByProcess[key] + 1,
      },
    }))
  },
  setSelectedFieldLocation: (location, process) => {
    const key = process ?? get().process
    set((s) => ({
      selectedFieldLocationByProcess: {
        ...s.selectedFieldLocationByProcess,
        [key]: location,
      },
    }))
  },

  filterRisks: new Set(['高风险', '中风险', '低风险']),
  toggleRisk: (r) => {
    const s = new Set(get().filterRisks)
    if (s.has(r)) s.delete(r)
    else s.add(r)
    set({ filterRisks: s })
  },
  setFilterRisks: (s) => set({ filterRisks: s }),
}))
