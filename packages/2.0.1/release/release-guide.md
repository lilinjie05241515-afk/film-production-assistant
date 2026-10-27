# 影视制作助手 · 发行与更新

正式插件身份固定为 `film-production-agent@film-production-local`。本工具只构建、核验、写入明确的本地 Git 发布目录及获取发行包；不会联网、设置远端、上传、注册宿主插件或切换运行中的聊天。

当前目标为 2.0.1，支持 Windows 与 macOS 桌面本地执行。发行运行环境需要 Python 3.11+（核心使用 `hashlib.file_digest`），仅使用 Python 标准库；本地 Git 发布还需要 Git。其他操作系统未列为本版支持平台。Python、FFmpeg 与桌面宿主的可用性由安装器检查；FFmpeg 是媒体预览和渲染的可选外部依赖。

## 构建并冻结

先在独立目录整理干净 payload。根目录包括 `plugin/`、`release/installer.py`、`release/bootstrap.ps1`、`release/bootstrap.sh`、`release/publisher.py`、`install.py` 和必要文档。`plugin/` 内含兼容插件清单、相对路径 MCP 模板、完整 runtime、总控、编剧、导演、美术总监、脑暴接口五个技能入口和八个专业方法模块。构建器不会复制任意源码树或扫描作品。

```powershell
python -X utf8 -B release/assemble.py --source '<本版源码绝对路径>' --output '<新的payload绝对路径>'
python -X utf8 -B release/publisher.py build --payload '<新的payload绝对路径>' --output '<新发行目录绝对路径>' --version '<本次发行版本>' --channel stable
```

构建结果有三个同级文件：

- `film-production-agent-<版本>-stable.zip`：程序与方法发行包。
- `film-production-agent-<版本>-stable.release.json`：归档版本、文件大小、ZIP SHA-256 和内部清单 SHA-256。
- `film-production-agent-<版本>-stable.zip.sha256`：便于人工比对的摘要。

ZIP 根 `release-manifest.json` 的 `files` 列出除清单自身外的全部文件、大小和 SHA-256；清单本身由外部发行记录保护。运行 schema 区间在 `runtime` 中声明，专业模块清单用 `modules_lock` 固定。发行记录不代表代码已经安装，也不代表任何作品获批。

相同输出版本只要 ZIP、发行记录或校验文件有一个已存在，构建立即拒绝覆盖。变更正文、模块、安装器或依赖锁后必须递增版本。保留旧 ZIP 和旧 Git 标签。

构建与核验会拒绝数据库、作品目录、环境秘密文件、媒体原件、机器专属绝对路径、疑似凭据以及不安全 ZIP 成员。此扫描能检查既定模式，不能证明所有第三方文件的权利或所有秘密已经被自动识别；人工依赖来源审查仍以模块清单中的实际分发状态为准。

## 校验

从可信交付摘要取得 SHA-256 后，执行：

```powershell
python -X utf8 -B release/publisher.py verify '<发行ZIP绝对路径>' --sha256 '<交付摘要中的64位SHA-256>'
```

它会校验 ZIP 摘要、文件全集、各文件 SHA-256、插件版本和模块依赖锁。没有 `--sha256` 时仍检查包内一致性，但包内清单和文件被一起替换无法依靠自校验识别。SHA-256 是完整性证据，不能独立证明发布者身份；应核对可信交付渠道和 Git 来源。

## 版本与跨平台验证

运行模块、插件清单、看板版本及发行清单必须一致；2.0.1 的预期是 26 个工具、8 个方法模块和 5 个公开技能入口。维护旧版本目录、标签和摘要，不将本轮修改反写已安装缓存或既有发行包。

使用 `.github/workflows/compatibility.yml` 验证 Windows、Apple Silicon Mac 与 Intel Mac：后端工作流、安装/发行工具、全部当前看板交互测试，以及由实际安装包启动的隔离 stdio 和合成媒体流程。冻结后再次使用同一 ZIP 验证，重新组装的 payload 必须与 ZIP 内文件逐字节一致。跨平台 Unicode 文件名与换行差异不能仅靠版本字符串掩盖。

在上传正式 Release 前记录各平台结果、源提交和冻结 ZIP SHA-256。失败项修复后重新验证；来源不清或仅模拟执行的检查不能标为实际 Mac 测试通过。CI 验证运行层，目标客户端的插件发现、原生看板和实际工作对话单独验收。

## 本地 Git 发布源

```powershell
python -X utf8 -B release/publisher.py publish '<已冻结发行ZIP绝对路径>' --repo '<新的空发布目录绝对路径>'
```

首次操作只接受空目录，自动建立 Git `main` 分支。后续只能操作带匹配身份记录的本地仓库；检测到未提交文件会拒绝混入发布。提交使用工具自身的本地提交身份，不改全局 Git 配置。

发布目录包含：

```text
release-source.json
.agents/plugins/marketplace.json
channels/stable.json
channels/development.json                  # 有开发版时出现
releases/stable/<version>/<archive>.zip
releases/stable/<version>/release.json
packages/<version>/plugin/
development/.agents/plugins/marketplace.json
development/packages/<version>/plugin/
```

每个版本有 `stable/v<version>` 或 `development/v<version>` Git 标签。稳定 marketplace 名为 `film-production-local`；开发 marketplace 名为 `film-production-local-development`，用于明确选择的测试环境。稳定索引不会因发布开发版而更新。开发包仍保留正式产品身份于发行清单，开发 marketplace 后缀仅用于避免测试环境与稳定安装混淆。

发布源中的 `.mcp.json` 是可移植模板。安装器会在各目标平台另建本机适配副本，并生成适合当前桌面的 marketplace；先完成该流程，再用桌面插件管理加载。不要把尚未替换运行环境的模板直接当作当前机器已可启动的配置。

本地发布工具不会执行 `git remote add` 或 `git push`。远端目标未确定时，`release-source.json` 保持 `remote_status=not_configured`、`remote_url=null`。本地 Git 仓库和固定身份已准备，不表示远端更新服务已经上线。

## GitHub 仓库与发行资产

本项目的公开仓库名称为 `film-production-assistant`，展示名为“影视制作助手”。用户可以从公开仓库下载并使用发布包。仓库保存维护源码和固定版本的发布目录；GitHub Release 附件提供用户安装的 ZIP、发行记录及 SHA-256 文件。

公开下载与使用按项目发布者的本次授权记录。各模块来源、旧分发记录及上游许可状态随包保留，第三方依赖遵循各自许可；本次没有另加统一开源许可证，也不把未声明或尚未核实的上游许可改成“已核实”。

上传前以实际准备推送的文件和归档为范围检查：不要把作品目录、实际运行 catalog、用户配置、凭据、个人路径、真实聊天／Page ID、个人持续授权或开发机安装回执加入 Git。合成 TEST 数据应有明确标记；必要测试不借用真实作品。

推送源代码和稳定标签后，再上传同一冻结版本的三份发行资产。核对远端仓库可见性、提交、标签及资产名称，并下载资产比对 SHA-256。网页显示上传完成与取得的实际文件一致分别核验。失败或结果未知先查询既有远端状态，不新建同版本替代包或覆盖旧资产来掩盖差异。

GitHub 上的 `Source code (zip)` 是 Git 标签对应的源码快照；用户应下载名字包含 `film-production-agent-<版本>-stable.zip` 的发行资产。该资产包含安装器与完整运行内容，用户无需在另一台电脑从源码手工拼装插件。

本项目没有后台自动升级服务。仓库推送、Release 发布、另一台电脑取得更新、执行安装器、桌面加载插件和目标聊天换用新版，是不同步骤。用户端操作见 `installer-guide.md`。

## 检查与获取更新

```powershell
python -X utf8 -B release/publisher.py check --repo '<已审查本地发布源绝对路径>' --installed-version '<实际已安装版本>' --channel stable
python -X utf8 -B release/publisher.py fetch --repo '<已审查本地发布源绝对路径>' --destination '<下载目录绝对路径>' --version '<本次发行版本>' --channel stable --sha256 '<可信ZIP摘要>'
```

`check` 校验所选本地源的最新包并比较版本，不刷新远端。`fetch` 复制指定发行包并核验，已存在同名包只在摘要相同时复用，下载后 `runtime_changed=false`。

获得明确远端账号、仓库地址、可见性与上传授权后，才将经审核的发布仓库推送到指定 Git 远端。未来可通过官方 `codex plugin marketplace add <用户指定Git地址> --ref <明确分支或标签>` 追踪 Git 来源；本机不以命令存在推定账号具备访问权限。

官方 marketplace 刷新、此工具获取、安装器 stage、安装器 switch、桌面宿主安装、新聊天 `film_health` 是不同证据。升级须遵循安装指南，先保存工作并核对执行中的任务，备份配套配置、catalog 和明确指定作品后选择新版本。不要把 Git 同步或本地状态指针更新说成当前聊天已经换用新规则。

## 恢复与作品移交

发行包不含作品、真实项目、作者账号、Pages 或聊天绑定。作品移交包由明确作品的导出/备份流程生成，与程序 ZIP 分开。

回退由安装器的事务快照恢复程序选择、用户配置、catalog 和显式指定作品；schema 不兼容时不能只切换缓存。本工具获取旧版本只是取回程序，不执行数据逆迁移。保留新版本后的修改快照，再按安装指南恢复。

## 官方依据与验收边界

2026-10-24 核对的 [OpenAI 插件打包文档](https://developers.openai.com/plugins/build/plugins) 说明 marketplace 的相对路径与 Git 来源，并保留 `.codex-plugin/plugin.json` 兼容入口。[桌面插件文档](https://developers.openai.com/plugins/deploy/desktop-only) 说明 `${PLUGIN_ROOT}` 及 stdio 本地执行。规范支持与本机实际展开情况分别验收，发行流程使用安装时生成本机配置的兼容路径。

本地 Git、合成安装目录和独立 stdio 进程测试不能替代另一台 Windows 电脑，也不能替代当前桌面聊天的真实面板。最终交付报告应逐项写明实际版本、安装副本摘要、当前聊天 health、面板操作、异机测试是否完成。
