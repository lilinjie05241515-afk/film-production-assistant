# 美术方案与项目交接

本参考负责项目中的方案身份、选择和接续。完整专业创作读取 `../../../modules/film-art-director/SKILL.md`；本次 task_module 为 art_director，工作对话职责为 art。style 阶段进入美术模块；research 继续进入 film-analysis，旧研究记录和独立入口保持原义。

## 先读准确状态

先核对项目、已有正式 style_bible、最新工作候选、云稿手改、已选资产与运行中任务。既有任务读取 execution_compatibility 与完整检查点；新角色不能抢占同范围成果或改变旧锁。没有完整正式基准时可讨论和形成候选，不能声称已确定全片风格。

使用 `film_art(root=真实作品目录,action=动作,payload=参数)`，基础字段见[接口契约](../../../docs/integration-art-1.13.0.md)，1.14 剧本来源更新与风格引用扩展见[本版接入说明](../../../docs/integration-1.14.0.md)及下文；准确参数以当前工具定义为准。不清楚时查询 film_action_help，不重读整套源码。读取、选择与保存各有不同结果，程序不做审美判断、生成图片或调用其他聊天。

`read` 的 payload 必须有 `expected_project_id`，可选 `comparison_id`。默认只读摘要；需要完整对比和正文时同时传 `comparison_id` 与 `include_content=true`。读取返回当前 `revision`，所有写动作均带 `op_id`、`expected_project_id`、`base_revision`；此处 base_revision 是美术状态 revision，不是成果 version。未知结果保持原操作号和参数先核对，不能换号重做。

所有准确引用均为 `{artifact_id,version,sha256}`，摘要来自真实保存回执；不得按标题猜版本或自己填写未经核对的哈希。以下三个引用职责不同：

| 引用 | 指向什么 | 用途 |
| --- | --- | --- |
| baseline | 当前已采用 style_bible 的准确引用；确实没有采用版才为 null | 检查正式采用指针和累积偏移，不能用候选冒充 |
| working_ref | 目标成果当前最新的完整本地工作稿；云端手改先读取并保存为本地新候选 | 保留尚未采用的完整工作内容；prepare 时从未有稿才可为 null，revise 时必需 |
| source_ref | 当前 active selection 最近一次 integrate/revise 成功保存的完整成果；尚未建立美术选择的旧项目见下文窄兼容 | 仅用于 revise 的可追溯编辑起点；不是纯视觉方案或任意旧稿 |

同一份成果可以兼具几个身份，但不能仅因为 ID 相同就将不同版本互换。read 中原对比的 working_draft、selected_proposal 和 integration_preview 不是后续修订链的最新正文；接续 revise 使用返回的 revision_source，并准确读取该完整成果。revision_source_kind=managed_chain 表示当前选择或旧基准接续链的最近完整版本，legacy_approved 表示尚无美术选择时可继承的当前已采用基准；为空时不能编造可修订来源。

## 比较方案与选择

首次定调默认完成一套主选、一套备选，用相同剧本情境、时代和人物前提比较。主选只是推荐。方案完整正文先保存为 research 候选，再登记准确引用；不要把两个选项都保存成全剧正式 style_bible。每份方案保留来源、适用范围、完整呈现及未知，不能用几个标签充当完整方案。

`prepare` 除共有写字段外，传 `comparison_id,title,target_artifact_id,baseline,working_ref,main,alternate,context,visual_ranges`。main、alternate 是两份独立 ID、不同完整正文的 research 引用，两者 deps 都须包含同一组 context；context 为非空准确引用列表，至少包含一份明确的大纲、小说或剧本情境，同一成果不能出现多个版本。不要将目标 style_bible 自己的旧版本混入 context。对比记录不可覆盖，方案需要重新比较时使用新准确引用和新的 comparison_id，保留旧记录。

有完整工作稿时，`visual_ranges=[{start,end,quote}]` 标出要替换的视觉内容，禁止再传 nonvisual_sections。start/end 为 **Python Unicode 码点偏移，左闭右开**；不是 UTF-8 字节数、显示字符宽度或 JavaScript UTF-16 索引。范围按原文顺序且互不重叠，quote 必须与 `完整正文[start:end]` 逐字符相同；包括换行、空格、emoji 和组合字符都按真实正文计算，不能从渲染 HTML 或肉眼行号估计。各区间长度须等于 quote 的码点数。

宿主必须先核读完整工作稿，判断哪些区域确属视觉。程序只检查切片和范围，不能证明分类正确；不得把整稿或导演、表演、声音、世界规则随意圈入。无法安全分界时保留全文，先提出清楚的结构整理／修订范围，不通过猜偏移绕过。所有将被移除的视觉条款都须在所选完整方案中得到保留、明确修订或有依据的替代，不能误以为其他视觉区间会自动留在原位。

确实没有工作稿时，working_ref=null、visual_ranges=[]，另传 `nonvisual_sections={direction,performance,sound,world_rules}` 四份非空正文。未确认的专业内容写明未知和已知约束，不为美术方案伪造导演或世界规则；已有稿不能用这条首次创建路径覆盖旧内容。

选择记录只说明用户选择了哪个准确方案和范围。选择备选后不混入主选内容；只选局部参考不能升级成整套采用。用户要求融合时形成明确的新方案正文，保留所用来源及取舍，不能让下游从两个候选自行拼接。选择、完整整合和正式批准分别核实；已有清楚用户证据不重复要求同一确认。

`select` 传 `comparison_id,choice,user_request,synthetic`；choice 仅为 main、alternate 或 fusion。选 fusion 时必须另传融合成果的准确 `fusion` 引用；其他选择禁止带 fusion。融合稿先独立保存完整 research，具有同一 context，并在 deps 中保留主备双方的准确版本；不能以“两个都选”直接拼入基准。

`user_request={source:"conversation"|"panel",reference:真实消息或点击标识,quote:实际原话}`。选择和局部修订都保留真实来源；不能把推测的用户偏好、AI 建议或自检结果填成用户原话。test_only 项目使用 synthetic=true；生产选择使用真实证据，字段记录本身不是用户身份认证。原请求已明确授权基准内细化时，局部修订记录该持续有效授权与本轮原因，不反复向用户索取相同许可。

## 整合为唯一基准

在原稳定 style_bible 身份下生成完整候选，保持 category=style、scope=project/style。已有本地候选或云端手改先读取保留，不从旧通过稿整篇覆盖。视觉部分与保留的跨专业内容明确对应：导演、表演、声音、剧情与世界能力规则不由美术自行删除或替换。

整合时同时使用上一份实际工作稿和当前正式基准：前者用于保留本轮以前尚未采用的改动，后者用于检查长期累积偏移。两者不互相冒充。保存整合候选不会改变正式采用指针，也不让已有下游自动失效。

`integrate` 传 `selection_id` 与 `base_version`，后者等于准备时 working_ref.version，无工作稿时为 0；可选 task_id、cloud_update。selection_id 使用真实 select 回执，不猜造。程序在首个 visual_range 插入所选方案的完整视觉正文，移除其余明确选中的视觉范围，逐字符保留其外原文；不接受调用者传整稿覆盖。首次创建才组装视觉及四类其他专业章节。提交前复核预览是否完整，保存后核对准确成果、摘要及 art_revision。

若工作稿、已采用基准或 context 已变化，先读回真实状态并核对影响，不能放宽字段强行集成。已有稳定 target_artifact_id 不变，不因选备选或改标题建立第二份基准。

## 基准内局部修订

方向已经选择、只需局部细化时使用 `revise`，不重新凑主备方案。旧项目从未建立美术选择，但已有正式完整基准时，可用 selection_id=null 首次接续，source_ref 必须精确等于当前已采用基准；之后沿这条完整 revise 链继续。该窄兼容继承旧采用事实，不重新要求定调或把旧候选当成已采用。项目已有主备选择时不能用 null 绕过当前选择。无法确认只是基准内变化时保留现有基准，并提出新候选与具体差异。

除共有写字段，revise 需要 `selection_id,source_ref,working_ref,baseline,base_version,edits,scope_judgment,reason,user_request,synthetic`；可选 task_id、cloud_update，以及下文限定的 rebase。除上述旧基准窄兼容外，selection_id 必须是当前 active_selection_id，source_ref 必须是该选择最近一次完整集成或修订的准确成果。working_ref 必须是同一稳定目标的最新完整稿，base_version 等于 working_ref.version。scope_judgment 固定为 within_baseline，表示宿主已同时对照上一版和正式基准作出的判断，不是程序自动判定。

`edits=[{start,end,quote,replacement}]` 的区间采用上述码点规则，但全部以 **source_ref 的完整正文** 为坐标；按顺序、不重叠，quote 匹配真实切片。程序只替换这些范围并保留其余正文。replacement 可以为空表示明确删除；不能把整篇圈入局部修改，或用许多区间覆盖全文来更换方向。确有回灌登记或下文剧本来源更新时允许 edits=[]，保留完整正文；普通无变化不为制造版本提交空操作。

source_ref 与 working_ref 相同时，执行本轮明确的局部编辑。两者不同时，程序要求 edits 应用到 source 后的完整结果 **恰好等于现有 working_ref 正文**，并要求两稿 deps 相同；这是解释并保留已回灌手改的接续，不是再次覆盖手改的机会。先用准确编辑计划登记全部已回灌差异，保留新的完整 revise 回执；再以这份新 source_ref/working_ref 进行后续新增修改。存在无法解释的云改、两稿原依赖不一致或超出基准的变化时，保留观察并处理具体分歧，不丢弃手改或改用旧通过版。已采用剧本换版只可按下文显式 rebase 更新本次候选依赖，不先篡改回灌稿的原 deps。

reason 写清本轮修改、适用范围和为何仍在基准内。每轮同时比较上一版与正式基准，检查累计色彩重心、时代线索、场景体系及已选外观是否偏移；小步修改次数多不构成绕过方向选择的理由。revise 保存完整候选和修订链，不自动批准或清除其他成果的需复核状态。

## 剧本采用更新后的美术接续

采用新版剧本后，旧美术基准可能因依赖变化进入 needs_review。先读真实基准引用、复核原因、revision_source、最新完整工作稿，以及原依赖中旧新剧本的完整正文；needs_review 不让旧采用事实消失，baseline 仍填真实已采用版本，不能改为 null。核对实际剧情、场景、时代与人物外观变化；属于原方向内细化时沿原选择或旧基准接续链修订，不重凑主备。改变整体方向仍先交用户选择。

1.14 允许在 `revise` 显式加 `rebase={previous_inputs:[REF],inputs:[REF]}`；每个 REF 均为准确 `{artifact_id,version,sha256}`。previous_inputs 须完整列出 source_ref 原 deps 的全部准确版本和真实摘要；inputs 保留同一组 ID，不增删来源。至少一份 kind 为 script、screenplay 或 source_script 的来源推进到更高版本；其他来源保持原版本。只有本次推进的剧本须为当前已采用且无需复核、依赖新鲜的准确版本；未变化的其他来源沿用原准确版本及原有新鲜度规则，合法且新鲜但尚未批准的 research 可以保留，不新增批准要求，也不自动批准或豁免其过期、换版、需复核。若基准已 needs_review，其记录的上游与版本还须恰好由本次列出的剧本更新解释；其他未处理来源变化不能借此放行。

reason 写明剧本差异、核对到的影响和仍在原基准内的依据；user_request 继续引用真实有效授权。正文无需变化时可传 edits=[]，保存完整正文及明确更新的依赖，不凭空制造文字差异。存在云手改时，先按原 deps 回灌完整 working_ref；source 加 edits 的完整结果必须恰等该工作稿，同次 revise 才可用 rebase 换成本轮新依赖。新增而尚未保存的文字改动留待下一轮，不能混在解释云手改的编辑计划里。

成功只形成完整候选和可追溯接续记录，旧批准基准仍保持 needs_review。独立核对实际完整候选后，有真实采用证据再走 content.approve；审批会再次检查基准、最新工作版本和 rebase 的准确来源。其间又有上游换版、其他来源待复核或实际依赖回环时保留结果并处理具体分歧，不改状态字段、不删依赖、不重建相同操作来绕过。此流程不自动修复旧项目已经形成的依赖环路。

## 活动任务与准确输入

无 task_id 时 integrate/revise 走原候选保存机制；同范围已有活动任务会拒绝抢写。有 task_id 时走原 task.submit，任务 scope 必须是 project/style，若锁定 artifact_id 则须与稳定目标一致，并满足原 execution_lock 与当前输入校验。

integrate 的任务 inputs 必须恰好等于 read 中该 comparison.required_inputs：当前工作稿原 deps 与 context 的完整版本并集，不多不少。普通 revise 的任务 inputs 须等于 source_ref 完整稿的 deps；带 rebase 时则等于 rebase.inputs 对应的全部 artifact_id/version，不用旧 inputs 提交新来源候选。引用同一来源的不同版本时先核对实际底本；不把未选方案、被修订基准自身旧版混入 inputs。主备选择通过准确选择记录冻结，不用自引用制造依赖。需要任务接续时据此创建或恢复实际 art_director 任务，不能改已存在任务的冻结输入来适配新调用。旧任务锁或输入不适用时保留原检查点，按[任务与采用规则](registry-rules.md)处理真实接续。

只有用户明确采用准确完整版本与范围时，使用原 content.approve 流程；film_art 不新增批准捷径。用户只是“选 B 看看”“先融合试试”时继续候选；明确完整采用的证据可以按其实际范围接续，不要求再点面板。纳入美术流程的目标须为当前选择或旧基准窄兼容链对应的完整 integrate/revise 候选，普通 artifact.save 的纯视觉稿、任意回灌稿或已过时集成不能冒充可直接采用的完整基准。批准后下游引用唯一正式风格的准确版本，未选方案留在历史中。

## 工作稿、对话与下游

完整基准初稿及每轮明确修订按[云稿规则](cloud-round-workflow.md)保存和同步。纯讨论、比较建议、检查点与选择记录不触发另建云页；用户明确要求保存可编辑方案时按具体成果处理。原基准的项目、成果 ID 和 scope 不变，就继续原云稿；角色或标题变更不能重建页面。未知云创建先恢复原请求，手改冲突保留实际观察。

老项目未准备 art 入口时可保留解析得到的真实总控回退；新入口通过明确授权的工作区补建，不重建其他职责。进入对话、发送任务、创建聊天及媒体制作分开按授权执行；美术的自主协调不自动授予这些外部动作。

导演、资产与特效读取同一采用基准、准确剧本及本次设计简报。基准内细化正常推进；整体风格、时代、已选角色外观或其他明确决定发生变化时提交具体新候选。完整版本依赖只提供需复核对象，专业 Agent 实际核对后决定改写范围，不能把语义影响识别说成程序已自动完成，也不自动批量重做。
