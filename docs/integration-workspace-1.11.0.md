> 版本专题与兼容记录。接口细节按当前工具定义核对；旧版看板按钮、当时开发目录和执行安排只用于追溯。当前操作职责见 [现行规则](current-rules.md)，兼容边界见 [兼容说明](compatibility.md)。

# 1.11.0 对话工作区接入契约

本模块管理主要阶段对话的准备与宿主观察记录。实际创作始终发生在 Codex 对话；准备职责槽位不创建聊天、不执行创作、不创建任务、不生成媒体、不批准正文。模块不调用宿主工具、不读写全局 catalog、不移动真实聊天。所有示例均为 `test_only` 合成身份，不是生产回执。

排队恢复依赖宿主真实能力：clientThreadId 不可传给需要 threadId 的读取/等待工具，也不等于 operationId。只有实际回执包含相应 operationId 时才用其状态接口；否则从宿主聊天清单定位候选，再读原始初始化请求中的准确 project_id/role/scope/request_id 认领。初始提示应包含这些标识。无法取得证据时保持 queued/unknown 并继续其他缺项，不按标题或时间猜测成功/失败，不重建。

## 路线与稳定身份

路线必须先经现有 `project.workflow.set` 明确选择。`workspace.prepare` 不接受或猜测路线。

| 路线 | 主要职责槽位 |
| --- | --- |
| novel_only | control / planning / novel / review，共4项 |
| screenplay | control / planning / script / director / assets / review，共6项 |
| novel_to_screen | control / planning / novel / script / director / assets / review，共7项 |

职责标签依次为项目总控、灵感与需求、小说创作、剧本制作、导演与特效、资产与视频提示词、审核与交付。研究等可选工作不因初始化自行执行。

`slot_id` 由准确 `project_id + role + scope` 计算；默认 `scope=project`。`initialization_id` 标识整份工作区，`request_id` 标识槽位的原始创建请求。重复准备保留这些标识、既有真实对话、排队标识和未知结果。路线变化时无关槽位进入 `retired_slots`，原记录不删除；回到原路线会复用。已发出的旧路线请求仍可记录晚到结果，但不能新启动已退出路线的槽位。

旧登记每条只按一个归属规则匹配，优先级为：准确 `workspace_slot_id` → 明确 `workspace_role/workspace_scope` → `current_control=true` 唯一归入 `project/control` → 相同 scope 下准确 `purpose=role`。较高优先级字段存在时不再尝试较低规则；例如旧聊天同时有 `purpose=novel` 与 `current_control=true` 时，只填总控，不再同时占据小说职责。不解析标题猜归属。一个槽位只有一个匹配时标为 `registered` 并要求宿主核验；多个匹配标为 `conflict`，不创建。未领取槽位在重复 prepare 时还会检查后来新增的准确登记。没有明确标签的旧聊天由宿主读取实际上下文后提出或确认复用，不因名字相近自动认领。

scope 是当前查看或准备的分组，不是可用性的开关。`slots` 保留当前路线有效职责的全部 scope，每槽 `active=true`；`selected_scope=true` 表示当前 prepare 选择的组。`retired_slots` 只包含已退出当前路线的职责，不包含仅因切换 scope 而暂不展示的项目级或章节级工作。切换 scope 不妨碍其他有效范围槽位的核验、创建领取或接续；退出路线的职责仍禁止新领取。

## 接口与返回

`filmprod.workspace1110.action_schemas()` 返回四个动作的完整 schema，和 `ACTION_SCHEMAS` 内容一致但返回独立副本；`OBSERVATION_SCHEMAS` 列出各事件字段。MCP 应在打开项目之前执行 `validate_workspace_payload(action,payload)`。读写均要求准确 `expected_project_id`，任何未知字段、错误类型、错误事件组合和不带时区的观察时间会拒绝。

```json
{"action":"workspace.read","payload":{"expected_project_id":"TEST-WORKSPACE"}}
```

```json
{"action":"workspace.resolve","payload":{"expected_project_id":"TEST-WORKSPACE","role":"script","scope":"project"}}
```

```json
{"action":"workspace.prepare","payload":{"op_id":"synthetic-prepare-1","expected_project_id":"TEST-WORKSPACE","base_revision":0}}
```

read、prepare、record 直接返回工作区对象，没有额外 envelope。主要字段为：

- `project_id/revision/workflow_mode/prepared_workflow_mode/prepared/needs_prepare/scope/initialization_id`。
- `slots/retired_slots`：每槽含 `slot_id/role/label/scope/title/status/thread_id/client_thread_id/request_id/active/selected_scope`。
- 每槽独立保存 `registry_status/catalog_binding_status/client_project_status/client_project_id/open_status/host_observation/observations/next_action`。
- `host_execution=false`、`creation_is_execution=false`、`observations_are_live=false`。
- `evidence_level=caller_reported_observations`，即调用方报告的宿主观察。`needs_prepare` 只检查当前选组是否齐全及路线是否变化。`all_associations_observed` 要求当前选组齐全，且当前路线有效职责的全部已准备 scope 都有完整关联观察；它只汇总观察记录，绝不是实时宿主核验或已打开证明。

resolve 返回 `project_id/workspace_revision/slot/next_action/host_execution=false/execution_authorized=false`，并返回 `requested_scope/resolved_scope/resolution/role_active/registry_candidates/project_fallback_blocked`。路由检索当前路线有效职责的全部 scope：先选准确 scope；只有没有准确槽位、也没有该 scope 的明确旧登记候选时，才回退到 `scope=project` 的同职责槽位。精确槽位处于 planned、queued、unknown、conflict 等任何状态都不回退，其 next_action 要求继续核对原范围。

- 准确槽位：`resolution=exact`，`resolved_scope=requested_scope`。
- 项目级回退：`resolution=project_fallback`，`resolved_scope=project`，请求 scope 必须不是 project。
- 没有可用槽位：`resolution=missing`、`slot=null`、`resolved_scope=null`、`next_action=prepare`。若准确 scope 存在旧登记但尚未准备槽位，会返回 `registry_candidates` 和 `project_fallback_blocked=true`，供明确 prepare 后核验；此只读发现不认领、不写入，也不能逃逸到项目级聊天。
- 请求的职责已退出路线：`role_active=false`，不返回历史槽位，不启动该职责。

resolve 不导航、不发消息、不启动创作。UI 应核对 `slot.scope == resolved_scope` 及上述 resolution 规则，不自行降级查找其他对话。

所有写入沿用 Registry 的 `op_id` 幂等缓存、事务、项目身份核对和事件记录，并使用工作区全局准确 `base_revision`。冲突后读取当前状态，不能静默改底本重放。工作区保存在现有 settings 的 `workspace/v1` 键内，不迁移数据库 schema。snapshot 增加 `workspace` 和能力标记。

## 主状态与下一步

| status | 含义 | next_action |
| --- | --- | --- |
| planned | 已准备槽位，尚未领取创建请求 | create |
| registered | 只发现本地准确登记 | verify_existing |
| conflict | 同职责存在多个明确登记 | resolve_conflict |
| requesting | 宿主已领取，真实创建结果尚未记录 | check_pending |
| queued | 只有排队 clientThreadId | check_pending |
| unknown | 结果未知，禁止再次创建 | check_pending |
| failed | 宿主明确报告未创建任何聊天 | create |
| host_confirmed | 已记录真实 threadId 的宿主观察，并原子登记 threads | bind_catalog 或 observe_client_project |
| associated_observed | 真实对话、本地 catalog 绑定和客户端归属均有观察记录 | open_existing |

`registry_status=registered` 只说明作品登记存在。`catalog_binding_status=host_reported_bound` 只说明宿主报告执行或读取了 catalog 绑定；本模块不冒称已独立核验全局库。客户端归属记录为 `host_reported_project` 或 `host_reported_projectless`，与作品的本地绑定分开。打开状态为 `not_observed/host_reported_opened/host_reported_failed`；打开失败不会清除 threadId、释放创建请求或重建聊天。

## record 事件

通用写入形状：

```json
{
  "action":"workspace.record",
  "payload":{
    "op_id":"synthetic-claim-unique-1",
    "expected_project_id":"TEST-WORKSPACE",
    "base_revision":1,
    "slot_id":"从read返回的准确slot_id",
    "event":"request_started",
    "observation":{"request_id":"从read返回的准确request_id"}
  }
}
```

`request_started` 是本地领取意图，不是宿主创建回执。只允许 planned 或明确未创建的 failed，且没有真实 threadId。UI 不提前逐槽领取；真正要调用 create_thread 的宿主执行者在调用之前以新的 op_id 和准确 revision 领取。并发领取只有一个成功，失败方不得调用 create_thread。

宿主观察共有字段如下，具体工具名受 schema 枚举限制：

```json
{
  "request_id":"原槽位request_id",
  "source":"host_tool",
  "tool":"create_thread",
  "observed_at":"2026-10-25T12:00:00+08:00"
}
```

| event | 除通用字段外的字段 | 约束 |
| --- | --- | --- |
| queued | client_thread_id | 只能给尚未完成的 requesting/queued/unknown；同一请求不能换排队标识 |
| unknown | 仅 request_id、reason，不含宿主共有字段 | 本地传输未知；只允许未决创建请求 |
| host_confirmed | thread_id、title、origin(created/existing) | created 须先领取；existing 可明确复用 planned/registered/conflict；必须是真实ID与宿主实际标题 |
| catalog_bound | thread_id、project_id | tool=film_projects；必须与槽位真实ID及目标作品一致 |
| client_project_observed | thread_id、client_project_id（字符串或null） | 来自宿主读取/移动结果；null明确表示观察到projectless |
| opened | thread_id | tool=navigate_to_codex_page；不能将queued当已打开 |
| open_failed | thread_id、reason | 保留全部真实对话关联 |
| failed | reason、no_thread_created | true 必须有宿主明确“未创建”证据；超时、无权限或不完整列表不能证明未创建，须false并保持unknown |

`host_confirmed` 的示例 observation：

```json
{"request_id":"原槽位request_id","source":"host_tool","tool":"create_thread","observed_at":"2026-10-25T12:00:00+08:00","thread_id":"宿主返回的真实threadId","title":"宿主返回的实际标题","origin":"created"}
```

clientThreadId 不能填入 thread_id；同一职责已有真实 threadId 时不能静默改成另一对话；同一真实对话不能占两个职责槽位。记录真实确认时，模块在同一事务调用原 thread 登记逻辑，保存准确角色、scope 和观察。之后独立记录 catalog 和客户端归属，不以 threads 登记成功冒称全部关联完成。观察时间早于已记录宿主观察时拒绝覆盖；原 op_id 的完整幂等重试仍返回原操作结果。

## 宿主协调顺序与未知结果

1. 读取明确项目和工作区，准备当前路线所需槽位。核对已有登记与真实聊天，优先复用；不扫描导入其他作品。
2. 每槽根据最新 next_action 分流。create 时以新 op_id 执行 request_started 成功后才调用 create_thread。创建初始提示只加载身份、职责、准确上下文并等待用户，不写正文或启动专业制作。
3. 已有真实返回 threadId：记录 host_confirmed。只有 clientThreadId：记录 queued。传输中断或结果不明：记录 unknown，查询原请求或实际宿主状态。
4. 对已确认真实ID调用 film_projects bind，并读取结果后记录 catalog_bound。再读取真实 Codex 项目归属，记录 client_project_observed；绑定本地作品不会移动真实聊天。
5. 用户进入对话时调用 navigate_to_codex_page，再按真实结果记录 opened 或 open_failed。不要给已存在的其他聊天发送新消息，除非用户另外明确要求。

**幂等缓存只覆盖本地记录，不能使外部 create_thread 幂等。** 重放 request_started 的原 op_id 会按原协议返回缓存回执；缓存回执不能作为再次执行外部创建的授权。每次协调必须先读当前槽位。已 requesting/queued/unknown 的槽位必须核对；若执行者不确定自己是否已经调用过 create_thread，也必须核对，不能重放。明确未创建才能记录 failed(no_thread_created=true)，再按新的领取操作补建。

当前总控工作对话执行 prepare 后，如宿主创建结果未知或执行中断，可重新读取并继续同一 initialization_id 的协调；旧面板 ui/message 流程仅为历史背景，不再作为当前入口。还未领取的槽位可以继续领取，已经领取的按原请求恢复；整批或单槽部分成功不会重建已有真实对话。模块能保证本地状态、事务与请求记录一致，不能自行证明宿主工具实际执行、标题归属真实、目录权限足够、当前账号仍有访问权或人类批准发生。

## 隔离验证

`python -X utf8 -m unittest tests.test_workspace1110 -v` 使用独立临时 test_only 项目，覆盖三路线4/6/7槽位、重复准备、旧登记复用与歧义、准备后新增登记、领取互斥、排队/断线/重开恢复、部分关联、打开失败、真实ID冲突、路线退回、准确项目身份与修订、幂等回执、迟到观察、完整schema、只读数据库字节不变。新增边界覆盖归属优先级避免同ID双占、跨scope准确优先与项目回退、精确queued/unknown/conflict不回退、旧准确登记未准备时阻止回退、切换选组不阻止合法范围工作、退出路线职责不能启动。测试从未调用宿主聊天工具或真实作品。
