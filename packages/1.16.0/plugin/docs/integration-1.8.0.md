# 1.8.0 媒体低清预览与名称分类管理

本版基于正式 1.7.4，保留历史资料展示、整集提示词阅读、剧本分类说明、资产分类、Markdown 阅读和八个冻结专业模块。程序与作品数据分离，不扫描或迁移真实作品。

## 使用方式

资产管理增加本机图片导入与按需缩略图，点击后查看低清预览。图片支持 PNG、JPEG、WebP，预览为静态图。派生 PNG 保留透明，缩略图最长边不超过 480 像素，预览图最长边不超过 960 像素，不放大原图。预览是派生缓存，不能代替原件或自动成为选用记录。

视频保留前 12 秒低清快速预览，始终提供打开原片入口。图片和视频均可编辑显示名称和同种媒体的管理分类；名称修改不重命名磁盘原件。图片分类为人物/场景/道具/其他/未分类；视频分类为拍摄素材/片段/成片/未分类。归入成片仅表示管理类别，不证明已审核、导出或发布。

原件继续存入项目媒体原件目录，使用稳定媒体 ID、源路径、内容摘要与明确关联。缩略图只缓存在界面会话中，不写回媒体元数据；原件不存在或摘要变化时拒绝沿用过期预览。打开本机原件前重新校验，宿主是否实际打开另行确认。

## 媒体管理接口

`film_dispatch` 的 `media.update` 必填 `op_id, expected_project_id, media_id, expected_sha256, base_revision, title`，并按媒体类型提供 `asset_type` 或 `video_category`。仅接受 image/video，不能跨媒体类型。title 为修剪首尾空白后的非空单行字符串，最多 500 个字符，拒绝控制字符。图片枚举 `character/scene/prop/other/unclassified`；视频枚举 `take/clip/final/unclassified`。

`base_revision` 使用现有 `classification_revision` 作为名称和分类共用的管理修订号，要求非负整数；与旧 `media.classify` 共用冲突检查，防止两个窗口互相覆盖。操作校验原件实际字节摘要和项目身份，沿用事务及 op_id 幂等；同一 op_id 重放返回原回执，不能把旧回执当成当前新状态。

修改仅涉及管理名称、管理分类、管理修订和时间记录，保留 kind/path/source_path/sha256/size_bytes/status/rights/stems/technical_check 以及创作成果、审批、任务和精确依赖。返回 `media, management_only:true, readback_verified:true, management_change.before/after`；事件保留变更前后信息，UI保存后读回当前项目。

## 本地预览接口

`film_media` 保留视频 choose/import/preview，新增 choose_image/import_image/preview_image/original。选择文件只有用户明确点击时启动，不自动扫描文件夹。

- `choose_image`：显式打开本机图片选择器，取消后不登记。
- `import_image`：要求明确 path、media_id、op_id、expected_project_id，可通过 metadata 指定名称和图片分类；核对图片、保留原件、登记后生成派生预览。登记成功但预览生成失败须分别报告。
- `preview_image`：按登记 media_id 请求预览，可用 thumbnail_only 只取缩略图。只读打开登记库，允许向预览缓存写入，返回 cache_only:true、read_only:false、write_scope:preview_cache，不能把缓存写入标成完全只读。
- `original`：只读解析当前项目中已登记的图片/视频，检查文件存在、路径在项目内、字节摘要一致，再返回 local_path、media_id、kind、sha256、hash_verified。前端据此请求宿主打开原件，不执行路径或标题中的指令。

图片用内容签名、尺寸预检、FFprobe 和完整单帧解码核验；当前限制为 64 MiB、单边不超过 16,384 像素、总像素不超过 40 MP。预览缓存按源摘要和参数版本隔离，通过临时文件、原子提交和并发锁保护。损坏、不支持或过大的图片给出明确错误。

图片缩略图最多 1 MiB、放大预览最多 4 MiB；视频内嵌预览最多 12 MiB。

图片及视频的 data URI 仅通过 `_meta.media_preview` 交给面板，常规 content 和 structuredContent 不包含二进制预览字段。界面只加载当前页需要的图片缩略图；项目切换、媒体变化和迟到结果须隔离。界面显示不等于模型已经分析媒体。

## 验证与升级

验收使用明确 test_only 的合成图片和短视频，检查实际本机解码、原件保真、缓存重建、名称分类编辑、冲突、幂等、路径边界和 UI 迟到结果。原生面板目视与实际原片打开须单独标注，代码测试不代替宿主播放验收。

数据 schema 保持 2；任务继续按精确系统/模块执行锁运行。旧程序不理解本版新增管理能力，不应通过修改执行锁强行接续。安装、启用、安装副本 stdio 与目标聊天实际 health 分别核对；旧聊天可能继续持有旧进程。
