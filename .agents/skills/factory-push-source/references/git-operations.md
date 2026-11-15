# Git 登录、跨电脑同步与恢复

## 定位与登录

路径和分支按当前电脑替换：

```powershell
git -C <local-path>
git -C <local-path>
git -C <local-path>
git -C <local-path>
gh auth status
gh repo view fang1776358081-arch/local-service-factory --json nameWithOwner,isPrivate,url,defaultBranchRef
```

检查 remote 前确保输出不会暴露嵌入 URL 的凭证；必要时先脱敏 URL，只显示主机、所有者和仓库。不要输出 token。浏览器登录不等于 CLI 登录。当前电脑工具常见位置为 `<local-path>`、`<local-path>`；PATH 缺失可直接使用。

缺登录则使用 `gh auth login` 的浏览器设备流程，用户自行完成授权。不要读取或写入 token；优先目标仓库现有 credential helper，当前开发副本通过 CLI `auth git-credential` 使用凭证。使用 `gh auth setup-git` 前确认配置范围。新电脑需独立登录。

已有仓库直接使用，不重建、不改公开、不误推到 releases/rules 仓库。只有用户指定才换目标。网络代理仅复用本机已配置代理，作用于本次进程，不改系统代理、不打印带凭证地址。

## 远端和并行修改

先 `git fetch origin`，核实 upstream 与双方提交差异。工作区干净且只有远端领先时 `git pull --ff-only`。有本地变更先确定归属，再提交已完成的本次工作或保留待合并内容；不擅自 stash、reset、clean、结束其他任务或强推。

双方有提交时保留历史并合并验证，按行为和用户目标解决冲突。推送被拒绝则 fetch 审阅远端新增内容，不把拒绝当强推理由。用户未要求时不额外创建 PR。

## 验收与中断恢复

推送已确认 remote 和分支，不假设所有机器都叫 main：

```powershell
git -C <local-path>
git -C <local-path>
git -C <local-path>
```

认证错误先修复登录。网络错误且结果不明确，先比较远端 SHA；一致则完成，不一致且为暂时故障最多再推送一次。持续失败报告已保存的本地提交和具体阻碍，不无限重试。

首次同步用全新临时目录克隆，检查文档入口与 skills；仅相关代码变更运行对应测试，遵守 AGENTS.md 禁用命令与生产授权边界。克隆成功不代表安装包发布或生产数据迁移。
