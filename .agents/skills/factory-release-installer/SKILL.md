---
name: factory-release-installer
description: "为本地生活服务图片工厂构建、验证并发布 Windows 独立安装包到 GitHub Releases，或恢复中断的软件发布。适用于发布新版安装包、发布软件更新、仅构建安装包；规则和提示词数据发布使用 factory-release-rules。"
---

# 发布新版安装包


## 单仓迁移与同步

以根目录 development/REPOSITORY_MIGRATION.md 为最新约定：源码、软件与规则共仓但独立发布；不要求源码永久私有。普通开发不构建/发布/改可见性。旧仓记录及链接是历史，不是当前默认目标。

保留 release-index.json 和规则发布生成的远端提交。发布后运行 development/sync_repository.py 核对并快进；脏工作树或分叉先保留、审阅、提交明确归属变化后合并，禁止自动 stash/reset/强推。源码导出缺文件不代表应删除。

正式软件与规则发布计划绑定干净已提交源码 SHA；软件构建保存 stage-provenance/build-provenance，发布回传 source_sha。过渡 target=legacy-software 不改变包内新地址；首次规则迁移显式 migration_from_legacy=true，按执行台账的旧版本下界验证。updates recover 默认只读，明确恢复授权才完成已验证公开版本指针，不重传不明附件。

跨 GitHub 账号再次迁移时，旧软件入口必须由 `distribution/update-config.json` 的 `legacy_software_repository.owner/repo` 明确列出；不能只改当前 owner 后沿用同名猜测。发布和公开下载验证都要分别核对目标 owner/repo，旧入口只用于同一桥接产物的过渡发布。

## 定位与授权

在含 `factory.py` 和 `distribution/update-config.json` 的维护项目执行。当前项目为 `<project-root>`；优先使用用户指定项目，不能把本 skill 泛用于其他软件。先读项目 `AGENTS.md`、`agent_memory/current_state.md`、`distribution/README.md`，以当前代码及配置为准，不沿用历史版本号。

- “发布新版安装包/发布软件更新”授权必要的版本调整、构建、验证和软件上传；已有授权不再次确认。“仅构建/不上传”止于本地产物。
- 询问发布方法、创建 skill、普通开发或修复不自动授权构建/发布。可先做只读检查和准备，缺少实际授权时在具体结果可审阅后询问。
- 不同时发布规则、不付费生图、不删除历史安装包/任务/图片、不新建仓库或配置第三方中转。
- 使用 `python factory.py updates ...` 的 JSON 标准输入接口。内部脚本仅用于诊断或恢复中断发布，不另建一套发布协议。

## 常规发布

1. 检查当前源版本、GitHub 最新版本及发布锁；确认 `gh auth status` 的账号和配置仓库写权限。凭证只经 keyring/私有环境读取，不能输出 token。先检查进程和确切 Release，再恢复未完成发布，不能直接重复执行 publish。
2. 用户指定版本时尊重指定值，否则选高于远端及本地版本的合适补丁版本。同步 `dashboard/package.json`、lockfile 顶层及根包版本、`distribution/update-config.json` 的 `app_version`。不降级、不覆盖同版已发布资源。保持可信公钥；私钥只在维护电脑。
3. 按 [build-and-verify.md](references/build-and-verify.md) 准备全新暂存目录、独立 Python 和 NSIS 安装包。输出用新的版本目录，避免覆盖旧产物。读配置确定运行时版本和摘要，不硬编码最近一次发布版本。
4. 运行与本次改动相关的短测试及独立运行验收。源码修改后重启开发看板。涉及更新器/安装布局/运行环境时验收实际 NSIS 和更新模块；普通功能补丁复用未变更更新链路的已有证据，避免无意义地重复大文件下载。不要把测试适配器或缓存复用称为真实旧版本整机升级。
5. `updates release-plan` 输入 `{"directory":"产物绝对路径"}`，保存返回的 `data` 为 `.runtime/updates/software-release-plan-<版本>.json`。确认三项资源摘要、版本一致和发布范围；`updates publish` 输入该 directory、files、source_sha、target 和 `authorization:"publish_software_update"`。授权字段是已有用户指令的机器标记，不是再次征求确认。
6. 成功需要：三项产物及 `software-manifest.json` 公开可下载，摘要与签名一致，GitHub 最新版本正确，自己的发布锁释放。服务端 digest 或上传成功不能代替公开下载校验。中断时按 [recovery.md](references/recovery.md) 继续同一发布。
7. 更新分发 README 和 `agent_memory/current_state.md`，记录版本、链接、SHA256、验收边界与恢复状态。仅报告真实完成事项；说明是否有 Authenticode 证书。最终给首次安装下载链接，说明以后启动/每六小时检查、无任务退出后安装。

## 减少等待

先复用通过摘要校验的官方 Python ZIP 和 wheelhouse；已验证且未改变的私有 Python 可复用，但每版重新暂存引擎与配置。公开校验时用 `scripts/verify_public_release.py --project-root <项目> --plan <已保存计划>`，有效下载直接复用，未完成安装包按分片续传。该 helper 只下载和核验，不上传、不设最新版、不处理锁。

`--cached-only` 用于复核既有公开下载证据；它不能证明文件来源。没有先前真实公开下载记录时，不得把本地构建包拷入缓存后声称下载验收通过。

长传输先报告阶段和真实进度；不要用预计完成时间替代事实。网络请求有时限，读请求可有界重试；写请求失败先查远端，不盲目重放。网络持续失败时保留计划、草稿和缓存，报告准确阻塞步骤，不能声称发布完成。
