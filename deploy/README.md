# 部署说明

## 安全约定

- 不要把 `backend/.env` 打包、提交或发给别人。
- 真实大模型 Key 只写到服务器 `/etc/trust-ai-review-demo/backend.env`。
- 后端只监听 `127.0.0.1:18101`，外部统一通过 Nginx 的 `28101` 端口访问。

## 一键上传并安装

在本地项目根目录执行：

```bash
chmod +x deploy/*.sh
./deploy/upload_and_install.sh root@192.168.21.103
```

脚本会提示输入服务器密码，但不会保存密码。

## 日常更新（推荐）

网页、规则库页面或后端代码更新后，在本地项目根目录执行：

```bash
./deploy/upload_and_update.sh root@192.168.21.103
```

此脚本会重新构建前端、上传更新包并重启后端服务。它会在服务器的
`/opt/` 下保留一个带时间戳的完整备份，并保留以下运行数据：

- `/etc/trust-ai-review-demo/backend.env` 中的 DeepSeek Key；
- 已上传的材料和审核输出；
- 已通过网页或 API 导入的规则集；
- 规则库网页中已保存的规则。

更新期间后端会有数秒不可用；Nginx、端口、防火墙和现有 systemd 服务配置
不会被重新安装或修改。更新完成后浏览器请使用强制刷新（macOS：`Command + Shift + R`）。

如果更新同时包含了要覆盖服务器现有“规则库内容”或“已导入规则集”的数据，
请先导出或备份服务器数据；默认更新策略以保护服务器上正在使用的数据为准。

## 首次部署后配置 Key

登录服务器：

```bash
ssh root@192.168.21.103
nano /etc/trust-ai-review-demo/backend.env
systemctl restart trust-ai-review-demo
```

## 验证

```bash
curl http://127.0.0.1:18101/api/health
systemctl status trust-ai-review-demo --no-pager
systemctl status nginx --no-pager
```

浏览器访问：

```text
http://192.168.21.103:28101
```
