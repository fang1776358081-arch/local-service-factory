---
name: factory-push-source
description: 整理本地生活服务图片工厂开发源码、Agent 指引和项目 skills，脱敏审阅后提交并推送到统一 GitHub 仓库，支持原生产目录重新导出及跨电脑 Git 同步。用于推送开发 Agent、备份开发源码或开发完成后同步；安装包发布和云端规则发布使用各自发布 skill。
---

# 推送开发 Agent 到 GitHub

同步可迁移的源码、配置模板、Agent 指引和项目 skills，让其他电脑能够克隆并继续开发。这里的 Agent 指项目内指引与技能；Codex 模型、对话历史、账号登录和个人运行环境不在同步范围。


## 单仓迁移与同步

以根目录 development/REPOSITORY_MIGRATION.md 为最新约定：源码、软件与规则共仓但独立发布；不要求源码永久私有。普通开发不构建/发布/改可见性。旧仓记录及链接是历史，不是当前默认目标。

保留 release-index.json 和规则发布生成的远端提交。发布后运行 development/sync_repository.py 核对并快进；脏工作树或分叉先保留、审阅、提交明确归属变化后合并，禁止自动 stash/reset/强推。源码导出缺文件不代表应删除。

正式软件与规则发布计划绑定干净已提交源码 SHA；软件构建保存 stage-provenance/build-provenance，发布回传 source_sha。过渡 target=legacy-software 不改变包内新地址；首次规则迁移显式 migration_from_legacy=true，按执行台账的旧版本下界验证。updates recover 默认只读，明确恢复授权才完成已验证公开版本指针，不重传不明附件。

## 入口与范围

- 当前开发仓库：`fang1776358081-arch/local-service-factory`；它是独立公开项目，不是原仓 fork。核实实际可见性和 remote 身份，不能从本机 Git 作者猜目标仓库，公开仅按迁移授权执行。
- 当前原生产目录：`<local-path>`；Git 开发副本：`<local-path>`。换电脑以实际 Git 根目录、remote 和源码位置为准。
- 先读工作区 `AGENTS.md`、`agent_memory/current_state.md` 和 `development/README.md`。
- 用户要求推送/同步开发源码时，完成必要的导出、审阅、提交、推送及验证，无须重复询问已授权动作。仅创建 skill、检查状态或开发功能不授权推送；用户说等另一任务完成，就等完成后再执行。
- 同一批文件仍由其他对话修改时，保留现状；未获完成信息前不导出变化中的快照或替对方提交，不自行给其他对话发送消息。
- 本流程不构建安装包、不发布规则、不生图。安装包用 `factory-release-installer`，云端规则用 `factory-release-rules`。

## 选择同步路线

### 已在 Git 开发副本

核实分支、remote、工作区变更与远端状态，检查已有修改归属。获取远端更新后，在干净工作区使用快进拉取；双方都有改动则保留两边并合并，不强推、硬重置或整目录覆盖。审阅本次源码差异，再提交推送。

### 仍在原生产目录开发

读取 [references/production-export.md](references/production-export.md)。使用项目 `development/export_source.py` 导出到全新目录，将已审阅源码差异合并到 Git 副本。导出物是脱敏快照，不是生产备份，也不会自动同步到 Git。缺失文件不自动视为应删除文件；保留开发副本独有文档、技能与其他电脑的改动。

## 提交与验收

1. 检查状态、差异统计与明确文件内容；单独审阅未跟踪文件。只暂存本次确认文件，不在生产根目录盲目执行 `git add -A`。`.gitignore` 不能保护已跟踪秘密。
2. 密钥、客户资料、生产许可、图片、任务/日志、签名私钥、依赖与构建产物不提交。敏感扫描只报告路径和问题类型，不输出秘密。保留测试用合成号码和公开锁文件哈希，不能批量替换这些内容。
3. 按实际改动做必要本地检查。修改提示词/批次逻辑遵循项目 audit 要求；不能运行任何 dry-run 或整个 `tests.test_factory_safety`，不触发付费生成。仅文档/skill 变更验证结构、引用与 UTF-8 即可。
4. 提交说明描述具体变更，推送已核实目标分支。验证远端分支 SHA 与本地 HEAD 一致，检查剩余变更。无变化则报告已经同步，不制造空提交。
5. 首次导出、迁移技能位置或更改导出规则时，用独立临时克隆验证入口及完整性；日常改动不重复安装全部依赖。记录源目录、Git 目录、提交 SHA、检查结果和未同步部分。

认证、远端更新和中断恢复见 [references/git-operations.md](references/git-operations.md)。推送结果不明确先核对远端 SHA，网络故障最多再推送一次。缺权限、目标不明或冲突取舍无法确定时，保留全部修改并提出具体问题。

最终给出开发仓库链接、提交 SHA 和检查结果。原生产目录后续修改仍需再次整理同步；源码推送不意味着用户端软件或规则已更新。
