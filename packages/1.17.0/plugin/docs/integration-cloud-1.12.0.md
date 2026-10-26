# 1.12.0 按轮同步云端工作稿

云稿是可编辑候选，正式采用仍使用原批准机制。初版完整正文形成或一轮明确修订完成后，本地保存与同步待办在同一事务中登记；对话探索、任务检查点、旧版不带新字段的保存与普通导入不触发云端写入。真正的 Pages 调用仍由宿主执行，不由 Python 联网，不启动后台监听，也不改变真人采用状态。

## 保存与默认策略

完整正文保存/提交增加可选 `cloud_update`：

```json
{"trigger":"full_draft","user_request":{"source":"conversation","reference":"实际任务或消息标识","quote":"用户的真实要求"}}
```

trigger 为 `full_draft / confirmed_revision / local_only`；人工编辑用 `confirmed_revision`，source 为 `panel`，保留实际点击/范围证据。云稿含用户手动编辑、并作为本轮修订底本时，另传准确 `base_observation_id`。默认 policy.mode 为 `round_end`、destination 为 `{kind:"private"}`；可配置 `local_only` 或明确 `{kind:"space"|"page",id:实际ID}`。首次准备只生成本地待办，不证明 Page 已创建。设置为 local_only 或单次 trigger=local_only 不排队。

适用分类：outline、novel、character_bio、style、source_script、script、director、vfx、asset、video_prompt、research。idea、requirements、planning_record、cloud_working_draft、媒体与技术记录不作为本流程的完整成稿。

## 公开动作

`film_cloud` 的动作来自 cloud1120.action_schemas；所有写入仍需要 `op_id / expected_project_id / base_revision`，保存附带的 cloud_update 在原保存事务中处理，不另要求 cloud revision。

| action | 附加参数 | 含义 |
| --- | --- | --- |
| read | expected_project_id；可选 artifact_id、observation_id | 默认返回紧凑状态，显式 observation_id 才返回该完整观察正文 |
| configure | mode、user_request；可选 destination | 设置按轮或仅本地及新建目的地；不改变已冻结请求 |
| bind | artifact、user_request、observation | 依据完整实际云稿观察建立准确成果关联，或刷新同一 Page 的来源观察；不同 Page 不能替换已有绑定 |
| prepare | artifact、trigger、user_request；可选 base_observation_id | 为准确最新保存成果准备一轮请求；相同版本重复准备复用原请求 |
| record | job_id、event、observation | 记录领取、真实创建回执、完整读回、未知或失败等 |

artifact 为 `{artifact_id,version,sha256}`。文档身份固定 project_id/artifact_id/scope，分类只用于展示；不能把分类总稿 Page 或另一成果 Page 当单章覆盖目标。确需重整旧分类绑定时走明确迁移方案，不由此流程猜测。

## 返回值

cloud.read / snapshot.cloud 返回 `{project_id,revision,policy,documents,jobs,host_execution:false,background_sync:false,evidence_level:"host_reported_observations",observations_are_live:false}`。

document 包含 document_id、artifact_id、scope、category、page_id/page_url、last_synced_ref、last_synced_sha256、last_observation_id、last_observed_at、known_revision/known_revision_sha256（已知整数修订水位）。job 包含 job_id、document_id、artifact（准确引用）、scope、category、trigger、user_request、request_id、creation_key（稳定UUID）、title、destination、page_id/page_url、base_sha256、base_observation_id、status、next_action、created_at。普通读回不含历史正文；正文按准确artifact引用取一次。

prepare / 保存回执 cloud_update 直接返回紧凑 job 字段及 project_id/revision/host_execution；仅本地返回 status/skip_reason=local_only 和准确 artifact。record 返回 `{project_id,revision,document,job,host_execution:false}`。bind 返回 document、observation_id 和程序计算的 sha256；这不是同步成功。

## 宿主执行与完整观察

1. 读状态；next_action=claim 的准确最新请求可尝试 record(request_started)，只在本次新领取成功后调用宿主一次。读取 operation 缓存或重复领取不授权重新外部执行。
2. 没有 page_id 时使用冻结 title/destination、准确完整正文及稳定 creation_key 创建工作稿，initial_blocks 从该准确正文确定性构造（例如 `[exact_content]`），不重新生成一份文案。调用 create_page 时保留同一 idempotency_key 和参数；结果未知先核查原请求，只有当前工具明确支持原参数、原key的幂等恢复时才使用该恢复方式，否则保留待核对，不能新建替代Page。record(page_created) 只确认真实 page_id/page_url，状态为 awaiting_readback；此时不能报告已同步。
3. 已有 Page 时先完整读取真实当前云稿，record(preflight)。与已确认基线不同则保留完整观察、标为 conflict；不能拿旧本地稿覆盖。当前内容已经等于准确待同步稿时，该次完整观察足以标为 synced，不需要再写一次。其余匹配基线的情况才领取并编辑；真实 block_id/hash 和可用 sequence 仍从此次实际 Page 读取取得。
4. 每次外部写入后完整读取，再 record(verified)。只有程序计算的正文 SHA-256 与冻结成果完全一致才 synced；否则 conflict。后续看板观察可复用这次读回交给 film_pages_import，不称后台实时镜像。

preflight / verified 的 observation 为：

```json
{"request_id":"原请求ID","source":"host_tool","tool":"read_page","observed_at":"带时区实际观察时间","page_id":"真实PageID","page_url":"实际HTTPS链接","content":"完整云稿Markdown正文","whole_page_complete":true,"revision":null}
```

只接受完整读取；不能把 excerpts、部分选择、截断内容或不知道是否完整的内容标 true。revision 未返回则 null，不用本地版本、内容hash或时间冒充服务端revision。本协议不做去空白、换行归一化或摘要相似判定；若 Pages 对 Markdown 的规范化导致差异，保留 conflict 并核对实际完整内容，不能用宽松比较伪造同步成功。记录的 source/tool/完整性是宿主声明，程序不认证远端身份。

record 其他事件：

- request_started：`{request_id}`。
- page_created：`{request_id,source:"host_tool",tool:"create_page"|"read_page",observed_at,page_id,page_url}`。
- unknown：`{request_id,reason}`；请求已经发送且结果未知，下一步恢复原创建或读回，不重发。
- failed：`{request_id,reason,no_write_performed:true}`；仅确定未写入的失败可结束后重新准备，unknown/awaiting_readback 不能凭此清除。
- conflict：`{request_id,reason}`；发送前的明确冲突可记录，已发送/未知请求必须完整读回。

status 为 prepared、awaiting_read、requesting、awaiting_readback、unknown、conflict、failed、synced、superseded。next_action 为 claim、preflight、readback_existing、recover_creation、resolve_previous、reconcile_cloud_changes、prepare_retry、local_only、done。

## 云端手动改动与并发恢复

接续已绑定工作稿先读取最新实际云稿。明确把该版本作为修订来源时，用 bind 对同一Page保存完整来源观察，得到 observation_id；保存本轮完整修订时传 base_observation_id。发送前仍需实际重新读取并 preflight；云稿又改变则冲突，不能用旧观察覆盖更新。

初稿已自动排队后再绑定已有Page，bind会把同一文档尚未发送的待办指向该Page、设为awaiting_read并清除旧preflight；不会替换未决发送，也不会把绑定正文偷当写入基线。正文相同可经完整preflight直接确认；确需依据绑定正文继续修改时，以返回的base_observation_id明确准备新请求。未发送旧请求保留superseded历史。

每个Page保留真实整数revision水位。较新的observed_at不能让较低整数revision的旧正文被接受；同一非空revision对应不同完整正文也拒绝。null和不透明字符串不推定先后顺序，且不会清除已知整数水位。未知修订保持未知，严格正文摘要比较不变。

新的完整本地版本可以保存并排队。尚未发送的旧待办保留为 superseded；已经发送、未知或等待读回的旧请求保留，并阻止另一请求领取。旧请求恢复后，新版本使用同一个 Page；旧版本已落后时不能再次领取。未知创建取得真实ID后先读回，不能新建替代Page。

旧 sync.intent 与新工作稿请求共用 Page 排他检查：一方已发送/未决时，另一方不能启动。同一 Page 不同时成为分类总稿覆盖目标和准确成果工作稿；普通批准仍可保存本地正式版本，不要求把单章云稿改绑成整类总稿。

真实批准、云稿同步、专业语义质量与远端访问是不同证据层。本轮程序测试只证明登记与状态转换；只有真正宿主创建、编辑、读回的证据才证明一次真实云端流程。
