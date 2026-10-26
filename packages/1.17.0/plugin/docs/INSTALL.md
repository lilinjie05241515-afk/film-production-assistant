# 安装影视制作助手

本页为安装入口。完整命令和恢复规则保存在**源码根或发行 ZIP 根的 `release/installer-guide.md`**。发行 ZIP 内本页位于 `plugin/docs/`，不要把它所在目录当成安装命令的工作目录。

## 安装顺序

1. 从公开仓库的 [GitHub Releases](https://github.com/lilinjie05241515-afk/film-production-assistant/releases) 下载对应版本的 `film-production-agent-<版本>-stable.zip`、`.zip.sha256` 和 `.release.json`。用户可直接下载并使用发布包，无需单独申请仓库访问。
2. 核对下载摘要，完整解压发行 ZIP。运行环境为 Windows 或 macOS 桌面本地执行、Python 3.11+；媒体预览和渲染按需使用 FFmpeg／ffprobe。
3. 在解压根目录运行 `release/installer.py env`、`verify` 和 `install`，明确应用、数据和配置目录。
4. 运行 `release/installer.py host-plan`，取得本机 marketplace 路径，通过目标桌面的插件管理接入 `film-production-agent@film-production-local`。
5. 新开工作会话，要求核实实际 `film_health` 版本和八个内置模块，并打开看板查看结果。本版预期版本为 `1.17.0`。

Mac 的 Terminal 命令、目录和媒体工具说明见 [Mac 安装指南](MACOS.md)。Windows 使用 `python`／PowerShell，Mac 使用 `python3`／Terminal 或随包 `bootstrap.sh`；两者安装同一个发行 ZIP。

GitHub 自动生成的 `Source code (zip)` 是源码快照，与可直接安装的发行资产不同。下载安装包不会自动改变已打开的聊天。

## 第一次使用

说明作品名、明确保存目录和创作路线，可一次要求建立全部主要工作对话。项目搭建流程会保存目录、协作入口、对话索引及待处理状态，并复用已确认的对话。宿主没有创建客户端项目能力时，需要先完成对应项目的关联，不能用本地目录冒充侧栏项目。

安装包不设置你的个人持续授权。希望每次建项都自动搭建时，在自己的工作对话中明确设定；其他人安装同一包不会继承这项个人选择。

项目文件保存在授权的作品目录，程序安装目录保留固定版本。音乐创作和视频生成提供方未接入；可先使用文本创作、提示词和已有素材管理。
