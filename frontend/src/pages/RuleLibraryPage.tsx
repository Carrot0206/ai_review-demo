import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Button,
  ConfigProvider,
  Dropdown,
  Empty,
  Input,
  Modal,
  Segmented,
  Select,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
  message,
} from 'antd'
import type { TableColumnsType } from 'antd'
import {
  CopyOutlined,
  DeleteOutlined,
  DownloadOutlined,
  EditOutlined,
  EllipsisOutlined,
  FileTextOutlined,
  ImportOutlined,
  PauseCircleOutlined,
  PlayCircleOutlined,
  PlusOutlined,
  SearchOutlined,
} from '@ant-design/icons'
import {
  copyRuleLibraryRule,
  deleteRuleLibraryRule,
  deleteRuleLibraryRules,
  deleteRuleLibraryRulesByProcess,
  downloadRuleLibraryTemplate,
  getRuleLibraryRules,
  setRuleLibraryRuleEnabled,
} from '../api'
import type {
  RiskLevel,
  RuleLibraryMethod,
  RuleLibraryProcess,
  RuleLibraryResponse,
  RuleLibraryRule,
} from '../types'
import ImportRulesModal from '../components/rule-library/ImportRulesModal'
import RuleDetailDrawer from '../components/rule-library/RuleDetailDrawer'
import RuleEditorDrawer from '../components/rule-library/RuleEditorDrawer'
import {
  PROCESS_LABELS,
  PROCESS_OPTIONS,
  REVIEW_DIMENSIONS,
} from '../components/rule-library/config'
import './ruleLibrary.css'

type MethodFilter = 'all' | RuleLibraryMethod
type StatusFilter = 'all' | 'enabled' | 'disabled'

function riskColor(risk: RiskLevel) {
  if (risk === '高风险') return 'error'
  if (risk === '中风险') return 'warning'
  return 'processing'
}

export default function RuleLibraryPage() {
  const [process, setProcess] = useState<RuleLibraryProcess>('pre_registration')
  const [data, setData] = useState<RuleLibraryResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [method, setMethod] = useState<MethodFilter>('all')
  const [dimension, setDimension] = useState<string>('all')
  const [material, setMaterial] = useState<string>('all')
  const [risk, setRisk] = useState<string>('all')
  const [status, setStatus] = useState<StatusFilter>('all')
  const [keyword, setKeyword] = useState('')
  const [selectedIds, setSelectedIds] = useState<React.Key[]>([])
  const [detailRule, setDetailRule] = useState<RuleLibraryRule | null>(null)
  const [editorRule, setEditorRule] = useState<RuleLibraryRule | null>(null)
  const [editorOpen, setEditorOpen] = useState(false)
  const [importOpen, setImportOpen] = useState(false)

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      setData(await getRuleLibraryRules(process))
    } catch (error: any) {
      message.error(error?.response?.data?.detail || error?.message || '规则库加载失败')
    } finally {
      setLoading(false)
    }
  }, [process])

  useEffect(() => {
    setSelectedIds([])
    setDetailRule(null)
    setMethod('all')
    setDimension('all')
    setMaterial('all')
    setRisk('all')
    setStatus('all')
    setKeyword('')
    refresh()
  }, [process, refresh])

  const materialOptions = useMemo(() => {
    const values = new Set<string>()
    data?.rules.forEach((rule) => rule.applicable_materials.forEach((item) => values.add(item)))
    return [...values].sort().map((value) => ({ value, label: value }))
  }, [data])

  const filteredRules = useMemo(() => {
    const normalizedKeyword = keyword.trim().toLowerCase()
    return (data?.rules || []).filter((rule) => {
      if (method !== 'all' && rule.review_method !== method) return false
      if (dimension !== 'all' && rule.review_dimension !== dimension) return false
      if (material !== 'all' && !rule.applicable_materials.includes(material)) return false
      if (risk !== 'all' && rule.risk_level !== risk) return false
      if (status === 'enabled' && !rule.enabled) return false
      if (status === 'disabled' && rule.enabled) return false
      if (
        normalizedKeyword &&
        !`${rule.rule_name} ${rule.rule_id} ${rule.rule_text}`.toLowerCase().includes(normalizedKeyword)
      ) return false
      return true
    })
  }, [data, dimension, keyword, material, method, risk, status])

  async function handleCopy(rule: RuleLibraryRule) {
    try {
      const copied = await copyRuleLibraryRule(rule.rule_id)
      message.success(`已复制为 ${copied.rule_id}，默认处于停用状态`)
      setDetailRule(null)
      await refresh()
    } catch (error: any) {
      message.error(error?.response?.data?.detail || error?.message || '复制失败')
    }
  }

  async function handleToggle(rule: RuleLibraryRule) {
    try {
      await setRuleLibraryRuleEnabled(rule.rule_id, !rule.enabled)
      message.success(rule.enabled ? '规则已停用' : '规则已启用')
      setDetailRule(null)
      await refresh()
    } catch (error: any) {
      message.error(error?.response?.data?.detail || error?.message || '状态更新失败')
    }
  }

  async function handleDelete(rule: RuleLibraryRule) {
    try {
      await deleteRuleLibraryRule(rule.rule_id)
      message.success('规则已删除')
      setDetailRule(null)
      setSelectedIds((ids) => ids.filter((id) => id !== rule.rule_id))
      await refresh()
    } catch (error: any) {
      message.error(error?.response?.data?.detail || error?.message || '删除失败')
    }
  }

  function confirmDelete(rule: RuleLibraryRule) {
    Modal.confirm({
      title: '删除该规则？',
      content: `${rule.rule_name}（${rule.rule_id}）删除后不可恢复。`,
      okText: '删除',
      cancelText: '取消',
      okButtonProps: { danger: true },
      onOk: () => handleDelete(rule),
    })
  }

  function confirmBatchDelete() {
    Modal.confirm({
      title: `删除已选中的 ${selectedIds.length} 条规则？`,
      content: '删除后不可恢复。',
      okText: '批量删除',
      cancelText: '取消',
      okButtonProps: { danger: true },
      async onOk() {
        try {
          const result = await deleteRuleLibraryRules(selectedIds.map(String))
          message.success(`已删除 ${result.deleted_count} 条规则`)
          setSelectedIds([])
          await refresh()
        } catch (error: any) {
          message.error(error?.response?.data?.detail || error?.message || '批量删除失败')
        }
      },
    })
  }

  function confirmClearProcess() {
    const processLabel = PROCESS_LABELS[process]
    const ruleCount = data?.total || 0
    if (!ruleCount) return
    Modal.confirm({
      title: `清空${processLabel}全部规则？`,
      content: `将永久删除${processLabel}流程下的 ${ruleCount} 条规则，其他登记流程不受影响。删除后不可恢复。`,
      okText: '确认清空',
      cancelText: '取消',
      okButtonProps: { danger: true },
      async onOk() {
        try {
          const result = await deleteRuleLibraryRulesByProcess(process)
          message.success(`已清空${processLabel}流程，共删除 ${result.deleted_count} 条规则`)
          setSelectedIds([])
          setDetailRule(null)
          await refresh()
        } catch (error: any) {
          message.error(error?.response?.data?.detail || error?.message || '清空当前流程失败')
        }
      },
    })
  }

  function openNewRule() {
    setEditorRule(null)
    setEditorOpen(true)
  }

  function openEditRule(rule: RuleLibraryRule) {
    setDetailRule(null)
    setEditorRule(rule)
    setEditorOpen(true)
  }

  const columns: TableColumnsType<RuleLibraryRule> = (() => {
    const configTitle = method === 'script' ? '可视化规则' : method === 'ai' ? '专属提示词' : '规则配置摘要'
    return [
      {
        title: '规则名称 / ID',
        dataIndex: 'rule_name',
        width: 210,
        fixed: 'left',
        render: (_, rule) => (
          <div className="rule-name-cell">
            <strong>{rule.rule_name}</strong>
            <span>{rule.rule_id}</span>
          </div>
        ),
      },
      {
        title: '规则类型',
        dataIndex: 'review_method',
        width: 100,
        render: (value) => (
          <Tag color={value === 'script' ? 'blue' : 'purple'}>
            {value === 'script' ? '脚本规则' : 'AI规则'}
          </Tag>
        ),
      },
      {
        title: '适用材料',
        dataIndex: 'applicable_materials',
        width: 190,
        render: (materials: string[]) => (
          <Space size={[4, 4]} wrap>
            {materials.slice(0, 2).map((item) => <Tag key={item}>{item}</Tag>)}
            {materials.length > 2 && <Tooltip title={materials.slice(2).join('、')}><Tag>+{materials.length - 2}</Tag></Tooltip>}
          </Space>
        ),
      },
      {
        title: '审查对象',
        key: 'target',
        width: 190,
        render: (_, rule) => (
          <div className="rule-target-cell">
            <span>{rule.rule_object}</span>
            <small>{rule.field_path || rule.table_name || '-'}</small>
          </div>
        ),
      },
      {
        title: '具体规则',
        dataIndex: 'rule_text',
        width: 260,
        ellipsis: { showTitle: false },
        render: (value) => <Tooltip title={value}><span>{value}</span></Tooltip>,
      },
      {
        title: configTitle,
        key: 'config',
        width: 270,
        ellipsis: { showTitle: false },
        render: (_, rule) => {
          const value = rule.review_method === 'script' ? rule.visual_rule : rule.special_prompt
          return <Tooltip title={value}><span>{value || '-'}</span></Tooltip>
        },
      },
      {
        title: '审查维度',
        dataIndex: 'review_dimension',
        width: 150,
      },
      {
        title: '风险等级',
        dataIndex: 'risk_level',
        width: 100,
        render: (value) => <Tag color={riskColor(value)}>{value}</Tag>,
      },
      {
        title: '版本 / 状态',
        key: 'status',
        width: 130,
        render: (_, rule) => (
          <div className="rule-version-cell">
            <span>{rule.version}</span>
            <Tag color={rule.enabled ? 'success' : 'default'}>{rule.enabled ? '启用' : '停用'}</Tag>
          </div>
        ),
      },
      {
        title: '操作',
        key: 'actions',
        width: 120,
        fixed: 'right',
        render: (_, rule) => (
          <Space size={2} onClick={(event) => event.stopPropagation()}>
            <Button type="link" size="small" onClick={() => setDetailRule(rule)}>查看</Button>
            <Dropdown
              trigger={['click']}
              menu={{
                items: [
                  { key: 'edit', label: '编辑', icon: <EditOutlined /> },
                  { key: 'copy', label: '复制', icon: <CopyOutlined /> },
                  {
                    key: 'toggle',
                    label: rule.enabled ? '停用' : '启用',
                    icon: rule.enabled ? <PauseCircleOutlined /> : <PlayCircleOutlined />,
                  },
                  { type: 'divider' },
                  { key: 'delete', label: '删除', danger: true, icon: <DeleteOutlined /> },
                ],
                onClick: ({ key, domEvent }) => {
                  domEvent.stopPropagation()
                  if (key === 'edit') openEditRule(rule)
                  if (key === 'copy') handleCopy(rule)
                  if (key === 'toggle') handleToggle(rule)
                  if (key === 'delete') confirmDelete(rule)
                },
              }}
            >
              <Button type="text" size="small" icon={<EllipsisOutlined />} aria-label="更多操作" />
            </Dropdown>
          </Space>
        ),
      },
    ]
  })()

  return (
    <ConfigProvider theme={{ token: { colorPrimary: '#4A54A8', borderRadius: 4 } }}>
      <div className="rule-library-page">
        <header className="rule-library-header">
          <div className="rule-library-brand"><FileTextOutlined /></div>
          <div>
            <h1>信托登记规则库</h1>
            <span>脚本规则与AI规则统一管理</span>
          </div>
          <div className="rule-library-header-spacer" />
          <Typography.Text className="rule-library-header-count">
            {PROCESS_LABELS[process]}：{data?.total || 0} 条规则
          </Typography.Text>
          <Button icon={<DownloadOutlined />} onClick={() => downloadRuleLibraryTemplate(process)}>下载导入模板</Button>
          <Button icon={<ImportOutlined />} onClick={() => setImportOpen(true)}>导入Excel</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={openNewRule}>新增规则</Button>
        </header>

        <main className="rule-library-main">
          <section className="rule-process-band">
            <div className="rule-process-label">登记流程</div>
            <Segmented
              block
              value={process}
              options={PROCESS_OPTIONS}
              onChange={(value) => setProcess(value as RuleLibraryProcess)}
            />
          </section>

          <section className="rule-summary-band">
            <div><span>规则总数</span><strong>{data?.total || 0}</strong></div>
            <div><span>脚本规则</span><strong>{data?.script_count || 0}</strong></div>
            <div><span>AI规则</span><strong>{data?.ai_count || 0}</strong></div>
            <div><span>已启用</span><strong>{data?.enabled_count || 0}</strong></div>
          </section>

          <section className="rule-list-panel">
            <div className="rule-list-heading">
              <div>
                <h2>{PROCESS_LABELS[process]}规则</h2>
                <p>按规则类型筛选，点击规则查看完整内容与配置。</p>
              </div>
              <div className="rule-list-heading-actions">
                <Segmented
                  value={method}
                  options={[
                    { label: `全部 ${data?.total || 0}`, value: 'all' },
                    { label: `脚本 ${data?.script_count || 0}`, value: 'script' },
                    { label: `AI ${data?.ai_count || 0}`, value: 'ai' },
                  ]}
                  onChange={(value) => setMethod(value as MethodFilter)}
                />
                <Button
                  danger
                  icon={<DeleteOutlined />}
                  disabled={!data?.total}
                  onClick={confirmClearProcess}
                >
                  清空当前流程
                </Button>
              </div>
            </div>

            <div className="rule-filter-bar">
              <Input
                allowClear
                prefix={<SearchOutlined />}
                value={keyword}
                onChange={(event) => setKeyword(event.target.value)}
                placeholder="搜索规则名称、规则ID或规则内容"
                className="rule-search-input"
              />
              <Select
                value={dimension}
                onChange={setDimension}
                options={[{ value: 'all', label: '全部审查维度' }, ...REVIEW_DIMENSIONS.map((value) => ({ value, label: value }))]}
              />
              <Select
                value={material}
                onChange={setMaterial}
                options={[{ value: 'all', label: '全部适用材料' }, ...materialOptions]}
              />
              <Select
                value={risk}
                onChange={setRisk}
                options={[{ value: 'all', label: '全部风险等级' }, ...['高风险', '中风险', '低风险'].map((value) => ({ value, label: value }))]}
              />
              <Select
                value={status}
                onChange={setStatus}
                options={[
                  { value: 'all', label: '全部状态' },
                  { value: 'enabled', label: '启用' },
                  { value: 'disabled', label: '停用' },
                ]}
              />
            </div>

            {selectedIds.length > 0 && (
              <div className="rule-batch-bar">
                <span>已选择 {selectedIds.length} 条规则</span>
                <Button danger size="small" icon={<DeleteOutlined />} onClick={confirmBatchDelete}>批量删除</Button>
              </div>
            )}

            <Table<RuleLibraryRule>
              rowKey="rule_id"
              loading={loading}
              dataSource={filteredRules}
              columns={columns}
              size="middle"
              scroll={{ x: 1650 }}
              pagination={{ pageSize: 10, showSizeChanger: true, showTotal: (total) => `共 ${total} 条` }}
              rowSelection={{ selectedRowKeys: selectedIds, onChange: setSelectedIds }}
              onRow={(rule) => ({ onClick: () => setDetailRule(rule) })}
              locale={{
                emptyText: (
                  <Empty
                    image={Empty.PRESENTED_IMAGE_SIMPLE}
                    description={data?.total ? '没有符合当前筛选条件的规则' : `当前${PROCESS_LABELS[process]}流程暂无规则`}
                  >
                    {!data?.total && (
                      <Space>
                        <Button icon={<ImportOutlined />} onClick={() => setImportOpen(true)}>导入Excel</Button>
                        <Button type="primary" icon={<PlusOutlined />} onClick={openNewRule}>新增规则</Button>
                      </Space>
                    )}
                  </Empty>
                ),
              }}
            />
          </section>
        </main>

        <RuleDetailDrawer
          open={Boolean(detailRule)}
          rule={detailRule}
          onClose={() => setDetailRule(null)}
          onEdit={openEditRule}
          onCopy={handleCopy}
          onToggle={handleToggle}
          onDelete={handleDelete}
        />
        <RuleEditorDrawer
          open={editorOpen}
          process={process}
          rule={editorRule}
          onClose={() => setEditorOpen(false)}
          onSaved={async () => {
            setEditorOpen(false)
            await refresh()
          }}
        />
        <ImportRulesModal
          open={importOpen}
          process={process}
          onClose={() => setImportOpen(false)}
          onImported={async () => {
            setImportOpen(false)
            await refresh()
          }}
        />
      </div>
    </ConfigProvider>
  )
}
