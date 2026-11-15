## 软件 1.4.22 已发布（2026-11-15）

[下载 1.4.22](https://github.com/fang1776358081-arch/local-service-factory/releases/tag/v1.4.22)。新增 Codex 内置生成的任务、结果回填、排版与恢复入口，保留 API 流程；修复原生执行/回填/排版期间的安装保护及安装开始后的写入准入。源码来源38f767dbdf7d4854bc0efa4b177a7d27c58b2095。安装包124594822字节，SHA256 `e0c00d38fac5f59770ab26588228d2ee886e5d99a243cd207730f5f746ddf406`。

三项附件公开下载及Ed25519签名验证通过，Latest=v1.4.22，发布锁已释放。规则内容/签名索引保持1794662868654979100，未重复发布。更新14项、传输5项、正式stage初始化2项通过；复用相同产品代码31项原生回归和七图真实链路，用户图片验收通过。3036个运行时文件、144个包内引擎文件一致，正式包九项目/双生成入口启动通过。隔离身份1.4.20→1.4.21真实NSIS及互斥已验证；本轮未替换本机正式安装，未重验全新Windows或正式身份机器级覆盖升级。无Authenticode证书，整套test_factory_safety按约束未运行；不新增生图，不删除旧仓。

源码、Agent指引和项目skill已随候选同步；隔离适配器、本机feed、测试公钥和私有数据未进入正式包。详细证据见维护工作区.runtime/release-native-1.4.22/release-verification.json及development/CODEX_NATIVE_VALIDATION.md。旧版在启动/每六小时检查，包下载验证完成且无任务时退出安装，重开后核对1.4.22。

## 软件 1.4.19 已发布（2026-11-15）

[下载 1.4.19](https://github.com/fang1776358081-arch/local-service-factory/releases/tag/v1.4.19)。本版打包已完成的维护端发布链接/验证工具修正；同步版本及公开克隆说明，没有修改客户端更新器、安装布局、生产提示词或运行时依赖。来源提交 5dc6e7b，安装器 SHA256 `5acdd78105e787d28f9495f05a558529724d4e2f5596738950958446f82c4c34`，133103647 字节。公开下载、Ed25519 签名、Latest 及锁释放通过。无 Authenticode 身份证书。

规则 40 文件无变化，保留 `1794662868654979100`，未重复发布。新使用端匿名同步 updated→current 通过；本版独立初始化两测试通过。安装/更新路径文件与上次真实验收完全相同，本次复用链路证据，未再安装到正式电脑。旧仓保留 1.4.18 过渡入口，不能仅凭新版发布就删除旧仓。

## 统一仓库约定

源码、软件 v 标签 Release、规则 rules 标签 Release 统一使用 fang1776358081-arch/local-service-factory，软件与规则独立更新，规则不抢 Latest。该仓库是独立公开项目，不是原仓 fork；旧仓链接只保留为历史证据。开发不授权构建/发布。

以 [迁移与上线清单](../development/REPOSITORY_MIGRATION.md) 和 [执行台账](../development/UNIFIED_REPOSITORY_EXECUTION_PLAN.md) 为准。release-index.json 是发布维护的签名索引，普通源码同步不得覆盖/删除；规则发布后 fetch 并保留远端索引提交，禁止自动 stash/reset/强推。

# 软件与规则发布（1.4.16）

## 软件1.4.16及潜水打捞规则已发布（2026-10-31）

软件 [v1.4.16](https://github.com/eish1997/local-service-factory-releases/releases/tag/v1.4.16) 已设为最新版；安装包 `dashboard/releases/1.4.16/LocalServiceFactory-1.4.16-setup.exe`，132691907字节，SHA256 `0d7594851e0ca8d27990c3dd7525c5274b8cf351d5ec27ecbd59f87f36bfe487`。公开三项资源摘要及Ed25519签名验证通过，发布锁已释放。

规则 [1793435166580719500](https://github.com/eish1997/local-service-factory-rules/releases/tag/rules-1793435166580719500) 同步发布，40文件、9业务，最低软件1.4.16，ZIP SHA256 `03e171fe99c4e169a92879eed895e532192cf284b5e691a34777dbee782f669a`。全新使用端实际公开下载、验签、激活成功。旧八业务规则不能作为新版活动规则，升级会刷新随包规则，历史版本目录及冻结任务仍保留。

包含潜水打捞33任务类型、统一1+6、12条默认服务词、按分支隔离阶段水印、隐藏“滞空入水动作预览”标题且保留电话服务词。5项包内潜水测试、规则隐私/兼容/升级检查、源端audit10000通过；真实打包Electron隔离创建7图批次，阶段标题正确，付费请求0。98份引擎源码与7个关键UI文件和源码一致，证据 `.runtime/release-validation-1.4.16.json`。没有客户整机安装迁移验证，无Authenticode签名，整套factory safety按约束未运行。源码版与已有客户批次/图片不自动改写。本机C盘不足，构建临时文件已使用F盘；首次失败暂存保留。


## 1.4.15 继续和自动补齐改用当前密钥模型（2026-10-29，已发布）

已发布 [软件 1.4.15](https://github.com/eish1997/local-service-factory-releases/releases/tag/v1.4.15)，[首次安装下载](https://github.com/eish1997/local-service-factory-releases/releases/download/v1.4.15/LocalServiceFactory-1.4.15-setup.exe)。本地 `dashboard/releases/1.4.15/LocalServiceFactory-1.4.15-setup.exe`，132548774 字节，SHA256 `a9b09a155c9a940cf35fbe4a73c684904f7d7fa65d955aa616d2e680bcbcef34`。blockmap 137643 字节，SHA256 `48590ce53768cac08cabf13b47f9df36d74271ab1cc18d26cd0479603dc535ea`。latest.yml 370 字节，SHA256 `73ade909cc5ad7cab576926cc4ba820d5ae2955bdc4be57a7f1abc56777245dc`。GitHub 资源摘要与这三项一致，已设为最新版，发布锁已释放。本次没有重新发布规则，也没有付费生图。

继续原任务、自动补齐和正在执行的检查会按密钥重新识别。列出 `gpt-image-2.5-flare` 就改用它和 1024x1536；仍只列出 `gpt-image-2-4k` 才继续用 4K。已计数的请求不退，预算不重建。识别出唯一模型后，会改写本机保存的模型名，避免之后保存密钥又写回 4K。有任务在跑时，更新要等到退出且没有进行中的任务才安装。本版没有客户整机或全新 Windows 虚拟机升级验证。整套 `tests.test_factory_safety` 按桌面约束未运行。无 Authenticode 发布者证书，更新清单使用 Ed25519。

## 1.4.14 每个密钥用自己的模型（2026-10-28，已发布）

已发布 [软件 1.4.14](https://github.com/eish1997/local-service-factory-releases/releases/tag/v1.4.14)，[首次安装下载](https://github.com/eish1997/local-service-factory-releases/releases/download/v1.4.14/LocalServiceFactory-1.4.14-setup.exe)。本地 `dashboard/releases/1.4.14/LocalServiceFactory-1.4.14-setup.exe`，132546053 字节，SHA256 `590845b4207e6893ea33bf91ba1de69c7578e53ce3493aa934c72fff82bc9751`。blockmap SHA256 `55a70e97654e817ef5e258b843711db39051ac2517963840b9dc3fd07db82316`，latest.yml SHA256 `6043a8928622372de610d3f0683eb14a5378a88aecc738a7a1d97cb06347b15e`。公开下载摘要与这三项一致，已设为最新版，发布锁已释放。本次没有重新发布规则，也没有付费生图。

新任务开始前按每个密钥列出模型，不生图。一个密钥只对应 `gpt-image-2-4k` 或 `gpt-image-2.5-flare` 其中一个：4K 用 medium、2560x3840，普通用 medium、1024x1536。同一批可以混用，各自按自己的尺寸生成。已保存的 `.env` 模型不会改写这次选择。已经开始的任务保持原冻结模型，不改、不退已计数的请求。本版没有客户整机或全新 Windows 虚拟机升级验证。整套 `tests.test_factory_safety` 按桌面约束未运行。无 Authenticode 发布者证书，更新清单使用 Ed25519。

## 1.4.13 新建水印与普通分组模型（2026-10-25，已发布）

已发布 [软件 1.4.13](https://github.com/eish1997/local-service-factory-releases/releases/tag/v1.4.13)，[首次安装下载](https://github.com/eish1997/local-service-factory-releases/releases/download/v1.4.13/LocalServiceFactory-1.4.13-setup.exe)。本地 `dashboard/releases/1.4.13/LocalServiceFactory-1.4.13-setup.exe`，132564152 字节，SHA256 `ba1e82d3cd9235a21c194440ca7709e0ed1d2e2fdfcd68efbe71279a50b41be7`。blockmap SHA256 `2e7a4b437c1a6ea8d1acb6bc14d73185571ff3dbb98c768adca8be2ccde33e9b`，latest.yml SHA256 `cd7edc103136a6edfd800f395a44fd22f3527a7b88a9368469ea6dabd92215a8`。暂存目录 `.runtime/distribution-stage-20261025-1.4.13`，独立环境检查通过。公开校验通过后已设为最新版，发布锁已释放。本次没有重新发布规则，也没有付费生图。

新建批次窗口列出当前水印。电话行跟随本次手机号。服务词每条一行，可改、可删、可添加；空行去掉后冻进本批次，并记给该项目下次新建。已有批次和图片不改。新安装在还没有 `.env` 时默认模型是 `gpt-image-2.5-flare`，质量 medium，尺寸 1024x1536。已有 `.env` 不会被安装覆盖。安装包带上当前商务KTV成组提示词：24 套装修、副标题「商务会所」、店名两字或三字。1.4.12 没有这些程序改动。本版没有客户整机或全新 Windows 虚拟机升级验证。整套 `tests.test_factory_safety` 按桌面约束未运行。无 Authenticode 发布者证书，更新清单使用 Ed25519。

## 规则 1792428948499520800（2026-10-20，已发布）

已发布 [规则 1792428948499520800](https://github.com/eish1997/local-service-factory-rules/releases/tag/rules-1792428948499520800)。37 个文件，SHA256 `289421a62da41a87d9209f33772db1c947a82fd3649f6a0a5de0a7ef1165e3d8`。相对上一版只变了 `projects/business_ktv/project.json` 和 `projects/business_ktv/variable_catalog.json`。八个业务本地组装通过，没有付费生图，没有发布安装包。商务KTV 一组七张的店名、副标题、档次和装修池在 `tools/business_ktv/group_prompt.py`，不在这 37 个规则文件里，已安装的 1.4.12 不会因这次规则更新改用新提示词。

## 1.4.12 后处理文字可留给新批次和重生成（2026-10-20，已发布）

已发布 [软件 1.4.12](https://github.com/eish1997/local-service-factory-releases/releases/tag/v1.4.12)，[首次安装下载](https://github.com/eish1997/local-service-factory-releases/releases/download/v1.4.12/LocalServiceFactory-1.4.12-setup.exe)。本地 `dashboard/releases/1.4.12/LocalServiceFactory-1.4.12-setup.exe`，132564009 字节，SHA256 `3df5eb2482c02a86162aec835ff16dac1d07e422d318ccac770d613abb7e9a0a`。blockmap SHA256 `7d63107f45f9b2cb11107b0ae110781f0cc88e9d0ded0db27b68c8a3b51b0dc3`，latest.yml SHA256 `99d34b4dbed22d648ca4fb478c0c8012af4d7e5a86d85237aac5affbdcfbe089`。暂存目录 `.runtime/distribution-stage-20261020-1.4.12`，独立环境八个业务检查通过。公开校验通过后已设为最新版，发布锁已释放。本次没有发布规则，也没有新的付费生图。

后处理里增删的服务词会记在该项目上。之后新建批次、右键「重新组装并生成此图」和「重新后处理」使用这组文字。补生成仍沿用原来的冻结文字。电话只用于当前预览。原批次记录和尚未重做的图片不改。1.4.11 没有这个行为。

## 1.4.11 本地文件占用不再中断整批（2026-10-19，已发布）

已发布 [软件 1.4.11](https://github.com/eish1997/local-service-factory-releases/releases/tag/v1.4.11)，[首次安装下载](https://github.com/eish1997/local-service-factory-releases/releases/download/v1.4.11/LocalServiceFactory-1.4.11-setup.exe)。本地 `dashboard/releases/1.4.11/LocalServiceFactory-1.4.11-setup.exe`，132560906 字节，SHA256 `24e6483b9f47bdf94bde52b2c363ff026283b5f1c41379abb5ce6812a46284eb`。blockmap SHA256 `a6e5a8030f1eb29b115110d3aeebe062b23f2cbe656cbaa9f608efc2652e2149`，latest.yml SHA256 `2072793a52dbe656338c5b801596f16eea7cab1af6edc33413e15d776d86e66c`。暂存目录 `.runtime/distribution-stage-20261019-1.4.11`，独立环境八个业务检查通过。公开校验通过后已设为最新版，发布锁已释放。本次没有发布规则。

Windows 暂时占用锁文件或交付队列时，不再把整批标成失败。已生成的图片和已计数的请求保留，任务继续。1.4.10 安装包没有这个修复。

## 1.4.10 批次收尾、补齐显示与商务KTV标题（2026-10-19，已发布）

已发布 [软件 1.4.10](https://github.com/eish1997/local-service-factory-releases/releases/tag/v1.4.10)，[首次安装下载](https://github.com/eish1997/local-service-factory-releases/releases/download/v1.4.10/LocalServiceFactory-1.4.10-setup.exe)。本地 `dashboard/releases/1.4.10/LocalServiceFactory-1.4.10-setup.exe`，132557439 字节，SHA256 `12158cec4c3350d13d6f8cfc531966d668783174bbc9c535196735b8b0977b79`。blockmap SHA256 `734ef1bac8289b3bacbbafe376d277ea9d0ec7d5c53f9cd774799efb5cef66c9`，latest.yml SHA256 `6853b4a5adbfa8bb2c939d9a9ce2ee2d8105bdb671de4314cf631aa5f54cde89`。暂存目录 `.runtime/distribution-stage-20261019-1.4.10`。公开校验通过后已设为最新版，发布锁已释放。本次没有发布规则。

## 1.4.9 界面精简、图库批量操作与HTTP400恢复（2026-10-06，已发布）

已发布 [软件1.4.9](https://github.com/eish1997/local-service-factory-releases/releases/tag/v1.4.9)，[首次安装下载](https://github.com/eish1997/local-service-factory-releases/releases/download/v1.4.9/LocalServiceFactory-1.4.9-setup.exe)。本地 `dashboard/releases/1.4.9/LocalServiceFactory-1.4.9-setup.exe`，132138142字节，SHA256 `a7638d8bce5d785b8a13e6fbb6b9bb367c9fa6ee26544abd1d91a09370c7f2af`。公共发布流程已完成三项资源及签名清单下载校验，latest=v1.4.9，发布锁释放。 独立无凭证公开下载64个分片完成，并再次验证三项产物摘要与签名，见 `.runtime/updates/public-verify-1.4.9.log`。

简化常用界面、生成前额度核对和具体文本按钮；技术记录按需展开，错误保留完整诊断，弹窗风格统一，新建窗口按内容收缩。图库支持多选及跨页全选待确认、批量确认/取消复用。持续任务在冻结整批额度内有界重试未知原因的明确HTTP400，允许合法旧任务原预算续接；明确参数/权限/内容拒绝、未知结果与已返回未保存结果仍受保护。旧许可、冻结内容、原图、审核及历史输出保留。

31项独立包内Python回归、6项Node更新/启动检查通过；实际包内Electron验证7原卡→5成品/7图库、批量确认、额度改动使旧计划失效、错误详情、820px及520px弹窗边界、四项主进度和新建空号码。所有测试付费POST0。88份脱敏引擎源码、16个UI/运行文件及包版本核对一致。37份规则与1.4.8相同，没有规则发布。源码audit10000/api=false；包内不包含历史prompt JSONL，legacy audit依赖该文件，未冒充包内audit通过。证据 `.runtime/updates/release-validation-1.4.9.json`、`packaged-ui-1.4.9.json`、`source-stage-proof-1.4.9.json`。

源码看板已重新打开并恢复原项目/批次（旧实例已关闭，不停止Worker），见 `.runtime/updates/source-dashboard-1.4.9.json`。没有生产生图或实际客户图库资格写入。安装布局、更新器及运行时版本不变，沿用既有NSIS链路证据；本版没有全新Windows虚拟机/客户整机升级验证。整套factory safety测试按桌面约束未运行。无Authenticode发布者证书，更新清单使用Ed25519。用户端启动/每六小时检查，有任务时不安装，无任务退出后安装。

## 1.4.8 原图生产看板、共享原图库与持续额度（2026-10-06，已发布）

已发布 [软件 1.4.8](https://github.com/eish1997/local-service-factory-releases/releases/tag/v1.4.8)，首次安装下载 [LocalServiceFactory-1.4.8-setup.exe](https://github.com/eish1997/local-service-factory-releases/releases/download/v1.4.8/LocalServiceFactory-1.4.8-setup.exe)。本地正式产物为 `dashboard/releases/1.4.8-final`。安装包132676247字节，SHA256 `0b070c5dd5007c76f84eaa2645cc156cfced7450edcc32f903062fdb70041a67`。公共 publish 完成四项公开下载及 Ed25519 签名检查；独立无凭证分片公开下载再次验证三项产物摘要与签名，证据在 `.runtime/updates/public-download-1.4.8`、`public-verify-final-1.4.8.log`。远端 latest=v1.4.8，软件发布锁已释放。

每份原图一张待开始/进行中/已完成卡，三拼为三份来源原图。成功保存后自动本地后处理并回填批次对应组。新任务冻结开始时明确显示的整批最高POST数，额度内持续补齐，不再固定两轮；原许可与父绑定修订各每素材最多两次，合计由持久预留账本限制。崩溃/暂停不重置已预留额度，未知结果不盲目重发，先免费恢复已返回图片。缺图继续留在进行中，额度耗尽等待新增授权；旧任务不自动升级策略。原图库按项目、门头/详情及主题归档，复用率使用本项目已确认可用原图；来源、原始字节及当前历史输出保留，打包读取当前版本。

发布验收额外修复Windows长路径的子许可、事件解析、暂停标记、批次/修订发现、成品提交、冻结子任务重放、图库登记读写与运行任务守卫；不可覆盖原文件的UUID临时路径独立适配。子Agent最后独立复核关闭全部必要问题，239字符目标/超过260字符临时文件的原子发布、幂等及拒绝不同字节覆盖验证通过。87份脱敏引擎源码与最终包资源逐文件一致；37份规则与1.4.7一致，本次未发布规则。

包内Python3.11.9及24锁定依赖通过；13项持续额度、11项图库、5项原卡详情、4项资产路径、历史当前版本打包/同字节竞争、KTV门禁、八项目冻结组装、5项更新传输、真实离线多Worker与三处kill/免费子任务恢复通过；6项Node更新与bootstrap通过。实际包内Electron在私有夹具中验证7原卡→5成品回填、7图库记录、整批额度0且请求0，820px无横向溢出；22个后处理预设可读取。`factory.py audit`10000唯一/api=false。首次测试及旧构建失败证据保留；部分测试夹具长路径读取、界面测试批次选择修正后复验。最终验收汇总 `.runtime/updates/release-validation-1.4.8.json`，源码/包摘要 `.runtime/updates/source-stage-proof-1.4.8.json`。

源码看板已重启（当前PID/创建时间见 `.runtime/updates/source-dashboard-1.4.8.json` 和实际进程），8项目、看板/图库入口确认，生产Worker未停止。没有付费生成、规则发布或本机生产安装。更新器、NSIS安装布局、依赖未改，沿用历史安装链路证据；本版未执行客户整机升级、全新Windows虚拟机或真实KTV视觉审核，整套 `tests.test_factory_safety` 按桌面约束未运行。无Windows Authenticode发布者证书，更新清单使用Ed25519；使用端启动/每六小时检查，运行中不安装，无任务退出后安装。

## 1.4.7 两轮自动补齐与隔离槽位恢复（2026-10-04，已发布）

用户确认“自动补缺两轮，每个缺失素材每轮最多2次”，并授权子Agent独立检查后打包发布。新共享plan冻结主任务、额外补缺和合计请求上限；start绑定完整策略。主任务收尾后先本地找回私有返回字节/加密URL、保存及合成，再创建父任务绑定的独立补缺许可，每轮只处理缺失素材，保留已成功三拼格子、冻结提示词/主题/电话/服务词和来源顺序。原许可及计数不重置，暂停/继续沿用同一ledger，不新增第三轮；自动子任务不能公开单独plan/resume。成功成品追加历史并设为当前，打包按当前版本。结果不确定且没有恢复证据不重复付费；旧任务没有冻结策略仍保留原预算。

两名子Agent独立复核并验证，修复边界包括私有返回结果隔离、原ready=0而自动子任务仍有余量、充值后原槽位和已隔离子任务无法恢复。1.4.7仅在显式resume经冻结配置与原槽位校验成功后发布恢复epoch，子任务每epoch清隔离一次并并入当轮父隔离；普通自动阶段不复活坏key，纯本地恢复无需API。失败诊断取最终缺失子任务HTTP/分类，不显示供应商原文。任务进度合并主/补缺实际许可，子任务不覆盖整批进度，只有全部素材及成品有效才完成，仍不代表审核通过。1.4.6已经发布，最后复查发现充值恢复边界后以更高1.4.7修正，未覆盖同版资源。

包内独立Python六个短模块50项回归、实际Electron隔离界面（7/7、失败0、12/42请求、两轮、820px三页面）、八项目本地组装/查看、bootstrap两项与更新模块四项、audit10000通过。37规则文件与1.4.5完全一致，未发布规则。最终源码看板已重启（CDP9227），产物dashboard/releases/1.4.7、stage .runtime/distribution-stage-20261004-1.4.7；证据.runtime/updates/bundled-engine-1.4.7.json、packaged-ui-1.4.7.json、eight-projects-1.4.7.json。

已发布[软件1.4.7](https://github.com/eish1997/local-service-factory-releases/releases/tag/v1.4.7)，[下载Windows安装包](https://github.com/eish1997/local-service-factory-releases/releases/download/v1.4.7/LocalServiceFactory-1.4.7-setup.exe)。安装包132536958字节，SHA256 `f58698db5c6b9b1d08556b371ef6f9fd37116658b8e3152975f1dfe61e6f93bc`。公共updates publish成功完成三项资源及签名清单的真实公开下载、摘要及Ed25519签名核验；再次核对latest=v1.4.7、自己的发布锁释放。无Authenticode发布者证书。软件启动/每六小时检查更新，有任务时不安装，空闲退出后安装。未付费生图、未安装到生产；NSIS/更新器/运行环境未改，沿用既有链路证据，不宣称本版真实旧版整机升级或全新Windows验收。桌面禁用的整套tests.test_factory_safety未运行。持续接口拒绝、密钥不可用或未知请求结果仍可能留下需处理项，有界补缺不保证任何故障都能自动完成。

## 1.4.5 无人值守失败恢复与显式补缺（2026-10-03）

已发布软件[1.4.5](https://github.com/eish1997/local-service-factory-releases/releases/tag/v1.4.5)，[下载Windows安装包](https://github.com/eish1997/local-service-factory-releases/releases/download/v1.4.5/LocalServiceFactory-1.4.5-setup.exe)。安装包132078661字节、SHA256 `9bc1921c0e2fa5271e448b344c64d61c43cdb08ba33406fe9d5941298485382d`；三项资源及签名清单已从公开地址实际下载核对，Ed25519签名通过，latest=v1.4.5、自己的发布锁释放。初次公共publish大文件写超时，核对同一草稿401997871无资源后通过既有代理补缺，未覆盖已有有效资产；公开下载63个有界分片全部通过。

共享批次自动补一次可恢复失败，balance/明确401隔离槽位；不可重试/次数耗尽/未知/已返回未保存跳过并继续其它单元，原单元两次和原总预算不变。新增“补生成此图 · 复用已有素材”(repair-prepare)，保留冻结主题/提示词及三拼来源顺序，只有缺失单元按两倍上限建立独立修订；父manifest/raw/license不改写。成功追加历史为当前图，打包读取当前版本。结果不确定或已返回未保存不可重复付费，先核对/找回结果。本地合成逐图最多两次，原图可无密钥resume；已发布child恢复不退回父原图，坏sidecar标未审核并保留。短暂admin锁有界等待10秒，未开启Windows长路径时相关IO支持扩展路径，不改系统注册表。

子Agent发现5处稳健性问题并修复，独立5测试和嵌入Python长路径3测试通过。最终包内独立Python33项回归、八业务本地组装/查看、实际包内820px三页面及补缺按钮、37规则文件不变/无私有数据、audit10000通过。最终stage .runtime/distribution-stage-20261003-1.4.5-verified，产物dashboard/releases/1.4.5-verified；初构建保留作长路径失败证据。源码看板重启，未付费生图、未安装到生产；规则不发布。NSIS/更新器/运行环境未改，复用历史链路验收，不宣称本版真实旧版整机迁移或全新Windows验收。无Authenticode发布者证书，更新Ed25519签名已验证。


## 1.4.4 单图失败后继续任务修复（2026-10-02）

已发布软件[1.4.4](https://github.com/eish1997/local-service-factory-releases/releases/tag/v1.4.4)，[下载Windows安装包](https://github.com/eish1997/local-service-factory-releases/releases/download/v1.4.4/LocalServiceFactory-1.4.4-setup.exe)。安装包132389918字节，SHA256 `c9d29710b75dd1f2570f28a6878297fd9b1f90bc765c4cdad35a502e3dccc461`。三项产物和software-manifest.json已从公开地址完整下载，摘要与Ed25519签名核验通过，实际latest=v1.4.4，本次发布锁已释放。初次上传超时后核对同一草稿，资源为空时通过既有代理有界补传；没有覆盖有效资源或重建同版本Release，公开安装包验证使用64个有界分片。

一张不可重试、结果不确定或下载失败不再拦住整批继续。Agent与看板共享逐单元恢复策略，保留成功原图，跳过需要处理的单元，其余沿用原任务许可、配置和预算继续。任务列表可展开逐项原因及安全HTTP状态码，完全没有可执行项时禁用继续。仅重试仍只选可恢复失败项；全部原图已保存时可无API调用继续本地合成。已有未完成组仍阻止另建同范围预算；升级后使用“继续原任务”。原图、已有成品和历史记录保留。

18项源码回归、包内独立Python8项恢复检查、八项目本地业务校验、5项传输及6项Node检查、实际源码/安装包隔离UI和10000条audit通过。820px无溢出；公开下载验证不使用维护端凭证。Python3.11.9及24个依赖与锁一致，官方ZIP摘要核对，规则37文件与已发布规则1790789310472053700完全一致，本次未发布规则数据。更新链路、依赖和NSIS安装脚本未变，复用历史NSIS链路证据；当前包内运行不是本版真实客户整机升级或全新Windows虚拟机验收。没有付费生图，暂无Authenticode发布者证书。截图中远端30组任务的原始单图错误及“新建也不行”的具体阶段尚未确认，不能宣称其他故障已解决。

## 1.4.3 通用规则升级兼容与图片主题（2026-10-01）

已发布软件[1.4.3](https://github.com/eish1997/local-service-factory-releases/releases/tag/v1.4.3)和规则[1790789310472053700](https://github.com/eish1997/local-service-factory-rules/releases/tag/rules-1790789310472053700)，规则最低软件1.4.3。安装包132408388字节，SHA256 `2eb21e46c361ecbbdadf808f73bdf6b02c1f0456251fe5bde2f68ca32efbfed3`；规则37文件，SHA256 `0c016acf10ef7e0b9f9f3a00f7af5d2e926ae23f7a79b77ba64504a902a81496`，只改configs/postprocess.json。公共publish完成四项公开软件资源实际下载/签名/摘要校验，latest=v1.4.3，自己的发布锁释放；公开规则manifest签名与ZIP验证通过。

消费者优先从GitHub官方raw HEAD获取签名索引，运输失败回退官方API；签名、白名单、摘要、软件兼容检查不放宽，不配置用户发布凭证或专用代理。维护端API优先，raw备用按准确文件字节计算Git blob SHA保持CAS。HTTP限流不立即重复同一路径。新安装/启动和新共享组装走同一rules bootstrap：离线验证已激活规则，旧内置/不兼容记录时选当前软件唯一随包快照，保留旧文件和历史批次；兼容的签名规则不被覆盖。损坏的已有远程版本缓存不得再激活。规则失败保留兼容本地版本，下次启动/六小时检查继续尝试。

修复结构模板提前返回遗漏service_role：详情保留自己的冻结主题，三拼三格分别保留对应主题；首图不添加详情主题。主题使用模板字体、配色、描边、效果及局部底板，记录主题、格子和实际参数；与电话/副服务词互不重叠，来源顺序不变。只做文字边界检查，没有人物车辆识别或避让承诺。长服务词最后两次尝试完整自然换行，不能漏词。八个当前项目的新共享批次启用最新18结构/4兼容预设；家电/开锁原有副服务词表为空时只保留任务主题和电话，不凭空新增文案。商务KTV主题由本批次ROOM_TYPE冻结，视觉生产门禁继续生效。旧批次不重写；主动预览/右键换样式取新设计与旧确认内容，追加历史，打包当前版本。Windows后处理暂存路径已缩短。

38项相关Python检查、6项Node检查、audit10000、安装包内独立Python八项目本地真实渲染和旧批次主动预览/应用通过。包内程序用实际旧36文件内置规则1的隔离副本启动，离线切换兼容快照并保留旧规则/私有配置/冻结证据/隐藏项目，820px三页无溢出或pageerror。全新消费者使用默认网络、无凭证及无NO_PROXY修改同步updated→current；八项目新批次冻结新规则、模板与主题参数。真实货车原图6个详情/三拼私有预览视觉检查通过：.runtime/template-previews/detail-themes-143.png及triptych-themes-143.png，原图/当前成品未修改，无付费生图。开发看板已重启。

本版验收的是包内程序加旧规则/用户数据副本；NSIS安装脚本、依赖版本和更新器备份链路未改，沿用1.3.1实际NSIS证据，不宣称本版旧程序整机升级、全新Windows虚拟机或付费API验收。暂无Authenticode发布者证书。源码测试整体tests.test_factory_safety未运行，遵守桌面禁用要求。安装端需升级1.4.3才能使用通用恢复逻辑和这版规则，1.4.2本机的一次性恢复保留为下方历史证据。

## 1.4.2 电话透明底板、三拼修复与专业相机（2026-10-01）

已发布软件[1.4.2](https://github.com/eish1997/local-service-factory-releases/releases/tag/v1.4.2)及规则[1790782473702205200](https://github.com/eish1997/local-service-factory-rules/releases/tag/rules-1790782473702205200)，最低软件1.4.2。安装包132060071字节，SHA256 `7496f8c605cf419a397764ab224ff4d0b6d392c523c71fb7df89c196025ded0d`；规则37文件，SHA256 `4ece3eb7daecaa9505fcf737c69ed94e11ac7ab353fba0754a3bd99438e30b10`。公开四项软件资源/签名及规则ZIP/manifest实际核验，GitHub latest=v1.4.2、本次发布锁释放，独立Python全新消费者updated→current、指针与manifest一致。

18个结构预设的design.headline_board固定none，兼容预设phone_background为null；随机不能恢复电话底板，服务底板仍可随机。新结构三拼按整幅高度合成，消除旧18%预留栏；保留来源顺序和旧固定底栏渲染。货车catalog revision5包含10手机+10专业相机，安装包包含独立专业成像提示词分支和单图变量绑定。专业相机只是生成参数，不宣称真实设备/EXIF。

汽车/货车新共享批次使用新版冻结规则；旧批次及当前成品不自动重做，主动后处理追加历史并按当前版本打包。其他类别没有扩展自动结构范围。29项相关Python检查、5项Node检查、audit10000、包内八业务和十张本地输出、真实原图三个三拼预览与820px打包UI通过；私有对比图.runtime/template-previews/triptych-phone-transparent-142.png。源码看板已重启，无付费调用。

首次上传超时后核对同一草稿，仅补齐缺失资源；实际公开下载通过既有代理的有界分片完成。隔离同步的既有代理共享出口曾耗尽匿名API配额，仅验证子进程使用官方API直连，资源仍经既有代理，无凭证。安装更新链路未改，沿用1.3.1验收；无本版实际旧版整机迁移、全新Windows虚拟机或Authenticode证书。历史安装包/规则/原图/输出保留。

## 1.4.1 历史发布
维护者：`eish1997`。2026-09-30 软件1.4.1和规则1790778405162892300已发布，公开下载、SHA256、Ed25519签名及隔离使用端同步均通过。软件：[1.4.1 Release](https://github.com/eish1997/local-service-factory-releases/releases/tag/v1.4.1)；规则：[规则 Release](https://github.com/eish1997/local-service-factory-rules/releases/tag/rules-1790778405162892300)，最低软件1.4.1。

安装包SHA256：`f3ba07bcda1b1261e534d8441a0384010e1a8bc44f9912521c66f000cabc794b`。规则ZIP SHA256：`7d8952d831468b7166fb7d349dc6d6498a5f733fdbb70e3166b331c4c93f603a`。最终安装产物在dashboard/releases/1.4.1-final，构建计划与恢复证据在.runtime/updates；旧产物保留。

1.4.1提供独立后处理页面、18结构模板及模板内随机变化，修复新共享批次自动入口未启用和规则白名单遗漏layout_categories/auto_layout_categories。汽车救援、货车救援新批次自动启用；已有批次继续冻结false或缺失标志，已有图片需右键重新后处理或应用预览，追加历史并以当前版本打包。其他类别保持既有范围，后处理不调用生图API。

发布使用固定构建快照：货车变量目录revision3；暂存后新增的专业相机代码/目录revision4–5留在维护源码，未包含在本版安装包或规则中，不被发布覆盖。

## 日常约定

Agent 修改规则后先本地检查，不自动上传。收到“发布项目更新”才执行 rules publish；收到“构建安装包”才准备正式构建资源并运行 NSIS；收到“发布软件更新”才上传软件。使用端不持有发布凭证，界面没有发布接口。

Agent 与看板共用 `python factory.py rules/updates`。命令均从标准输入接收 JSON，并返回统一 JSON。示例中的版本号采用递增正整数字符串；省略版本由本地生成。不要将密钥粘贴到对话或写入命令历史。

## 首次发布准备

1. 在维护电脑用 `gh auth login` 登录，或在该进程的私有环境设置 `GH_TOKEN`。工具只在内存读取凭证，不打印、不打包。
2. 明确要求初始化后，调用 `updates setup`，输入 `{"authorization":"initialize_update_repositories"}`。只创建缺少的公开仓库并初始化默认分支，不发布版本，也不改变已有私有仓库的可见性。
3. 发布签名使用 Ed25519。本机私钥位于 `.runtime/private/release-signing.pem`，公钥已写入 `update-config.json`。应另行妥善备份私钥；私钥不进入安装包、规则包或公开仓库。可通过 `FACTORY_RELEASE_KEY_FILE` 和 `FACTORY_RELEASE_KEY_ID` 指定维护端签名密钥。公钥轮换需先发含新旧公钥的软件版本，再改用新私钥签名。

## 项目规则发布

- `rules release-plan` 输入 `{}`：导出白名单数据、排除私密字段，验证八个业务的本地组装，保存不可覆盖的新版本计划并返回差异清单。
- `rules publish` 输入 `{"version":"计划返回的版本","authorization":"publish_project_update"}`：签名、上传完整规则 ZIP 和清单，确认公开 ZIP 可下载后，用 GitHub Contents SHA 比较并交换最新版本指向。
- `rules sync` 输入 `{}`：使用端校验并激活；维护端只读取远端版本和基准 SHA，不覆盖编辑文件。并发发布冲突后，先 sync 再重新 release-plan。
- `rules rollback` 输入 `{"from_version":"本机保存的历史发布计划版本","authorization":"publish_project_update"}`：复用历史数据，重新验证后以更高版本发布，绝不倒退版本号。旧计划保留在 `.runtime/updates/release_plans/`。
- `updates status/check` 输入 `{}`：查询状态或请求检查。软件下载安装由桌面进程执行，Agent 的检查请求通过本地记录交给同一个服务；看板未打开时等待下次启动。

白名单固定在 `rules-fields.json`，当前共 37 个数据文件。`configs/prompt_templates.json` 是实际组装读取的额外模板段落，默认空列表，不改变既有提示词；支持 shared 或按业务的 cover/detail 段落，只允许 `{phone}`、`{category}`、`{services}` 占位，不执行代码。已有 Python 中的提示词算法通过软件更新发布；`prompt_template_storefront.md` 是参考说明，不将整篇说明直接附加到图片提示词。

客户端下载后逐文件验证，检查路径、大小、私密字段、业务结构和软件兼容性。整包通过后只原子切换版本指针。每次组装固定一个版本，批次 snapshot 记录版本；后台 worker 恢复该批次原规则目录，缺失则明确停止，不能改用最新规则。规则历史不自动清理。

## 正式 Windows 构建与软件发布

必须先有明确的构建指令。本轮用户要求打包发布安装包和规则，已完成独立运行构建与GitHub发布；运行时及安装/更新链路未改，复用1.3.1实际NSIS证据，旧安装包保留。

1. 官方 Python 3.11.9 x64 嵌入 ZIP 的地址和 SHA256 固定在 `python-runtime.json`。依赖使用 `requirements-runtime.lock` 的 Windows CPython 3.11 轮包哈希。
2. 使用 Python 3.11 或更高版本，在工厂根目录调用 `python -m tools.stage_distribution --confirm-build --python-zip <ZIP绝对路径> --python-sha256 <已固定摘要> --destination <全新暂存目录>`。该步骤准备干净引擎、37 个基础规则文件、Python 和依赖，并使用内置解释器检查八个业务。不会复制 `.env`、任务、原图、私钥或客户历史。
3. 设置本地构建环境的 `FACTORY_DISTRIBUTION_STAGE` 为该暂存目录，使用 Node.js 22 或更高版本，在 dashboard 执行 `npm run build:installer -- --confirm-build`；可设置 `FACTORY_DISTRIBUTION_OUTPUT` 为新的产物目录，保留旧安装包。构建目标 NSIS x64，`--publish never`，不会顺便发布。
4. 如需 Windows 发布者身份签名，通过 electron-builder 标准 `CSC_LINK` / `CSC_KEY_PASSWORD` 配置 Authenticode 证书；证书和密码不进仓库。应用自己的发布签名校验始终启用，不能代替 Windows 的发布者身份签名。
5. 明确要求发布后，调用 `updates release-plan`，输入 `{"directory":"构建产物目录"}`；再调用 `updates publish`，输入相同 directory、计划返回的 files，以及 `authorization:"publish_software_update"`。

软件发布先取得 GitHub 原子发布锁，上传安装程序、blockmap、latest.yml、签名清单到草稿版本，公开为非最新版本；验证公开下载内容及签名后才设为最新。若中途失败，保留版本文件和 `software-publish-lock` 标签；Agent 检查是否仍有发布进程、核对内容后，才可处理锁并重新发布，不能无条件抢锁。

## 使用端目录与恢复

安装目录包含程序、生成引擎和私有 Python；用户目录为 Electron userData 下的 workspace，保存 `.env`、任务、冻结批次、规则版本与状态。图片仍遵循用户选择的资产目录。首次启动与升级通过共享 `rules bootstrap` 建立带软件版本和规则摘要的不可变随包快照，离线检查八业务兼容性；旧规则文件和冻结批次保留。兼容的已签名远程规则继续使用。

软件启动检查，此后每六小时检查，验证下载包签名及摘要后备份当前安装目录。正常退出时再次取得任务管理锁、确认没有后台任务，再写安装标志并启动安装；安装标志存在时 Agent 和看板都不能启动/续接生产。启动已验证的程序后清理标志并记录实际安装版本。

消费者优先读取 GitHub 官方 raw HEAD 的签名索引，传输失败备用官方 API，签名/摘要/兼容校验相同；规则更新失败保留已验证的兼容活动版本；软件下载/验证/备份失败不执行安装。旧程序备份在用户目录 `.runtime/updates/previous-app/<旧版本>/`，验证过的安装包在 `.runtime/updates/installers/`。NSIS 实际安装失败时，可从旧程序备份启动恢复；不要删除用户 workspace 或资产目录。本版没有修改用户数据格式，无需批次迁移。后续需要迁移时必须先增加专门备份与兼容测试。

源码维护端不下载/安装软件更新，规则同步只检查远端，不覆盖编辑区。使用端隐藏/删除项目记录独立存放，规则刷新不会重新显示已隐藏项目。

## 本次验证边界

31项后处理/历史/规则/共享渲染Python检查、4项更新传输检查、5项更新服务与独立启动Node检查、隔离renderer异步竞态检查通过，源码audit10000通过。安装包内独立Python验证八业务组装，汽车/货车各五张本地自动模板渲染通过；打包界面三个同级页、820px无横向溢出、无pageerror通过。公开132059359字节安装包与全部资源签名/摘要一致，实际latest=v1.4.1且本次锁已释放。

规则包37文件/八业务通过，公开ZIP和manifest签名核验通过；全新使用端真实同步updated→current，活动指针与manifest的版本和摘要一致，之后组装的汽车/货车auto_layout=true，其余false。维护端sync仅检查基准，不覆盖本地编辑；一次公开API检查403后，经既有维护凭证核验同一签名指针并保留后续编辑，随后公开接口恢复。

软件上传初次超时，核对同一次草稿后仅补齐缺失资源；公开分片下载直连不稳定，改用既有系统代理完成同一签名校验，没有用本地构建文件伪造下载缓存。安装/更新链路复用1.3.1证据，不宣称本版真实旧版整机迁移；全新Windows虚拟机、付费生图未执行。当前无Authenticode发布者证书。首次全预设预览较慢，仍需要实际文字视觉审核。
