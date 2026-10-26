# 影视制作助手 1.16.0 · Windows 安装、升级与恢复

本版支持 Windows 桌面本地执行。Python 3.11 或更新版本及其内置 sqlite3 为必要依赖；安装器只用标准库。FFmpeg 与 ffprobe 用于媒体探测、预览和本地渲染，文字创作、版本登记不依赖它们。安装器检查缺项并用中文说明，不自动联网下载、不配置模型 API、不启动 HTTP 服务。

程序发行 ZIP 与作品移交包分开。发行 ZIP 不应包含作品数据库、媒体、账号秘密、Pages 或聊天绑定。SHA-256 可以证明取得的字节与已知摘要一致；发布源身份仍须来自可信的 Git 地址或明确交付渠道。

## 从 GitHub 下载

打开公开仓库的 [Releases](https://github.com/lilinjie05241515-afk/film-production-assistant/releases)，下载并使用发布包，无需单独申请仓库访问。下载同一版本的三个资产：

- `film-production-agent-1.16.0-stable.zip`
- `film-production-agent-1.16.0-stable.zip.sha256`
- `film-production-agent-1.16.0-stable.release.json`

这里需要的是发行资产 ZIP，GitHub 自动提供的 `Source code (zip)` 是开发源码快照。将发行 ZIP 完整解压到自行选择的新文件夹，后续命令在该解压根目录运行；保留原 ZIP 用于安装与核验。

先核对发行资产摘要，再检查包内文件：

```powershell
$filmPackage = (Resolve-Path '<已下载的发行 ZIP>').Path
$filmExpected = ((Get-Content -LiteralPath ($filmPackage + '.sha256') -Raw) -split '\s+')[0]
$filmActual = (Get-FileHash -LiteralPath $filmPackage -Algorithm SHA256).Hash
if ($filmActual -ne $filmExpected) { throw '下载的发行包摘要不匹配，请核对来源和版本。' }
python -B -X utf8 release/publisher.py verify $filmPackage --sha256 $filmExpected
```

Windows PowerShell 字符串比较默认不区分大小写，SHA-256 的大小写形式不影响上述比较。不要从未知来源的同名文件推定其可信。

## 目录与首次安装

完整解压发行 ZIP，在包根使用 `python -B -X utf8 release/installer.py`；同目录 `release/bootstrap.ps1` 可检测 `py -3` 或 `python`，也可传 `-Python`。安装器所有目录参数必须为绝对路径。

三个位置由用户明确选择。以下 PowerShell 变量仅为可调整的安装示例，不绑定任何既有作品：

```powershell
$filmApp = Join-Path $env:LOCALAPPDATA 'FilmProduction/application'
$filmData = Join-Path $env:LOCALAPPDATA 'FilmProduction/data'
$filmConfig = Join-Path $env:APPDATA 'FilmProduction'
$filmPackage = (Resolve-Path '<已下载的发行 ZIP>').Path
python -B -X utf8 release/installer.py env
python -B -X utf8 release/installer.py verify --package $filmPackage
python -B -X utf8 release/installer.py install --package $filmPackage --app-root $filmApp --data-root $filmData --config-root $filmConfig
```

首次安装依次检查环境、完整文件集合及哈希，保存不可变原包，生成本机绝对 MCP 配置，运行真实 stdio `tools/list` 和 `film_health`，最后初始化空 catalog 与必要用户配置。没有默认项目、演示项目、Pages/账号/聊天绑定；不扫描磁盘或导入真实作品。检查失败不会把该版本标为有效活动版本；已留下的残缺版本目录会在 `status` 或下一次安装中明确拒绝，供人工核查。

目录结构：

| 位置 | 内容 | 升级策略 |
| --- | --- | --- |
| `app-root/releases/<版本>/` | 按发行清单校验的原包 | 不覆盖同版本 |
| `app-root/deployments/<版本>/` | 独立安装副本、生成的本机 MCP 配置 | 仅 `.mcp.json` 为登记的本机差异 |
| `app-root/deployment-records/` | 来源清单摘要与本机差异摘要 | 每版本留存 |
| `app-root/state.json` | 本机选择的版本与目录 | 不代表已有聊天实际运行版本 |
| `data-root/catalog/projects.sqlite3` | 明确登记的项目目录和聊天关联 | 不覆盖 |
| `config-root/user.json` | 必要用户配置及用户扩展设置 | 不覆盖既有配置 |
| `app-root/backups/<事务ID>/` | 程序选择、配置、catalog、显式作品一致快照 | 更新和恢复分别保留 |
| 用户明确的作品目录 | `.project/registry.sqlite3`、媒体与项目文件 | 不在程序目录中；不扫描 |

现有用户可以显式传 `--catalog-path <原 catalog 绝对路径>` 沿用原登记及聊天关联。安装器只核查该数据库结构与完整性，不打开里面登记的任何作品。已有配置目录的 `app_root/data_root/catalog_path` 若不同，安装拒绝覆盖，须先安排明确迁移。

Python 路径可用 `--python <python.exe>` 选择；升级默认沿用已保存的 Python 配置。本机 `.mcp.json` 指向 `deployments/<精确版本>/plugin/mcp_server.py`，不依赖 `PLUGIN_ROOT` 变量展开，不指向可变的 `current` 目录，也不依赖开发源目录。

Windows 未启用长路径时，深层专业方法文件可能触及系统路径长度上限。安装器预先检查并提示选择较短的 `app-root`，不会要求移动作品；推荐使用上方应用数据目录示例，避免多层长名称目录。

## 接入桌面宿主

```powershell
python -B -X utf8 release/installer.py host-plan --app-root $filmApp
```

此命令生成 `host-marketplaces/<版本>/.agents/plugins/marketplace.json` 及已核验插件副本，使用 `./plugin` 相对来源；MCP 仍指固定部署版本。用当前桌面附带 CLI 的实际 `--help` 或宿主插件界面添加返回的 marketplace 目录，再安装 `film-production-agent@film-production-local`。不要把系统 PATH 中另一份 CLI 当作当前桌面 CLI。

如果当前桌面 CLI 支持 marketplace 命令，可使用 `codex plugin marketplace add '<host-plan 返回的 marketplace 绝对目录>'`，然后在桌面插件目录选择该来源并安装。具体入口以目标客户端的实际功能为准；只添加来源不等于安装完成。插件展示为影视制作助手，稳定技术身份仍是上述 `film-production-agent@film-production-local`。

`host-plan` 不操作宿主安装；`install`、`stage`、`switch` 也不会自行重载已有聊天。安装成功、工具子进程通过、原生面板显示、目标聊天实际 `film_health` 是四层不同证据。接入后在目标聊天核对实际版本、`runtime_isolated=true`、八模块解析，并打开面板验证。旧聊天可继续持有旧版本，其固定目录保持保留。

新会话中可要求：“核验影视制作助手实际运行版本，确认八个内置模块并打开看板。”本版预期 `film_health.version=1.16.0`；读取结果与预期不符时先核对该会话加载的来源，不能仅凭下载文件名称声称已经更新。

## 建立第一个项目

在工作对话中说明作品名称、明确保存目录、创作路线，以及是否搭建整套主要工作对话。总控负责登记、读取现有绑定、创建缺少的真实对话，并调用随包助手生成项目目录和索引。

随包助手位于 `plugin/skills/film-production-agent/scripts/scaffold_project.py`，参考流程位于同一技能的 `references/project-bootstrap.md`。助手只处理已登记项目的本地目录与导航，真实聊天创建仍由宿主完成。已有对话与未知请求先恢复，专业对话不递归创建整个工作区。

安装包不写入全局个人规则，不携带开发者对自动建聊的持续授权。若使用者希望以后建项自动搭建，可在自己账号的工作对话中明确设定；已有本机个人默认继续保留。缺少对应客户端项目或宿主能力时，报告“待关联／待创建”并保存已完成步骤。

## 检查、预备和切换更新

```powershell
python -B -X utf8 release/installer.py check-update --app-root $filmApp --package '<新版 ZIP 绝对路径>'
python -B -X utf8 release/installer.py stage --package '<新版 ZIP 绝对路径>' --app-root $filmApp --data-root $filmData --config-root $filmConfig
python -B -X utf8 release/installer.py switch --app-root $filmApp --version '1.16.0' --quiescent
python -B -X utf8 release/installer.py host-plan --app-root $filmApp
python -B -X utf8 release/installer.py status --app-root $filmApp
```

`check-update` 仅校验和比较版本；`stage` 仅准备不可变副本，已安装时即使使用 `install` 也不会自动改活动版本；`switch` 选择目标副本并备份配置/catalog。新建宿主接入或更新后，必须在目标聊天读真实 health。刷新来源不等于正在执行的聊天升级。

切换前应让 catalog、配置和显式作品的写入停止，再传 `--quiescent`。该参数是操作方的明确确认，不是进程自动探测或强制结束；它保证失败恢复不会覆盖同时发生的外部写入。只读的旧聊天及已固定的旧 runtime 文件不被改写。

作品只接受重复传入的 `--project-root <明确作品目录>`；省略时所有作品均未打开、未迁移。显式作品的 schema 必须落在发行清单兼容区间内，在执行任务（created/in_progress/needs_review）会阻止切换。未显式打开的项目依靠运行时任务版本锁与旧固定 runtime 保护，不会把旧任务的规则改成新模块。不能用开关绕过该锁。

目前数据 schema 为 2，发行更新不需要变更数据库。schema 不兼容会直接拒绝：需先配套备份，在隔离副本用目标运行时进行明确迁移并验证；安装器不声称可自动逆迁移。旧 schema 1 的运行时转换仍遵守核心先备份后迁移的规则，不能把仅切回插件版本当成数据回退。

## 失败与恢复

切换前会生成 SQLite 一致备份、完整配置快照，以及每个显式作品的全部文件快照（包括媒体），并保存事务日志。故障发生在切换事务内时，自动恢复程序选择、catalog、配置和这些显式作品；异常日志仍需读取，不能把失败当成功。

手动恢复前结束相关编辑、关闭相关 stdio 写入者，再执行：

```powershell
python -B -X utf8 release/installer.py rollback --app-root $filmApp --quiescent
# 或指定历史事务 ID：
python -B -X utf8 release/installer.py rollback --app-root $filmApp --transaction '<事务ID>' --quiescent
```

`--quiescent` 表示操作者已确认相关写入停止，不是检测或强杀进程。恢复会先保存升级之后的配置/catalog/显式作品安全快照，再按目标快照恢复。配置恢复为旧完整文件集合，原配置目录额外留存为 `config.before-restore-<ID>`；新生成的项目媒体不自动删除，数据库引用恢复为目标版本。返回的 `post_update_safety_backup` 保留更新后的全部变化，便于必要时找回。不会覆盖历史正式发行包。

崩溃后若 `transaction.json` 留在 `prepared`，在确认进程已退出后使用 `recover --app-root ... --quiescent`。若 `.installer.lock` 残留，先核对其中 PID 和时间，确认没有安装进程后人工移开该锁，再恢复。安装器不猜测另一个进程已经结束，也不删除活跃锁。

回退仅改变本机安装选择和备份覆盖范围；已有宿主聊天并不会自动重载。使用恢复版本的 `host-plan` 重新接入，并在新聊天核验 health。仅靠旧缓存不能证明完成恢复。

## 唯一总控入口与独立专业技能

先只读检测明确技能根：

```powershell
python -B -X utf8 release/installer.py duplicates --skill-root '<明确个人 skills 根目录>'
```

确认插件内置方法和宿主入口可用后，只将重复个人总控移到技能发现目录以外：

```powershell
python -B -X utf8 release/installer.py migrate-entry --skill-directory '<明确个人 skills 根>/film-production-agent' --backup-root '<技能发现目录之外的备份目录>'
python -B -X utf8 release/installer.py restore-entry --receipt '<上一步返回的备份路径同名 .json>'
```

该功能先复制全部文件并核验哈希，再仅移除明确的重复总控源目录，生成可逆回执；恢复拒绝覆盖已存在入口。不能用它处理其他技能。独立安装的专业技能与原导演工程保持原样，仍可单独写小说/拉片；总控项目内先恢复正确 project/task/精确版本，再使用八个包内模块，不启动旧引擎或旧数据库。安装器不会自动停用专业入口。

## 停用、卸载和搬家

`deactivate` 或 `uninstall` 仅将本机选择标为停用并返回下一步说明，保留所有程序版本、配置、catalog 和作品。实际宿主停用/卸载须在桌面插件管理中完成。保留旧目录是恢复保障，不声称插件已从宿主移除。

新设备先空白安装，再单独移交用户明确选择的作品备份及配置。程序 ZIP 不夹带作品。作品保持 project ID；明确使用 `film_projects relink` 校验项目身份并重映射本地目录。聊天/Pages 关联在原目录迁移中保留为历史事实，新账号或新宿主需要重新确认可访问性并明确重绑，不把旧 ID 当成新宿主实际身份。

本仓库公开提供可下载版本与源码，没有后台设备同步或远程安装服务。登录同一账号、同步聊天、拉取 GitHub 仓库均不能代替新设备上的安装和宿主接入。个人 `AGENTS.md`、自定义默认、外部资料库及媒体路径应按明确范围迁移；不可直接用旧机器的绝对路径覆盖新环境。

## 验证边界

`test_installer.py` 全部使用 synthetic 临时夹具，测试文件完整性、ZIP 路径安全、首次空安装、既有 catalog 保留、更新检查与切换分离、活动任务/schema 拒绝、失败恢复、手动全快照恢复、残缺安装、重复个人总控可逆迁移、宿主方案生成和 CLI。其小型 stdio 夹具只验证安装器事务行为；真实 filmprod 模块、工具、面板和 AI 视频提示词必须在整体发行验收另行核查。本机换目录模拟不等于另一台电脑或另一 Windows 账户的真实验收。
