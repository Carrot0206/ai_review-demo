import type {
  RuleLibraryDimension,
  RuleLibraryProcess,
  RuleLibraryRuleInput,
} from '../../types'

export const PROCESS_LABELS: Record<RuleLibraryProcess, string> = {
  pre_registration: '预登记',
  pre_report: '事前报告',
  initial: '初始登记',
  termination: '终止登记',
}

export const PROCESS_OPTIONS = Object.entries(PROCESS_LABELS).map(([value, label]) => ({
  value: value as RuleLibraryProcess,
  label,
}))

export const REVIEW_DIMENSIONS: RuleLibraryDimension[] = [
  '文件格式标准化',
  '法定要素完整性',
  '文本语义合规',
  '跨文件数据一致性',
  '非标资产穿透',
  '报送时效合规',
]

export const MATERIAL_PRESETS: Record<RuleLibraryProcess, string[]> = {
  pre_registration: ['预登记申报模板', '预登记申请书', '合规承诺书', '其他附件'],
  pre_report: ['事前报告申报模板', '事前报告申请书', '其他附件'],
  initial: ['初始登记申报模板', '初始登记申请书', '信托合同', '产品说明书', '其他附件'],
  termination: ['终止登记申报模板', '终止登记申请书', '清算报告', '其他附件'],
}

export const OPERATOR_OPTIONS = [
  { value: 'required', label: '必填校验' },
  { value: 'enum', label: '枚举值校验' },
  { value: 'dependent_enum', label: '联动枚举校验' },
  { value: 'max_length', label: '最大长度校验' },
  { value: 'number_precision', label: '数值精度校验' },
  { value: 'date_format', label: '日期格式校验' },
  { value: 'date_range', label: '日期范围校验' },
  { value: 'regex_match', label: '正则格式校验' },
  { value: 'sequence_contiguous', label: '序号连续性校验' },
  { value: 'compare_fields', label: '字段数值比较' },
  { value: 'cross_template_equal', label: '跨模板字段一致性' },
  { value: 'conditional_compare', label: '条件触发校验' },
  { value: 'material_required', label: '材料必交校验' },
  { value: 'conditional_material_required', label: '条件性材料必交' },
  { value: 'unique', label: '主键与重复校验' },
  { value: 'reference_exists', label: '参照数据有效性校验' },
  { value: 'formula_compare', label: '公式计算比较' },
  { value: 'group_consistency', label: '同组字段一致性' },
  { value: 'compound_condition', label: '多条件组合校验' },
]

export function emptyRule(process: RuleLibraryProcess): RuleLibraryRuleInput {
  return {
    rule_id: '',
    rule_name: '',
    process,
    review_method: 'script',
    applicable_materials: [],
    rule_object: '字段',
    table_name: '',
    field_path: '',
    review_dimension: '法定要素完整性',
    trigger_condition: '',
    rule_text: '',
    basis_text: '',
    risk_level: '中风险',
    version: 'V1.0',
    enabled: true,
    remarks: '',
    operator: 'required',
    script_params: {},
    special_prompt: '',
  }
}

export function buildVisualRule(values?: Partial<RuleLibraryRuleInput>): string {
  if (!values || values.review_method !== 'script') return ''
  const field = values.field_path || values.table_name || values.rule_name || '待选择字段'
  const params = values.script_params || {}
  let detail = '执行校验'
  switch (values.operator) {
    case 'required':
      detail = '不得为空'
      break
    case 'enum':
      detail = `只能填写：${((params.values as string[]) || []).join('、') || '规定枚举值'}`
      break
    case 'dependent_enum':
      detail = '必须满足父子字段联动枚举关系'
      break
    case 'max_length':
      detail = `长度不得超过 ${params.max_length || '指定'} 个字符`
      break
    case 'number_precision':
      detail = `最多保留 ${params.scale ?? 2} 位小数`
      break
    case 'date_format':
      detail = '必须符合 YYYY-MM-DD 日期格式'
      break
    case 'date_range':
      detail = `日期范围为 ${params.min || 'today'} 至未来 ${params.max_days || '指定'} 天`
      break
    case 'regex_match':
      detail = `必须匹配格式 ${params.pattern || '待填写'}`
      break
    case 'sequence_contiguous':
      detail = '序号必须从1开始连续递增'
      break
    case 'compare_fields':
      detail = `不得大于字段 ${params.right_field || '待选择字段'}`
      break
    case 'cross_template_equal':
      detail = `必须与基准字段 ${params.baseline_field || field} 一致`
      break
    case 'conditional_compare': {
      const trigger = (params.trigger || {}) as Record<string, string>
      const target = (params.target || {}) as Record<string, string>
      detail = `当 ${trigger.field || '条件字段'} ${trigger.op || '等于'} ${trigger.value || '条件值'} 时，${target.field || field} 执行 ${target.op || '校验'}`
      break
    }
    case 'material_required':
    case 'conditional_material_required':
      detail = `必须提交材料 ${params.material_label || values.rule_name || '指定材料'}`
      break
    case 'unique': {
      const fields = (params.fields as string[]) || [field]
      detail = `${fields.join('、')} 在 ${params.scope_label || params.scope || '当前表'} 内不得重复`
      break
    }
    case 'reference_exists':
      detail = `必须存在于 ${params.reference_source || '指定参照数据源'}${params.reference_field ? ` 的 ${params.reference_field}` : ''} 中`
      break
    case 'formula_compare':
      detail = `按公式 ${params.expression || '指定公式'} 计算并与 ${params.expected_field || params.expected_value || '目标值'} 比较${params.tolerance !== undefined && params.tolerance !== '' ? `，允许偏差 ${params.tolerance}` : ''}`
      break
    case 'group_consistency': {
      const consistentFields = (params.consistent_fields as string[]) || [field]
      detail = `按 ${params.group_by || '分组字段'} 分组时，${consistentFields.join('、')} 必须保持一致`
      break
    }
    case 'compound_condition': {
      const conditions = (params.conditions as Array<string | Record<string, string>>) || []
      const labels = conditions.slice(0, 3).map((condition) => {
        if (typeof condition === 'string') return condition
        return condition.description || `${condition.left || ''} ${condition.op || ''} ${condition.right || ''}`.trim()
      }).filter(Boolean)
      detail = labels.join(params.combinator === 'any' ? ' 或 ' : ' 且 ') || '执行多条件组合校验'
      break
    }
  }
  const prefix = values.trigger_condition ? `当 ${values.trigger_condition} 时，` : ''
  return `${prefix}${field} ${detail}`
}
