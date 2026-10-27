> 版本专题与兼容记录。接口细节按当前工具定义核对；旧版看板按钮、当时开发目录和执行安排只用于追溯。当前操作职责见 [现行规则](current-rules.md)，兼容边界见 [兼容说明](compatibility.md)。

# 1.9.0 分类排序与文件回收站

本版基于正式 1.8.0，保留媒体低清预览、名称分类编辑、历史资料展示、整集提示词阅读与源剧本/动态分场剧本说明。八个专业模块保持原版本。程序升级不扫描、导入或修改真实作品。

## 分类排序

创作内容分类、图片资产分类与视频分类支持拖动排序，同时提供不使用拖动的移动入口。排序以项目为单位持久化，其他聊天重新读取同一项目时取得相同顺序。“全部”筛选固定在首位，不作为业务类别参与排序。这里只调整分类显示次序，不改变创作路线、镜头、正文或任务的执行顺序。

film_dispatch 的 board.order.set 必填 op_id、expected_project_id、group、order、base_revision。group 只接受 content_categories、asset_types、video_categories；order 必须是该组所有类别 ID 的完整无重复排列；base_revision 为非负整数，布尔值不作为修订号。各组独立保存修订，旧窗口提交过期排序会收到冲突，不能静默覆盖后来修改。

默认类别：

- content_categories：idea、requirements、outline、novel、character_bio、style、source_script、script、director、vfx、asset、video_prompt。
- asset_types：character、scene、prop、other、unclassified。
- video_categories：take、clip、final、unclassified。

snapshot.board_order.groups[group] 返回 order 与 revision。首次读取返回默认排列且不写数据库。新建/重新加载面板以项目返回的设置为准，不把浏览器本地缓存当作权威。

## 删除与恢复

界面“删除”经过明确的“移入回收站”按钮确认后，只把选中的准确文件版本或登记媒体移出正常列表。项目回收站可查看身份和恢复。恢复只取消回收状态，不新增正文版本或重新导入原件。

这是逻辑回收站，不物理移动或永久删除磁盘文件，不释放磁盘空间，不调用系统删除或删除云端 Pages。原件、内容、摘要、批准、总稿、旧依赖和任务执行锁保持完整。被总稿、任务或已有成果引用的内容仍能按原精确版本读取；回收站不撤销批准或采用。管理回收状态与旧“归档到历史资料”分别保存，恢复时保留原来的展示分类、归档状态和审核状态。为新工作挑选常用素材或候选时排除回收站项；已有精确依赖读取保持完整，明确的历史核查和恢复按准确身份执行。

film_dispatch 的 trash.set 必填 op_id、expected_project_id、target_type、target_id、expected_sha256、base_revision、deleted。target_type 为 artifact 或 media；artifact 必填准确正整数 version，media 禁止提供 version。deleted 为布尔值，true 移入回收站、false 恢复。禁止任意文件路径或未登记目标。

目标身份以登记摘要核对，媒体原件已缺失也可管理其列表状态；此操作不读取或复核媒体原件字节，不返回字节核验成功。摘要不符、目标不存在、错误项目、过期修订或额外字段均拒绝。每个准确版本/媒体独立回收修订，不把一个版本的删除状态套用到同 ID 的新版本。

snapshot.trash.entries 包含 target_type、target_id、sha256、title、kind、revision、deleted、deleted_at、updated_at；artifact 另有 version。历史版本不必出现在 current_content 中，回收站仍应完整展示。UI 过滤正常列表时必须同时匹配准确目标和摘要，不能修改原 snapshot 的权威记录或推断业务状态改变。

返回及说明保留 management_only:true、disk_space_reclaimed:false，写入后读回核对。所有写操作沿用事务、同操作号幂等和审计事件；未知回执保留原请求、项目和操作号，先核查再恢复，不以新操作号盲目重复。拖动和确认窗口均冻结项目身份，切换项目或较晚返回的结果不能误写其他项目。

## 验证与升级

使用明确 test_only 的独立合成数据验证：项目设置重开、不同项目隔离、排序完整性、并发冲突、幂等、准确版本回收与恢复、原件/正文/审批/任务依赖不变、UI 迟到结果、未知写入回执与实际 stdio 协议。源数据和旧发行包保持不动。

数据 schema 保持 2。新增管理状态放在独立设置中，旧程序可能忽略新排序与回收状态，因此需实际运行 1.9.0 看板；不要把旧程序显示某记录误认为恢复，也不要为接续任务手改执行锁。安装、启用、安装副本 stdio、当前聊天版本以及原生面板验收分别记录。

