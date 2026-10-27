> 版本专题与兼容记录。接口细节按当前工具定义核对；旧版看板按钮、当时开发目录和执行安排只用于追溯。当前操作职责见 [现行规则](current-rules.md)，兼容边界见 [兼容说明](compatibility.md)。

# 1.15.0 项目进度与资料看板

本版以 1.14.0 编剧与美术总监联合版为基础。八个专业模块及其完整方法原字节保留；当前数据 schema 仍为 2，无自动真实作品扫描或迁移。看板职责为查询进度、完整资料和审核记录，以及项目内文件素材管理。业务执行留在工作对话。

## 调用边界

所有旧工具明确声明 `_meta.ui.visibility=["model"]`，保留工作对话的创作、导演反馈、美术、采用、云稿、任务和渲染能力。新的 `film_board_manage` 只对 app 可用；其 `action` 按有限允许列表校验，拒绝业务动作后才解析项目目录。界面只使用此入口，没有发送消息、创建对话或通用工具转发出口。旧 HTTP 兼容入口仅保留准确查询，不作为本版发行运行依赖。

MCP Apps 宿主必须按工具 visibility 拒绝 App 调用 model-only 工具，见 [官方规范](https://github.com/modelcontextprotocol/ext-apps/blob/main/specification/2026-01-26/apps.mdx)。服务端允许列表、界面出口及宿主实际执行是不同验证层次；stdio 本身无法从调用者自报字段认证来源，不以伪造 origin 标记授予权限。

允许的管理包括：项目登记 register/relink/bind/unbind/forget；已有媒体导入和低清预览；准确版本正文、历史、引用、使用关系、同步和审核查询；显示名称、分类、排序、标签和资产关联；选定导出与逻辑回收恢复。新建作品、选路线、创建任务、新版正文、恢复旧正文为候选、审批、云端写入、生成和渲染不在允许列表。

## 准确管理协议

`film_board_manage` 参数为 `root`、`action`、`payload`。snapshot 可以从已知真实 thread_id/client_project_id 解析既有绑定，也可使用明确 root；后续资料操作必须携带 expected_project_id。查询用只读 Registry，缺少 catalog 时不建立空库。

| action | 主要字段与结果 |
| --- | --- |
| `board.item.set` | op_id、expected_project_id、target_type、target_id、version（成果必需）、expected_sha256、base_revision、title、category_id、tags；asset_id 可空。仅写展示设置。 |
| `board.categories.set` | op_id、expected_project_id、media_kind（document/image/video/audio）、base_revision、categories[{id,label}]。保留已存在ID，允许新增、改名称与排序。 |
| `board.items.batch` | op_id、expected_project_id、operation（organize/trash）、items。事务内全成功或全部回退。 |
| `board.reference` / `board.usage` | 准确目标、version和expected_sha256；返回稳定引用、范围、采用事实及实际已登记使用关系。外部未追踪使用为 unknown。 |
| `board.export` | expected_project_id、items 中明确列出的准确身份和摘要；核验所选正文/原件，写入项目固定资料包目录后读回哈希。 |
| `trash.set` | 准确目标、摘要、base_revision、deleted；仅管理列表，采用、正文、原件和冻结依赖保持。 |

`snapshot.board_library` 含项目内分类、准确版本条目、分媒体计数、明确资产关联、总览和审核记录。旧 presentation、media分类和trash记录继续读取，不强制改写。新管理设置不进入正文、正式采用或依赖表。

文字资产提示词与媒体分开。稳定asset_id是明确的管理关联，不能变成采用决定。图片、视频和音频原件各自计数；同一文稿的多个展示版本应按版本身份阅读，不将计数等同于项目完成。

## 版本与范围

最新工作稿、当前准确采用指针、既有任务冻结输入和本批制作锁定分别展示。任务曾引用某版不等于当前批次采用；没有明确批次关系时本批锁定保持未记录。已回收资料从新任务自动风格选择和默认建议中排除，已存在任务的精确输入及执行锁保持。

全剧范围、代表章节和当前批次仅展示实际登记的非空证据和来源版本；一集通过不代表全剧完成。没有全剧范围就保持未知；本版不计算基于文件数的完成百分比。

审核记录区分意见、处理、新版复核、用户采用和依赖变化原因。每条结论绑定准确版本与范围；无记录显示未记录，已处理意见不是新版通过。更名、分类、标签和恢复不会改变业务状态。

## 媒体与导出

图片沿用静态PNG/JPEG/WebP核验与480/960边长预览；视频沿用前12秒低清预览。音频接受已有WAV/MP3/M4A/AAC/FLAC/OGG/OPUS/AIFF等文件，使用本地FFmpeg/ffprobe核验及生成最长20秒的低码率试听副本，不创作音乐。派生二进制仅通过UI `_meta.media_preview` 返回。缺少FFmpeg或不能预览时如实显示原因，原件不是预览文件。

导入只接收用户选择的明确文件，不扫描作品或全盘；不因名称含“最终版”而采用。原件保留来源、摘要和稳定登记ID。重复操作使用原op_id核对；不同请求复用同号拒绝。媒体目的目录、预览和导出拒绝越界链接。

资料包保存在 `11-导出/资料包`，包含准确正文/原件与资料清单。原件不上传；导出不发布、不改变采用。回收站是逻辑管理，不物理删除原件、不释放磁盘空间、不自动撤销采用；恢复只恢复可见性。

## 兼容和验证边界

编剧、美术、云稿手改保护、准确依赖、完整正文、旧任务锁、项目登记和工作对话中的历史恢复能力继续保留。1.14任务按旧锁接续，不把新版本安装视为旧任务可写许可。新看板不重放旧版业务待处理请求。

包交付、隔离安装、正式安装与客户端实际启用须分别报告。本轮默认交付可安装包，既有安装不变；实际验证结果见同级交付报告和验收日志。测试仅用独立test_only项目、synthetic决定和模拟云观察，不代表真实影片质量或云端写入成功。
