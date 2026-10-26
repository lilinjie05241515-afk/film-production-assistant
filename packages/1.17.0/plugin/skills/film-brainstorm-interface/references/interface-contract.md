# 输入交接与未来提供方契约

当前系统版本 1.4.0，接口版本 `1.0`。以 `film_brainstorm(action="interface")` 返回的 `input_schema`、`output_schema` 和 `candidate_output_schema` 为字段权威；不要根据技能版本推断运行中插件版本。工具未加载时如实说明，不把文本整理冒称为工具调用成功。

## 调用边界

`interface` 无需项目，只返回静态能力。`prepare` 要求明确的绝对 `root` 和以下 `payload`，没有 `op_id`，不进入写入恢复队列：

| 字段 | 来源与含义 |
| --- | --- |
| expected_project_id | 已核验项目身份，必填；路径相同不等于项目相同 |
| topic | 用户本轮希望讨论的明确问题，非空字符串 |
| scope | 明确章节、场次或角色范围；未知为 null，不推定整部作品 |
| context_refs | 用户选定的精确 `{artifact_id,version}` 数组；未选为 []，不自动收集全部内容 |
| base_ref | 用户指定的主底本精确引用，须属于 context_refs；未指定为 null，不以第一项猜选 |
| must_keep / constraints | 用户明确的数组；没有信息为 null，明确没有限制才可为 [] |
| allow_candidate_context | 默认 false；只有明确选择候选作为参考时才为 true，不能表示批准 |

登记路径、实际 project_id 与预期身份不符即拒绝。准备仅使用只读连接，不初始化项目、不迁移旧数据库、不创建目录、不写事件。旧 schema 1 需要另行明确的正常项目迁移流程；不能为脑暴准备偷偷迁移。`film_dispatch` 的 `brainstorm.interface/prepare` 是同一只读路径，建议调用专用工具。

## 返回内容如何解释

`status=interface_only`、`provider_status=not_connected`、`can_generate=false`、`read_only=true`、`generation_performed=false`、`candidate_output=null` 是本版真实能力边界。

`contexts` 包含选择版本的完整正文、SHA-256、类别、范围、metadata、deps，以及 `context_status=approved/candidate/historical_approved/needs_review`、`is_candidate`、`current_approved_ref` 和 `input_status=current/stale`。保留历史通过与当前通过的区别，不能默默替换成最新版。需要候选许可的错误只应由真实选择解决，不能自动重试并打开许可。

`global_style` 是当前全剧风格状态。只有仍有效的通过风格，才作为完整精确 `approved_style` 返回；缺失、候选或需复核时为 null 并列入 `unknown_inputs`。自动附带全剧风格不会改写用户选定的 `context_refs` 或推定 `base_ref`。语义合规仍为 `not_assessed`，宿主需另外审查。

`unknown_inputs` 保留尚未提供的范围、底本、约束、上下文和风格。准备成功不消除这些缺口，也不证明可以正式制作。

## 后续提供方接入

真实提供方尚未实现。未来接入应消费上述精确输入与状态，新增独立的生成调用、错误与成本边界测试，并明确变更能力声明。当前工具不接受 generate、provider 或其他未声明参数；不调用外部网络或模型。

未来候选输出契约要求 `status=candidate`，一个或多个 `directions`，每项含 direction_id/title/proposal/source_refs/benefits/risks/assumptions/unknowns；还包含 `tradeoffs`、`open_questions`、`selection_status=awaiting_user_choice`、`automatically_adopted=false`。需要比较时 tradeoffs 绑定至少两个实际方向。该 schema 仅描述未来结果，不是本轮结果；不能用示例补齐假方向。

即使未来生成成功，保存候选、正式批准、更新总稿和 Pages 同步仍使用各自既有流程。准备接口不能替用户挑选、批准、创建聊天、发送消息或触发任何生成。
