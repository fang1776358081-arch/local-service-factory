---
name: factory-release-rules
description: "为本地生活服务图片工厂检查、脱敏、签名并发布项目规则、场景变量和提示词数据到 GitHub，验证使用端同步，或恢复中断规则发布。适用于发布项目规则、发布项目更新、回退规则内容；软件代码和安装包发布使用 factory-release-installer。"
---

# 发布项目规则


## 单仓迁移与同步

以根目录 development/REPOSITORY_MIGRATION.md 为最新约定：源码、软件与规则共仓但独立发布；不要求源码永久私有。普通开发不构建/发布/改可见性。旧仓记录及链接是历史，不是当前默认目标。

保留 release-index.json 和规则发布生成的远端提交。发布后运行 development/sync_repository.py 核对并快进；脏工作树或分叉先保留、审阅、提交明确归属变化后合并，禁止自动 stash/reset/强推。源码导出缺文件不代表应删除。

正式软件与规则发布计划绑定干净已提交源码 SHA；软件构建保存 stage-provenance/build-provenance，发布回传 source_sha。过渡 target=legacy-software 不改变包内新地址；首次规则迁移显式 migration_from_legacy=true，按执行台账的旧版本下界验证。updates recover 默认只读，明确恢复授权才完成已验证公开版本指针，不重传不明附件。

跨 GitHub 账号再次迁移时，旧规则入口必须由 `distribution/update-config.json` 的 `legacy_rules_repository.owner/repo` 明确列出。规则 URL 属于签名 payload；即使 40 个规则文件完全不变，换仓也必须生成更高迁移版本、重新签名目标 URL，并保持规则 Release 非 Latest。这是信任链迁移，不得伪报为规则内容变化或复用旧签名。

## 定位与范围

定位含 `factory.py`、`distribution/rules-fields.json` 的维护项目，当前为 `<project-root>`。先读项目 `AGENTS.md`、`agent_memory/current_state.md`、`distribution/README.md`；使用当前配置中的仓库、公钥和兼容版本，不固定历史版本号。

“发布项目规则/发布项目更新”授权检查、生成计划及规则上传，不需要重复询问发布确认。普通编辑、创建 skill 或咨询不自动授权上传。回退须有明确回退指令。此 skill 不构建安装包、不执行付费生图、不扩展业务白名单、不上传客户电话、密钥、图片或任务历史。

`configs/prompt_templates.json` 等受白名单允许的数据可独立发布；Python 提示词算法/引擎实现必须走软件更新。新数据需要代码支持时，先说明所需软件兼容版本，不擅自把代码塞入规则包。

## 发布步骤

1. 检查维护端身份：本次发布进程不能设置 `FACTORY_DATA_HOME`，`gh auth status` 和配置仓库写权限正常，签名私钥存在且公钥匹配。凭证不得输出、上传或进入计划。既有仓库无需重复创建或重新登录。
2. `python factory.py rules sync`，标准输入 `{}`。维护端仅检查远端并记录基准 SHA，不覆盖编辑文件。当前代码的 sync 失败必须处理后再生成计划，避免使用陈旧 `base_sha`。已有计划/Release 中断时先读 [recovery.md](references/recovery.md)，不能先创建另一个版本。
3. 若本次修改了提示词逻辑或批次数据，按项目指令运行 `python factory.py audit`；发布本身不重写旧批次或冻结提示词，也不触发生图。运行相关短模块，避免全量 safety 测试和任何 dry-run。
4. `rules release-plan` 输入 `{}`，由程序产生递增正整数字符串版本，导出白名单、脱敏、验证结构和当前八业务组装，并保存不可覆盖计划。检查 `changed_files`；无数据变化时报告无需发布，不为凑版本重复上传。唯一迁移例外是显式 `migration_from_legacy=true` 且计划含已验签旧仓身份：此时 `changed_files=[]` 仍可因目标 URL 变化发布更高迁移版本，但要如实记录“内容未变、签名 URL 已迁移”。详细数据/兼容约束见 [rules-and-consumer.md](references/rules-and-consumer.md)。
5. `rules publish` 输入 `{"version":"本次计划版本","authorization":"publish_project_update"}`。这个字段体现已有用户授权。程序签名并创建带 `rules.zip`、`manifest.json` 的 Release，公开下载通过后，以计划的 `base_sha` 更新 `release-index.json`。冲突不强推，按恢复流程重新 sync/评估。
6. 在全新隔离使用端验证 `rules sync`：设置仅此验证子进程的 `FACTORY_DATA_HOME`，使用兼容的独立引擎和内置 Python；首次返回 updated、本版活动指针和 manifest 一致，再次返回 current。还原环境后维护端再 sync，确认远端基准更新。本地模拟或仓库快照不代替真实下载、签名和激活验收。
7. 更新规则仓库 README 及 `agent_memory/current_state.md`，给出版本、变化范围、Release 链接和兼容要求。若失败说明停在哪一步、原活动规则是否保持，不声称已上线。

## 回退

用户明确要求回退时使用 `rules rollback`，输入历史计划版本 `from_version` 和 `authorization:"publish_project_update"`。复用验证过的历史数据，以新的更大规则版本发布；从不降低指针版本或覆盖旧计划。没有所需历史计划时先核对可恢复证据，不猜测内容。
