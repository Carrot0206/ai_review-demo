# 一键部署说明

## 日常部署或首次安装

在本地项目根目录执行：

```bash
cd "/Users/xieyinghan/Downloads/ai审核信托产品登记demo/trust-rule-engine"
./deploy/upload_and_update.sh root@192.168.21.103
```

同一个命令同时支持首次安装和后续更新，会自动完成：

- 前端lint与生产构建；
- 生成不包含密钥、虚拟环境和运行数据的部署包；
- 上传并备份服务器现有程序；
- 安装/更新Python依赖及systemd服务；
- 安装整合后的Nginx配置并执行健康检查。

默认保留服务器的规则库、审核任务数据库、上传材料和API Key。若明确需要用本地规则库覆盖服务器规则库，执行：

```bash
./deploy/upload_and_update.sh root@192.168.21.103 --sync-rules
```

覆盖前脚本会自动备份服务器的 `rules.json`。

## 数据与服务

目标部署目录：

- 原审核Demo：`/opt/trust-ai-review-demo`
- 规则库与规则引擎：`/opt/trust-rule-engine`
- 可写规则数据：`/opt/trust-rule-engine-data/rules.json`
- 审核任务数据库：`/opt/trust-rule-engine-data/rule_engine.db`
- 上传材料与解析结果：`/opt/trust-rule-engine-data/materials`

真实模型配置保存在服务器 `/etc/trust-rule-engine/backend.env`，不会进入部署包。首次部署后编辑：

```bash
nano /etc/trust-rule-engine/backend.env
systemctl restart trust-rule-engine
```

至少填写：

```env
DEEPSEEK_API_KEY=你的API_KEY
```

## 验证

```bash
ssh root@192.168.21.103
systemctl status trust-rule-engine --no-pager
curl http://127.0.0.1:18102/api/rule-engine/health
curl 'http://127.0.0.1:28101/api/rule-library/rules?process=pre_registration'
```

访问地址：

- 规则库：`http://192.168.21.103:28101/rule-library/`
- 登记审核：`http://192.168.21.103:28101/rule-library/review`

规则引擎必须保持单个 Uvicorn worker；当前全局并发信号量和内存任务调度器以单进程为边界。
新审核页面的材料上传、解析和审核均由规则引擎提供，不需要启动原审核Demo后端。
实际登记JSON的四流程字段映射已生成在代码目录 `backend/data/template_mappings`，服务器运行时不读取或部署原始XLSM。

当前服务器因Python运行环境位于 `/root/miniconda3`，规则引擎systemd服务暂时使用root用户运行。服务仍启用 `NoNewPrivileges`、`PrivateTmp` 和 `ProtectSystem=full`；后续迁移到 `/opt` 独立Python环境后，应恢复为 `trustreview` 用户。
