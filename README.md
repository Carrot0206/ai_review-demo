# 信托登记 AI 辅助审核 Demo

中信登信托产品登记 AI 辅助审核演示项目，支持两类登记流程：
- 初始登记
- 事前报告

> 本项目为 **演示用 demo**，不是生产系统。

## 项目状态（当前阶段：CLI 先行）

按既定开发顺序：**命令行真跑通 → 封装 FastAPI 接口 → 搭建前端页面**。

当前已完成：
- ✅ 项目骨架与依赖清单
- ✅ 规则加载器（按流程加载、过滤、分组、剥离需人工复核规则）
- ✅ 材料解析器（JSON 模板、PDF 文本型、DOCX、TXT）
- ✅ DeepSeek 客户端（OpenAI 兼容协议，强 JSON 输出）
- ✅ Prompt 模板（规则数组 + 材料片段 + 强约束）
- ✅ 命令行 review runner

进行中 / 待办：
- ⏳ 用真 DeepSeek 跑通事前报告 16 条 → 初始登记全量
- ⏳ 封装 FastAPI 接口
- ⏳ 搭建前端

## 目录结构

```
trust-ai-review-demo/
├── README.md
├── .gitignore
├── backend/
│   ├── requirements.txt
│   ├── .env.example
│   ├── cli/
│   │   └── run_review.py             # 命令行入口
│   ├── services/
│   │   ├── schemas.py                # 共享 Pydantic 模型
│   │   ├── rule_loader.py            # 规则加载/过滤/分组
│   │   ├── material_parser.py        # 材料解析（JSON/PDF/DOCX/TXT）
│   │   ├── prompt_builder.py         # Prompt 组装
│   │   ├── llm_client.py             # DeepSeek 客户端
│   │   └── review_service.py         # 核心审核服务
│   ├── data/
│   │   └── rules/
│   │       ├── rules_pre_report.json
│   │       └── rules_initial_registration.json
│   ├── samples/                      # 演示材料（自备）
│   ├── uploads/                      # 接口阶段上传缓存
│   └── out/                          # CLI 结果输出
└── docs/
```

## 快速开始（CLI）

### 1. 安装依赖

```bash
cd trust-ai-review-demo/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. 配置 DeepSeek

```bash
cp .env.example .env
# 编辑 .env，填入 DEEPSEEK_API_KEY
```

### 3. 准备样例材料

把"事前报告模板.json"、"事前报告申请书.pdf/docx"等文件放进 `backend/samples/`。

### 4. 跑事前报告（16 条规则）

```bash
cd ..   # 回到项目根
python -m backend.cli.run_review \
  --process pre_report \
  --materials backend/samples/事前报告模板.json backend/samples/事前报告申请书.pdf \
  --output backend/out/pre_report_result.json
```

控制台会逐批打印进度，结束后输出 `backend/out/pre_report_result.json`。

### 5. 跑初始登记（162 条规则）

```bash
python -m backend.cli.run_review \
  --process initial \
  --materials backend/samples/初始登记模板.json backend/samples/初始登记申请书.pdf backend/samples/信托文件样本.pdf \
  --output backend/out/initial_result.json \
  --max-concurrency 6
```

### 调试小范围规则

```bash
python -m backend.cli.run_review \
  --process pre_report \
  --materials backend/samples/事前报告模板.json \
  --rules PRE-FILE-AI-001 PRE-FILE-AI-002 \
  --output backend/out/debug.json
```

## 关键约定

- **PDF**：仅支持文本型 PDF。扫描件 / 复杂表格不在 demo 范围。
- **版式/显著位置类规则**：自动标"需人工复核"，不进 AI 批次，**不计入高/中/低风险统计**，在结果中单独列出。
- **`rule_basis` 与 `risk_level`**：由后端依据规则库回填，**不让模型自由发挥**，避免幻觉。
- **`temperature=0.1`** + **`response_format=json_object`**：保证输出稳定可解析。
- **禁用 mock**：CLI 阶段强制走真实 DeepSeek，避免"看起来能跑实际没验证"。

## 输出 JSON Schema

详见 `backend/services/schemas.py::ReviewResult`，关键结构：

```json
{
  "summary": {
    "registration_type": "事前报告",
    "total_issues": 4,
    "high_risk_count": 1,
    "medium_risk_count": 2,
    "low_risk_count": 1
  },
  "issues": [
    {
      "issue_id": "ISSUE-001",
      "rule_id": "PRE-FILE-AI-001",
      "issue_summary": "...",
      "risk_level": "高风险",
      "rule_basis": { "basis_type": "内置规则", "basis_file": "...", "rule_text": "..." },
      "issue_location": [
        { "material_name": "...", "location": "...", "value": "..." }
      ],
      "suggestion": "..."
    }
  ],
  "human_review_items": [
    { "rule_id": "...", "rule_name": "...", "rule_text": "...", "reason": "..." }
  ],
  "batch_logs": [
    {
      "batch_id": "B01",
      "review_dimension": "登记必填要素规则库(6条)",
      "rule_count": 6,
      "status": "success",
      "issues_found": 2,
      "duration_seconds": 3.21,
      "input_tokens": 4823,
      "output_tokens": 1205
    }
  ]
}
```

## 未来扩展（不在第一版范围）

- 扫描件 OCR
- 问题点位 → 原文跳转高亮
- 审核历史记录
- 多版本材料差异审核
