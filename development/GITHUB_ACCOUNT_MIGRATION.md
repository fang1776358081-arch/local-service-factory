# GitHub 账号与仓库迁移执行记录

状态：执行中。目标独立公开仓库为 `fang1776358081-arch/local-service-factory`，不是原仓 fork。

## 已核实源端基线

- 源仓库：`eish1997/local-service-factory-dev`，公开，默认分支 `main`，未归档。
- 2026-11-15 核对的 `main`：`8f8d0b17f03de3a69c0759ed7e1bad9233122f5f`。
- 可达历史：11 个提交；远端只有 `main` 一个分支。
- 标签：`v1.4.18`、`v1.4.19`、`v1.4.22`、`rules-1794662868654979100`。
- Release：上述四个标签各一个，共 14 个附件；`Latest` 为 `v1.4.22`，规则 Release 不占 Latest。
- GitHub Actions：无工作流。仓库根目录没有 LICENSE/COPYING/NOTICE；npm 元数据为 `UNLICENSED`。迁移保留全部作者和提交信息，不擅自改变许可。
- 本机原 F 盘维护副本当前不可访问；迁移源是从公开远端取得的完整镜像。若原维护副本之后重新可用，必须先检查是否有未推送提交，不能把生产根目录当成 Git 副本。
- 本机 GitHub CLI 钥匙串当前登录为 `fang1776358081-arch`，对源仓只有 READ；浏览器当前未登录。该账号是否为目标账号仍需用户确认。

## 安全审查结论和停止条件

已检查全部可达提交和 blob：未发现私钥头、GitHub Token、AWS 凭证或大于 2 MiB 的 Git blob。两类表面命中已确认是测试结果文件名和测试夹具文字，不是真实凭证。

`development/CODEX_NATIVE_VALIDATION.md` 含一个只在该验收文档出现、且被原文明确标为测试手机号的值。用户随后明确要求“完整拉取原仓”并建立独立项目，因此保留已经公开的原提交和签名来源 SHA；当前配置和本次新增文档不再引入号码。若以后确认该值属于私人资料，应单独制定历史清理和签名来源处置方案，不能在迁移中静默改写提交、导致既有签名清单的 `source_sha` 失效。

发现其他秘密、私人数据、目标仓非空、标签或 Release 冲突、签名私钥不匹配时立即停止对应写入。报告路径和类型，不输出秘密正文。

## Release 附件验证

源端 14 个附件已下载到本机迁移缓存 `E:\Downloads\road-rescue-migration-20261115\releases`，不进入 Git：

- 三个软件版本的全部附件与 GitHub API SHA-256 一致；三个 `software-manifest.json` 均通过现有 Ed25519 公钥验证，附件摘要全部匹配。
- 规则 `rules.zip`、`manifest.json` 与 GitHub API SHA-256 一致；签名有效，ZIP 内 40/40 文件摘要匹配。
- 仓库根 `release-index.json` 与规则 Release 的 `manifest.json` 逐字节语义一致，签名有效。

这些缓存是迁移既有 Release 的可信输入，不是新的构建产物。复制后仍须从目标仓匿名重新下载并复核摘要和签名。

## 目标仓写入顺序

目标仓必须由用户指定并确认是空的公开仓。不要初始化 README、LICENSE 或 `.gitignore`，不要覆盖已有内容。

1. 通过 GitHub 官方 CLI 创建 `fang1776358081-arch/local-service-factory`，visibility=PUBLIC，不初始化内容。
2. 再次核对源 `main`、全部分支/标签和目标空仓状态。
3. 推送分支和标签，不使用强推，不使用会删除目标引用的镜像覆盖：

   ```powershell
   git remote add source https://github.com/eish1997/local-service-factory-dev.git
   git remote add new https://github.com/fang1776358081-arch/local-service-factory.git
   git fetch source --prune --tags
   git push new --all
   git push new --tags
   ```

4. 核对目标分支/标签对象与源端一致；再按原标签、标题、正文、draft/prerelease 状态创建四个 Release，上传已验证的 14 个附件。软件 `v1.4.22` 最后设为 Latest；规则 Release 必须保持非 Latest。
5. 从目标仓匿名下载全部附件，核对大小、SHA-256、软件签名、规则签名和 ZIP 内成员。
6. 修改实际生效配置、发布工具、项目 skills 和文档中的当前仓库身份；历史验收事实中的旧链接保留并明确标注“历史/过渡”，不机械替换。

## 老用户更新过渡

仅复制 `v1.4.22` 不能让已安装软件迁移，因为 1.4.22 包内仍指向源仓。完整过渡需要一个更高的软件版本，建议 `v1.4.23`：

1. `distribution/update-config.json`、`dashboard/package.json` 及发布检查改为 `fang1776358081-arch/local-service-factory`，保留原公钥、应用身份、安装目录和用户数据目录。
2. 从固定源码提交构建一次 v1.4.23；同一组安装包、blockmap、latest.yml、签名清单先发布到新仓并匿名验证。
3. 规则下载 URL 属于签名 payload。目标仓需要一个严格高于 `1794662868654979100` 的迁移规则版本；内容可保持不变，但 URL 必须指向目标仓并使用原 Ed25519 私钥重新签名。规则 Release 不设 Latest。
4. 新仓软件、规则、签名索引全部可用后，把同一组 v1.4.23 软件附件发布到源仓，最后才推进源仓 Latest。这样旧版从源仓取得桥接包，安装后转向新仓。
5. 真实验证：有任务时拒绝安装；无任务完成升级；重启后软件和规则请求均走新仓；旧任务、冻结规则、原图、配置和请求计数保留。

构建和发布 v1.4.23、创建新的迁移规则版本属于新的实际发布。按照用户约束，应在代码、测试和发布计划准备完成后，再由用户确认该版本的构建/发布范围。不得为验证制造空版本，不得重复发布未变化的普通规则。

## 当前代码准备和验证

已在本地候选中把上一轮“同 owner 迁移”的硬编码改为显式旧仓身份：

- `legacy_software_repository.owner/repo` 控制源仓桥接软件目标和公开下载复核。
- `legacy_rules_repository.owner/repo` 控制已验签旧规则索引来源。
- 跨账号规则迁移会如实返回 `changed_files=[]`，同时保留迁移证据并生成指向新仓的签名 URL；普通无变化规则仍不发布。
- 未确认目标前没有把上述字段写入生效配置，没有改变 1.4.22 客户端地址。

当前候选验证：相关 Python 20 项通过，Node 构建配置 2 项通过，三个修改脚本 `py_compile` 通过，`git diff --check` 通过。干净克隆另外完成 Python 哈希锁安装、Python 13 项、Node 更新保护 14 项、`git fsck --full` 和隔离开发看板启动。首次启动因干净克隆缺少被忽略的 `output/` 失败，补充首次创建命令后九项目界面加载成功并退出，残留测试 Electron 进程为 0。

## 回退

- 新仓代码推送失败：源仓和现有用户不受影响；保留本地镜像，修复权限后继续，禁止强推。
- Release 复制不完整：不推进 Latest；保留目标 Release 现场，核对已上传附件后恢复。
- 新仓通道未完整验证：不发布源仓桥接版，旧用户继续使用 v1.4.22 和旧规则入口。
- 桥接软件故障：保留源仓 v1.4.22 下载和 previous-app 恢复；修复使用更高软件版本。
- 规则故障：活动索引不切换；回退内容也使用更高规则版本并重新签名。

## 尚未完成

- 新电脑目标位置仍待实机确认；当前电脑最终独立克隆放入当前项目目录。
- 恢复与现有公钥 `release-2026-09` 匹配的 Ed25519 发布私钥。本机环境变量和三个约定位置均未找到私钥；不得在聊天中发送或生成新钥冒充。
- 目标账号官方登录、空仓创建、推送与 Release 复制。
- 目标配置修改、桥接版代码和小范围测试。
- 用户确认桥接软件/迁移规则的实际构建与发布范围。
- 目标仓干净克隆和新电脑实机验证。
