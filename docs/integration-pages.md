> 版本专题与兼容记录。接口细节按当前工具定义核对；旧版看板按钮、当时开发目录和执行安排只用于追溯。当前操作职责见 [现行规则](current-rules.md)，兼容边界见 [兼容说明](compatibility.md)。

# Pages 宿主协作协议 1.5.0

云稿和原始批注以 Pages 为权威；MCP stdio 本身没有 Pages 凭据或私有 API。由当前宿主可用 Pages connector 操作，先读实际工具 schema；原生 Doc/Canvas 与普通 Page 的正文、区块和编辑工具不能混用。

1.12 补充：完整初稿及每轮明确修订使用 `film_cloud` 的准确成果关联和持久待同步记录，见[按轮云稿工作方式](../skills/film-production-agent/references/cloud-round-workflow.md)及[1.12 接入契约](integration-cloud-1.12.0.md)。该路径不要求先批准，也不使用分类 `master.bind_page` 代替单篇关联。以下 `sync.intent` / `sync.observe` 保留既有显式同步和通过总稿协议；不要为同一次新流程操作重复建立另一套写入请求。Pages 的实际读取、编辑、部分应用恢复与完整读回要求对两条路径都适用。

1. 通过宿主当前工具读取 Page 身份、完整正文/区块、批注、可获得的 revision。保留实际请求 `view=full` 或 `view=editing`、完整 selection、truncated 状态；若返回 structuredContent 没有 view 字段，由宿主按实际请求补录，不能根据正文长度猜测完整性。封装实际 `observed_at`（含时区）、page_id、来源和精确内容 SHA-256；无 revision 保持未知，以内容哈希作观察标识而非假称服务端 revision。excerpts、正文截断、局部选择与完整性未知均不能导入成完整云稿。
2. 建立本地 `sync.intent`：唯一 sync_id/op_id、page_id、基础 revision/内容标识、拟发送内容。保存具体目标段和修改范围。提交前再次读取受影响段，差异则保留本地候选并请求处理冲突，不自动覆盖。
3. 使用当前宿主工具执行准确区块/段落编辑一次。记录请求和回执。超时、断线、未知结果写 unknown；下一次先读取云稿比较原稿与意图，明确已生效或冲突后才推进。不能凭未收到成功回执再发相同修改。
4. 成功后读回正文与批注，`sync.observe` 保存实际 observed_content、receipt、revision、comments 和观察时间。匹配只证明该次观察时一致；宿主不提供条件写/事务时不能宣称跨系统原子事务或完全消除读写竞态。
5. 将既有完整宿主读回交给 `film_pages_import(root,observation,op_prefix)` 或 CLI 的 pages-import；适配器原样转交完整 observation（包括 category/artifact 映射、selection、through_sequence）到 `filmprod.pages_bridge.import_observation`，保存工作稿正文及 Page 来源快照，不自行联网，不读取未授权内容。重复导入相同正文不会制造新版，旧观察不能覆盖较新观察；完整读回里已删除场次使用显式 tombstone。导入只生成候选，不直接改通过版。用户批准使用精确 `content.approve`；开发测试只能 synthetic。页面继续编辑不改变已封存通过内容。

## 通过总稿同步

`master.bind_page` 建立 category/page_id 关联。`content.approve` 在本地事务中更新对应通过段、总稿版本与下游影响，保存真实批准证据。宿主随后用相同分类和总稿版本执行云同步，不能把“云端失败”当成本地审批失败或要求用户重批。

`sync.intent` 必须同时传 master_category 与 master_version，intended_content 必须为该精确总稿正文，page_id 必须符合当前绑定；提交前读实时云稿和当前revision，保留工作稿差异。云端已有未通过修改时不能用本地总稿盲目覆盖：先保留完整工作稿快照/候选；冲突则标为审核已通过、云端待同步。当前在工作对话依据真实用户指令批准并走这一流程；历史面板批准记录仍保留原证据，当前看板不提供批准入口。

宿主执行实际 Page 区块编辑一次，读回后 `sync.observe` 更新该总稿同步状态。failed/unknown/conflict 均保留已通过状态；unknown 先读回核查，不直接重发。恢复操作复用原请求/操作号，新的同步意图用新号，不能重新审批来“修复”同步。插件本身不具备 Pages 凭据，也不伪造宿主回执。

系统没有云端实时事件订阅、后台自动双向合并或跨系统原子事务。1.12 的“按轮同步”由宿主在已授权完整初稿/明确修订完成后继续执行，不能解释为后台上传任意本地文件或每个键盘输入。看板展示最后实际观察与未决状态。真实云端验收记录由总控保存在 `reports/cloud/`，其证据等级与本地模拟测试分开。

## 长篇稿件、人物小传与全剧风格

完整工作稿分类支持 outline、novel、character_bio、style、source_script、script、director、vfx、asset、video_prompt、research。剧本底稿 source_script 与动态剧本 script 使用不同总稿及 Page 绑定，避免将同场次的两种阶段稿件混进一个总稿；旧无阶段信息的剧本保留原分类。人物小传与全剧风格各自保存正文及云源身份。Pages 导入始终是 cloud_working_draft 观察，不会因 category=style 就成为已通过的全剧风格，也不会因研究报告已存在而自动采用其中观点。

章节、分集与场次的阅读目录是显示组织。已有整篇稿件可按明确 Markdown 标题定位，但不得由阅读器自动拆分数据库中的批准范围。需要独立批准章节时，创作任务应明确保存稳定分段 ID、scope、metadata.chapter/episode/scene 和排序信息；不可只凭标题推定既有批准已经覆盖新分段。

研究定调应先形成独立 style_bible 候选，声明研究来源、适用范围与尚未确定项。用户确认后，全剧风格的精确版本作为动态剧本、导演拍摄建议、特效、资产及 AI 视频提示词的任务输入。风格 Page 的编辑或读回本身不改变该批准指针；批准新风格后再对声明依赖的下游标记需复核。绑定了风格版本只说明来源明确，不证明正文已做过语义一致性审查。
