# 2.1.0 会话协作与开放探索

本版扩展已登记部门的管理与执行分层，增加跨职责交接，分开记录成果完成与回报，并在原灵感记录中保存明确的探索阶段。工作方式见[分层会话管理](../skills/film-production-agent/references/conversation-management.md)、[职责归属与转交](../skills/film-production-agent/references/request-routing.md)和[灵感、需求与记录](../skills/film-production-agent/references/planning-workflow.md)。当前字段以 `film_action_help` 和运行包 schema 为准。

## 数据和身份

仍使用同一作品 Registry、schema 2、`conversation/v1` 和已有 `planning_record`；不建立第二套权威记录库。读操作不迁移真实作品，不补建聊天、不发送旧消息、不修改任务执行锁。旧项目未采用分层时保留原语义；已采用项目的当前登记决定管理/执行职责，旧初始化提示或标题不能覆盖该登记。

`film_conversations(action,root,payload)` 继续要求明确作品 root。所有写动作保留 `op_id`、`expected_project_id`、准确 `base_revision`；除 claim/observe，另有实际 `actor_thread_id`。业务写入可携带本次 `authorization`，不提供时仅沿用已保存且覆盖当前动作与目标的授权。`configure` 仍要求明确授权。身份、原话、授权和宿主观察均是调用者报告，字段检查不认证人类身份或理解自然语言。

授权 actions 新增 `route`、`route_accept`、`report`，其余结构沿用 [1.17.0 合同](integration-1.17.0.md)。只登记用户实际授权范围，不能为了通过校验默认填 `*`。允许登记或完成不代表允许向其他聊天发送；其他 Agent 的请求本身也不是人类授权。

## 部门与任务

父入口从已核验的项目级 workspace 槽位取得，须有准确真实聊天、宿主观察、目录绑定以及同一客户端项目归属。基础总控、灵感和当前路线编剧入口继续必需；其他已核验部门可纳入 parents。缺少主责由项目总控按适用授权补齐再 configure，不以同名聊天或目录存在冒充已关联，不自动复制七类入口。

| 部门 role | 接受的专业范围 |
| --- | --- |
| planning | 灵感探索、需求规划；讨论话题和需要独立交付的规划任务分开 |
| script | 剧本、大纲、人物、修订和改编 |
| novel | 小说、大纲与人物 |
| director | 导演与特效，保留各自真实 task_module |
| art | 美术总监及其影视研究支持 |
| assets | 资产提示词、AI 视频提示词 |
| review | 独立审核、剪辑及交付登记 |

`read.role_modules` 返回实际接受的模块名称与兼容别名。创建任务仍使用 `film_modules` 返回的准确 task_module，完成时校验该模块允许的真实成果种类。部门存在不表示音乐、视频或其他生成服务已连接，review 的任务范围也不替代独立审查者、实际渲染或用户采用证据。script/novel 仍校验项目既有路线，不借转交悄悄改路线。

旧项目若已经 `enabled=true`，但 parents 仍仅含早期的 control/planning/script（或适用小说入口），新增导演、美术等任务会触发 2.1.0 部门与执行话题校验；“旧项目兼容”不代表这些新任务仍可在旧部门入口直接执行。由项目总控核验当前 workspace 的准确部门关联，在适用授权内显式 configure 补齐父入口，再复用或建立执行 topic 并创建、绑定准确任务。不能仅改 actor、复制聊天或绕过 guard；缺部门时先协调补齐，不把读操作当迁移。旧 enabled=false 项目继续原非分层语义，已有任务的原 execution_lock 与恢复规则保持不变。

总控与部门总控做输入核对、必要澄清、派发和汇总；具体正文与制作在准确执行话题完成。简单咨询可以就地解释。既有灵感 `decide/accept` 交编剧流程保留；直接明确需求可以直接 prepare，不强制先创建灵感记录。任务模块、作用范围、目标成果和输入必须与话题吻合，同范围一名编辑者。原任务尚未结束时继续原任务与检查点，不以新聊天、route 或 task 绕过旧锁与未知结果。

## 跨职责交接

以下为公共写字段之外的追加字段；所有准确成果引用均为 `{artifact_id,version}`，不能填“最新”。

| action | 追加字段与行为 |
| --- | --- |
| route | `request_id`、`original_request`、`target_role`、`scope`、`inputs`、`deliverable`、`report_to_thread_id`。原请求保留用户原话，deliverable 写清完整交付要求；inputs 可在确无来源时为空。准确源 actor、目标部门和回报聊天须属于该项目已核验登记。可选 target_artifact_id 锁定交付目标；填写时 prepare/continue 必须匹配。 |
| route_accept | `request_id`、`status=received/clarifying/ready/declined`，可带 `brief/questions/inputs`。仅真实目标部门 actor 可接收；clarifying 有具体 questions，declined 用 brief 说明原因；ready 必须有 brief、inputs 且无未决问题。 |
| prepare（转交执行） | `topic_id`、`kind="execution"`、`title`、`scope`、`route_id`、`target_artifact_id`。route_id 是准确交接 request_id，须 ready 且尚未分配执行话题。与 handoff_id、direct_brief、inputs、target_role、planning_ref 互斥。 |
| continue（复用执行） | 原 topic_id、brief、inputs，可选 route_id。接新转交时必须提供 ready 且未分配的准确 route；同部门、同范围、原目标成果及完整 inputs 均须匹配。保留原聊天，不绕过旧轮完结检查。 |
| prepare（直接执行） | 原 direct_brief/inputs/target_role/target_artifact_id 形状保留；target_role 扩展为上表已登记部门。 |

route 保存来源、目标、原始准确 inputs、交付要求、回报目标与授权证据，返回 `notification_sent=false`、`dispatch_allowed=false`。它不创建外发待办，不发送消息，也不证明接收方已经阅读。由当前宿主在真实授权范围把准确交接引用发给已核验部门；接收方读取记录后再 route_accept。没有发送权限时保留待交接事实和交接包，不伪造已转达。

同 request_id 的原请求、输入、目标和回报目标被冻结；参数改变不能静默复用。接收 ready 可补充必要准确输入，但须保留原交接输入；确需换底本时另行明确新交接，不能把旧输入换成当前候选。没有目标部门、主责冲突或路线不符时先协调，不能创建任意替代聊天。已有同任务话题优先复用，不能因每条问题、每次改稿或脑暴分支新增聊天。

准备话题之后沿用完整宿主链：prepare → claim → 实际创建/复用 → observe 真实 ID → 作品绑定 → task.create/bind_task → start → claim → 实际发送 → observe → 有限等待与准确成果核验。登记工具不执行宿主动作；排队 ID、保存成功、宿主受理和业务完成分别核对。未知结果先查原请求，不换号重发。原话题后续明确新轮继续使用 continue，保留历史任务和输出。带 route_id 时绑定本轮新转交与回报目标；未带时是直接接续，本轮不继承旧转交的外发目标。旧轮 route_id/report_to_thread_id 与待回报结果保存在 task_history，历史 report 仍使用该轮准确收件人，不被新轮目标覆盖。

## 完成与回报分开

`complete` 仍使用 `topic_id/task_id/output_ref/summary`。实际执行话题或所属部门须报告真实 actor，并有 complete 授权；绑定任务必须已 submitted，准确输出、范围、专业成果种类及 execution_lock 必须匹配。只写聊天总结或保存部分草稿不能登记完成。

完成记录保存准确成果、完成摘要、正文 SHA-256 和完成时间。缺少某个接收人的 send_message_to_thread 授权时仍保留完成记录，该接收人的回报保持 pending_authorization；授权覆盖的接收人可正常准备原宿主待办。返回 `completion_recorded=true` 只表示完成事实已登记，`notification_sent=false` 表示此接口本身没有发送消息。执行完成不等于独立复核、云稿同步、用户采用或发布。

新增 `report` 使用 `topic_id/task_id/output_ref`，仍要求公共写字段与实际 actor，并核验 report 授权。它针对已登记完成的准确当前轮或历史轮核对真实任务、输出及内容摘要，然后补齐缺少的回报待办。不能以 report 替代 complete，不能把新输出套到旧回报，不能重复创建已有请求。回报目标默认含所属部门和项目总控，转交任务还保留原 report_to_thread_id，重复目标去重。

有发送权限后由宿主领取、实际发送并保存观察。host_accepted 仅证明宿主已受理；接收方仍须读取完整准确成果，不能把它当已读、验收或采用。业务已处理需另有真实证据，不在消息受理时推断。

`read.topics` 增加只读派生字段，原 topic.status 保留：

| 字段 | 含义 |
| --- | --- |
| task_status / task_output_ref | 该话题当前绑定任务的实际登记状态与准确输出；没有记录保持 null |
| completion_recorded | 本话题是否已有完成登记 |
| needs_completion_record | 任务已 submitted 但尚未完成登记；它是待核验步骤提示，不会自动完成 |
| report_status | not_ready、pending_authorization 或既有 planned/in_flight/queued/unknown/failed/cancelled/host_accepted |
| report_recipients | 各准确目标的 thread_id、request_id、status、可能的 reason；business_processed=false 保留业务读取未核实的边界 |

索引脚本与 API 使用同一纯派生规则，脚本在只读事务中取得会话和其关联任务快照。项目对话索引分别显示话题登记、任务提交、完成登记和回报状态；不复制正文、私有授权原话或派发提示。看板仅增加这些进度的只读展示，不增加任务、派发或自动完成按钮。索引不是实时状态，调用时仍读当前工具结果。

## 探索阶段

当前宿主加载包内 idea-explorer 开展创意讨论。没有用户选择时持续多方向发散；回答问题、偏好、补充约束和“继续”只更新讨论材料，不自动选择或切换深入。允许必要短解释和比较，不顺势扩成未选方向的全剧制作。自然语言中的明确选择足够，无固定确认词；直接制作请求仍按实际范围接续。

不新增规划工具，使用原 `planning.record` 的 `change.exploration`，仅用于 idea 记录。`film_action_help(action="planning.record")` 提供 `exploration_help` 的严格命令 schema、准确示例和摘要规则；planning.read 返回保存状态，读取不迁移旧记录。

命令共同字段为 `action/event_id/source`，source 必须是 `{type,reference,quote}`，type 仅为 user_message 或合成测试用 synthetic_user_message；reference 与 quote 保留实际用户消息来源和原话。仅 select/preview 必须另带非空 branch_refs，其余动作禁止带它。每项引用包含 `branch_id/record_version/branch_sha256`，版本须等于本次 base_version，分支必须已保存且摘要吻合，不允许在同一写入新增/改写分支并选择它。准确摘要算法见工具帮助，不以标题或顺序猜引用。

| action | 结果 |
| --- | --- |
| open | 明确建立开放探索；已有阶段或旧 current_branch 时拒绝，防止清掉既有选择 |
| select | 保存明确选定的准确分支或组合，phase=deepening；不批准 Canon 或授权制作 |
| preview | 仅本次请求深入指定准确分支，phase 与正式选择保持不变 |
| return_open | 按用户明确要求返回多方向发散，历史选择与原话继续保留 |
| pause | 保留当前阶段与选择并暂停 |
| resume | 恢复暂停前阶段，不猜测新方向 |

服务端生成 `record.state.exploration`：`schema_version=1`、`phase=open/deepening/paused`、`selected_refs`（含准确分支快照）、`history`、`resume_phase`、`last_preview`。历史保留实际来源、前后阶段和冻结引用。last_preview 的 scope=this_request_only，**只是该次请求的历史证据，后续回合不能靠它持续深挖**。新阶段已启用后 current_branch 由阶段动作维护，不能通过普通 state/set 直接绕过阶段规则。

旧记录未带 exploration 时保持原样，缺状态表示未知；不按 current_branch、偏好或包版本自动建立新阶段。明确的旧决定与已授权任务不被重置。服务端检查结构、准确版本和摘要，不认证人类身份、授权语义或原话是否真的表示选择；宿主必须先正确理解用户意图。普通记录、阶段变化和选定方向不自动创建任务、聊天、批准、外发、付费或生成操作。

外部 `film_brainstorm interface/prepare` 仍是 interface_only/not_connected/can_generate=false，只准备输入包。不能将宿主 idea-explorer 的真实讨论称为外部接口已生成。个人表达风格继续留在用户配置中，不打包毒舌措辞、私人路径或持续授权。

## 验证边界

测试使用独立 TEST/synthetic 项目覆盖全部门绑定、跨职责转交、准确版本与锁、完成而回报权限不足、补回报去重、只读派生索引，以及探索阶段、局部试探、旧记录和无授权副作用。合成测试不证明真实宿主聊天已创建、实际消息已送达或用户采用。当前宿主轮次执行协作，持久待办可恢复，不提供后台常驻调度或离线自动唤醒保证。
