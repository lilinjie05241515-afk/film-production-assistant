> 版本专题与兼容记录。接口细节按当前工具定义核对；旧版看板按钮、当时开发目录和执行安排只用于追溯。当前操作职责见 [现行规则](current-rules.md)，兼容边界见 [兼容说明](compatibility.md)。

# 1.11.0 完整成稿交付证据

保存正文与完成交付分开。现有草稿、检查点及候选保存仍可保留未完成内容；本模块仅登记本次要求、准确成稿的覆盖审查和完成记录，绝不调用审批、替用户采用、发布或修改正文。`ready_for_delivery` 表示当前记录的完整交付证据已闭合且未过期，不保证审美、创意、读感或真实制作效果。

完整指**完整完成本次授权范围和粒度**。用户只改一句时，可以只定义这一句及受影响承接；不强制重审无关全稿。全文任务不得自行缩成概要。默认 `mode=full`；摘要须由宿主提供真实用户摘要请求，`summary_request.actor=user`、reference 与冻结 user_request 相同，quote 必须是其原文子串。程序核对文字关系，不具备认证真实用户身份或理解这句话是否确实授权摘要的能力；来源真实性及授权解释由宿主负责，返回 `host_reported_unverified`。

## 接口与接入

`filmprod.delivery1110.action_schemas()` 是四个动作的唯一参数 schema 来源，均包含 expected_project_id；工具 root 位于外层。写操作另需 op_id。不要在接入层复制另一份字段定义。

- `delivery.read`：可选 delivery_id。省略时返回 `{schema_version:1,items:[...]}` 的全项目精简摘要，不带原话、源文或正文。指定时返回当前契约、最新审查、最近完成记录及历史编号。
- `delivery.define`：delivery_id、base_revision、target_artifact_id、scope、granularity、user_request `{reference,quote}`、inputs、units；mode 可省，summary_request 仅用于 summary。inputs 为 `{artifact_id,version,sha256}`；每个 unit 包含 unit_id、description 和 source。artifact 来源另有准确引用、location、quote；user_request 来源有同 reference 和原话子串。所有单元均为本次必需单元，删减或改变范围须创建新契约版本并保留用户来源。
- `delivery.review`：delivery_id、revision、base_review_revision、artifact 准确引用、author `{type,id}`、reviewer `{type,id,source_reference}`、coverage、findings。每行 coverage 有 unit_id、status、note；covered/needs_revision 还必须有 output `{location,quote}`。missing 可以省 output。每条 finding 有 finding_id、severity、status、location、quote、detail；resolved 另需 resolution `{location,quote,explanation}`。
- `delivery.complete`：delivery_id、revision、review_id、artifact 准确引用、base_completion_revision。只能引用当前契约和最新审查；缺单元、待返修单元、未闭合 blocking/major、来源更新、正文更新或契约更新均拒绝完成。

definition、review、completion 的 revision 分别从 1 递增，相应 base 字段从 0 起做并发比较。review_id、definition_id 和 completion_id 取本操作 op_id。契约存为 `definition_revisions`，审查和完成记录分别追加；旧版本不覆盖。未闭合 blocking/major 在新审查中没有明确处理时自动保留，不能通过不再列出或降低严重度清空。

core 接入只需要：只读分支 `return read_delivery(self,p)`（函数自身管理锁和只读事务）；三个写动作进入既有 handlers，调用 define_delivery/review_delivery/complete_delivery；在幂等缓存查找**之前**要求这些动作带 expected_project_id。沿用现有写事务、项目身份复核、op_id 缓存和事件机制。`snapshot` 在已有读锁内调用 `delivery_summary(self)` 加到 `snapshot.delivery`，该函数不调用 snapshot。没有新数据库表、迁移或独立服务。

## 完整性证据与边界

源文 quote 必须在准确输入版本中，正文 quote 必须在准确输出版本中。登记器保存第一个匹配位置的 Unicode 字符起止偏移及出现次数；location 是宿主提供的可读位置说明，不冒充程序已认证的行号。coverage 保存原来源到输出位置的对应。重复引文、同一句被多个单元引用、对应关系是否真正承接了情节或功能，仍须专业阅读判断。

author 与 reviewer 必须保留实际宿主来源；reviewer 类型允许 host_subagent 或 human，id 必须不同于作者，source_reference 应指向真实子代理/人工审查记录。接口不接受 independent=true 等自证字段，但程序也不能通过一个字符串认证子代理是否存在、上下文是否隔离或其报告是否诚实，因此返回 `independence_evidence=host_reported_unverified`。宿主须在实际独立上下文中提供准确源文与完整稿，保存报告，再登记有证据的发现。缺少这种实际来源不能伪填标识以完成交付。

未提供覆盖、missing 单元或过期审查时 status=incomplete；有需要返修的覆盖单元或 open blocking/major 时 status=needs_revision；当前覆盖闭合时 status=reviewed。reviewed 尚未执行完成动作，ready_for_delivery 仍为 false；成功 complete 后 completion_state=ready。出现新稿、新契约、新来源版本或新的未完成审查后，旧完成记录保留但 completion_state=stale，ready_for_delivery=false。审查记录不能自动变成用户批准。

外部输入新增版本即使仍是候选，也会使此份**交付审查证据**需要重新核对；不会因此修改已通过总稿或已通过下游状态。本成果自己的旧版本可以作为局部修订底本输入，冻结后新的输出不会让该底本失效；评审之后的输出变更仍照常使评审过期。明确需要沿用旧底本的场景须在宿主层解决真实输入选择，不绕过过期状态。

幂等重试返回原操作时点回执，不把其历史 ready 状态当作当前状态；需通过 delivery.read 或实时 snapshot.delivery 核对新鲜度。哈希证明准确字节、版本和传输完整，不能证明语义完整；字数、覆盖表行数或 quote 出现次数不构成创作质量分数。

## 合成验证范围

`tests/test_delivery1110.py` 仅创建 test_only 的 TEST 临时项目。验证准确证据完成、被审稿者指出缺动作/反应单元的概括稿无法完成、真实正文引文匹配、请求原话关系、自审/自证拒绝、未闭合阻断继承、版本过期、局部修订底本、CAS、项目身份、哈希、幂等与只读读取。它不声称程序可以独立识别所有语义压缩或保证真实作品好看；实际完整性仍需源文与成稿的专业独立阅读。
