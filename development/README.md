# 在另一台电脑开发

统一仓库为 `fang1776358081-arch/local-service-factory`，源码、软件和规则共仓但独立发布。仓库是独立公开项目，不是原仓 fork；旧仓只作为历史证据保留。提交源码不构建、不发布、不生图。流程与完整上线检查见 [迁移说明](REPOSITORY_MIGRATION.md)。

账号和仓库再次迁移的当前执行记录见 [GitHub 账号与仓库迁移](GITHUB_ACCOUNT_MIGRATION.md)；新电脑环境、私人资料边界和 Codex 接续见 [新电脑接续](NEW_PC_HANDOFF.md)。目标账号和仓库确认前，这两份文档中的占位符不得用于发布。

## 首次克隆

安装 Git、Python 3.11 或更新版本、Node.js 22 或更新版本，公开克隆不需要 GitHub 登录；推送或发布时才需要对应写权限。

```powershell
git clone https://github.com/fang1776358081-arch/local-service-factory.git
cd local-service-factory
py -3.11 -m venv .venv
.venv/Scripts/python.exe -m pip install --require-hashes -r distribution/requirements-runtime.lock
npm --prefix dashboard ci
New-Item -ItemType Directory -Force output | Out-Null
$env:ROAD_RESCUE_PYTHON = (Resolve-Path .venv/Scripts/python.exe).Path
npm --prefix dashboard start
```

`output/` 是被 `.gitignore` 排除的本地运行目录；干净克隆必须先创建，否则源码看板无法确认项目根。`requirements.txt` 只锁直接依赖，开发接续也优先使用上面的完整哈希锁，避免新电脑解析到不同传递依赖。

Agent 打开整个仓库并先读 AGENTS.md。项目 skill 位于 `.agents/skills/`，不依赖原电脑的个人 skill 目录。Agent 与看板使用同一解释器和公共命令；命令示例中的 python 可换成本机 `.venv/Scripts/python.exe`。

生产前通过本机 `.env`/看板密码表单配置密钥及已有可信渠道，明确本批次的组数、号码与范围。仓库不保存原电脑的客户资料、生成图片、任务许可、签名私钥或账号凭证；新电脑不能据此继续原电脑尚未同步的生产任务。

## 日常开发

```powershell
git pull --ff-only
# 修改代码，按 Agent 指引做相关检查
git status --short
git add <本次修改的源码或规则文件>
git commit -m "Describe the change"
git push
```

多台电脑先拉取后开发。有未提交变更时先检查并保留自己的修改，不用强推或硬重置覆盖另一台电脑。API密钥、客户记录、运行状态、node_modules与构建产物由.gitignore排除；提交前仍检查暂存内容，不新增秘密到受跟踪文件。

发布新版安装包使用 factory-release-installer；发布项目规则使用 factory-release-rules。发布需要本机 gh 登录及既有 Ed25519 发布私钥，私钥须通过用户自己的可信离线方式配置，不通过 Git 传输，也不能重新生成密钥冒充原公钥。

## 原生产工作区首次导出

`python development/export_source.py --destination <全新目录>` 只生成干净开发源码，复用规则白名单及脱敏逻辑，不上传、不复制运行数据、不覆盖已有 Git 工作副本。首次导出后在该副本初始化 Git 并推送。以后在克隆/开发副本中直接使用标准 Git 流程。

如果仍在原生产工作区修改，源码不会自动同步到开发副本；再次导出到新目录后审阅差异，再合并到 Git 副本。不要整目录覆盖已存在的开发副本或生产用户数据。

## 使用 skill 整理推送

开发任务完成后，在对话中调用：`使用 $factory-push-source，把已完成的开发源码和 Agent 指引整理并推送到已核实的统一仓库。`

该 skill 位于 `.agents/skills/factory-push-source/`，会判断当前是 Git 开发副本还是原生产目录，检查并合并远端改动，脱敏审阅、提交推送并验证远端提交。另一个对话仍在修改时等待开发完成；仅创建或查看 skill 不会触发推送。它与安装包发布、云端规则发布相互独立。
