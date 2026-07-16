import { useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Divider,
  Drawer,
  Form,
  Input,
  InputNumber,
  Radio,
  Select,
  Switch,
  message,
} from 'antd'
import { SaveOutlined } from '@ant-design/icons'
import {
  createRuleLibraryRule,
  updateRuleLibraryRule,
} from '../../api'
import type {
  RuleLibraryProcess,
  RuleLibraryRule,
  RuleLibraryRuleInput,
} from '../../types'
import {
  buildVisualRule,
  emptyRule,
  MATERIAL_PRESETS,
  OPERATOR_OPTIONS,
  PROCESS_OPTIONS,
  REVIEW_DIMENSIONS,
} from './config'

type Props = {
  open: boolean
  process: RuleLibraryProcess
  rule: RuleLibraryRule | null
  onClose: () => void
  onSaved: (rule: RuleLibraryRule) => void
}

function formValue(rule: RuleLibraryRule | null, process: RuleLibraryProcess) {
  const value = rule ? { ...rule } : emptyRule(process)
  const params = { ...(value.script_params || {}) } as Record<string, unknown>
  if (params.mapping) {
    params.mapping_json = JSON.stringify(params.mapping, null, 2)
  }
  if (params.conditions) {
    params.conditions_json = JSON.stringify(params.conditions, null, 2)
  }
  return { ...value, script_params: params }
}

function normalizeParams(operator: string, raw: Record<string, unknown> = {}) {
  const params: Record<string, unknown> = {}
  const copy = (...keys: string[]) => {
    keys.forEach((key) => {
      const value = raw[key]
      if (value !== undefined && value !== null && value !== '') params[key] = value
    })
  }
  switch (operator) {
    case 'enum':
      copy('values')
      break
    case 'dependent_enum':
      copy('parent_field', 'child_field')
      if (raw.mapping_json) params.mapping = JSON.parse(String(raw.mapping_json))
      break
    case 'max_length':
      copy('max_length')
      break
    case 'number_precision':
      copy('scale')
      break
    case 'date_range':
      copy('min', 'max_days')
      break
    case 'regex_match':
      copy('pattern')
      break
    case 'compare_fields':
      copy('right_field')
      break
    case 'cross_template_equal':
      copy('current_field', 'baseline_field')
      break
    case 'conditional_compare':
      params.trigger = raw.trigger || {}
      params.target = raw.target || {}
      break
    case 'material_required':
    case 'conditional_material_required':
      copy('material_label', 'file_ext')
      break
    case 'unique': {
      copy('fields', 'scope')
      const labels: Record<string, string> = {
        current_table: '当前表',
        current_process: '当前流程',
        history: '历史登记记录',
      }
      if (raw.scope) params.scope_label = labels[String(raw.scope)] || String(raw.scope)
      break
    }
    case 'reference_exists':
      copy('reference_source', 'reference_field')
      break
    case 'formula_compare':
      copy('expression', 'expected_field', 'expected_value', 'relation', 'tolerance')
      break
    case 'group_consistency':
      copy('group_by', 'consistent_fields')
      break
    case 'compound_condition':
      copy('combinator')
      if (raw.conditions_json) params.conditions = JSON.parse(String(raw.conditions_json))
      break
    default:
      break
  }
  return params
}

export default function RuleEditorDrawer({ open, process, rule, onClose, onSaved }: Props) {
  const [form] = Form.useForm<RuleLibraryRuleInput & { script_params: Record<string, unknown> }>()
  const [saving, setSaving] = useState(false)
  const watched = Form.useWatch((values) => values, form) as RuleLibraryRuleInput | undefined
  const method = watched?.review_method || 'script'
  const operator = watched?.operator || 'required'
  const ruleObject = watched?.rule_object || '字段'
  const selectedProcess = watched?.process || process
  const visualRule = useMemo(() => buildVisualRule(watched), [watched])

  useEffect(() => {
    if (!open) return
    form.resetFields()
    form.setFieldsValue(formValue(rule, process))
  }, [form, open, process, rule])

  async function handleSubmit() {
    try {
      const values = await form.validateFields()
      setSaving(true)
      const payload: RuleLibraryRuleInput = {
        ...values,
        rule_id: values.rule_id.trim(),
        rule_name: values.rule_name.trim(),
        applicable_materials: values.applicable_materials || [],
        table_name: values.table_name || '',
        field_path: values.field_path || '',
        trigger_condition: values.trigger_condition || '',
        remarks: values.remarks || '',
        version: values.version || 'V1.0',
        operator: method === 'script' ? values.operator : '',
        script_params:
          method === 'script'
            ? normalizeParams(values.operator, values.script_params)
            : {},
        special_prompt: method === 'ai' ? values.special_prompt || '' : '',
      }
      const saved = rule
        ? await updateRuleLibraryRule(rule.rule_id, payload)
        : await createRuleLibraryRule(payload)
      message.success(rule ? '规则已更新' : '规则已新增')
      onSaved(saved)
    } catch (error: any) {
      if (error?.errorFields) return
      message.error(error?.response?.data?.detail || error?.message || '保存失败')
    } finally {
      setSaving(false)
    }
  }

  function renderParameterFields() {
    switch (operator) {
      case 'enum':
        return (
          <Form.Item
            label="允许值"
            name={['script_params', 'values']}
            rules={[{ required: true, message: '请至少填写一个允许值' }]}
          >
            <Select mode="tags" tokenSeparators={[',', '，', '、']} placeholder="输入后回车，例如：是、否" />
          </Form.Item>
        )
      case 'dependent_enum':
        return (
          <>
            <div className="rule-form-grid two-cols">
              <Form.Item label="父字段" name={['script_params', 'parent_field']} rules={[{ required: true }]}>
                <Input placeholder="例如：业务分类" />
              </Form.Item>
              <Form.Item label="子字段" name={['script_params', 'child_field']} rules={[{ required: true }]}>
                <Input placeholder="例如：业务子类" />
              </Form.Item>
            </div>
            <Form.Item
              label="联动映射"
              name={['script_params', 'mapping_json']}
              rules={[
                { required: true, message: '请填写联动映射' },
                {
                  validator: async (_, value) => {
                    if (!value) return
                    try {
                      const parsed = JSON.parse(value)
                      if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') throw new Error()
                    } catch {
                      throw new Error('请输入合法JSON对象')
                    }
                  },
                },
              ]}
            >
              <Input.TextArea rows={4} placeholder='例如：{"投资类":["固定收益类","权益类"]}' />
            </Form.Item>
          </>
        )
      case 'max_length':
        return (
          <Form.Item label="最大字符数" name={['script_params', 'max_length']} rules={[{ required: true }]}>
            <InputNumber min={1} precision={0} style={{ width: '100%' }} />
          </Form.Item>
        )
      case 'number_precision':
        return (
          <Form.Item label="最大小数位" name={['script_params', 'scale']} initialValue={2} rules={[{ required: true }]}>
            <InputNumber min={0} max={12} precision={0} style={{ width: '100%' }} />
          </Form.Item>
        )
      case 'date_range':
        return (
          <div className="rule-form-grid two-cols">
            <Form.Item label="最早日期" name={['script_params', 'min']} initialValue="today">
              <Input placeholder="today 或 YYYY-MM-DD" />
            </Form.Item>
            <Form.Item label="未来最大天数" name={['script_params', 'max_days']} rules={[{ required: true }]}>
              <InputNumber min={0} precision={0} style={{ width: '100%' }} />
            </Form.Item>
          </div>
        )
      case 'regex_match':
        return (
          <Form.Item label="正则表达式" name={['script_params', 'pattern']} rules={[{ required: true }]}>
            <Input placeholder="例如：[A-Z]{2}\\d{6}" />
          </Form.Item>
        )
      case 'compare_fields':
        return (
          <Form.Item label="右侧比较字段" name={['script_params', 'right_field']} rules={[{ required: true }]}>
            <Input placeholder="当前字段不得大于该字段" />
          </Form.Item>
        )
      case 'cross_template_equal':
        return (
          <div className="rule-form-grid two-cols">
            <Form.Item label="当前字段" name={['script_params', 'current_field']}>
              <Input placeholder="留空时使用字段路径" />
            </Form.Item>
            <Form.Item label="基准字段" name={['script_params', 'baseline_field']} rules={[{ required: true }]}>
              <Input placeholder="上次登记中的字段" />
            </Form.Item>
          </div>
        )
      case 'conditional_compare':
        return (
          <>
            <div className="rule-parameter-caption">触发条件</div>
            <div className="rule-form-grid three-cols">
              <Form.Item label="条件字段" name={['script_params', 'trigger', 'field']} rules={[{ required: true }]}>
                <Input />
              </Form.Item>
              <Form.Item label="关系" name={['script_params', 'trigger', 'op']} initialValue="equals" rules={[{ required: true }]}>
                <Select options={[{ value: 'equals', label: '等于' }, { value: 'not_equals', label: '不等于' }, { value: 'required', label: '有值' }]} />
              </Form.Item>
              <Form.Item label="条件值" name={['script_params', 'trigger', 'value']}>
                <Input />
              </Form.Item>
            </div>
            <div className="rule-parameter-caption">目标校验</div>
            <div className="rule-form-grid two-cols">
              <Form.Item label="目标字段" name={['script_params', 'target', 'field']} rules={[{ required: true }]}>
                <Input />
              </Form.Item>
              <Form.Item label="校验方式" name={['script_params', 'target', 'op']} initialValue="required" rules={[{ required: true }]}>
                <Select options={[{ value: 'required', label: '必填' }, { value: 'equals', label: '等于' }, { value: 'gt', label: '大于' }, { value: 'gte', label: '大于等于' }]} />
              </Form.Item>
            </div>
          </>
        )
      case 'material_required':
      case 'conditional_material_required':
        return (
          <div className="rule-form-grid two-cols">
            <Form.Item label="材料名称" name={['script_params', 'material_label']} rules={[{ required: true }]}>
              <Input placeholder="例如：信托合同" />
            </Form.Item>
            <Form.Item label="允许扩展名" name={['script_params', 'file_ext']}>
              <Select mode="tags" tokenSeparators={[',', '，']} placeholder="例如：.pdf、.docx" />
            </Form.Item>
          </div>
        )
      case 'unique':
        return (
          <div className="rule-form-grid two-cols">
            <Form.Item label="唯一键字段" name={['script_params', 'fields']} rules={[{ required: true, message: '请填写唯一键字段' }]}>
              <Select mode="tags" tokenSeparators={[',', '，', '、']} placeholder="可填写一个或多个联合唯一字段" />
            </Form.Item>
            <Form.Item label="校验范围" name={['script_params', 'scope']} initialValue="current_table" rules={[{ required: true }]}>
              <Select options={[
                { value: 'current_table', label: '当前表' },
                { value: 'current_process', label: '当前流程' },
                { value: 'history', label: '历史登记记录' },
              ]} />
            </Form.Item>
          </div>
        )
      case 'reference_exists':
        return (
          <div className="rule-form-grid two-cols">
            <Form.Item label="参照数据源" name={['script_params', 'reference_source']} rules={[{ required: true, message: '请填写参照数据源' }]}>
              <Input placeholder="例如：信托产品登记库" />
            </Form.Item>
            <Form.Item label="参照字段" name={['script_params', 'reference_field']} rules={[{ required: true, message: '请填写参照字段' }]}>
              <Input placeholder="例如：产品编码" />
            </Form.Item>
          </div>
        )
      case 'formula_compare':
        return (
          <>
            <Form.Item label="计算公式" name={['script_params', 'expression']} rules={[{ required: true, message: '请填写计算公式' }]}>
              <Input placeholder="例如：months_between(预计到期日期, 产品成立日期)" />
            </Form.Item>
            <div className="rule-form-grid three-cols">
              <Form.Item label="比较目标字段" name={['script_params', 'expected_field']}>
                <Input placeholder="例如：信托产品期限" />
              </Form.Item>
              <Form.Item label="比较关系" name={['script_params', 'relation']} initialValue="within_tolerance" rules={[{ required: true }]}>
                <Select options={[
                  { value: 'equals', label: '等于' },
                  { value: 'lte', label: '小于等于' },
                  { value: 'gte', label: '大于等于' },
                  { value: 'within_tolerance', label: '偏差不超过' },
                ]} />
              </Form.Item>
              <Form.Item label="允许偏差" name={['script_params', 'tolerance']} initialValue={0}>
                <InputNumber min={0} style={{ width: '100%' }} />
              </Form.Item>
            </div>
          </>
        )
      case 'group_consistency':
        return (
          <div className="rule-form-grid two-cols">
            <Form.Item label="分组字段" name={['script_params', 'group_by']} rules={[{ required: true, message: '请填写分组字段' }]}>
              <Input placeholder="例如：受益权代码" />
            </Form.Item>
            <Form.Item label="组内一致字段" name={['script_params', 'consistent_fields']} rules={[{ required: true, message: '请填写需要保持一致的字段' }]}>
              <Select mode="tags" tokenSeparators={[',', '，', '、']} placeholder="输入字段后回车" />
            </Form.Item>
          </div>
        )
      case 'compound_condition':
        return (
          <>
            <Form.Item label="条件组合方式" name={['script_params', 'combinator']} initialValue="all" rules={[{ required: true }]}>
              <Select options={[{ value: 'all', label: '全部满足（且）' }, { value: 'any', label: '任一满足（或）' }]} />
            </Form.Item>
            <Form.Item
              label="条件列表"
              name={['script_params', 'conditions_json']}
              rules={[
                { required: true, message: '请填写条件列表' },
                {
                  validator: async (_, value) => {
                    if (!value) return
                    try {
                      const parsed = JSON.parse(value)
                      if (!Array.isArray(parsed) || parsed.length === 0) throw new Error()
                    } catch {
                      throw new Error('请输入非空的JSON数组')
                    }
                  },
                },
              ]}
            >
              <Input.TextArea
                rows={6}
                placeholder={'例如：\n[{"left":"受益权起始日","op":"gte","right":"产品成立日期","description":"起始日不早于成立日"}]'}
              />
            </Form.Item>
          </>
        )
      default:
        return <Alert type="info" showIcon title="该校验无需额外参数" />
    }
  }

  return (
    <Drawer
      open={open}
      title={rule ? '编辑规则' : '新增规则'}
      size="large"
      onClose={onClose}
      destroyOnHidden
      footer={
        <div className="rule-drawer-footer">
          <Button onClick={onClose}>取消</Button>
          <Button type="primary" icon={<SaveOutlined />} loading={saving} onClick={handleSubmit}>
            保存规则
          </Button>
        </div>
      }
    >
      <Form form={form} layout="vertical" requiredMark="optional" preserve>
        <div className="rule-form-grid two-cols">
          <Form.Item
            label="规则ID"
            name="rule_id"
            rules={[
              { required: true, message: '请输入规则ID' },
              { pattern: /^[A-Za-z0-9_-]{3,80}$/, message: '仅支持3-80位字母、数字、下划线和连字符' },
            ]}
          >
            <Input placeholder="例如：INITIAL-SCRIPT-001" />
          </Form.Item>
          <Form.Item label="规则名称" name="rule_name" rules={[{ required: true, message: '请输入规则名称' }]}>
            <Input placeholder="用于列表和问题标题" />
          </Form.Item>
          <Form.Item label="适用流程" name="process" rules={[{ required: true }]}>
            <Select options={PROCESS_OPTIONS} />
          </Form.Item>
          <Form.Item label="审核方式" name="review_method" rules={[{ required: true }]}>
            <Radio.Group optionType="button" buttonStyle="solid">
              <Radio.Button value="script">脚本规则</Radio.Button>
              <Radio.Button value="ai">AI规则</Radio.Button>
            </Radio.Group>
          </Form.Item>
          <Form.Item label="审查维度" name="review_dimension" rules={[{ required: true }]}>
            <Select options={REVIEW_DIMENSIONS.map((value) => ({ value, label: value }))} />
          </Form.Item>
          <Form.Item label="风险等级" name="risk_level" rules={[{ required: true }]}>
            <Select options={['高风险', '中风险', '低风险'].map((value) => ({ value, label: value }))} />
          </Form.Item>
          <Form.Item label="当前版本" name="version" rules={[{ required: true }]}>
            <Input placeholder="V1.0" />
          </Form.Item>
          <Form.Item label="启用状态" name="enabled" valuePropName="checked">
            <Switch checkedChildren="启用" unCheckedChildren="停用" />
          </Form.Item>
        </div>

        <Form.Item label="适用材料" name="applicable_materials" rules={[{ required: true, message: '请至少选择一项材料' }]}>
          <Select
            mode="tags"
            showSearch
            tokenSeparators={[',', '，', '、']}
            options={MATERIAL_PRESETS[selectedProcess].map((value) => ({ value, label: value }))}
            placeholder="选择预设材料或输入自定义材料后回车"
          />
        </Form.Item>

        <div className="rule-form-grid three-cols">
          <Form.Item label="规则对象" name="rule_object" rules={[{ required: true }]}>
            <Select options={['文件', '材料', '表', '字段', '跨材料'].map((value) => ({ value, label: value }))} />
          </Form.Item>
          <Form.Item
            label="要素分类/表名"
            name="table_name"
            rules={[{ required: ruleObject === '表', message: '表类规则必须填写表名' }]}
          >
            <Input placeholder="例如：产品基本信息" />
          </Form.Item>
          <Form.Item
            label="字段路径"
            name="field_path"
            rules={[{ required: ruleObject === '字段', message: '字段类规则必须填写字段路径' }]}
          >
            <Input placeholder="例如：产品基本信息.募集规模" />
          </Form.Item>
        </div>

        <Form.Item label="触发条件" name="trigger_condition">
          <Input placeholder="可选，例如：是否涉及关联交易=是" />
        </Form.Item>
        <Form.Item label="具体规则" name="rule_text" rules={[{ required: true, message: '请输入具体规则' }]}>
          <Input.TextArea rows={4} placeholder="描述正式的业务审核要求" />
        </Form.Item>
        <Form.Item label="审查依据" name="basis_text" rules={[{ required: true, message: '请输入审查依据' }]}>
          <Input.TextArea rows={3} placeholder="法规、业务指南、填表说明或内部口径" />
        </Form.Item>

        <Divider titlePlacement="start" plain>{method === 'script' ? '脚本规则配置' : 'AI规则配置'}</Divider>
        {method === 'script' ? (
          <>
            <Form.Item label="操作符" name="operator" rules={[{ required: true, message: '请选择操作符' }]}>
              <Select options={OPERATOR_OPTIONS} />
            </Form.Item>
            {renderParameterFields()}
            <div className="visual-rule-preview">
              <div className="visual-rule-label">可视化规则</div>
              <div className="visual-rule-text">{visualRule || '请完成字段和条件配置'}</div>
            </div>
          </>
        ) : (
          <Form.Item label="专属提示词" name="special_prompt" rules={[{ required: true, message: '请输入专属提示词' }]}>
            <Input.TextArea
              rows={8}
              placeholder={'审核目标：\n违规判定条件：\n不应判定为违规的情形：\n需要核查的材料或字段：\n必须引用的证据：\n特殊说明：'}
            />
          </Form.Item>
        )}

        <Form.Item label="备注" name="remarks">
          <Input.TextArea rows={2} placeholder="可选" />
        </Form.Item>
      </Form>
    </Drawer>
  )
}
