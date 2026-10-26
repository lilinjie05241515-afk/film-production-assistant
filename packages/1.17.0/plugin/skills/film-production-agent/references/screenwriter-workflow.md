# 编剧意见登记与修订接续

文本方法先加载 `film_modules(module="screenwriter")` 返回的入口。以下工具保存准确反馈与处理证据，不代替编剧判断、正文保存、独立复核或用户采用。完整接口说明见系统 `../../../docs/integration-screenwriter-1.13.0.md`，字段以当前 `film_action_help` 为准。

## 意见登记

使用 `film_screenwriting(root,action="read",payload={expected_project_id,...})` 取得当前 revision 和相关意见，可用 artifact_id 或 feedback_id 缩小范围。

确认意见针对的实际完整剧本。`record` 写入操作号、项目身份、当前 base_revision、稳定 feedback_id、准确 script 引用（artifact_id/version/sha256）、与成果一致的 scope、scene_id、原文中的非空 anchor、problem、expected_effect、must_keep、impact、source，可选 suggestion。source 保留真实 role 与 reference，不能伪造导演来源。scene_id 与 anchor 应对应实际内容，程序的字面锚点检查不能证明全部场次语义。

impact 为 staging、expression、structure 或 major；按实际影响选择，不能为绕开决定降低等级。major 初始为 needs_user_choice，其余为 open。登记建议只保存意见，不改剧本、不批准、不自动云写；纯拍法 staging 优先留在导演。

## 修订与处理结果

读取当前剧本与云稿观察、明确授权及冻结意见，在约定范围内生成完整修订候选。重大剧情无相应选择时先列待选方案，不混入主修订正文；用户明确要比较版时保留独立候选身份。沿用 `film_draft_save` / `film_draft_submit` 或完整文件保存，1.12 云稿规则继续适用。

保存新版后重新读取意见 revision，用 `resolve` 保存 feedback_id、status、response 及必要 revised_script。状态为 addressed、partially_addressed、deferred、declined 或 needs_user_choice。expression/structure/major 的前两种状态要求同成果 ID、更高且最新的完整剧本版本；不能把仅说明“计划改”标为已处理。staging 的纯拍法处理可以没有新剧本。

major 的处理还需准确 user_decision，引用真实选择原话、来源、范围、原意见剧本及 feedback_id；真实操作 actor=human、synthetic=false，测试 synthetic=true。字段存在不是账号身份认证，也不能凭模型自述形成授权。若用户只要求比较候选而尚未选择实施，保留需要选择状态及比较稿引用说明，不伪造正式处理决定。

来源更新时 read/snapshot 中的 source_changed 表示意见基于旧版，需人工判断仍是否适用。旧 script 引用不改绑；必要时记录针对新版的另一条意见，并保留关系与旧处理历史。新候选不自动使通过下游失效，采用新稿后按依赖复核。

采用新版剧本导致既有美术基准需复核时，总控按[美术交接](art-direction-workflow.md)接续：交付新旧准确剧本、实际差异和必须保留项，由美术核对现有完整基准与云稿手改；仅在原方向内调整时沿稳定基准形成完整候选，不要求再次编写主备方案。风格、时代或已选角色外观需要改变时仍由用户明确选择。美术修订的保存、语义复核和正式采用分别进行；编剧意见的已处理状态不能替代它们，也不能为了消除需复核而改旧剧本或风格的准确依赖。

每次写入带原 op_id 和准确请求，冲突先重读并整合；结果未知先核查，同一操作不换号重发。意见处理结果、完整正文版本、语义复核、云稿已同步与真人采用分别向用户说明。保存意见不会创建聊天或自动发送任务。
