import { useEffect, useState } from 'react'
import { Alert, Button, Modal, Space, Spin, Table, Tag, Upload, message } from 'antd'
import { FileExcelOutlined, InboxOutlined } from '@ant-design/icons'
import {
  commitRuleLibraryImport,
  previewRuleLibraryImport,
} from '../../api'
import type {
  RuleLibraryImportPreview,
  RuleLibraryProcess,
} from '../../types'
import { PROCESS_LABELS } from './config'

type Props = {
  open: boolean
  process: RuleLibraryProcess
  onClose: () => void
  onImported: () => void
}

export default function ImportRulesModal({ open, process, onClose, onImported }: Props) {
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<RuleLibraryImportPreview | null>(null)
  const [loading, setLoading] = useState(false)
  const [committing, setCommitting] = useState(false)

  useEffect(() => {
    if (open) return
    setFile(null)
    setPreview(null)
    setLoading(false)
    setCommitting(false)
  }, [open])

  async function handleFile(selected: File) {
    setFile(selected)
    setPreview(null)
    setLoading(true)
    try {
      const result = await previewRuleLibraryImport(process, selected)
      setPreview(result)
    } catch (error: any) {
      message.error(error?.response?.data?.detail || error?.message || 'Excel解析失败')
    } finally {
      setLoading(false)
    }
    return false
  }

  async function handleCommit() {
    if (!file || !preview?.valid) return
    setCommitting(true)
    try {
      const result = await commitRuleLibraryImport(process, file)
      message.success(`已导入 ${result.imported_count} 条规则：脚本 ${result.script_count} 条，AI ${result.ai_count} 条`)
      onImported()
    } catch (error: any) {
      const detail = error?.response?.data?.detail
      message.error(typeof detail === 'string' ? detail : detail?.message || '导入失败')
    } finally {
      setCommitting(false)
    }
  }

  return (
    <Modal
      open={open}
      width={760}
      title={`导入${PROCESS_LABELS[process]}规则`}
      onCancel={onClose}
      footer={
        <Space>
          <Button onClick={onClose}>取消</Button>
          <Button type="primary" disabled={!preview?.valid} loading={committing} onClick={handleCommit}>
            确认导入
          </Button>
        </Space>
      }
    >
      <Alert
        type="info"
        showIcon
        title="一份Excel仅导入当前登记流程"
        description="至少包含“脚本审核规则”或“AI审核规则”Sheet。任何重复规则ID或行级错误都会拒绝整次导入。"
        style={{ marginBottom: 16 }}
      />
      <Upload.Dragger
        accept=".xlsx,.xlsm"
        multiple={false}
        showUploadList={false}
        beforeUpload={handleFile}
        className="rule-import-dragger"
      >
        <p className="ant-upload-drag-icon"><InboxOutlined /></p>
        <p className="ant-upload-text">选择或拖入规则Excel</p>
        <p className="ant-upload-hint">当前流程：{PROCESS_LABELS[process]}，仅支持 XLSX / XLSM</p>
      </Upload.Dragger>

      {file && (
        <div className="selected-import-file">
          <FileExcelOutlined />
          <span>{file.name}</span>
        </div>
      )}

      {loading && <div className="import-preview-loading"><Spin /> 正在校验规则表...</div>}
      {preview && !loading && (
        <div className="import-preview">
          <div className="import-summary">
            <span>识别规则 <strong>{preview.total_rules}</strong> 条</span>
            <Tag color="blue">脚本 {preview.script_count}</Tag>
            <Tag color="purple">AI {preview.ai_count}</Tag>
            <Tag color={preview.valid ? 'success' : 'error'}>{preview.valid ? '校验通过' : `错误 ${preview.errors.length}`}</Tag>
          </div>
          {preview.errors.length > 0 && (
            <Table
              size="small"
              pagination={false}
              rowKey={(item, index) => `${item.sheet}-${item.row}-${index}`}
              dataSource={preview.errors}
              scroll={{ y: 260 }}
              columns={[
                { title: 'Sheet', dataIndex: 'sheet', width: 120, render: (value) => value || '-' },
                { title: '行', dataIndex: 'row', width: 60, render: (value) => value || '-' },
                { title: '规则ID', dataIndex: 'rule_id', width: 150, render: (value) => value || '-' },
                { title: '错误原因', dataIndex: 'message' },
              ]}
            />
          )}
        </div>
      )}
    </Modal>
  )
}
