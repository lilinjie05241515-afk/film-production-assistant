> 版本专题与兼容记录。接口细节按当前工具定义核对；旧版看板按钮、当时开发目录和执行安排只用于追溯。当前操作职责见 [现行规则](current-rules.md)，兼容边界见 [兼容说明](compatibility.md)。

# 1.9.3 文本编辑、云端工作稿与讨论修改

本版补齐小说、剧本等文本从阅读到修订的入口。内容列表与准确章节的阅读工具栏提供「编辑正文」「云端工作稿」「讨论修改」，与原有审核、历史、导出入口分别呈现。使用已有登记与宿主能力，不新增独立云服务、模型 API 或后台自动同步。

后续 1.12 行为：完整初稿/明确修订的保存可带 `cloud_update`，以准确成果生成待同步记录，宿主在本轮继续建立或更新云稿；讨论、仅打开、检查点和旧稿导入仍不触发。本文保留 1.9.3 原入口说明，新的默认成稿接续、准确成果绑定和恢复流程以[1.12 契约](integration-cloud-1.12.0.md)与[按轮云稿工作方式](../skills/film-production-agent/references/cloud-round-workflow.md)为准。本地候选和正式批准仍独立。

## 编辑正文

编辑以选中成果的准确 artifact_id/version/scope 为来源；连续阅读多章不扩大保存范围。来源来自已通过总稿 segment 时仍须对应真实成果版本；无法解析的组装文本不能伪装成可保存成果。项目切换、回收站或来源失效后不沿用旧表单。

编辑器保留原始文本、依赖及适用元数据，保存调用 artifact.save，带当前基础版本生成新候选。普通编辑遇到比阅读版本更新的稿件时，提示打开最新版本编辑，不能静默以旧通过版冲掉新候选。并发更新由 base_version 拒绝，批准状态保持原样。历史版本恢复沿用 artifact.restore，云端工作稿观察继续由宿主 Pages 流程维护。

历史页保留独立的「修订为新候选」：重新读取完整历史来源和最新基础版本，在编辑表单显著显示历史底本版本与当前最新版本，用户点击「保存历史修订为新候选」明确提交。保存后新候选的 metadata.revision_source 记录历史 artifact_id/version/sha256；原有同名元数据完整保存在 previous。原历史、批准和依赖保留；打开表单后又出现新版本时由 base_version 检查拒绝并提示冲突，不改写最新稿或原通过指针。

## 云端工作稿

云稿入口交给当前宿主执行，至少携带明确 root、project_id、内容分类及准确成果引用。解析已有 Page 时区分选中工作稿的 metadata.page_id、snapshot.master_bindings 中的分类绑定及其他已观察来源；多份来源不凭标题或浏览历史猜选。

云稿表单可选择已观察 Page、指定已有 Page，或明确请求创建新的工作稿；已有来源也须明确选择目标，避免把单章当作整类总稿。创建仅以本次准确内容建立独立工作稿，不自动改绑整类总稿。仅打开「云端工作稿」不自动建 Page、替换绑定、批准正文或向云端写入。本地 master.bind_page 只保存 category/page_id/base_revision 关联，带 op_id 和 expected_project_id；它不创建页面，也不证明内容已同步。同一 Page 不得作为两个整稿分类的覆盖目标。

已明确 Page 时，宿主使用真实 Pages 工具读取正文和相关批注，再调用 open_in_codex 的 page 目标打开。queued 只代表排队。要刷新看板内工作稿，使用 film_pages_import(root,observation,op_prefix) 导入完整宿主观察：view 为 full/editing，content.page_id 与来源一致，blocks 包含准确 id/hash/kind/markdown，observed_at 带时区，category 明确；存在 selection 时必须 whole_page_complete=true。局部、截断、失败或仅打开页面的结果不能当作完整读回。

film_pages_import 只保存本地 cloud_working_draft 观察，不发起云端请求、不移动批准指针。现有工具不接收 expected_project_id 参数，宿主调用前需核对明确 root 下的项目身份。metadata 中保留 page_id、page_url、cloud_revision、observed_at 与 blocks；云端修订未知时保持未知，不凭内容长度或本机版本号捏造。

用户手动编辑 Page 后可请求刷新工作稿；要求宿主修改时，先读取准确区块和批注，再使用真实 block_id/expected_hash 和可用 sequence 保护限定范围的编辑。未知结果先读回核查。完整读回更新云稿观察；将修改接入本地小说或剧本时，核对对应成果范围和最新基础版本，另存候选。通过总稿、未批准工作稿和最后观察是三个不同状态，不用通过总稿无条件覆盖用户的云端修改。细节沿用 [Pages 宿主协作协议](integration-pages.md)。

## 讨论修改

用户填写修改要求并选择「当前对话」或「新建专属对话」。当前对话模式只发送当前宿主请求。新建模式只有在用户明确选择并提交后，才使用 list_projects/create_thread；已有客户端项目映射须核对，未映射使用 projectless 并注明作品目录，不擅自改权限。

面板请求冻结所选成果的准确 ID/version/scope、已知云稿来源和用户修改要求。宿主随后读取 snapshot/history，核对当前通过版与最新候选，再把实际读到的状态补入交接；不能声称面板已携带尚未读取的版本。新对话先读取核对来源，再讨论或按授权修改。没有具体要求时先讨论，不因打开入口就重写全文。候选保存、真实批准与全稿同步各自按现有流程进行；任务版本锁继续保留。

创建返回真实 threadId 后，thread.register 保存 thread_id/title/scope/status/purpose/artifact_refs，并通过 film_projects bind 建立关联。排队的 clientThreadId 不能当成真实 threadId；登记成功不能冒充创建成功；本入口不授权给已有其他聊天发送消息。正文列表、阅读页与聊天间的操作均保留明确来源，不把阅读会话中的所有章节合并为一个编辑范围。

## 验证范围

回归使用 test_only 合成项目，覆盖：准确选中章的入口和请求、旧通过版与新候选冲突、编辑生成候选、未批准内容的已有云稿绑定、工作稿与分类多来源选择、当前对话与新建对话的授权区别、跨项目晚到响应及既有未决写保护。

界面代码、宿主请求、真实客户端聊天创建和真实 Pages 编辑分别验证并报告。界面能发送请求不等于云稿已打开或聊天已创建；本地安装也不等于已有聊天已加载新版。本版开发不自动操作真实作品、创建创作聊天或修改云端稿件。
