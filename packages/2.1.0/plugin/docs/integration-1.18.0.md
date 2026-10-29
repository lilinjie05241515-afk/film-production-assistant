# 1.18.0 创作看板正式接入

以已冻结 1.17.0 发行包为基础。主导航仅项目总览、创作任务、素材库；确认记录位于总览，项目设置位于辅助导航。保留 1.17.0 分层工作对话与专业模块，未迁移或自动操作作品。文稿可从成果阅读，独立版本回档管理页后续开发。

## 精确用户决定

新增 board.confirm、board.style.select、board.asset.select，仅经 film_board_manage 的固定允许列表供界面使用。保留通用业务工具 model-only，界面不能发送消息、创建聊天、创建任务、改稿或生成。显示候选不等于采用，打开、筛选和取消不写入决定。

- board.confirm：op_id、expected_project_id、target_type=artifact、target_id、version、expected_sha256、base_latest_version、base_master_version、confirmed=true，选填 note。核对原件、当前候选和总稿基础，复用已有批准检查、依赖失效标记与总稿更新；参考、回收项不能通过。只记录所确认版本，不自动开始后续创作或写云稿。
- board.style.select：op_id、expected_project_id、comparison_id、choice=main/alternate、target_id、version、expected_sha256、base_revision、confirmed=true，选填 note。只选择已登记完整主备方案，复用 art.select 对情境和版本的校验，不自动生成完整基准或批准。融合方案继续在美术工作对话先创作。
- board.asset.select：op_id、expected_project_id、target_type=media、target_id、expected_sha256、object_id、purpose、base_revision、link_revision、confirmed=true，选填 note。核对准确媒体字节和用途关联；reference_only 禁止选择。每个对象用途独立保存当前选用及完整选择历史，不删除旧候选，不替换冻结任务输入。

TEST 项目自动使用 synthetic 决定，不可冒充真人。panel-click 记录表示显式界面操作，不声称宿主认证用户身份。仍使用现有事务、op_id 幂等与未知结果查证。UI 缓存不是决定依据；旧窗口遇到版本或修订变化必须刷新后再确认。

## 对象、资料与项目

- board.object.set：object_id、title、type=character/scene/prop/shot/sound/final/other、base_revision，选填 intro/scope，以及统一 op_id/expected_project_id。
- board.asset.link：准确 target_type/target_id/版本/expected_sha256、object_id、purpose、reference 布尔值、base_revision。不得把已选素材直接挪到别的用途或改成参考。旧 asset_id 只作为显式分组来源，不从名称猜对象、用途或采用。
- board.project.set：title、intro、cover（null 或准确 media_id/sha256）、base_revision，统一 op_id/expected_project_id。项目资料保存在原 Registry，封面只作展示，不影响作品素材采用。
- projects.visibility：op_id、project_id、expected_root、base_revision、status=active/archived。归档只更新项目目录登记；保留文件、任务、绑定和真实对话。默认选择器隐藏归档项目；“已归档项目”可恢复同一项目。
- projects.forget 沿用原精确身份检查，仅忘记本机登记和定位绑定，不删除作品文件、云稿和真实对话。

数据继续使用 schema 2。新增对象、用途和决定在 settings 的 board1180/ 前缀中；snapshot.creator_board 返回 objects/links/selections/decisions/confirm_targets。项目 profile_revision 在 settings.project；归档 status/revision 在外部 catalog。只读打开不会补写对象或修改旧作品。

素材参考、候选和选用分别呈现。缺少真实图片显示占位或预览不可用，不用虚构图片冒充作品。缩略图按登记摘要核验。工作对话按钮只打开当前项目的实际关联，不创建或发送。

## 验证与交付边界

测试使用独立 TEST 数据，含后端事务测试、实际 UI 脚本的 VM DOM 操作测试、真实 stdio 接口测试及安装包摘要校验。VM DOM 通过不等于宿主视觉验收；安装与新进程版本不等于既有聊天已重载。保留旧发行、个人配置及工作区默认规则。
