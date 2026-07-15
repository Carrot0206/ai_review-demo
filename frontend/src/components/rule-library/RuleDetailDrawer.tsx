import {
  Button,
  Descriptions,
  Divider,
  Drawer,
  Popconfirm,
  Space,
  Tag,
  Typography,
} from 'antd'
import {
  CopyOutlined,
  DeleteOutlined,
  EditOutlined,
  PauseCircleOutlined,
  PlayCircleOutlined,
} from '@ant-design/icons'
import type { RuleLibraryRule } from '../../types'
import { PROCESS_LABELS } from './config'

type Props = {
  rule: RuleLibraryRule | null
  open: boolean
  onClose: () => void
  onEdit: (rule: RuleLibraryRule) => void
  onCopy: (rule: RuleLibraryRule) => void
  onToggle: (rule: RuleLibraryRule) => void
  onDelete: (rule: RuleLibraryRule) => void
}

function riskColor(risk: string) {
  if (risk === '高风险') return 'error'
  if (risk === '中风险') return 'warning'
  return 'processing'
}

export default function RuleDetailDrawer({
  rule,
  open,
  onClose,
  onEdit,
  onCopy,
  onToggle,
  onDelete,
}: Props) {
  return (
    <Drawer
      open={open}
      size={620}
      title="规则详情"
      onClose={onClose}
      footer={
        rule ? (
          <div className="rule-drawer-footer spread">
            <Popconfirm
              title="删除该规则？"
              description="删除后不可恢复。"
              okText="删除"
              cancelText="取消"
              okButtonProps={{ danger: true }}
              onConfirm={() => onDelete(rule)}
            >
              <Button danger icon={<DeleteOutlined />}>删除</Button>
            </Popconfirm>
            <Space>
              <Button icon={<CopyOutlined />} onClick={() => onCopy(rule)}>复制</Button>
              <Button
                icon={rule.enabled ? <PauseCircleOutlined /> : <PlayCircleOutlined />}
                onClick={() => onToggle(rule)}
              >
                {rule.enabled ? '停用' : '启用'}
              </Button>
              <Button type="primary" icon={<EditOutlined />} onClick={() => onEdit(rule)}>编辑规则</Button>
            </Space>
          </div>
        ) : null
      }
    >
      {rule && (
        <div className="rule-detail">
          <div className="rule-detail-heading">
            <div>
              <Typography.Title level={4}>{rule.rule_name}</Typography.Title>
              <Typography.Text type="secondary">{rule.rule_id}</Typography.Text>
            </div>
            <Space wrap>
              <Tag color={rule.review_method === 'script' ? 'blue' : 'purple'}>
                {rule.review_method === 'script' ? '脚本规则' : 'AI规则'}
              </Tag>
              <Tag color={riskColor(rule.risk_level)}>{rule.risk_level}</Tag>
              <Tag color={rule.enabled ? 'success' : 'default'}>{rule.enabled ? '启用' : '停用'}</Tag>
            </Space>
          </div>

          <Descriptions bordered size="small" column={2}>
            <Descriptions.Item label="适用流程">{PROCESS_LABELS[rule.process]}</Descriptions.Item>
            <Descriptions.Item label="当前版本">{rule.version}</Descriptions.Item>
            <Descriptions.Item label="审查维度">{rule.review_dimension}</Descriptions.Item>
            <Descriptions.Item label="规则对象">{rule.rule_object}</Descriptions.Item>
            <Descriptions.Item label="表名">{rule.table_name || '-'}</Descriptions.Item>
            <Descriptions.Item label="字段路径">{rule.field_path || '-'}</Descriptions.Item>
            <Descriptions.Item label="适用材料" span={2}>
              <Space size={[4, 6]} wrap>
                {rule.applicable_materials.map((item) => <Tag key={item}>{item}</Tag>)}
              </Space>
            </Descriptions.Item>
            <Descriptions.Item label="触发条件" span={2}>{rule.trigger_condition || '-'}</Descriptions.Item>
          </Descriptions>

          <Divider titlePlacement="start" plain>具体规则</Divider>
          <div className="rule-content-block">{rule.rule_text}</div>

          <Divider titlePlacement="start" plain>审查依据</Divider>
          <div className="rule-content-block secondary">{rule.basis_text}</div>

          {rule.review_method === 'script' ? (
            <>
              <Divider titlePlacement="start" plain>可视化规则</Divider>
              <div className="visual-rule-preview detail">
                <div className="visual-rule-text">{rule.visual_rule}</div>
              </div>
              <Descriptions bordered size="small" column={1} className="rule-technical-detail">
                <Descriptions.Item label="operator">{rule.operator}</Descriptions.Item>
                <Descriptions.Item label="结构化参数">
                  <pre>{JSON.stringify(rule.script_params, null, 2)}</pre>
                </Descriptions.Item>
              </Descriptions>
            </>
          ) : (
            <>
              <Divider titlePlacement="start" plain>专属提示词</Divider>
              <pre className="prompt-block">{rule.special_prompt}</pre>
            </>
          )}

          {(rule.source_file || rule.remarks) && (
            <>
              <Divider titlePlacement="start" plain>来源与备注</Divider>
              <Descriptions bordered size="small" column={1}>
                {rule.source_file && (
                  <Descriptions.Item label="导入来源">
                    {rule.source_file} / {rule.source_sheet} / 第 {rule.source_row} 行
                  </Descriptions.Item>
                )}
                {rule.remarks && <Descriptions.Item label="备注">{rule.remarks}</Descriptions.Item>}
              </Descriptions>
            </>
          )}
        </div>
      )}
    </Drawer>
  )
}
