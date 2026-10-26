# 在 Mac 安装影视制作助手

1.17.0 提供 macOS 安装与运行适配，与 Windows 使用同一发行 ZIP。插件需要支持本地执行和本地插件的 Codex／ChatGPT 桌面客户端、Python 3.11+ 及其 sqlite3。请先确认目标 Mac 能运行所选客户端；插件脚本的兼容性不代表所有旧款 Mac 都能运行该客户端。

本页在源码中位于 `docs/`，在发行 ZIP 中位于 `plugin/docs/`。下方命令均从**完整解压后的发行 ZIP 根目录**执行；完整安装、升级和恢复规则在该根目录的 `release/installer-guide.md`。

## 下载与核验

从 [GitHub Releases](https://github.com/lilinjie05241515-afk/film-production-assistant/releases/latest) 下载 `film-production-agent-1.17.0-stable.zip`、同名 `.zip.sha256` 和 `.release.json`。GitHub 自动附带的 `Source code (zip)` 是源码快照，请选择发行附件。

打开 Terminal，按文件实际位置调整以下路径。双引号保留空格与中文路径，`$HOME` 会展开为当前用户目录：

```sh
film_package="$HOME/Downloads/film-production-agent-1.17.0-stable.zip"
film_expected="$(awk '{print $1; exit}' "$film_package.sha256")"
film_actual="$(shasum -a 256 "$film_package" | awk '{print $1}')"
if [ "$film_actual" != "$film_expected" ]; then
  printf '%s\n' '发行包 SHA-256 不匹配，请停止安装并核对下载来源。' >&2
  exit 1
fi
```

完整解压到自行选择的文件夹，进入该解压根目录，再检查环境和包内清单：

```sh
bash release/bootstrap.sh env
bash release/bootstrap.sh verify --package "$film_package"
```

`bootstrap.sh` 检查可用的 Python 3.11+ 与 sqlite3，找不到时给出说明，不自动安装。可以显式指定 Python，参数放在动作之前：

```sh
bash release/bootstrap.sh --python '/自己安装的 Python 绝对路径/python3' env
```

已经确认 `python3` 可用时，也可用 `python3 -B -X utf8 release/installer.py` 替代 `bash release/bootstrap.sh`。不要依赖 macOS 自带 Python 的具体版本，也不要把 `python` 必然存在作为前提。

## 首次安装

以下目录是可修改示例，均为当前用户有权写入的位置；不需要 `sudo`：

```sh
film_base="$HOME/Library/Application Support/FilmProduction"
film_app="$film_base/application"
film_data="$film_base/data"
film_config="$film_base/config"
bash release/bootstrap.sh install --package "$film_package" \
  --app-root "$film_app" --data-root "$film_data" --config-root "$film_config"
bash release/bootstrap.sh host-plan --app-root "$film_app"
```

安装器核验文件与版本，保存独立部署副本、用户配置和空 catalog，并实际启动 stdio 进程检查工具列表及 `film_health`。Python 与脚本路径写成当前机器的绝对路径，带空格的路径作为单个参数传递。安装器不复制真实作品，不访问其他电脑，也不自动注册客户端插件。

通过目标桌面客户端的插件管理接入 `host-plan` 返回的 marketplace 路径，安装 `film-production-agent@film-production-local`。如果客户端附带 CLI 的实际帮助支持 marketplace 命令，也可使用该 CLI 添加此目录；具体入口以目标客户端当前功能为准，不套用 Windows 的可执行文件路径。

接入后新开工作对话，核实 `film_health.version=1.17.0`、`runtime_isolated=true` 和八个模块校验结果，再打开看板检查文稿与素材展示。安装器检查通过不代表客户端已经加载插件；原生面板的显示和操作仍在该 Mac 上验证。

## 图片、视频与音频

文字创作与版本登记不要求 FFmpeg。部分媒体探测、低清预览和本地渲染需要目标 Mac 可运行的 `ffmpeg` 与 `ffprobe`，由使用者自行准备。

```sh
command -v ffmpeg
command -v ffprobe
bash release/bootstrap.sh env
```

从 Finder 启动的桌面程序可能没有 Terminal 的完整 PATH。本版媒体查找先使用显式工具路径，再查当前 PATH；仅在 macOS 上继续检查 `/opt/homebrew/bin`（Apple Silicon 常见位置）和 `/usr/local/bin`（Intel 常见位置）。不会修改全局 PATH，也不会读取或执行 shell 启动文件。显式给出的路径无效时会报错，不绕过该选择改用另一份工具。

这些位置只是常见安装路径；FFmpeg 和 Python 仍须实际可运行。插件不要求 Rosetta，也不自动安装 Rosetta 或转换二进制架构。其他自定义工具位置应通过目标运行环境的 PATH，或相应功能支持的明确工具参数配置。

## 更新与 Windows 项目迁移

更新沿用现有三个目录，先核对新包，再准备新部署。保存工作并确认相关数据停止写入后，才执行 `switch --quiescent`：

```sh
bash release/bootstrap.sh check-update --app-root "$film_app" --package "$film_package"
bash release/bootstrap.sh stage --package "$film_package" \
  --app-root "$film_app" --data-root "$film_data" --config-root "$film_config"
bash release/bootstrap.sh switch --app-root "$film_app" --version '1.17.0' --quiescent
bash release/bootstrap.sh host-plan --app-root "$film_app"
```

这些命令用于已有安装的升级；首次安装已选择本版时无需重复切换。`--quiescent` 是操作者对写入已停止的确认，不是自动探测。回退使用完整安装指南中的 `rollback`，Mac 同样通过 shell 入口调用。

从 Windows 换到 Mac 时先新装程序，再移交用户明确选择的作品备份与个人规则。保留项目 ID，通过 `film_projects relink` 核对身份和新目录；重新检查旧聊天及云稿是否可访问。不要把 Windows 部署配置、盘符路径、Python 可执行文件或整个运行 catalog 当作在 Mac 已经正确绑定的环境。

显式 `FILMPROD_CATALOG_PATH` 及安装器保存的路径优先。未显式配置时，Mac 的默认 catalog 位于 `~/Library/Application Support/FilmProduction/projects.sqlite3`。此前手工运行旧版形成的 `~/AppData/Local/FilmProduction/projects.sqlite3` 不会被自动迁移或合并；先核实并备份，再用安装器的 `--catalog-path` 明确选择沿用哪个库。

## 验证范围

安装器输出记录实际 Python、操作系统和 CPU 架构，以及本次环境检查；这些不是桌面 UI 验收记录。单元测试、macOS CI、真实 stdio 安装测试与个人电脑客户端操作分别记录。macOS CI 验证范围以本版发行记录为准；即使 CI 通过，首次使用仍应在目标 Mac 核对插件加载、看板显示、对话搭建与实际媒体预览。
