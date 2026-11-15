# 新电脑开发与 Codex 接续

目标独立公开仓库为 `fang1776358081-arch/local-service-factory`，不是原仓 fork。

## 环境基线

源码确认的最低开发环境：

- Windows x64、Git。
- Python 3.11 或更新版本；正式包内运行时固定为 CPython 3.11.9 x64，下载地址和 SHA-256 在 `distribution/python-runtime.json`。
- Node.js 22 或更新版本。`package-lock.json` 当前实际锁定 Electron 37.10.3、electron-builder 26.15.3、electron-updater 6.8.9。
- 不要求全局安装 Electron；使用 `npm ci` 恢复锁文件依赖。

## 克隆、安装和开发启动

```powershell
git clone https://github.com/fang1776358081-arch/local-service-factory.git
Set-Location local-service-factory
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install --require-hashes -r distribution\requirements-runtime.lock
npm --prefix dashboard ci
New-Item -ItemType Directory -Force output | Out-Null
$env:ROAD_RESCUE_PYTHON = (Resolve-Path .venv\Scripts\python.exe).Path
npm --prefix dashboard start
```

`output/` 是被 `.gitignore` 排除的本地运行目录；干净克隆必须先创建，否则源码看板无法确认项目根。`requirements.txt` 只锁直接依赖，可能在不同日期解析到不同传递依赖，所以接续命令直接使用完整哈希锁。正式发布还必须使用 `distribution/python-runtime.json` 的固定运行时，不能把开发机当前 Python 直接冒充正式包内运行时。

## 首次核对

```powershell
git status --short --branch
git remote -v
git show-ref --heads --tags
.venv\Scripts\python.exe -m unittest tests.test_repository_migration
node dashboard/tests/build-config.test.js
```

不要运行 dry-run，不要运行整个 `tests.test_factory_safety`。按改动选择相关小模块。启动看板前设置独立测试资料目录，避免连接生产 workspace；不执行付费生图。

## 四类接续内容

1. 仓库内内容：源码、`AGENTS.md`、`.agents/skills/`、开发/验收/迁移文档、标签和 Release。通过 Git 和 GitHub Release 取得。
2. 本机个人 skills：`%USERPROFILE%\.codex\skills`。只迁移确实需要且允许共享的个人技能；先检查是否包含账号、绝对路径或私人资料。项目发布技能以仓库 `.agents/skills/` 为准。
3. Codex 插件和登录：不在 Git 中。新电脑安装相同插件并重新登录 Codex/GitHub；旧聊天记录不是项目依赖。
4. 私人运行资料和发布秘密：不入 Git、不放公开 Release。通过用户自己的加密移动盘或受控私有存储迁移。

## 私人资料备份与恢复

当前电脑已确认的主要源目录：

- `%APPDATA%\road-rescue-dashboard`：安装版 userData；其 `workspace` 含任务、规则状态、配置和图片索引。
- `D:\桌面\货修素材`：用户导出的货修素材。
- `E:\AppData\RoadRescueDashboard`：存在本地资料，迁移前需由用户确认用途。
- `E:\道路救援看板\road-rescue-dashboard`：正式程序目录，不作为源码仓；新电脑优先从已验证安装包重装，不整目录覆盖。

备份目标必须是用户指定的加密外置盘或私有目录。示例只复制，不删除源和目标，不使用 `/MIR`：

```powershell
$backupRoot = 'X:\RoadRescuePrivateBackup-YYYYMMDD'
robocopy "$env:APPDATA\road-rescue-dashboard" "$backupRoot\road-rescue-dashboard" /E /COPY:DAT /DCOPY:DAT /R:2 /W:2 /XJ
robocopy 'D:\桌面\货修素材' "$backupRoot\货修素材" /E /COPY:DAT /DCOPY:DAT /R:2 /W:2 /XJ
robocopy 'E:\AppData\RoadRescueDashboard' "$backupRoot\E-AppData-RoadRescueDashboard" /E /COPY:DAT /DCOPY:DAT /R:2 /W:2 /XJ
```

单独安全迁移以下秘密：`.env`/API Key、GitHub/Codex 登录、Ed25519 发布私钥、可选 Authenticode 证书和密码。不得在聊天、Git、公开云盘或迁移日志中展示。发布私钥迁移后先用现有公钥做内存挑战验签；不匹配时阻塞发布，不换钥冒充旧信任链。

恢复顺序：安装软件但先不启动；恢复 `%APPDATA%\road-rescue-dashboard`；核对文件数和私有校验清单；再启动并只读检查项目、批次、规则版本和图片引用。没有新电脑访问权限时，只能报告“备份方案已准备”，不能报告“新电脑已验证”。

## 已知绝对路径依赖

- `development/export_source.py` 仅包含旧用户名路径到项目 skill 的脱敏替换规则，不应成为运行依赖。
- `factory.py` 的 `E:/Downloads/image_model_tests` 和 `tools/pinned_triptych.py` 的 `E:/Downloads` 是维护/导出默认路径；新电脑可显式传目标参数，迁移代码时应评估改成用户目录或配置项。
- `tools/validate_cover_text.py` 检查标准 Tesseract 安装路径；未安装 Tesseract 时相关 OCR 验证不可用，应明确记录，不应伪报通过。

## 可直接发给新 Codex 的启动提示词

> 这是道路救援图片工厂的新电脑开发接续。先读取仓库根 `AGENTS.md`、`agent_memory/current_state.md`、`development/GITHUB_ACCOUNT_MIGRATION.md`、`development/NEW_PC_HANDOFF.md`、`development/REPOSITORY_MIGRATION.md` 和 `development/UNIFIED_REPOSITORY_EXECUTION_PLAN.md`，再读取与任务相关的 `.agents/skills/`。核对当前 Git 分支、远端、HEAD、标签、Release Latest、规则签名索引和工作树，不把生产目录当 Git 副本。当前正式版本和迁移完成状态以远端及 `agent_memory/current_state.md` 为准。禁止输出或提交 API Key、GitHub Token、签名私钥、客户号码、任务、图片和运行日志；不运行 dry-run，不运行整个 `tests.test_factory_safety`，不执行付费生图。发布软件和规则必须分别使用项目 skill、保留 Ed25519 信任链，并先确认明确的发布授权。发现未提交修改、远端冲突、签名不匹配或私人数据时停止写入并具体汇报。

## 新电脑仍需实测

- 官方 GitHub/Codex 登录和目标仓写权限。
- `npm ci`、Python 依赖安装以及相关小模块测试。
- 独立测试资料目录下的开发看板启动。
- 发布私钥与现有公钥匹配；若不需要发布，不迁移私钥。
- 私人备份恢复后的任务、原图、规则和配置完整性。
