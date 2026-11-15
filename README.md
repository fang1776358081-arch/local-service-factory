# 本地生活服务图片工厂

本仓库维护源码、Windows 软件与项目规则的统一发布流程。统一仓库已公开，软件 1.4.19 与规则 1794662868654979100 已发布；旧仓保留过渡包和历史下载。

- 安装使用：从[软件 1.4.22](https://github.com/fang1776358081-arch/local-service-factory/releases/tag/v1.4.22) 下载 LocalServiceFactory-1.4.22-setup.exe。GitHub Source code ZIP 只是源码，不是安装包。
- 旧版过渡与历史下载：[旧软件仓](https://github.com/eish1997/local-service-factory-releases/releases/latest)。旧规则仓保留历史与过渡入口。
- 规则以 rules-递增版本标签独立发布，通过签名 release-index.json 发现；更新规则通常不需要重装软件，最低兼容版本由清单约束。
- [开发与 Git 同步](development/README.md) · [迁移与完整上线清单](development/REPOSITORY_MIGRATION.md) · [执行台账](development/UNIFIED_REPOSITORY_EXECUTION_PLAN.md)
- [Agent 入口](AGENTS.md) · [完整帮助](HELP.md) · [统一任务接口](TASK_WORKFLOW.md)
- [工厂 skill](.agents/skills/road-rescue-factory/SKILL.md) · [软件发布](.agents/skills/factory-release-installer/SKILL.md) · [规则发布](.agents/skills/factory-release-rules/SKILL.md)

源码推送不自动发布或生图。客户数据、API 凭据、签名私钥、图片和任务历史不进入仓库。仓库公开不代表已选择开源许可证。

迁移验收与范围见 [M5—M6 上线证据](development/M5_M6_RELEASE_VALIDATION.md)。安装包沿用 Ed25519 更新验签，没有 Windows Authenticode 发布者证书。旧安装可经旧仓 1.4.18 过渡包切换新源；不需要迁移客户资料目录。
