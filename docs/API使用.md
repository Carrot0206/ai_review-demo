# 信托登记 AI 审核网页 API 使用说明

本文说明如何通过 HTTP API 使用已部署的信托登记 AI 审核网页，包括上传规则、上传材料、加载后端样例、关闭内置规则并发起审核。

## 1. 基础信息

### 1.1 服务地址

当前部署地址示例：

```bash
BASE="http://192.168.21.103:28101"
```

如服务器 IP 或端口变化，请替换 `BASE`。

### 1.2 支持的流程 process

所有上传规则、上传材料、加载样例、发起审核都需要指定流程。可选值如下：

| process | 中文含义 |
| --- | --- |
| `pre_report` | 事前报告 |
| `initial` | 初始登记 |
| `pre_registration` | 预登记 |
| `pre_registration_reapply` | 重新申请预登记 |
| `pre_registration_supplement` | 补充预登记 |
| `termination` | 终止登记 |
| `change_general` | 变更登记（一般情形） |
| `correction_general` | 更正登记（一般情形） |

示例：

```bash
PROCESS="pre_registration"
```

### 1.3 一次完整审核的调用顺序

推荐顺序：

1. 上传规则 Excel，得到 `rule_set_id`
2. 可选：启用该规则版本
3. 上传材料，或加载后端样例，得到 `file_id`
4. 发起审核，传入 `file_ids` 和 `rule_set_id`
5. 查询进度和最终结果

如果不希望使用内置规则，发起审核时必须设置：

```json
"include_builtin_rules": false
```

## 2. 健康检查

用于确认服务是否可访问。

```bash
curl "$BASE/api/health"
```

成功返回：

```json
{"status":"ok"}
```

## 3. 规则 API

### 3.1 上传规则 Excel

接口：

```http
POST /api/rule-sets/import?process={process}
```

命令示例：

```bash
curl -X POST "$BASE/api/rule-sets/import?process=$PROCESS" \
  -F "file=@/你的路径/审核规则.xlsx"
```

支持文件：

- `.xlsx`
- `.xlsm`

规则表 sheet 要求：

- 至少包含 `AI审核规则` 或 `脚本审核规则` 其中一个 sheet
- 如果只想使用 AI 审核，可以只提供 `AI审核规则` sheet
- 如果有表级报送范围规则，可额外提供 `表级报送范围` sheet

成功返回示例：

```json
{
  "rule_set_id": "pre_registration_1783674842_534d3d",
  "process": "pre_registration",
  "filename": "审核规则.xlsx",
  "active": false,
  "total_rules": 12,
  "script_count": 0,
  "ai_count": 12,
  "scope_count": 0,
  "error_count": 0,
  "warning_count": 0
}
```

请记录返回的 `rule_set_id`，后续审核时会用到。

### 3.2 启用规则版本

接口：

```http
POST /api/rule-sets/{rule_set_id}/activate
```

命令示例：

```bash
RULE_SET_ID="pre_registration_1783674842_534d3d"

curl -X POST "$BASE/api/rule-sets/$RULE_SET_ID/activate"
```

说明：

- 启用后，网页上当前流程会默认使用该规则版本
- 同一流程下旧规则版本不会删除，只会变成未启用
- 如果发起审核时显式传 `rule_set_id`，则不依赖“当前启用版本”

### 3.3 查看规则版本列表

接口：

```http
GET /api/rule-sets?process={process}
```

命令示例：

```bash
curl "$BASE/api/rule-sets?process=$PROCESS"
```

返回中 `active: true` 的是当前启用版本。

### 3.4 查看某个规则版本内容

接口：

```http
GET /api/rule-sets/{rule_set_id}/rules
```

命令示例：

```bash
curl "$BASE/api/rule-sets/$RULE_SET_ID/rules"
```

### 3.5 删除旧规则版本

接口：

```http
DELETE /api/rule-sets/{rule_set_id}
```

命令示例：

```bash
curl -X DELETE "$BASE/api/rule-sets/$RULE_SET_ID"
```

注意：删除后不可通过网页/API 再使用该规则版本，请谨慎操作。

## 4. 材料 API

### 4.1 上传材料

接口：

```http
POST /api/upload
```

命令示例：

```bash
curl -X POST "$BASE/api/upload" \
  -F "process=$PROCESS" \
  -F "material_type=申请书" \
  -F "file=@/你的路径/申请书.pdf"
```

常见 `material_type`：

- `申请书`
- `申报模板`
- `信托文件样本`
- `清算报告`
- `其他附件`

如果不传 `material_type`，后端会根据文件名自动推断。

成功返回示例：

```json
{
  "file_id": "a1b2c3d4e5f6",
  "original_name": "申请书.pdf",
  "size_bytes": 123456,
  "material_type": "申请书",
  "process": "pre_registration",
  "parse_status": "已解析",
  "parse_error": null,
  "segments_count": 18
}
```

请记录返回的 `file_id`，审核时需要传入。

### 4.2 上传多个材料

每个材料调用一次 `/api/upload`。例如：

```bash
curl -X POST "$BASE/api/upload" \
  -F "process=$PROCESS" \
  -F "material_type=申报模板" \
  -F "file=@/你的路径/申报模板.json"

curl -X POST "$BASE/api/upload" \
  -F "process=$PROCESS" \
  -F "material_type=申请书" \
  -F "file=@/你的路径/申请书.pdf"
```

最终审核时把多个 `file_id` 一起传入：

```json
"file_ids": ["file_id_1", "file_id_2"]
```

### 4.3 查看已上传材料

接口：

```http
GET /api/upload?process={process}
```

命令示例：

```bash
curl "$BASE/api/upload?process=$PROCESS"
```

### 4.4 查看材料解析结果

接口：

```http
GET /api/upload/{file_id}/extracted
```

命令示例：

```bash
FILE_ID="a1b2c3d4e5f6"

curl "$BASE/api/upload/$FILE_ID/extracted"
```

### 4.5 删除材料

接口：

```http
DELETE /api/upload/{file_id}
```

命令示例：

```bash
curl -X DELETE "$BASE/api/upload/$FILE_ID"
```

## 5. 使用后端样例材料

如果只是测试接口，可以不手动上传材料，直接加载服务器 `backend/samples/` 目录下的样例。

### 5.1 查看有哪些样例

接口：

```http
GET /api/samples
```

命令示例：

```bash
curl "$BASE/api/samples"
```

返回会按流程分组，例如：

```json
{
  "pre_registration": [
    {
      "name": "预登记申报模板_新预登记.json",
      "size_bytes": 12345,
      "material_type": "申报模板"
    }
  ]
}
```

### 5.2 加载某个流程的样例

接口：

```http
POST /api/samples/load
```

命令示例：

```bash
curl -X POST "$BASE/api/samples/load" \
  -H "Content-Type: application/json" \
  -d "{\"process\":\"$PROCESS\"}"
```

成功返回示例：

```json
{
  "process": "pre_registration",
  "files": [
    {
      "file_id": "abc123def456",
      "original_name": "预登记申报模板_新预登记.json",
      "material_type": "申报模板",
      "parse_status": "已解析"
    }
  ],
  "skipped": []
}
```

说明：

- `files` 中的 `file_id` 可直接用于审核
- 如果样例已经加载过，接口可能返回 `skipped`
- 样例加载后，也会出现在网页的上传材料列表中

## 6. 审核 API

### 6.1 发起审核

接口：

```http
POST /api/review
```

关键参数：

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `process` | 是 | 流程类型 |
| `file_ids` | 是 | 材料 ID 数组 |
| `rule_set_id` | 否 | 上传规则版本 ID；建议显式传入 |
| `include_builtin_rules` | 否 | 是否启用内置规则，默认 `true` |
| `max_concurrency` | 否 | 并发数，默认 `48` |
| `material_slice_enabled` | 否 | 是否启用材料切片，默认 `false` |

### 6.2 只使用上传规则，不使用内置规则

如果不想用网页内置规则，必须设置：

```json
"include_builtin_rules": false
```

推荐同时传入本次要使用的 `rule_set_id`。

命令示例：

```bash
curl -X POST "$BASE/api/review" \
  -H "Content-Type: application/json" \
  -d '{
    "process": "pre_registration",
    "file_ids": ["abc123def456", "def456abc123"],
    "rule_set_id": "pre_registration_1783674842_534d3d",
    "include_builtin_rules": false,
    "max_concurrency": 48,
    "material_slice_enabled": false
  }'
```

成功返回：

```json
{
  "job_id": "review_xxxxx",
  "status": "pending"
}
```

请记录 `job_id`，用于查询进度和结果。

### 6.3 查看审核进度（SSE 流）

接口：

```http
GET /api/review/{job_id}/stream
```

命令示例：

```bash
JOB_ID="review_xxxxx"

curl -N "$BASE/api/review/$JOB_ID/stream"
```

说明：

- `curl -N` 表示不缓存输出，适合看实时进度
- 审核完成时会收到 `event: done`
- 审核失败时会收到 `event: failed`

### 6.4 查询审核结果

接口：

```http
GET /api/review/{job_id}
```

命令示例：

```bash
curl "$BASE/api/review/$JOB_ID"
```

返回示例：

```json
{
  "job_id": "review_xxxxx",
  "process": "pre_registration",
  "status": "done",
  "error": null,
  "result": {
    "summary": {
      "registration_type": "预登记",
      "total_issues": 3,
      "high_risk_count": 1,
      "medium_risk_count": 2,
      "low_risk_count": 0
    },
    "issues": [],
    "human_review_items": [],
    "batch_logs": []
  },
  "progress_log": []
}
```

重点字段：

- `status`: `pending` / `running` / `done` / `failed` / `cancelled`
- `error`: 失败原因
- `result.summary`: 审核汇总
- `result.issues`: 审核问题列表
- `result.batch_logs`: 分批调用日志

### 6.5 取消审核

接口：

```http
POST /api/review/{job_id}/cancel
```

命令示例：

```bash
curl -X POST "$BASE/api/review/$JOB_ID/cancel"
```

## 7. 完整示例：上传规则 + 使用样例 + 关闭内置规则审核

下面示例演示：

- 上传一份 AI 审核规则
- 加载后端样例材料
- 不启用内置规则
- 发起审核并查询结果

```bash
BASE="http://192.168.21.103:28101"
PROCESS="pre_registration"

# 1. 上传规则
curl -X POST "$BASE/api/rule-sets/import?process=$PROCESS" \
  -F "file=@/你的路径/审核规则.xlsx"

# 假设上一步返回 rule_set_id
RULE_SET_ID="pre_registration_1783674842_534d3d"

# 2. 可选：启用规则，让网页也默认使用它
curl -X POST "$BASE/api/rule-sets/$RULE_SET_ID/activate"

# 3. 加载样例材料
curl -X POST "$BASE/api/samples/load" \
  -H "Content-Type: application/json" \
  -d "{\"process\":\"$PROCESS\"}"

# 假设上一步返回两个 file_id
FILE_ID_1="abc123def456"
FILE_ID_2="def456abc123"

# 4. 发起审核：关闭内置规则
curl -X POST "$BASE/api/review" \
  -H "Content-Type: application/json" \
  -d "{
    \"process\": \"$PROCESS\",
    \"file_ids\": [\"$FILE_ID_1\", \"$FILE_ID_2\"],
    \"rule_set_id\": \"$RULE_SET_ID\",
    \"include_builtin_rules\": false,
    \"max_concurrency\": 48,
    \"material_slice_enabled\": false
  }"

# 假设上一步返回 job_id
JOB_ID="review_xxxxx"

# 5. 看实时进度
curl -N "$BASE/api/review/$JOB_ID/stream"

# 6. 查最终结果
curl "$BASE/api/review/$JOB_ID"
```

## 8. 完整示例：上传规则 + 上传自己的材料 + 关闭内置规则审核

```bash
BASE="http://192.168.21.103:28101"
PROCESS="pre_registration"

# 1. 上传规则
curl -X POST "$BASE/api/rule-sets/import?process=$PROCESS" \
  -F "file=@/你的路径/审核规则.xlsx"

RULE_SET_ID="替换为返回的rule_set_id"

# 2. 上传申报模板
curl -X POST "$BASE/api/upload" \
  -F "process=$PROCESS" \
  -F "material_type=申报模板" \
  -F "file=@/你的路径/申报模板.json"

TEMPLATE_FILE_ID="替换为返回的file_id"

# 3. 上传申请书
curl -X POST "$BASE/api/upload" \
  -F "process=$PROCESS" \
  -F "material_type=申请书" \
  -F "file=@/你的路径/申请书.pdf"

APPLICATION_FILE_ID="替换为返回的file_id"

# 4. 发起审核：关闭内置规则
curl -X POST "$BASE/api/review" \
  -H "Content-Type: application/json" \
  -d "{
    \"process\": \"$PROCESS\",
    \"file_ids\": [\"$TEMPLATE_FILE_ID\", \"$APPLICATION_FILE_ID\"],
    \"rule_set_id\": \"$RULE_SET_ID\",
    \"include_builtin_rules\": false,
    \"max_concurrency\": 48,
    \"material_slice_enabled\": false
  }"
```

## 9. 常见问题

### 9.1 API 上传的新规则会替换网页上的规则吗？

上传后会新增一个规则版本，不会自动删除旧版本。

如果调用：

```bash
curl -X POST "$BASE/api/rule-sets/$RULE_SET_ID/activate"
```

则该规则会成为网页当前流程的启用版本，旧版本仍保留但不启用。

如果审核请求中显式传：

```json
"rule_set_id": "指定规则版本ID"
```

则本次审核会使用该规则版本，不依赖网页当前启用状态。

### 9.2 如何确保完全不使用内置规则？

发起审核时传：

```json
"include_builtin_rules": false
```

并传入上传规则版本：

```json
"rule_set_id": "你的上传规则版本ID"
```

### 9.3 为什么上传材料后不能审核？

常见原因：

- `file_ids` 为空
- 材料解析失败，`parse_status` 不是 `已解析`
- `process` 和材料所属流程不一致
- 没有可用规则：关闭内置规则后，又没有传 `rule_set_id`

可通过以下接口检查材料：

```bash
curl "$BASE/api/upload?process=$PROCESS"
```

### 9.4 为什么规则上传失败？

常见原因：

- 文件不是 `.xlsx` 或 `.xlsm`
- 规则表没有 `AI审核规则` 或 `脚本审核规则`
- 缺少必要列：`规则ID`、`具体规则`
- 同一个规则表中 `规则ID` 重复

### 9.5 如何让网页和 API 使用同一套规则？

上传规则后调用启用接口：

```bash
curl -X POST "$BASE/api/rule-sets/$RULE_SET_ID/activate"
```

这样网页会默认使用该规则版本；API 也可以通过传 `rule_set_id` 精确指定。
