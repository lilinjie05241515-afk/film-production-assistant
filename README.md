# 影视制作助手 2.0.1

面向 AI 短剧及影视开发的本地工作插件，支持 Windows 与 macOS。2.0.1 在 2.0.0 双主题看板、独立导演和 Blender 白模预演基础上补齐跨平台安装、媒体运行与发行校验；新版本不覆盖已有作品、任务历史或个人规则。

从 [GitHub Releases](https://github.com/lilinjie05241515-afk/film-production-assistant/releases/latest) 下载 `film-production-agent-2.0.1-stable.zip` 及同版 SHA-256、发行记录。请使用发行附件；GitHub 的 `Source code (zip)` 是维护源码，不能代替安装包。首次安装见 [安装说明](docs/INSTALL.md)，Mac 的完整步骤见 [Mac 安装](docs/MACOS.md)，升级和换电脑见 [更新说明](docs/UPGRADE.md)。

## 专业能力与入口

插件提供五个技能入口：[影视总控](skills/film-production-agent/SKILL.md)、[编剧](skills/film-screenwriter/SKILL.md)、[导演](skills/film-director/SKILL.md)、[美术总监](skills/film-art-director/SKILL.md)、[头脑风暴接口](skills/film-brainstorm-interface/SKILL.md)。包内八项专业方法包括编剧、美术总监、导演、特效、资产与视频提示词、影视分析、灵感探索和需求规划；编剧内部保留小说与改编方法。

直接剧本优先，也支持先写小说再改编。导演负责拍法、镜头、人物调度、节奏和特效需要的判断，剧情与对白修订交由编剧接续。美术总监维护全剧视觉方向，提示词与参考画面读取已确认的准确版本。已有项目共享同一登记和来源，按需加载对应专业方法。

## 看板与项目协作

- 黑金夜间、磨砂白日间共用项目总览、创作任务和素材库；任务可按列表或看板查看，文稿在侧边连续阅读。
- 素材按对象与用途管理，支持分类、标签、更名、低清预览和可恢复回收。资产提示词保存文字，图片、视频、音频单独管理。
- 明确确认准确文稿、选择已登记美术方案或用途素材使用受限接口；创作、正文修订、云稿写入、渲染、创建对话和发送任务在工作对话中执行。
- 导演可按明确请求制作 Blender 白模预演；看板支持完整视频、双画面、镜头定位与时间点原话反馈。镜头混选须另行合成、核验和确认。
- 分层会话按项目总控、部门总控和专题话题组织，当前完整闭环覆盖灵感与编剧。已有准确对话复用，未知创建或发送结果先核查。保存待办不表示有后台调度器。
- 云稿依赖宿主 Pages 能力，按轮读取、保留手改、写后读回。候选、采用版本与任务冻结输入分别保存，不提供后台实时双向同步。

## 安装环境和验证

需要支持本地插件与本地执行的桌面宿主、Python 3.11+ 及 sqlite3。文字创作无需 FFmpeg；媒体预览和渲染按需安装 FFmpeg/FFprobe，白模预演另需可运行的 Blender。安装器不自动下载依赖，不设置模型 API，不在后台升级其他电脑。

[跨平台 CI](https://github.com/lilinjie05241515-afk/film-production-assistant/actions/workflows/compatibility.yml) 分别验证 Windows、Apple Silicon Mac 与 Intel Mac。具体成功状态、提交和冻结包摘要以对应发行记录为准；当前 Mac 原生客户端面板及真实用户工作对话仍需在目标客户端核验。运行层兼容不代表所有旧款 Mac 均可运行所选客户端。

本版保留 26 个工具、8 个方法模块和 5 个公开技能入口。安装后在新工作对话核实 `film_health.version=2.0.1`、`runtime_isolated=true` 及模块校验，再打开看板。下载、安装副本、宿主加载与已有聊天实际运行版本分别核验。

完整功能见 [功能说明](docs/FEATURES.md)，当前规则见 [现行执行规则](docs/current-rules.md)，兼容和测试范围见 [2.0.1 接入说明](docs/integration-2.0.1.md)。音乐创作技能及音乐/视频生成提供方尚未接入；外部头脑风暴提供方也未连接。

## 维护与构建

在独立开发副本修改。看板通过 `python -X utf8 scripts/build_creator_ui.py` 从保存的构建输入生成；发行使用 `release/assemble.py`、`release/publisher.py` 和 `release/installer.py`。完整流程见 [发行指南](release/release-guide.md)。测试只使用独立 TEST/synthetic 数据，公开源码和程序包不包含真实作品、个人授权、账号凭据或本机安装记录。

插件技术身份保持 `film-production-agent@film-production-local`。第三方来源与分发状态保存在模块清单，公开下载不改变各依赖原有许可。
