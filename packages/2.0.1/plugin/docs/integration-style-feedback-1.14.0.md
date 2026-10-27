> 版本专题与兼容记录。接口细节按当前工具定义核对；旧版看板按钮、当时开发目录和执行安排只用于追溯。当前操作职责见 [现行规则](current-rules.md)，兼容边界见 [兼容说明](compatibility.md)。

# 剧本与美术基准的联合接续 1.14.0

本说明补充1.13美术五动作，不增加新的批准入口或工具。完整版本依赖不等于创作参考：当既有风格是根据该剧本形成的，再把风格自动列为同一剧本新版的硬依赖会产生历史版本闭环。程序只对新自动加入的这条边采用下述冻结参考协议；真实显式依赖不删除、不改绑，旧数据不迁移。

## 自动风格参考与任务

`task.create`在自动追加已采用全剧风格前，沿准确版本的deps查找是否回到目标artifact_id。没有反向路径时保留原硬依赖。有路径时不新增该自动硬依赖，改为冻结完整创作参考，记录proof path与原因。显式inputs包含回环路径时拒绝，不把用户显式输入猜作可删除的自动边。

任务尚无artifact_id时，暂保留自动追加的输入，冻结策略为target_pending。task.submit／task.submit_checkpoint取得真实目标后再次检查：只有原已记录的自动style边可以在该输出的实际deps中改为冻结参考；原任务inputs、bound_versions、检查点和锁保持原文，提交记录另外给出submitted_inputs与submitted_style_reference。显式输入仍拒绝回环。

完整任务中的 `style_binding` 包含：

- `artifact:{artifact_id,version,sha256}`、`scope`、`content`、`deps`：原风格的准确引用、全文与原始依赖。
- `mode`：hard_dependency、target_pending或frozen_reference。
- `reason`：automatic_style_without_return_path或automatic_style_would_return_to_output。
- `dependency_path`：从风格到目标历史版本的准确ref数组；没有路径则为空。
- `target_artifact_id`、`automatic:true`：创建时已知目标及自动策略来源。

`style_execution_lock`是辅助执行锁，包含schema_version、method_lock_sha256、binding_sha256，冻结完整参考、原任务inputs、module/scope/目标身份。原execution_lock仍独立检查系统与专业模块版本。检查点和提交都会核对辅助锁、原风格全文与摘要、当前采用指针及其完整来源的新鲜度；整体风格换版、待复核或其他来源过时都会阻断。它不是跳过其他依赖检查的豁免。

task.style_context在冻结参考模式下明确status/reference_mode=frozen_reference，并给出frozen_reference准确ref、reference_reason、missing_context=[]。紧凑任务、检查点与成果回执只给参考概要和锁，不重复风格全文。需要正文时使用完整task.resume，或film_context(mode=resume)中的frozen_style_reference。

成果metadata使用 `style_reference` 保存提交时确定的完整参考；与task.style_binding名称区分。`submitted_style_reference`和`submitted_inputs`保留在任务提交结果。已有参考在后续保存、任务提交和历史恢复中不可无依据丢弃或篡改。

## 普通页面编辑和文件保存

`artifact.save`、`artifact.save_file`以及film_artifact_save_file可传可选布尔字段 `use_current_style:true`。这是请求后端应用自动风格策略，不表示用户显式选择了一条硬依赖。适用创作类别的新增自动style边与任务使用相同规则：无反向路径时加入准确deps；有路径时冻结完整参考。页面不得预先把自动style混入显式deps，之后又期待后端静默删除。

不传此字段的旧API保留其原输入行为。原deps仍逐条保留，显式回环拒绝。已存在style_reference默认继承并核对其当前有效性；普通metadata不能伪造或修改该参考。有新的自动参考时保留有界的previous_reference摘要，其中包含原风格artifact、mode、reason及prior_output_ref（上一成果准确ID/version/hash）。旧完整参考保留在不可变的上一成果元数据中，不把每轮全文和历史递归嵌入新稿。

冻结参考是准确创作依据，不能用它声称正文已符合风格。候选采用前仍会核对冻结参考未变；采用和云同步继续原独立流程。

明确`artifact.restore`会从指定不可变版本读取真实旧正文和原deps，保留restored_from_version／restored_from_sha256；该版本原风格来源另记为有界`restored_style_reference`（原artifact/mode/reason及prior_output_ref）。新候选的style_reference继续使用当前最新稿的准确参考并核对新鲜度，避免把历史来源冒充当前风格。旧版本不改，恢复仍是候选；普通metadata不能利用这个恢复入口的内部处理伪造或替换参考。

## 美术完整候选的受控rebase

`art.revise`保持原必需字段，并新增可选字段：

```json
{
  "rebase": {
    "previous_inputs": [{"artifact_id":"SCRIPT","version":1,"sha256":"准确旧摘要"}],
    "inputs": [{"artifact_id":"SCRIPT","version":2,"sha256":"准确新摘要"}]
  }
}
```

示例中的摘要为说明占位，实际字段必须是已核对的64位SHA-256。

previous_inputs必须完整精确匹配source_ref的全部原deps，不能漏项、重复、增删来源。inputs的ID集合必须完全相同，只允许把原script/screenplay/source_script来源更新到更高、当前已采用且无需复核的准确版本；其他专业输入保持准确原版本，并仍须新鲜。至少明确更新一份剧本。不允许通过这个入口换掉无关过时来源。

只有本次推进的新剧本要求当前已采用。未变化的原研究等来源沿用既有freshness规则：原本合法的准确当前候选可以继续作为原依赖，不要求补批准，也不会自动变成已采用；其版本变化或依赖过时仍阻断。重核不增删研究、不换掉研究版本以绕过待复核。

baseline仍单独冻结当前采用指针。只有附带合法rebase时，才允许针对needs_review的采用基准保存新完整候选；该待复核原因必须对应本次列明的准确剧本更新。新输入全部重新执行原freshness与回环检查。旧基准继续needs_review，程序不clear状态、不自动批准，也不解除旧任务锁。

source_ref仍必须来自当前选择最近一次integrate/revise完整链；从未有美术选择的旧项目可继承当前准确已采用基准，包含本次因剧本更新而待复核的该版本。working_ref仍必须是同一稳定ID的最新完整稿。edits沿用准确Unicode码点、切片及非重叠规则，保护全部未编辑正文；edits=[]允许保留完整正文仅核对新依赖。

云端手改先按原deps完整保存为本地working。source_ref与working_ref不同的情况下，source+edits全文必须恰好等于已回灌working，且原deps相同，之后可以在同一次合法rebase中把新候选的实际deps更新至inputs。未解释手改、未知云请求、Page身份和旧版本均保持，不能为消除冲突删除来源。

使用task_id时，美术任务inputs必须恰等rebase.inputs的ID/version集合；不带rebase时仍须等source_ref.deps。原任务范围、execution_lock和提交机制全部执行。

新候选metadata.art1130.rebase及art_integration.rebase保存准确previous_inputs/inputs。独立content.approve再次核对当前最新完整候选、当前选择、原baseline未被替换、新剧本仍为当前准确采用版本、其他来源仍新鲜及程序重建的完整正文。语义范围仍为宿主判断，不是程序证明。

## 完整接续与旧回环限制

正常链路为：准确旧剧本和风格→新协议编剧任务/普通编辑→新剧本候选→独立采用→旧风格待复核→完整art.revise rebase候选（可实际修改视觉）→独立采用→导演读取新剧本与新风格。无需删除真实deps或先谎称旧风格无需修改。

已有历史显式硬依赖回环不会被自动迁移，也不能伪造成新自动边。应保留原请求、版本、deps和检查点，明确列出回环路径，使用匹配旧运行包只读恢复旧任务，必要时明确结束旧任务后建立使用本协议的新任务。若历史已采用数据自身已形成互相过期闭环，则需要专门审定的迁移/联合采用方案；本入口不自动修补或豁免这些历史依赖。新协议的回归和恢复证明只适用于其实际记录的自动来源与精确完整候选。
