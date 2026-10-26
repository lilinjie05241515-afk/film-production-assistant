# 美术方案与完整全剧基准 1.13.0

1.14补充：`art.revise`现有五动作不变，新增受控`rebase`字段，允许准确剧本更新引起的待复核基准保存完整修订候选。下文“原deps不变／needs_review先核对”的旧规则适用于未附合法rebase的调用；新增字段、任务inputs、云手改保留及独立采用要求以[剧本与美术联合接续1.14规范](integration-style-feedback-1.14.0.md)为准，不是通用清除需复核状态的入口。

美术总监的两套候选先作为独立 research 文本保存，不占用 style_bible 的稳定正式身份。主选仅表示推荐；用户选择与完整基准采用分开。程序能核对身份、版本、原文保留和选择记录，不能判断视觉区域分类是否正确、是否真的具有审美价值。

## 五个动作

使用 `film_art`，参数格式为 `{root,action,payload}`。所有写入 payload 均有 `op_id / expected_project_id / base_revision`，与既有登记库事务和幂等缓存一致。准确引用 ref 为 `{artifact_id,version,sha256}`，version 为正整数、sha256 为真实正文摘要。

| action | payload 附加字段 | 结果 |
| --- | --- | --- |
| read | expected_project_id；可选 comparison_id、include_content | 紧凑对比、选择、集成历史与当前采用基准；include_content=true 必须指定comparison_id |
| prepare | comparison_id、title、target_artifact_id、baseline、working_ref、main、alternate、context、visual_ranges；首次无工作稿另传nonvisual_sections | 冻结一组可比较的主备准确版本及完整工作底稿，不创作、不选择、不批准 |
| select | comparison_id、choice、user_request、synthetic；choice=fusion时另传fusion | 记录当前唯一选中方案，返回selection_id；不批准 |
| integrate | selection_id、base_version；可选task_id、cloud_update | 程序确定性组装完整style_bible并沿用原保存或任务提交流程，返回候选 |
| revise | selection_id、source_ref、working_ref、baseline、base_version、edits、scope_judgment、reason、user_request、synthetic；可选task_id、cloud_update | 从可信完整基准链按准确局部编辑生成下一候选；无需重新主备选择，不批准 |

`user_request={source:"conversation"|"panel",reference:实际消息或点击标识,quote:真实原话}`。synthetic 仅标识测试；test_only项目拒绝非synthetic选择。宿主证据不是由程序认证的人类身份，不得补造原话。生产项目选择仍需要真实用户明确选择。

## 保存两套方案与对比

先用标准保存或任务提交保存完整主选和备选，kind均为research，分别使用稳定且不同的artifact_id/scope。二者有不同正文，并在deps中包含同一组context准确版本。context至少包含明确的大纲、小说或剧本情境，不用各自挑选的不同情境掩盖比较差异。方案的参考用途、范围、证据等级和未决问题由完整正文表达，程序不把依赖字段当作研究质量证明。

prepare 的 main/alternate 是这两份准确ref；context是非空ref数组。target_artifact_id必须沿用既有全剧基准的style_bible身份，scope固定project/style。对比记录不可覆盖，修改方案后用新准确引用保存新的comparison_id；旧对比和未选候选保留。

baseline为当前已采用全剧基准的准确ref，无已采用版本则null。working_ref为目标成果当前最新的完整本地工作稿ref，真正从未保存过才为null。若云端存在手改，先完整读取保留为本地新候选，再用其working_ref；不能直接用旧通过稿覆盖云端未批准修改。baseline用于采用指针与漂移核对，working_ref用于实际全文组装，两者可以是不同版本。

现有工作稿用 `visual_ranges:[{start,end,quote}]` 指定替换区域。start/end是Python Unicode code point偏移，区间左闭右开；不是UTF-8字节偏移或JavaScript UTF-16偏移。范围按正文顺序、非重叠，quote与完整工作稿切片逐字符一致。不允许把全部旧基准当作视觉区域替换；其余全部原文保持不变。

视觉范围分类是宿主读完全文后的语义判断。导演、表演、声音和世界规则不能被误归入视觉替换范围；旧文档无法安全分界时，先形成可审阅的完整结构化修订，不通过任意偏移强行跳过判断。

working_ref=null时visual_ranges必须为空，并提供 `nonvisual_sections:{direction,performance,sound,world_rules}` 四份正文。尚未确认的专业条款明确写未知，不凭美术方向伪造决定。有工作稿时禁止用nonvisual_sections另写一套替代旧条款。

## 选择、融合与完整集成

choice只选main、alternate或fusion。融合须先保存一份新的完整research方案，它具有独立身份、同一context，并依赖原主备双方准确版本；然后用fusion字段选择它。不得以“都选”直接把两个方向并入正式基准。

integrate不接受调用者传入整稿覆盖正文。程序在working_ref的首个视觉范围插入所选方案完整正文，移除其余已明确视觉范围，保留所有未选中原文，产生唯一完整候选。首次无工作稿时组装视觉、导演与摄影、表演、声音、世界规则章节。不会保留未选方案的完整正文作为第二套同时生效规则。

每次select/integrate都核对当前采用指针、当前最新工作稿和context是否仍然一致；变化后先重读并准备新的准确对比。目标kind/style分类/scope/ID稳定，既有云Page绑定不改；cloud_update可沿用1.12流程及准确base_observation_id。旧未知云请求继续保留，不因角色切换重建页面。

普通保存的候选不会被自动批准。对已纳入美术流程的style目标，content.approve还会检查候选是当前选择对应的准确完整集成版本，防止把纯视觉文本或其他方向偷偷作为完整基准采用；批准仍需要原机制的真实用户证据。已采用旧基准在比较、选择或保存新候选时保持原样。

## 基准内局部修订与旧项目接续

采用完整基准之后，用 `revise` 修改局部措辞或接入已完整保留的云端手改，无需重新生成两套方案或再次选择方向。`scope_judgment` 固定为 `within_baseline`，但这只是宿主对本轮变化范围的判断，不是程序已证明语义、时代、外貌或审美仍符合基准。改变整体方向、时代、已选角色外观时应回到具体方案和用户选择；边界不明时保留已采用版本，并交代未决变化。

`source_ref` 必须为当前selection最近一次integrate/revise产生的完整准确版本。`working_ref` 必须为同一稳定成果当前最新完整本地稿；`baseline` 单独冻结当前已采用准确版本（未采用时null），`base_version` 等于working_ref.version。三者分别表示完整修订来源、实际最新工作稿和正式采用锚点，不互相代替。read的 `revision_source` 提供可信source_ref，`revision_source_kind`为`managed_chain`、`legacy_approved`或null；它不是新的采用证明。

`edits` 是按source_ref正文定位的 `[{start,end,quote,replacement}]` 数组，仍使用Python Unicode code point左闭右开偏移、按顺序且非重叠，quote逐字符匹配；replacement可为空。程序只替换列出的范围并保留其余全部原文。不得将所有正文都作为编辑范围以实现整稿替换。纯插入使用附近非空quote作为锚点，在replacement内保留该锚点并增加内容。`edits=[]`允许同文完整核对。

若working_ref与source_ref不同（例如云端手改已通过普通保存保留为新候选），程序要求source正文应用全部edits后的完整结果恰等于working全文，同时保留原source、回灌版本和再次核对后的新候选。不能忽略未解释的云改，也不能在这一步附加尚未回灌的新变化；完成核对后可再对最新可信版本做下一次revise。来源deps必须与source一致且仍新鲜，避免局部编辑顺手更换专业依据。云端仍沿1.12的准确观察、base_observation_id和同页同步机制，不篡改读回正文以凑相等。

`reason`说明此次修订理由，`user_request`记录本轮依据的真实任务请求或用户授权原话；它可以沿用已有基准内自主协调授权，无需每个字再索取一次选择。TEST项目必须synthetic=true。revision返回 `scope_judgment:"within_baseline"` 和 `semantic_compliance:"host_judgment_not_program_proof"`，新成果仍为候选；正式采用继续走content.approve，核对当前最新工作稿、当前方向和正式基准未过时。

旧项目从未有任何美术选择记录时，允许 `selection_id:null`，首次source_ref仅能等于当前已有的准确已采用style基准。回执 `legacy_baseline_inherited:true` 表示继承已有采用证据，不创建选择记录、不补造批准；comparison_id与selected_proposal为null。之后沿该身份的最近revise完整链接续。已有任何美术选择记录后不能以null绕过当前方向；未采用的任意旧稿也不能用作继承锚点。旧云页绑定和未知请求均保持原样。

## 任务锁与来源

无task_id时集成走原artifact.save；同范围已有活动任务会拒绝抢写。有task_id时走原task.submit，须匹配project/style范围和目标ID、冻结所需inputs；旧任务仍须满足原execution_lock。返回后任务与成果状态按旧机制保存，不改锁、不清needs_review。

revise沿用同一保存或任务提交通道；修订任务的inputs须恰好等于source_ref完整版本的deps。source_ref本身作为冻结修订来源保存，不作为动态自依赖。旧任务版本不匹配时仍拒绝写入，不能通过美术入口绕过。

read中的 comparisons[].required_inputs 是当前工作稿原deps与本次context的完整版本并集；用于集成的任务inputs须恰好等于此集合。两组引用同一来源不同版本时拒绝，先核对受保护条款。基准本身通过baseline/working_ref冻结，不把目标自己的旧版本作为动态deps形成自引用；所选方案由selection_id及准确来源字段单独冻结，不向任务inputs混入未选方向。

主备方案以metadata.art1130保留准确选择来源和摘要；它们是选稿溯源，不能因为后来保存另一份未批准research草稿而挤掉已采用基准。正式下游仍绑定完整style_bible准确版本；通过新版基准后使用原依赖传播标记需复核，不自动判定全部返工或豁免。

## 读回与证据

summary字段包括 project_id/revision/comparisons/selections/integrations/active_selection_id/active_selection/current_style/current_style_status/revision_source/revision_source_kind。comparison含main/alternate准确ref、baseline/working_ref、required_inputs及stale_reasons，普通读取不回显正文；integrations的编辑记录只给start/end，不回显quote/replacement。

read指定comparison_id与include_content=true时另返回comparison完整记录、proposals.main/alternate完整成果、working_draft及对应完整集成/编辑记录；有该对比当前选择时返回selected_proposal和integration_preview。这个预览对应原对比的集成计划，不代替后续最新revise正文；最新准确正文按revision_source使用标准成果读取。预览不是已保存或已采用证明。

integrate/revise均返回原保存结果（artifact，以及原通道可能提供的task、cloud_update）及art_integration、art_revision；selection_is_approval=false。art_integration含integration_id、kind（integration或revision）、selection_id、comparison_id、artifact准确ref、baseline、working_ref、selected_proposal、created_at、approval_status:"candidate"。revision另有source_ref、edits偏移、reason、user_request、synthetic、scope_judgment、semantic_compliance及legacy_baseline_inherited。

程序验收使用隔离TEST项目。研究方法执行、实际媒体可读范围、完整片段或全片覆盖、用户审美采用分别报告，不把数据库成功当成视觉效果通过。
