import { useEffect, useMemo, useState } from 'react'
import {
  Button,
  Collapse,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Switch,
  Tag,
  Tooltip,
  Upload,
  message,
} from 'antd'
import {
  DeleteOutlined,
  EditOutlined,
  InboxOutlined,
  PlusOutlined,
  RocketOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import {
  createUserRule,
  deleteUpload,
  deleteUserRule,
  getRules,
  listUploads,
  loadSamples,
  startReview,
  subscribeReviewStream,
  updateUserRule,
  uploadFile,
} from '../api'
import { useStore } from '../store'
import type { RiskLevel } from '../types'

const { Dragger } = Upload

const REVIEW_DIMENSION_OPTIONS = [
  { value: '用户新增规则', label: '用户新增规则' },
  { value: '登记必填要素规则库', label: '登记必填要素规则库' },
  { value: '格式模板规则库', label: '格式模板规则库' },
  { value: '跨材料数据逻辑校验库', label: '跨材料数据逻辑校验库' },
  { value: '监管合规红线规则库', label: '监管合规红线规则库' },
  { value: '业务退回/整改案例库', label: '业务退回/整改案例库' },
  { value: '审查风险分级规则库', label: '审查风险分级规则库' },
]

const CHECK_TYPE_OPTIONS = [
  { value: '语义条件判断', label: '语义条件判断' },
  { value: '条件性必填', label: '条件性必填' },
  { value: '跨材料一致性', label: '跨材料一致性' },
  { value: '监管口径符合性', label: '监管口径符合性' },
  { value: '字段类型格式', label: '字段类型格式' },
  { value: '签字盖章存在性', label: '签字盖章存在性' },
  { value: '风险分级', label: '风险分级' },
  { value: '其他', label: '其他' },
]

function fmtSize(b: number) {
  if (b < 1024) return b + ' B'
  if (b < 1024 * 1024) return (b / 1024).toFixed(1) + ' KB'
  return (b / 1024 / 1024).toFixed(1) + ' MB'
}

export default function LeftPanel() {
  const process = useStore((s) => s.process)
  const rules = useStore((s) => s.rules)
  const userRules = useStore((s) => s.userRules)
  const uploads = useStore((s) => s.uploads)
  const setUploads = useStore((s) => s.setUploads)
  const setUserRules = useStore((s) => s.setUserRules)
  const setRules = useStore((s) => s.setRules)

  const setJobId = useStore((s) => s.setJobId)
  const setJobStatus = useStore((s) => s.setJobStatus)
  const setStage = useStore((s) => s.setStage)
  const appendProgress = useStore((s) => s.appendProgress)
  const resetProgress = useStore((s) => s.resetProgress)
  const setResult = useStore((s) => s.setResult)
  const appendBatchIssues = useStore((s) => s.appendBatchIssues)
  const setBatchTotal = useStore((s) => s.setBatchTotal)
  const resetBatchProgress = useStore((s) => s.resetBatchProgress)
  const jobStatus = useStore((s) => s.jobStatusByProcess[s.process])
  const materialSliceEnabled = useStore((s) => s.materialSliceByProcess[s.process])
  const setMaterialSlice = useStore((s) => s.setMaterialSlice)

  const [creating, setCreating] = useState(false)
  // 正在编辑的规则 id；为 null 表示新增模式
  const [editingRuleId, setEditingRuleId] = useState<string | null>(null)
  const [form] = Form.useForm()

  // 切换流程时：关闭 Modal、重置表单内容
  useEffect(() => {
    setCreating(false)
    setEditingRuleId(null)
    form.resetFields()
  }, [process, form])

  const builtinRules = useMemo(() => rules?.rules || [], [rules])
  const processLabel = process === 'pre_report' ? '事前报告' : '初始登记'

  // 适用材料：按流程不同
  const materialOptions = useMemo(() => {
    if (process === 'pre_report') {
      return [
        { value: '申报模板', label: '申报模板' },
        { value: '申请书', label: '申请书' },
        {
          value: '法律、行政法规、国家金融监督管理总局要求的其他文件',
          label: '法律、行政法规、国家金融监督管理总局要求的其他文件',
        },
      ]
    }
    return [
      { value: '申报模板', label: '申报模板' },
      { value: '申请书', label: '申请书' },
      { value: '信托文件样本', label: '信托文件样本' },
      {
        value: '法律、行政法规、国家金融监督管理总局要求的其他文件',
        label: '法律、行政法规、国家金融监督管理总局要求的其他文件',
      },
    ]
  }, [process])

  // 当前流程下的上传文件（演示版：全部都展示）
  const currentUploads = uploads

  async function refreshUploads() {
    const list = await listUploads(process)
    setUploads(list)
  }
  async function refreshRules() {
    const r = await getRules(process)
    setRules(r)
    setUserRules(r.user_rules || [])
  }

  async function handleUpload(file: File) {
    try {
      await uploadFile(file, { process })
      message.success(`${file.name} 上传成功`)
      await refreshUploads()
    } catch (e: any) {
      const status = e?.response?.status
      const detail = e?.response?.data?.detail || e?.message
      if (status === 409) {
        message.warning(detail || '同名文件已存在，未重复添加')
      } else {
        message.error('上传失败：' + detail)
      }
    }
    return false // 阻止 antd 自带上传
  }

  async function handleLoadSamples() {
    try {
      const res = await loadSamples(process)
      if (res.files.length > 0) {
        message.success(`已载入 ${res.files.length} 份样例材料`)
      }
      if (res.skipped && res.skipped.length > 0) {
        message.warning(
          `${res.skipped.length} 份样例已存在被跳过：${res.skipped
            .map((s) => s.name)
            .join('、')}`,
        )
      }
      if (res.files.length === 0 && (!res.skipped || res.skipped.length === 0)) {
        message.info('未找到可载入的样例文件')
      }
      await refreshUploads()
    } catch (e: any) {
      message.error('载入样例失败：' + (e?.response?.data?.detail || e?.message))
    }
  }

  async function handleDelete(fileId: string) {
    await deleteUpload(fileId)
    await refreshUploads()
  }

  async function handleCreateRule() {
    try {
      const vals = await form.validateFields()
      if (editingRuleId) {
        await updateUserRule(editingRuleId, {
          applicable_materials: vals.applicable_materials || [],
          rule_text: vals.rule_text,
          risk_level: vals.risk_level as RiskLevel,
          review_dimension: vals.review_dimension || '用户新增规则',
          check_type: vals.check_type || '语义条件判断',
          table_name: vals.table_name || '',
          field_name: vals.field_name || '',
          trigger_condition: vals.trigger_condition || '',
        })
        message.success('已保存修改')
      } else {
        await createUserRule({
          process,
          applicable_materials: vals.applicable_materials || [],
          rule_text: vals.rule_text,
          risk_level: vals.risk_level as RiskLevel,
          review_dimension: vals.review_dimension || '用户新增规则',
          check_type: vals.check_type || '语义条件判断',
          table_name: vals.table_name || '',
          field_name: vals.field_name || '',
          trigger_condition: vals.trigger_condition || '',
        })
        message.success('已新增规则')
      }
      setCreating(false)
      setEditingRuleId(null)
      form.resetFields()
      await refreshRules()
    } catch {
      /* validation */
    }
  }

  function handleOpenEdit(rule: {
    rule_id: string
    rule_text: string
    risk_level: RiskLevel
    applicable_materials?: string[]
    review_dimension?: string
    check_type?: string
    table_name?: string
    field_name?: string
    trigger_condition?: string
  }) {
    setEditingRuleId(rule.rule_id)
    setCreating(true)
    // setFieldsValue 在 Modal forceRender 之后会立刻生效
    setTimeout(() => {
      form.setFieldsValue({
        rule_text: rule.rule_text,
        risk_level: rule.risk_level,
        applicable_materials: rule.applicable_materials || [],
        review_dimension: rule.review_dimension || '用户新增规则',
        check_type: rule.check_type || '语义条件判断',
        table_name: rule.table_name || '',
        field_name: rule.field_name || '',
        trigger_condition: rule.trigger_condition || '',
      })
    }, 0)
  }

  async function handleDeleteUserRule(rid: string) {
    await deleteUserRule(rid)
    await refreshRules()
  }

  async function handleStart() {
    if (currentUploads.length === 0) {
      message.warning('请先上传材料或一键载入样例')
      return
    }
    // 锁定本次审核所属流程,避免审核过程中用户切流程时回调写到错误流程
    const reviewProcess = process
    resetProgress(reviewProcess)
    resetBatchProgress(reviewProcess)
    setResult(null, reviewProcess)
    setStage('parse', reviewProcess)
    setJobStatus('pending', reviewProcess)
    try {
      const { job_id } = await startReview({
        process: reviewProcess,
        file_ids: currentUploads.map((u) => u.file_id),
        max_concurrency: 48,
        material_slice_enabled: materialSliceEnabled,
      })
      setJobId(job_id, reviewProcess)
      setJobStatus('running', reviewProcess)
      setStage('batch', reviewProcess)

      subscribeReviewStream(
        job_id,
        (msg) => {
          appendProgress(msg, reviewProcess)
          // 从 "分组完成：共 N 批" 抓总批次数
          const m = msg.match(/分组完成[：:]\s*共\s*(\d+)\s*批/)
          if (m) setBatchTotal(parseInt(m[1], 10), reviewProcess)
          if (msg.includes('分组完成')) setStage('batch', reviewProcess)
          if (msg.includes('全部批次完成') || msg.includes('合并') || msg.includes('去重')) {
            setStage('merge', reviewProcess)
          }
        },
        async () => {
          setStage('done', reviewProcess)
          setJobStatus('done', reviewProcess)
          // 拉取最终结果（覆盖累积区为合并后的最终版）
          const { getReview } = await import('../api')
          const job = await getReview(job_id)
          setResult(job.result || null, reviewProcess)
        },
        (err) => {
          setStage('failed', reviewProcess)
          setJobStatus('failed', reviewProcess)
          message.error('审核失败：' + err)
        },
        (payload) => {
          // O6：批次完成事件 → 累积到 store，触发 RightPanel 重渲染
          appendBatchIssues(payload, reviewProcess)
        },
      )
    } catch (e: any) {
      setStage('failed', reviewProcess)
      setJobStatus('failed', reviewProcess)
      message.error('启动审核失败：' + (e?.response?.data?.detail || e?.message))
    }
  }

  const running = jobStatus === 'pending' || jobStatus === 'running'

  return (
    <>
      {/* ===== 规则面板 ===== */}
      <div className="panel">
        <div className="panel-header">
          <h3>📚 {processLabel}规则集</h3>
          <div className="right">
            <Tag color="processing">内置 {builtinRules.length}</Tag>
            <Tag color="purple">用户 {userRules.length}</Tag>
          </div>
        </div>
        <div className="panel-body" style={{ maxHeight: 320 }}>
          <Collapse
            size="small"
            ghost
            defaultActiveKey={['builtin', 'user']}
            items={[
              {
                key: 'builtin',
                label: (
                  <span style={{ fontSize: 13, fontWeight: 600 }}>
                    内置规则（{builtinRules.length}）
                  </span>
                ),
                children: (
                  <div style={{ maxHeight: 200, overflowY: 'auto' }}>
                    {builtinRules.length === 0 && (
                      <div className="muted" style={{ padding: '4px 0' }}>
                        暂未加载到内置规则（请检查后端是否已启动）
                      </div>
                    )}
                    {builtinRules.slice(0, 60).map((r) => (
                      <div key={r.rule_id} className="rule-row">
                        <span className="rid">{r.rule_id}</span>
                        <span className="txt">
                          <Tooltip title={r.rule_text}>
                            <span>
                              <strong>{r.rule_name}</strong>
                              <span className="muted" style={{ marginLeft: 6 }}>
                                · {r.review_dimension}
                              </span>
                            </span>
                          </Tooltip>
                        </span>
                      </div>
                    ))}
                    {builtinRules.length > 60 && (
                      <div className="muted" style={{ textAlign: 'center', padding: 6 }}>
                        … 还有 {builtinRules.length - 60} 条，仅展示前 60 条
                      </div>
                    )}
                  </div>
                ),
              },
              {
                key: 'user',
                label: (
                  <span style={{ fontSize: 13, fontWeight: 600 }}>
                    用户新增规则（{userRules.length}）
                  </span>
                ),
                children: (
                  <>
                    <div style={{ marginBottom: 8 }}>
                      <Button
                        type="dashed"
                        size="small"
                        icon={<PlusOutlined />}
                        onClick={() => {
                          setEditingRuleId(null)
                          form.resetFields()
                          setCreating(true)
                        }}
                        block
                      >
                        新增一条规则
                      </Button>
                    </div>
                    {userRules.length === 0 ? (
                      <div className="muted" style={{ padding: '4px 0' }}>
                        暂无用户规则
                      </div>
                    ) : (
                      userRules.map((r) => (
                        <div key={r.rule_id} className="rule-row">
                          <span className="rid">{r.rule_id.slice(0, 8)}</span>
                          <span className="txt">
                            <Tag
                              color={
                                r.risk_level === '高风险'
                                  ? 'error'
                                  : r.risk_level === '中风险'
                                  ? 'warning'
                                  : 'success'
                              }
                              style={{ marginRight: 6 }}
                            >
                              {r.risk_level}
                            </Tag>
                            {r.rule_text}
                            <div className="muted" style={{ marginTop: 2 }}>
                              {r.review_dimension || '用户新增规则'}
                              {r.check_type ? ` · ${r.check_type}` : ''}
                              {r.table_name || r.field_name
                                ? ` · ${[r.table_name, r.field_name].filter(Boolean).join('.')}`
                                : ''}
                            </div>
                          </span>
                          <Tooltip title="编辑">
                            <Button
                              type="text"
                              size="small"
                              icon={<EditOutlined />}
                              onClick={() => handleOpenEdit(r)}
                            />
                          </Tooltip>
                          <Popconfirm
                            title="删除该规则？"
                            onConfirm={() => handleDeleteUserRule(r.rule_id)}
                          >
                            <Button
                              type="text"
                              size="small"
                              icon={<DeleteOutlined />}
                              danger
                            />
                          </Popconfirm>
                        </div>
                      ))
                    )}
                  </>
                ),
              },
            ]}
          />
        </div>
      </div>

      {/* ===== 上传 / 剧本模式 ===== */}
      <div className="panel">
        <div className="panel-header">
          <h3>📥 材料上传</h3>
          <div className="right">
            <Button
              size="small"
              icon={<ThunderboltOutlined />}
              onClick={handleLoadSamples}
            >
              一键载入样例
            </Button>
          </div>
        </div>
        <div className="panel-body">
          <div className={currentUploads.length > 0 ? 'dragger-compact' : ''}>
            <Dragger
              multiple
              beforeUpload={handleUpload}
              showUploadList={false}
              accept=".json,.pdf,.docx,.txt"
              style={{ background: '#FAFBFF', borderColor: '#CBD5E1' }}
            >
              <p className="ant-upload-drag-icon" style={{ marginBottom: 4 }}>
                <InboxOutlined style={{ color: '#5B5BD6' }} />
              </p>
              <p style={{ fontSize: 13, color: 'var(--c-text)', margin: 0 }}>
                点击或拖拽上传材料
              </p>
              <p style={{ fontSize: 12, color: 'var(--c-text-3)', margin: 0 }}>
                支持 JSON / PDF / DOCX / TXT
              </p>
            </Dragger>
          </div>

          {currentUploads.length > 0 && (
            <>
              <div className="section-title" style={{ marginTop: 12 }}>
                已上传 {currentUploads.length} 份
              </div>
              <div className="upload-list">
                {currentUploads.map((u) => (
                  <div key={u.file_id} className="upload-item">
                    <span className="icn">📄</span>
                    <div className="meta">
                      <div className="name" title={u.original_name}>
                        {u.original_name}
                      </div>
                      <div className="sub">
                        {u.material_type && (
                          <Tag color="purple" style={{ marginRight: 6 }}>
                            {u.material_type}
                          </Tag>
                        )}
                        <span className="size">{fmtSize(u.size_bytes)}</span>
                      </div>
                    </div>
                    <Popconfirm
                      title="删除该文件？"
                      onConfirm={() => handleDelete(u.file_id)}
                    >
                      <Button
                        type="text"
                        size="small"
                        icon={<DeleteOutlined />}
                        danger
                      />
                    </Popconfirm>
                  </div>
                ))}
              </div>
            </>
          )}

          <div className="review-option-row">
            <div>
              <div className="review-option-title">材料片段裁剪</div>
              <div className="muted">
                开启后优先发送规则相关片段给 AI；命中不足时自动回退全文
              </div>
            </div>
            <Switch
              checked={materialSliceEnabled}
              onChange={(checked) => setMaterialSlice(checked, process)}
              disabled={running}
            />
          </div>

          <Button
            type="primary"
            block
            size="large"
            icon={<RocketOutlined />}
            onClick={handleStart}
            loading={running}
            style={{ marginTop: 14, fontWeight: 600 }}
          >
            {running ? 'AI 审核中…' : '开始 AI 审核'}
          </Button>
        </div>
      </div>

      {/* 新增规则 Modal */}
      <Modal
        key={process /* 切流程时强制重建并清空 */}
        title={`${editingRuleId ? '编辑' : '新增'}用户规则 · ${processLabel}`}
        open={creating}
        onCancel={() => {
          setCreating(false)
          setEditingRuleId(null)
          form.resetFields()
        }}
        afterClose={() => form.resetFields()}
        onOk={handleCreateRule}
        okText="保存"
        cancelText="取消"
        width={560}
        forceRender
        destroyOnHidden
      >
        <Form
          layout="vertical"
          form={form}
          initialValues={{
            risk_level: '中风险',
            review_dimension: '用户新增规则',
            check_type: '语义条件判断',
          }}
          preserve={false}
        >
          <Form.Item
            label="规则内容"
            name="rule_text"
            rules={[{ required: true, message: '请输入规则内容' }]}
          >
            <Input.TextArea
              rows={3}
              placeholder="例：信托产品名称中不得出现'保本'、'保收益'等表述"
            />
          </Form.Item>
          <Form.Item label="风险等级" name="risk_level">
            <Select
              options={[
                { value: '高风险', label: '高风险' },
                { value: '中风险', label: '中风险' },
                { value: '低风险', label: '低风险' },
              ]}
            />
          </Form.Item>
          <Form.Item label="适用材料" name="applicable_materials">
            <Select
              mode="multiple"
              allowClear
              placeholder="选择一个或多个材料类型（可不填，默认全部适用）"
              options={materialOptions}
              optionLabelProp="label"
              maxTagCount="responsive"
              dropdownStyle={{ maxWidth: 'unset' }}
            />
          </Form.Item>
          <Collapse
            size="small"
            ghost
            items={[
              {
                key: 'advanced',
                label: (
                  <span style={{ fontSize: 13, fontWeight: 600 }}>
                    高级定位信息（可选）
                  </span>
                ),
                children: (
                  <>
                    <div className="muted" style={{ marginBottom: 10 }}>
                      用于提升材料裁剪和 AI 定位准确性；不填写时会按规则文本弱检索，命中不足自动回退全文。
                    </div>
                    <Form.Item label="审核维度" name="review_dimension">
                      <Select options={REVIEW_DIMENSION_OPTIONS} />
                    </Form.Item>
                    <Form.Item label="校验类型" name="check_type">
                      <Select options={CHECK_TYPE_OPTIONS} />
                    </Form.Item>
                    <Form.Item label="表名" name="table_name">
                      <Input placeholder="例：产品特征" allowClear />
                    </Form.Item>
                    <Form.Item label="字段名" name="field_name">
                      <Input placeholder="例：约定优先劣后受益权比例" allowClear />
                    </Form.Item>
                    <Form.Item label="触发条件" name="trigger_condition">
                      <Input placeholder="例：是否结构化信托=是" allowClear />
                    </Form.Item>
                  </>
                ),
              },
            ]}
          />
        </Form>
      </Modal>
    </>
  )
}
