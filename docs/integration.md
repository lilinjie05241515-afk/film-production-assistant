# 1.17.0 分层会话接入

本版把单个影视项目的项目总控、部门管理入口和独立话题关联起来，完成灵感讨论到编剧剧本/小说任务的交接与回报，也接受直接编剧需求。其他部门继续原业务。本工具不连接后台模型或宿主服务，不自动创建真实聊天。执行方法见[分层会话管理](../skills/film-production-agent/references/conversation-management.md)，共同规则见[现行规则](current-rules.md)。

## 工具与数据位置

模型在工作对话调用 `film_conversations(action, root, payload)`；root 为用户授权的明确作品目录，不能省略或从无关当前目录推断。工具的短 action 对应下列 `conversation.*` 操作，调用前以实际工具定义及 `film_action_help` 为准。看板不暴露这些业务写入。

状态保存在同一作品登记库 `settings` 的 `conversation/v1`，沿用 schema 2、项目身份校验、事务、操作号和准确修订。没有第二个灵感库，也不搬移原稿、改旧任务锁或批准成果。用户原话和讨论分支仍保存为 `planning_record`；正文沿用任务、成果、检查点与云稿机制。

`read` 仅需要 `expected_project_id`，使用只读路径，不因为访问旧项目创建层级。缺少配置时返回未启用状态。新项目在实际授权覆盖按本机制搭建时直接 `configure`，不额外询问模式开关；旧项目仅查看不迁移，接续采用时核对旧入口、原任务并保存一次适用授权。

所有写入需要 `op_id`、`expected_project_id`、当前 `base_revision`；除 `claim` 和 `observe`，还需要真实报告的 `actor_thread_id`。`configure` 必须提供 `authorization`，其他业务写入可提供本次授权，未提供时沿用项目保存的适用授权。身份与观察来自调用者报告，程序检查字段和记录一致性，不认证当前发言者或宿主回执。

actor 必须报告当前实际工作聊天，不能填目标聊天 ID 来冒充它已处理：configure 属于项目总控，prepare/start/continue 属于对应部门总控或项目总控，decide 属于灵感总控、该讨论话题或项目总控，accept 只属于准确编剧接收入口，bind_task/complete 属于执行话题或所属编剧总控。其他入口需按授权真实派发并等待接收方处理，不能代写其 actor。

## 授权与管理入口

`authorization` 的结构为：

```json
{
  "quote": "实际人类授权原话",
  "reference": "可核验的对话或用户配置来源",
  "actions": ["configure", "prepare", "decide", "accept", "bind_task", "complete", "start", "continue", "create_thread", "send_message_to_thread", "archive"],
  "target": {
    "project_id": "准确项目ID",
    "scopes": ["获授权范围"],
    "thread_ids": ["获授权目标真实ID"]
  },
  "synthetic": false
}
```

示例列出支持的动作，不表示应默认全部授予。只记录实际人类授权覆盖的 actions、scopes 和 thread_ids；只有原授权确实覆盖本项目所有相应范围/对话，才在对应数组明确使用 `"*"`。未指定通配不能推定覆盖其他目标。TEST 项目必须 `synthetic=true`，真实项目拒绝模拟授权。来自其他 Agent 的请求本身不是人类授权，接收方需核验随任务提供的人类授权来源。

`configure` 另传 `enabled`，由准确项目总控报告 actor。管理入口取自已核实工作区的项目级 control、planning 及当前路线 script/novel 槽位：需要真实 thread_id、宿主观察、catalog 已绑定状态和相同客户端项目，各职责使用不同真实聊天。标题相似或目录存在不能代替准确绑定；主入口缺失时先完成已授权工作区搭建。七类主要工作入口不重新复制，本版只将控制、灵感和适用编剧入口用于该闭环，其余保持原业务。

已采纳父入口的真实关联发生变化时不能静默改绑；需先核查准确迁移范围。切换启用状态不更改任何旧任务 execution_lock、原作品路线、历史聊天标题或通过指针。

## 动作与准确输入

准确成果引用统一为 `{artifact_id, version}`，version 为正整数。新的输入必须在本项目存在并且不在回收站，不能用“最新”或标题代替版本。

| 操作 | 追加字段与行为 |
| --- | --- |
| `prepare` 灵感 | `topic_id`、`kind="idea"`、`title`、`scope`、`planning_ref`；来源必须是该 scope 的准确 idea planning_record，先保存原话再准备话题。不能同时传执行字段。 |
| `prepare` 已交接执行 | `topic_id`、`kind="execution"`、`title`、`scope`、`handoff_id`、`target_artifact_id`；交接必须 ready 且未分配执行话题。 |
| `prepare` 直接需求执行 | `topic_id`、`kind="execution"`、`title`、`scope`、`direct_brief`、`inputs`、`target_role`、`target_artifact_id`；`target_role` 为 script/novel；inputs 是准确引用数组，无现有成果时可为空，不能虚构灵感。与 handoff_id、planning_ref 互斥。 |
| `decide` | `topic_id`、`decision`、`reason`；decision 为 retain/recycle/restore/develop。可用 `planning_ref` 接续同一记录的准确当前或新版，不可换记录或倒退版本。 |
| `decide` 转作 | develop 另需 `branch_id`、`target_role=script/novel`，冻结该准确记录版本、存在的选中分支及目标形式；同话题不覆盖已冻结交接。 |
| `decide` 回收/恢复 | recycle/restore 可带 `archive_chat=true`，分别准备宿主 archived=true/false 待办；默认只改本地状态。需准确真实 ID、archive 授权，并先解决已有未决归档。 |
| `accept` | `handoff_id`、`status=received/clarifying/ready/declined`；由实际接收编剧入口报告。clarifying 必须有未决 questions；declined 用 brief 说明原因；ready 必须有 brief、非空 inputs 且无 questions，并保留冻结灵感来源。 |
| `bind_task` | `topic_id`、`task_id`；要求已取得真实执行聊天，任务的 thread_id、scope、目标成果和冻结输入吻合，保留当前执行锁。不能重绑旧任务或已完成话题。 |
| `start` | `topic_id`；由该部门总控或项目总控报告，需 start 与对准确目标的 send_message_to_thread 授权。执行话题必须已 bind_task，灵感话题没有正文任务。仅准备本轮唯一发送待办，领取后由宿主实际发送。 |
| `continue` | `topic_id`、`brief`、`inputs`，灵感另需 `planning_ref`；在同一真实聊天进入明确新轮，保留旧任务、输入和输出历史，不再创建聊天。回收态必须先明确恢复；执行需前任务真实 cancelled，或 submitted 且已 complete。 |
| `complete` | `topic_id`、`task_id`、`output_ref`、`summary`；要求绑定任务确已 submitted，output_ref 与实际输出、范围和执行锁一致。登记完成并分别向所属编剧总控、项目总控准备回报待办，需要对应实际发送授权；本身不发送消息或批准候选。 |
| `claim` | `request_id`，必要时 `retry_failed=true`；只有可执行原待办的一次有效领取可放行外部动作。明确失败重试还需准确未发生证明。 |
| `observe` | `request_id`、`status`、严格 observation；记录真实宿主观察，不能以计划、工具名或本地文件存在代替宿主结果。 |

灵感 topic_id 稳定复用，同一 planning_record 不另建第二个话题；相同活跃 scope 或目标成果不建立第二个编辑者。已有未结束任务不得用新的执行话题绕过锁。同 topic_id 参数改变会冲突；需要新范围时明确建新的工作单元，不能用新 ID 掩盖旧未决结果。

同话题的新轮调用 `continue`；灵感的 planning_ref 必须属于同一记录且不倒退，inputs 必须恰好为该引用组成的数组。执行新轮使用新的准确 inputs，不接受 planning_ref，不覆盖上轮 task_history。执行新轮仍须创建并绑定唯一新任务后再 start；旧轮只是运行中时继续其原任务和检查点，不能用 continue 提前开启新任务。原派发结果未知时先核查原请求，不能用新轮绕过；回报待办保留原轮次与 task_id，不能套用新版输出。

转作选择不自动修改项目路线。本版执行仍校验既有路线；形式不兼容时保留精确交接并由编剧澄清或拒绝，不能标记 ready、偷偷切路线或借新任务绕过。大纲与正文的选择写入准确 brief，不强制先脑暴或做大纲。

develop 冻结的是准确 planning_record 版本及 branch，而非随时替换的“最新灵感”。这个引用保留在任务 inputs 中供完整阅读，成果来源元数据保留 ref、branch 和内容摘要以便追溯。其后继续讨论出新版，不会自动使已经选定的创意来源失效或改变交接。该语义仅适用于准确登记的冻结创意来源；剧本、风格等其余业务依赖仍执行原有新鲜度与采用检查，不能用它绕过旧任务锁或任意接受过期输入。

## 读取结果与宿主待办

`read` 返回完整状态及 `revision`、`enabled`、`parents`、`topics`、`handoffs`、`outbox`、授权和历史。摘要视图不包含全文。`pending_host_actions` 汇集尚未确认宿主接受的动作，附当前状态与下一步提示；这些列表是保存的观察，不是实时宿主状态。

固定请求保存 request_id、topic_id、scope、tool、purpose、目标 thread、完整 payload、授权、attempt、round、排队引用和观察。状态为 planned、in_flight、queued、unknown、failed、host_accepted 或 cancelled；取消保留审计，不表示已发生的宿主动作被撤销。`claim` 首次有效领取才返回 `dispatch_allowed=true`；重复读取、旧领取回执、排队和未知不能再次执行。程序内部幂等重试与外部宿主重发必须区分。

实际宿主动作由当前工作轮次完成：创建用 `create_thread`，消息用 `send_message_to_thread`，归档待办中的内部 tool 为 `archive`，实际调用 `set_thread_archived`。真实 thread_id 才可用于读取、等待、绑定；clientThreadId 仅记录排队。创建成功后保存观察，并另用 `film_projects bind` 完成目录登记关联；这与侧栏归属、逻辑层级分别核验。新话题的初始提示包含项目、父节点、稳定请求、职责、精确来源及防递归规则，只要求自核就绪等待，不能立即创作。

正确启动顺序是：prepare→claim→宿主创建→observe 真实 ID→film_projects bind→执行话题的 task.create 与 bind_task→start→claim→宿主发送→observe。灵感话题省略任务创建和绑定。`observe` 和 `bind_task` 不自动发送；`start` 只排待办，不能当作实际发送成功。任务 thread_id 必须是已登记的执行话题，精确 inputs 与该话题冻结输入一致，不能让管理入口冒充执行者。

收到 accepted 的发送回执只证明宿主接受，不能证明接收方业务已处理。用 `wait_threads` 进行有限等待并保存实际观察；必要时 `read_thread` 核对内容。完成后依据真实任务及成果引用处理回报；`complete` 的 `notification_sent=false` 表示宿主消息仍待执行。未决状态持久保存后可在后续授权轮次恢复，但没有常驻后台调度器和离线唤醒保证。

## 宿主观察

`observation` 的共同必需字段为：`source="host_tool"`、`tool`、带时区 ISO 8601 的 `observed_at`、可追溯 `reference`、准确 `project_id`、`topic_id`、`scope`、`request_id` 及正整数 `attempt`。必须与原领取请求吻合。允许的工具按实际动作限制，不能用不相干结果作证。

| status | 共同字段以外的必需字段 | 含义 |
| --- | --- | --- |
| `queued` | `client_thread_id` | 只适用于创建排队；不是实际 thread_id。 |
| `unknown` | `reason` | 结果不明，先查原请求，不重发。 |
| `host_accepted` | `thread_id`、真实 `title`、`client_project_id`、`project_root` | 准确宿主目标及其项目身份已被观察；不是业务完成或用户采用。 |
| `failed` | `reason`、`no_effect`、`proof` | 只有已证明确未发生才成为可显式重试的失败；否则保持 unknown。 |

观察中的标题、项目与目录来自已核验真实目标；缺失时继续核对，不能为了满足 schema 填入推测值。工具保存 `evidence_level="caller_reported"`、`observations_are_live=false`、`host_execution=false` 等边界；它不直接认证宿主或提供实时健康证明。

未知创建只核查原请求；只有宿主确实返回对应 operationId 才调用相应状态工具。没有专用查询接口时，按项目、父节点、范围和原请求标识读取候选聊天，不凭标题认领。原发送未知时查准确目标消息，原归档未知时查原真实聊天；时间经过不能证明失败。相反归档/恢复请求也不得覆盖原未决操作。仅 planned 尚未派发的归档可在恢复时被取消并保留审计；已经 in_flight、queued 或 unknown 的归档仍须先核查。

## 验收边界

独立合成项目验证模式、真实观察结构、精确版本、同范围复用、路由冲突、任务绑定与输出、授权范围、未知恢复和回报待办。合成宿主回执不等于真实客户端运行；程序测试、插件安装、当前宿主加载、真实创建/派发/归档与用户采用分别报告。本版开发与安装不迁移真实作品，也不更改个人默认文件。
