# 统一仓库开发与上线检查

开发候选统一使用 fang1776358081-arch/local-service-factory，软件 vX.Y.Z 与规则 rules-整数版本独立发布。源码 push 不构建、不发布；规则 Release 固定不占 Latest。仓库是独立公开项目，不是原仓 fork；原仓只保留历史证据。未来发布仍须对应范围授权。

## 源码同步与签名索引

release-index.json 由规则发布的 Contents CAS 维护。源码导出不包含该文件，缺失不表示删除。禁止镜像覆盖 Git 副本、删除副本独有文件、把旧快照索引覆盖远端签名索引。导出后按共同基线逐文件审阅，只合并确认的源码变化。

规则发布会产生远端 Git 提交。发布后运行 `python development/sync_repository.py <Git副本路径>`：fetch 后干净且可快进时自动快进；有未提交修改或分叉时只报告 review_required，保留全部内容。审阅本地差异并提交已确认的本次文件，再 `git merge origin/main`，逐项解决源码冲突，签名索引以验证有效的远端发布结果为准；完成相关测试再推送。不得自动 stash/reset/clean/强推。

## 本地接口

命令使用 python factory.py updates/rules，通过 JSON 标准输入提供参数。

- 软件 release-plan 检查 directory 下三类附件和 build-provenance.json；publish 必须回传 files/source_sha 及已有范围授权。正式暂存/构建要求干净已提交源码；stage-provenance.json 绑定引擎文件清单与源码。
- target 默认为 unified；legacy-software 仅允许记录的旧软件仓。包内地址保持新仓；旧仓标签绑定旧仓提交，清单 source_sha 始终指向新仓源码。旧仓推进前验证新仓软件与规则通道。
- updates recover 默认只读；完整公开版本验证通过后，显式 finalize_software_recovery 及一致 files/source_sha 才可完成指针/锁。草稿、缺附件、不明上传仍需人工核对，不能盲目重放或删除锁。
- rules release-plan 首次迁移显式 migration_from_legacy=true；验证旧索引签名，保存旧版本下界，不覆盖旧缓存。新版本严格更高，新 URL 重新签名。后续正常 sync 建立同仓基准。
- rules publish 回传 version 和 publish_project_update；失败保留当前索引。回退使用更高版本，保留原内容 source_sha，缺来源的历史计划不得伪造关联。

## 上线清单（M5—M6，2026-11-14 验收）

- [x] 获得构建、公开及迁移发布范围授权；复查远端 SHA/全部分支标签、附件、自动化和公开安全，确认许可证选择未被擅改。
- [x] 审阅全部候选差异和未跟踪文件，提交并同步统一仓源码；核实仓库可见性、公钥及既有私钥匹配。
- [x] 选择高于远端 1.4.17 的软件版本，同步 package/lock/engine 版本，保留应用身份、安装目录和用户数据目录。
- [x] 正式暂存独立运行环境，验证 stage-provenance；明确授权后构建一次，保留 build-provenance、源码 SHA、附件摘要和验证日志。
- [x] 按公开审查结论切换可见性；匿名确认源码及下载入口，无 token 植入客户端。
- [x] 新仓发布软件并公开读回全部附件、签名；只在成功后设 Latest。
- [x] 验签旧规则索引，以更高版本初始化新仓规则；确认 min_app、重新签名 URL、公开 ZIP/manifest 摘要与索引 CAS。
- [x] 全新隔离使用端匿名安装与同步，updated→current；记录实际软件/规则版本及数据路径。
- [x] 同一构建以 legacy-software 发布过渡版，四类资源双仓摘要及签名清单字节完全一致；新通道可用后才推进旧 Latest。
- [x] 真实旧版从旧源升级，后续请求新源；验证活动任务阻止安装、旧冻结任务/额度/原图/私有配置保留。
- [x] 验证离线、下载失败、损坏签名不切换；previous-app 与已验证安装器恢复入口可用。错误规则以更高版本回退。
- [x] 同步发布产生的 Git 索引提交，完成源码再次推送不丢索引的检查；更新新旧 README 入口与版本证据。
- [x] 保留旧仓历史下载与过渡包；未满足 M7 条件不归档、不删除、不声称所有用户已升级。

任何写请求结果不明先核对远端，保留锁/草稿/附件证据。真实安装与公开下载证据必须在上线阶段采集，本地测试不能代替。

实际证据、两次本机隔离偏差与恢复记录见 [M5_M6_RELEASE_VALIDATION.md](M5_M6_RELEASE_VALIDATION.md)。本次是实际用户级安装验证，安装范围由测试启动器限定，升级后显式隔离启动；不代表全新虚拟机或所有机器级安装均已验收。下一次安装验收使用独立 Windows 用户/虚拟机，避免复用默认资料目录。
