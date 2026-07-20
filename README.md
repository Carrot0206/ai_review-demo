# 信托登记规则库与规则引擎

本项目已从 `trust-ai-review-demo` 中独立出来，提供规则库前端、材料上传解析、规则库API，以及独立的异步规则引擎API。

## 目录

```text
trust-rule-engine/
├── backend/
│   ├── api/            # 规则库及规则引擎API
│   ├── services/       # 规则库、任务编排、提示词和AI客户端
│   ├── executors/      # 十九类脚本operator和AI批次执行器
│   ├── models/         # 任务、快照和结果模型
│   ├── storage/        # SQLite任务持久化
│   ├── data/           # 当前规则库JSON
│   └── tests/
├── frontend/           # 独立规则库页面
├── deploy/             # Nginx与systemd配置参考
└── docs/
```

## 本地启动

```bash
cd trust-rule-engine
python3 -m venv backend/.venv
source backend/.venv/bin/activate
pip install -r backend/requirements.txt
cd frontend && npm install && cd ..
./start.sh
```

- 规则库页面：`http://127.0.0.1:5174/rule-library/`
- 信托产品登记审核：`http://127.0.0.1:5174/rule-library/review`
- 后端文档：`http://127.0.0.1:8001/docs`
- 健康检查：`http://127.0.0.1:8001/api/rule-engine/health`

## 一键部署

```bash
cd "/Users/xieyinghan/Downloads/ai审核信托产品登记demo/trust-rule-engine"
./deploy/upload_and_update.sh root@192.168.21.103
```

该命令同时支持首次安装和日常更新，默认保留服务器规则库、任务数据库、上传材料和模型密钥。需要用本地规则库覆盖服务器规则库时追加 `--sync-rules`。详细说明见 `deploy/README.md`。

## 数据

规则库默认读取 `backend/data/rule_library/rules.json`，任务默认写入 `backend/data/rule_engine.db`，上传材料默认保存在 `backend/data/materials`。生产环境分别通过 `RULE_LIBRARY_FILE`、`RULE_ENGINE_DB_FILE` 和 `MATERIAL_UPLOAD_DIR` 指向独立持久化目录，升级程序时不要覆盖该目录。

新审核页面的上传、解析和审核接口均由规则引擎后端 `127.0.0.1:8001` 提供，本地不需要启动原审核后端 `8000`。支持 JSON、XLSX/XLSM、文本型PDF、DOCX和TXT；扫描型PDF第一版不支持OCR。

实际登记系统导出的JSON支持预登记、事前报告、初始登记和终止登记。解析器会识别BOM及32位报文头，根据 `requestType` 校验登记流程，把接口字段代码和枚举代码转换为规则库使用的中文路径和值，并保留 `raw_location`、`raw_text` 供追溯。普通测试JSON仍沿用递归扁平化解析。

四流程运行时映射位于 `backend/data/template_mappings`，生产环境不需要部署XLSM。登记模板更新后，在项目总目录执行：

```bash
python3 tools/generate_registration_template_mappings.py
python3 tools/generate_registration_template_mappings.py --check
```

未知模板版本在字段结构和枚举代码仍可完整识别时兼容解析并返回警告；未知表、字段、枚举代码、流程不一致或多产品JSON会解析失败。

复制 `backend/.env.example` 为 `backend/.env` 并填写 DeepSeek 配置。该配置由规则引擎独立维护，不再读取原审核Demo的环境变量。AI完整输入输出默认保留7天，可通过 `AI_TRACE_RETENTION_DAYS` 调整。为保证 `AI_MAX_CONCURRENCY=2500` 是服务级全局限制，第一版必须使用单个 Uvicorn worker。

## 审核API

创建任务时自动加载指定流程的全部启用规则并固化快照，不允许调用方选择部分规则：

```bash
curl -X POST http://127.0.0.1:8001/api/rule-engine/materials \
  -F process=pre_registration \
  -F file=@预登记申报模板.xlsx
```

新审核页面使用上传接口返回的 `file_id` 创建任务：

```bash
curl -X POST http://127.0.0.1:8001/api/rule-engine/reviews \
  -H 'Content-Type: application/json' \
  -d '{"process":"pre_registration","file_ids":["替换为材料ID"]}'
```

原有直接提交解析结果的接口仍保持兼容：

```bash
curl -X POST http://127.0.0.1:8001/api/rule-engine/reviews \
  -H 'Content-Type: application/json' \
  -d '{
    "process": "pre_registration",
    "materials": [{
      "material_name": "预登记申报模板.json",
      "material_type": "申报模板",
      "file_kind": "json",
      "segments": [{"location": "产品基本信息.产品名称", "text": "示例信托计划"}]
    }]
  }'
```

返回的 `task_id` 可用于以下接口：

- `GET /api/rule-engine/reviews/{task_id}`：状态与进度
- `GET /api/rule-engine/reviews/{task_id}/result`：汇总、问题卡片、逐规则结果和批次日志
- `GET /api/rule-engine/reviews/{task_id}/events`：SSE进度事件
- `POST /api/rule-engine/reviews/{task_id}/cancel`：取消未结束任务
- `POST /api/rule-engine/reviews/{task_id}/retry-failed`：使用原快照重试失败批次

流程值为 `pre_registration`、`pre_report`、`initial`、`termination`。服务重启时未结束任务会转为 `interrupted`，可通过重试接口继续。

## 验证

```bash
python3 -m unittest discover backend/tests
python3 -m compileall -q backend
python3 ../tools/generate_registration_template_mappings.py --check
cd frontend
npm run lint
npm run build
```

外部继续使用 `28101` 端口时，可直接使用 `deploy/nginx.trust-platform.conf` 同时路由原审核Demo和本项目；详细步骤见 `deploy/README.md`。
