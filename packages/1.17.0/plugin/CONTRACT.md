# 1.14.0 内部接口

联合接续扩展：自动风格引用可在确认反向路径后保存为准确冻结参考，原显式依赖不静默删除；普通保存可选use_current_style策略。art.revise.rebase仅推进同身份已采用的剧本来源，完整候选仍独立批准。历史恢复保留真实历史来源及当前准确风格引用。详细字段、任务锁、云手改与旧回环限制以 docs/integration-style-feedback-1.14.0.md 为准；下文1.13历史接口说明由此增量扩展。

1.14.0 在已发布美术总监1.13.0基础上合并编剧：`film_screenwriting(action=read/record/resolve)` 与 dispatch 同名 screenwriting 动作保存准确剧本意见及处理历史，不生成正文或自动采用。编剧统一小说、改编与原创剧本，直接剧本可以从动态分场正文开始，底稿可选；旧项目路线、分类和执行锁不自动迁移。完整小说与改编方法纳入screenwriter内部，原兼容名称解析到相应写作模式，美术的全部五动作及工作对话/云稿机制保留。当前八个专业模块、四个公开技能、二十四个MCP工具。准确契约见 docs/integration-screenwriter-1.13.0.md；合并总览见 docs/integration-1.14.0.md。

1.13.0 增加 `film_art(action=read/prepare/select/integrate/revise)`；严格字段与状态转换由 `filmprod/art1130.py` 统一提供，read 用只读连接。主备均为同一情境的独立准确研究版本，选择不等于批准；集成只替换经宿主核对的视觉区间，保留区间外全文。revise 接续基准内的局部修订，不必重开主备；其语义范围由宿主判断，程序只核验准确来源和完整保留。保留完整统一 style_bible、稳定成果与云稿身份。美术专业模块为独立新增第九模块，原八模块文件不改。影视路线工作对话增加 art，纯小说 prepare 可显式 include_art；旧总控兼容解析明确标记 requested/resolved_role。详见 docs/integration-1.13.0.md 和 docs/integration-art-1.13.0.md。

1.12.0 增加 film_cloud(action=read/configure/bind/prepare/record)。字段与状态机由 filmprod/cloud1120.py 共享 schema 提供，cloud.read 及旧 dispatch 对应读动作均用只读连接。artifact.save、artifact.save_file、task.submit、task.submit_checkpoint 可附 cloud_update，保存候选与待同步记录同事务；紧凑回执保留该记录。检查点和未带字段的旧接口不自动触发云写入。详见 docs/integration-cloud-1.12.0.md；实际创建/编辑与读回由宿主完成，host_reported 记录不认证远端身份。snapshot.cloud 和 context summary 含无正文状态，显式 observation_id 才返回保存观察全文。

`from filmprod.core import Registry`，`Registry(root)` 打开/初始化显式作品根目录。`dispatch(action: str, payload: dict) -> dict` 为统一调用入口，`snapshot() -> dict` 为看板数据；所有写请求带 op_id，复用号不同参数拒绝。

action: project.init {project_id,title,test_only}; artifact.save {artifact_id,kind,scope,content,base_version,deps:[{artifact_id,version}],metadata}; task.create {task_id,title,module,scope,inputs:[{artifact_id,version}],must_keep,allowed_changes,requirements,thread_id?}; task.checkpoint {task_id,draft,completed,decisions,unresolved,next_step}; task.resume {task_id}; task.submit {task_id,artifact_id,kind,content,base_version,metadata?}; decision.record {artifact_id,version,scope,decision,evidence,actor,synthetic}; thread.register {thread_id,title,scope,task_id?,status,current_control?}; sync.intent {sync_id,page_id,base_revision,intended_content}; sync.observe {sync_id,status,receipt?,observed_content?,revision?,comments?}; media.register {media_id,kind,path,metadata}; cue.save {cue_id,content,base_version,deps,metadata}; backup.create {destination}; backup.restore {source,destination}。

snapshot 返回 project, artifacts（每个含 artifact_id,kind,scope,version,content,sha256,status,metadata,deps）,tasks,threads,decisions,sync,media,events,capabilities；结果包容补充字段。错误 ValueError/ConflictError，HTTP 映射 409/400。base_version=0 表示首次创建。core 方法应实现上述操作并可扩展。

源素材/时间线等媒体关联放 metadata 但验证 clip source/in/out，sequence clip refs，final exact timeline+tracks/subtitles/export specification。metadata 自由扩展不可取代关键不变量。

任务 completed/decisions/unresolved 和 must_keep/allowed_changes/requirements 必须为数组；draft/next_step 必须为字符串。外部 artifact.save 不接受 task_id；任务输出只经 task.submit 提交，并验证任务模块、目标成果与冻结输入。task.cancel {task_id,reason} 保留历史、释放编辑范围。

sync.observe 的状态为 sent/unknown/verified/conflict/failed；可传真实观察时间 observed_at，数据库另记 recorded_at。unknown 不可直接重发。verified 只证明记录所指的读回，不证明此刻云稿仍未变化。

final.music/dialogue/shots 必须指向相应实际媒体的成果；未完成音乐需求放 planned_music，同时 assembly_status=planned 且不能声明已渲染。sequence 和 timeline 均需非空 clips 精确引用。导出尺寸为正整数，帧率为正有限数。

## 客户端插件与历史

正式入口是 Codex 内的 stdio 插件，不需要 HTTP 服务或另配模型 API。当前共 24 个工具：原有 13 个兼容工具为 film_modules、film_board、film_snapshot、film_projects、film_brainstorm、film_media、film_resume、film_history、film_dispatch、film_health、film_export、film_pages_import、film_render；1.10.0 新增 film_context、film_action_help、film_task_create、film_draft_save、film_draft_submit、film_artifact_save_file；1.11.0 新增 film_workspace、film_delivery；1.12.0 新增 film_cloud；1.13.0 新增 film_art；1.14.0 新增 film_screenwriting。兼容清单位于 plugin/.codex-plugin/plugin.json，MCP 声明位于 plugin/.mcp.json；发行模板由安装器生成本机部署配置，不复用另一设备的绝对路径。

artifact.history {artifact_id} 是只读 action，不需要 op_id，返回全部不可变正文版本，版本从小到大排列；不存在的 ID 拒绝。film_history 包装它；读取历史不能新增事件或版本。

## 1.3.0 审批、总稿与迁移

schema 2 首次打开旧 schema 1 时先生成 SQLite 一致备份，位置为项目 `.project/migrations/`。旧 decision 保留为历史证据，不自动推定为已通过总稿；需要精确映射后使用统一批准入口。返回 schema 1 必须恢复迁移前数据库并配套旧系统源码，不可仅切换插件缓存。版本正文、依赖、决定封存内容不覆盖。

`content.approve {op_id,artifact_id,version,scope,evidence,actor,synthetic,user_authorization?,base_master_version?}` 是对话批准与面板“通过并更新总稿”的同一事务入口。scope 必须与目标分段完全一致。更窄范围先存独立候选段，不能根据文字猜切段；恢复旧稿使用 `artifact.restore {op_id,artifact_id,version,base_version,...}` 创建新候选。总稿按 metadata.order（章节/场/镜头数字数组）或 scope 自然序组装，只有本次批准段被替换。精确版本重复批准不生成重复总稿。`decision.record` 的精确全段 adopt 兼容进入相同流程。

真人操作证据绑定版本与范围；面板操作来源 `source=panel-click` 记录操作，不伪造认证账号。账号未知保持 `real_user_id=null`。TEST 所有批准必须 synthetic=true。`snapshot` 保留 artifacts 最新候选，并补充 approved_artifacts、current_content、pending_candidates、masters。current_content 每段优先已通过版本，没有通过版时明确 initial_draft。`master.history {category}` 为只读总稿历史；分段历史仍用 artifact.history。

未批准候选不会使当前已通过依赖失效；批准上游新版本后根据精确依赖传播 needs_review。待审核与需复核分别展示，系统不自动重写或重新批准下游。旧版本状态不能证明当前业务准备状态。

`master.bind_page {op_id,category,page_id,base_revision}` 关联实际云稿。`sync.intent` 可携带 master_category/master_version，intended_content 必须逐字等于该总稿，page_id 必须匹配绑定；`sync.observe` 读回后更新对应总稿同步状态。失败或冲突不撤销批准，不要求重复批准。同步由宿主 Pages 工具真实执行，本地登记不产生云端写入。

`film_pages_import` observation 可明确 category=outline/novel/character_bio/source_script/script/style/director/vfx/assets/research，完整宿主观察归档为 cloud_working_draft，包含正文与 Page 来源、观察时间、序号、块哈希。该导入不移动已通过指针；无 category 时保留旧稳定场次映射兼容入口。云端风格或人物工作稿不因导入而变成已通过内容。

## 1.3.0 项目目录、宿主与视频

`film_projects {action,payload}` 提供 list/resolve/outcome/register/create/relink/bind/unbind/forget。写操作带 op_id；默认登记库位于 LocalAppData/FilmProduction/projects.sqlite3，测试可用 FILMPROD_CATALOG_PATH 隔离。只登记明确目录；已有项目接续，搬家按 project_id 校验。thread_id 绑定优先于客户端 project_id，不以其他聊天最后浏览项目覆盖。面板切项目不移动宿主聊天，也不授予目录权限。实际聊天创建、打开由宿主工具执行，数据库关联本身不能冒称完成这些动作。

`film_media {root,action,payload}` 支持显式 choose、import、preview；导入已经制作好的本机视频，原件复制到当前项目并核验，按 take/clip/final 归类，metadata 关联 chapter/scene/shot。原视频不上传；缩略图和最多前 12 秒低清派生预览仅经 UI 专属 _meta 返回。已有 film_render 保留为次级技术能力，不调用付费生成。

1.3.0 安装包内置版本化 Python runtime/filmprod；发布前 build 后核验缓存，避免缓存随系统源目录开发漂移。Codex 原生、Work 本机访问、纯云端 Work 属于不同宿主能力，必须按实际联调报告说明。音乐生成仍未接入。

原生面板保存每项待确认写入的 root、工具名、action、完整 payload 和 op_id，并在作品写入 payload 中冻结 expected_project_id。film_dispatch、film_media、film_render 在打开 Registry 前只读校验磁盘项目身份；已在 catalog 登记的 root 还必须与登记 project_id 一致，旧调用即使未提供 expected_project_id 也不能绕过该校验。核心 dispatch 在写入前、事务内及缓存重放前校验可选 expected_project_id。相同目录被替换为另一个项目时拒绝写入，不以路径相同推定身份相同。

未决 journal v2 按真实 thread_id 隔离并保存 owner_context；未知真实聊天 ID 时只保留面板会话内状态，旧 v1 只读核查、不自动恢复或重放。超时表示结果未知；先读登记结果，同一写入只能以原请求重放，不能自动换号、换目标或换底本。身份冲突不证明之前的未知请求未提交，必须保留原未决记录。真人审批还需精确版本、范围及真实用户操作证据，普通登记点击不等于批准。

## 1.3.0 创作路线、人物小传与全剧风格

`project.workflow.set {op_id,expected_project_id,base_revision,mode,outline_order?}` 保存 project.workflow。expected_project_id 与 base_revision 必填；mode 为 novel_only/novel_to_screen/screenplay，outline_order 为 before_novel/after_novel。snapshot.workflow 提供已保存路线及只读建议阶段，默认 unset，不根据既有成果推断。选路线或开始阶段不创建聊天、不批准内容；面板阶段请求只交给当前聊天。小说转影视的大纲为正式阶段并可前后调整；纯小说与直接剧本的大纲可选，纯小说可止步。用户可跳过阶段，缺失输入保持未知。

dependency_suggestions 按当前路线所需来源及实际存在的可选资料列出，不把不存在的可选小说/大纲报告为缺口。可含 optional、candidate_refs、review_refs；status=candidate 时 refs 仍为空，待审候选不能冒充正式精确输入。

新增 kind/category=character_bio（人物小传），旧 character 仍按原 outline 分类。剧本底稿使用独立 kind/category=source_script；动态剧本仍用 kind/category=script，显式 metadata.workflow_stage=dynamic_script。两种 category 可以用相同 scope，各自形成独立总稿。旧 script 无阶段为 unclassified；旧 script 即使声明 source_script 阶段也不自动改类别或迁移历史。story/novel-master/screenplay/novel-to-screenplay 允许 character_bio；screenplay/novel-to-screenplay 允许 source_script。

旧 kind=character 未声明 metadata.workflow_stage 时，仅在流程视图进入 unclassified，reason=legacy_character_stage_not_declared；原 category=outline、通过指针与总稿保持不变，不因此算作已完成大纲或人物小传阶段。

新增 kind=style_bible、category=style，scope 必须为 project/style。影视研究及旧 style_constraints 仍属于 research，不自动升级为风格批准。snapshot.workflow.global_style 与顶层 global_style 相同，字段为 status（missing/candidate/approved/needs_review）、approved_ref（精确 artifact_id/version 或 null）、pending_refs、scope=project/style、semantic_compliance=not_assessed。状态不证明语义合规。

适用下游 task.create 自动冻结当前已通过全剧风格精确引用，显式旧风格冲突拒绝；尚无通过风格时允许候选工作并保留 missing_context=['global_style']。全剧风格新候选不改变已通过依赖；批准新版后相关精确依赖进入需复核，宿主完成语义审查，不自动重写或重新批准。资产阶段需整合全部适用已确认输入与准确版本，缺失资料不能补造。

current_content/approved_artifacts/pending_candidates 的顶层 style_context 是当前风格绑定缺口的只读视图；metadata.style_context 仍为该版本保存时的历史状态，不因读取回写。语义合规仍 not_assessed。

## Pages 观察与渲染

film_pages_import 只接收宿主真实取得的完整 Pages 观察；缺少完整视图或截断内容不导入。实际云端读写仍由内置 Pages 工具完成。sync 的 cloud_write_performed_by_registry=false 表示本地登记器不执行云端网络写入，cloud_write_executor=host-tools；它不否认回执所对应的真实宿主写入。历史记录不回填或改写。

film_render 的 payload 必须显式给出 preview 布尔值，连同 artifact_id、version、op_id 一起冻结。TEST 项目只能 preview=true。详细媒体格式、技术核验和拒绝条件见 docs/剪辑导出.md。渲染器保留完整提交请求，以便丢回执后原样恢复；缓存结果保留历史技术核验并重新计算当前依赖状态。render 成果与 final 清单分开登记，不自动记录采用、交付或发布。

## 1.5.0 AI 视频提示词

新增 `kind=video_prompt`、`category=video_prompt`、`metadata.workflow_stage=video_prompt`。旧 `kind=prompt` 默认映射仍为 `asset`；不扫描、重新分类或迁移旧成果。影视两路线在资产提示词之后提供新阶段，纯小说路线不强推。模块 `video_prompt` 与 `seedance-prompt` 可以提交该成果，沿用任务冻结输入、检查点与审核协议。

`content` 为一次独立生成的完整纯文本，可含多个镜头，按 `【风格总控】→【场景与角色锚定】→【分镜】` 写作。metadata 可记录 `target_platform`、`target_model`、`generation_unit`、`shot`，以及已有的 `chapter`、`episode`、`scene`、`order`；没有提供的值保持未知，不据此声称平台参数已设置。`deps` 记录精确来源，来源和审核说明不得混入复制给模型的正文。

视频类别参与全剧风格绑定、上游批准后需复核、精确版本审批、独立总稿、历史与 Pages 工作稿。资产仅在存在时作为可选来源，不因没有实际参考图阻断文字提示词，不虚构已上传素材。导出的每个生成单元另有逐字保持 `content` 的纯文本文件，总稿仍用于阅读汇总。

这是一项文本创作与管理能力；不产生视频、不上传素材、不调用付费生成接口、不自动批准作品。具体镜头与对白必须依照已有专业技能和明确输入进行语义核对。

## 1.4.0 只读头脑风暴接口

新增技能 film-brainstorm-interface 与 MCP film_brainstorm，工具 annotations.readOnlyHint=true。interface 无需项目；prepare 需要 root 和 payload.expected_project_id、topic，可带 scope、context_refs 精确版本数组、base_ref、must_keep、constraints、allow_candidate_context。base_ref 未指定为 null，指定时必须属于 context_refs；候选默认拒绝，明确 allow_candidate_context=true 才能作为候选参考。静态接口返回完整 input_schema/output_schema/candidate_output_schema，字段以该返回为准。

brainstorm.interface/brainstorm.prepare 为只读 action，无 op_id。MCP 在 Registry 构造前核验目录与 catalog 身份，专用 film_brainstorm 及兼容 film_dispatch 都转入独立 mode=ro/query_only 读取路径。缺失项目不初始化，schema 1 不迁移，不写事件、任务、成果或决定，不执行网络、聊天和生成。

结果 status=interface_only、provider_status=not_connected、can_generate=false、read_only=true、generation_performed=false、candidate_output=null。contexts 为明确所选精确版本全文/哈希/状态；context_status 区分 approved、candidate、historical_approved、needs_review。global_style 为当前风格状态，approved_style 仅为仍有效的已通过风格精确完整上下文；来源过期时保留需复核，review_reason 可为 dependency_stale。unknown_inputs 不被补造。准备成功不代表生成成功，未来候选输出 schema 不是真实方案，保存与批准继续使用正常版本流程。

## 1.7.1 发行与执行身份

`film_modules {module?}` 只读校验全部包内文件；无 module 返回清单，有值解析当前阶段入口。返回不代表创作或媒体生成。`task.create` 自动保存 execution_lock 系统/模块版本与完整模块摘要，不能由调用者覆盖。`task.resume` 补充 execution_compatibility；`task.checkpoint`/`task.submit` 要求锁与当前包一致，旧缺锁任务不补造历史。提交成果 metadata.execution_lock 保存同一执行身份。schema 保持2，旧任务只读/取消仍可用；不自动改绑规则。

## 1.7.1 灵感与需求

可选阶段idea/requirements通过snapshot.workflow.preproduction_stages提供，三条路线及unset均不强制执行。film_modules解析对应内置方法。task模块idea/idea-explorer仅提交kind=idea，requirements/requirements-planner仅提交kind=requirements；二者category同kind。content.approve只批准文本，不改变执行授权。

planning.record写请求必须提供op_id、expected_project_id、record_id、scope、base_version和change。首建change使用record_kind=idea|requirements、title、state、entries；后续使用title/set/append/item_updates/branch_updates/entries，禁止整体覆盖集合或改写旧decisions/authorizations/sources/attachments/projects。source与授权原话必须来自实际输入；工具只记录，不能证明人类身份或执行授权。返回saved/readback_verified、record、version、artifact_ref、sha256和project_root。底层kind=planning_record只经该接口保存，不可审批/普通保存/恢复旧状态覆盖。

planning.read只读读取record_id与可选version、since_version、limit(1..100)，返回最新/指定全文状态及有界增量changes；artifact.history保留所有不可变版本。saved附件必须指向本项目实际登记媒体并核验字节；外库附件没有导入时仅记录link_only。备份仍使用统一Registry备份；schema保持2。

## 资产业务分类与精确正文导出

资产成果的 `metadata.asset_type` 是显式业务分类，值仅为 `character/scene/prop/other/unclassified`。`artifact.save` 与 `task.submit` 对新提交值执行相同校验，只允许 `category=asset` 的成果携带该字段；不把旧 `character`（仍属 outline）或人物小传改成资产。旧 `prompt` 仍属于 asset。旧版本缺失或未知值只在读取视图显示为 `unclassified`，原 metadata 原样保留，不根据角色名、标题、文件名、media.kind 或时间推断类别。

兼容旧资产的正文编辑：若当前精确基础版原本属于 asset，提交的新版本仍满足 kind/scope/category 不变量，且携带的未知 `metadata.asset_type` 与当前旧版的该字段按稳定 JSON 表示完全相同，可原样延续该未知字段；对象键顺序不影响比较，`true` 与 `1`（包括数组/对象内）不相等。该例外不自动归类、不抹除字段；新建成果、把正常值或另一旧值改成非法值均拒绝。只对当前旧资产值生效，不允许借历史版本回填已经变化的旧值。`media.register` 与 `media.classify` 新提交值仍严格遵守枚举，不适用这一正文编辑兼容。

`snapshot` 在 `artifacts/approved_artifacts/pending_candidates/current_content` 的每个资产精确版本上分别增加只读 `asset_type`，待审候选的新分类不改变当前通过版的分类。`media` 每项增加只读 `asset_type` 和缺省为 0 的 `classification_revision`。`asset_summary={by_type:{character|scene|prop|other|unclassified:{artifacts,media}},artifact_count,media_count,artifact_scope:'latest_versions',media_scope:'registered_images',approval_inferred:false}`；该统计只计每个 artifact 的最新版本及 `media.kind=image` 的已登记图片，与资产图片管理范围一致，audio/video/project/other 不混入图片数量。统计不能用作当前采用数量。通过、待审、需复核和媒体登记状态仍由原状态字段表达。

`media.classify {op_id,expected_project_id,media_id,expected_sha256,asset_type,base_revision?}` 在现有写事务、项目身份和幂等协议内执行。`base_revision` 缺省 0，必须与当前分类管理修订号相同；成功递增 `classification_revision` 并记录 `classified_at` 和事件。同哈希但另一面板已改分类仍会产生修订冲突。执行前核对项目原件存在且实际字节 SHA-256 与登记一致，仅更新管理分类，不改媒体 ID/path/sha256/size/rights/registered 状态或任何采用决定。返回 `{media,asset_type,classification_only:true,readback_verified:true}`。同 op_id 相同请求返回原操作回执，参数不同拒绝；回执仍是该操作发生时的结果，不冒充后来状态。

`document.export {expected_project_id,artifact_id,version}` 是只读 action，`version` 必须为精确正整数。MCP 与 CLI dispatch 均使用 `Registry.open_readonly`，缺失项目不初始化、旧 schema 不迁移。只有字符串正文可以导出；对象及 `planning_record/pages_observation/cloud_observation/render` 记录或诊断拒绝，`cloud_working_draft` 若正文确为字符串可按工作稿身份导出，仍未通过。

返回 `{read_only:true,artifact_ref:{artifact_id,version},kind,status,content,filename,mime:'text/markdown; charset=utf-8',encoding:'utf-8',data_base64,sha256,size_bytes}`。字节为准确 `content.encode('utf-8')`，保留 CRLF/LF/CR 和所有 Markdown 源文，不包装标题、来源或审核页脚；核验摘要与登记一致。返回可用于客户端下载，不在服务端写文件、发事件或变更采用。既有 `export_project` 仍是带来源和规范化换行的阅读副本，不能当作这个精确纯正文导出。

本次不新增文件上传、编码转换或另一套 Markdown 导入记录。Markdown 的阅读排版由界面处理，原始正文、原始结构与版本保持独立。

# 1.7.4 历史资料展示与整集提示词阅读

本补丁增加展示管理与候选阅读功能，八个专业方法和原有创作、审批、任务执行锁保持独立。

## 展示管理

`presentation.set` 是作品登记库的管理操作，必填 `op_id, expected_project_id, artifact_id, version, expected_sha256, base_revision, display_category, title, archived`。目标与展示分类必须属于普通创作内容栏目；资产和研究使用专用管理页，本接口不接管。目标必须是存在的准确创作成果版本；摘要、项目身份和管理修订号必须匹配。初始修订号为0，成功后递增；同一操作号同参数返回原回执，异参数拒绝。

管理记录保存在独立设置中，不改变成果的kind、category、scope、正文、SHA-256、元数据、精确依赖、批准指针、总稿或任务锁。归档仅将该准确版本移出常用列表，仍可从历史资料查看；可恢复为常用。展示分类允许将旧参考放在更合适的阅读栏目，不能冒充原业务分类变化。

`snapshot.presentation.entries` 返回精确 `artifact_id/version/sha256` 和展示标题、展示分类、archived、revision等字段；`version_scoped=true`，`approval_inferred=false`。新版本不会继承旧版本的展示管理，原始登记历史保留。旧运行时不会解释新展示设置，因此需实际运行新版看板。

## 提示词合集

AI视频提示词默认按已明确登记的集或章提供合集，展开后按场次与单元顺序连续阅读。没有登记章节时保留未分组身份，不从名称臆测。生成单元不再成为顶层分组。

合集是只读阅读视图，从同一批准确的 `current_content` 版本组装：已有通过版时保留通过版，没有通过版时标为初稿。候选、待审和需复核状态继续分别显示；合集不创建新的正文副本，不生成批准总稿，不写审批。每个单元保留准确正文复制及编辑审核入口。

打开阅读时使用所选精确版本快照。新候选不会静默改写已打开正文；重新读取当前合集后可看到新版本。旧画面呈现稿可作为历史参考显示于提示词栏目，但仍保持原业务身份。

## 接续与核验

正式1.7.2包、旧任务execution_lock和用户作品继续保留；更新发行独立1.7.4包。本地安装、当前聊天运行和实际面板显示分别核验，安装成功不证明已打开面板热更新。

管理回归使用test_only夹具，覆盖精确版本、摘要、修订冲突、幂等和原创作记录不变；界面核查覆盖历史入口、章节合集、未知分组、候选/通过并存和正文复制。真实项目整理只在作者明确授权的项目内执行，并保留前后数据对照。

本版完整保留正式1.7.3的源剧本与动态分场剧本分类说明；与本次看板管理改动合并发布。


# 1.8.0 媒体低清预览与名称分类管理

本版基于正式 1.7.4，保留历史资料展示、整集提示词阅读、剧本分类说明、资产分类、Markdown 阅读和八个冻结专业模块。程序与作品数据分离，不扫描或迁移真实作品。

## 使用方式

资产管理增加本机图片导入与按需缩略图，点击后查看低清预览。图片支持 PNG、JPEG、WebP，预览为静态图。派生 PNG 保留透明，缩略图最长边不超过 480 像素，预览图最长边不超过 960 像素，不放大原图。预览是派生缓存，不能代替原件或自动成为选用记录。

视频保留前 12 秒低清快速预览，始终提供打开原片入口。图片和视频均可编辑显示名称和同种媒体的管理分类；名称修改不重命名磁盘原件。图片分类为人物/场景/道具/其他/未分类；视频分类为拍摄素材/片段/成片/未分类。归入成片仅表示管理类别，不证明已审核、导出或发布。

原件继续存入项目媒体原件目录，使用稳定媒体 ID、源路径、内容摘要与明确关联。缩略图只缓存在界面会话中，不写回媒体元数据；原件不存在或摘要变化时拒绝沿用过期预览。打开本机原件前重新校验，宿主是否实际打开另行确认。

## 媒体管理接口

`film_dispatch` 的 `media.update` 必填 `op_id, expected_project_id, media_id, expected_sha256, base_revision, title`，并按媒体类型提供 `asset_type` 或 `video_category`。仅接受 image/video，不能跨媒体类型。title 为修剪首尾空白后的非空单行字符串，最多 500 个字符，拒绝控制字符。图片枚举 `character/scene/prop/other/unclassified`；视频枚举 `take/clip/final/unclassified`。

`base_revision` 使用现有 `classification_revision` 作为名称和分类共用的管理修订号，要求非负整数；与旧 `media.classify` 共用冲突检查，防止两个窗口互相覆盖。操作校验原件实际字节摘要和项目身份，沿用事务及 op_id 幂等；同一 op_id 重放返回原回执，不能把旧回执当成当前新状态。

修改仅涉及管理名称、管理分类、管理修订和时间记录，保留 kind/path/source_path/sha256/size_bytes/status/rights/stems/technical_check 以及创作成果、审批、任务和精确依赖。返回 `media, management_only:true, readback_verified:true, management_change.before/after`；事件保留变更前后信息，UI保存后读回当前项目。

## 本地预览接口

`film_media` 保留视频 choose/import/preview，新增 choose_image/import_image/preview_image/original。选择文件只有用户明确点击时启动，不自动扫描文件夹。

- `choose_image`：显式打开本机图片选择器，取消后不登记。
- `import_image`：要求明确 path、media_id、op_id、expected_project_id，可通过 metadata 指定名称和图片分类；核对图片、保留原件、登记后生成派生预览。登记成功但预览生成失败须分别报告。
- `preview_image`：按登记 media_id 请求预览，可用 thumbnail_only 只取缩略图。只读打开登记库，允许向预览缓存写入，返回 cache_only:true、read_only:false、write_scope:preview_cache，不能把缓存写入标成完全只读。
- `original`：只读解析当前项目中已登记的图片/视频，检查文件存在、路径在项目内、字节摘要一致，再返回 local_path、media_id、kind、sha256、hash_verified。前端据此请求宿主打开原件，不执行路径或标题中的指令。

图片用内容签名、尺寸预检、FFprobe 和完整单帧解码核验；当前限制为 64 MiB、单边不超过 16,384 像素、总像素不超过 40 MP。预览缓存按源摘要和参数版本隔离，通过临时文件、原子提交和并发锁保护。损坏、不支持或过大的图片给出明确错误。

图片缩略图最多 1 MiB、放大预览最多 4 MiB；视频内嵌预览最多 12 MiB。

图片及视频的 data URI 仅通过 `_meta.media_preview` 交给面板，常规 content 和 structuredContent 不包含二进制预览字段。界面只加载当前页需要的图片缩略图；项目切换、媒体变化和迟到结果须隔离。界面显示不等于模型已经分析媒体。

## 验证与升级

验收使用明确 test_only 的合成图片和短视频，检查实际本机解码、原件保真、缓存重建、名称分类编辑、冲突、幂等、路径边界和 UI 迟到结果。原生面板目视与实际原片打开须单独标注，代码测试不代替宿主播放验收。

数据 schema 保持 2；任务继续按精确系统/模块执行锁运行。旧程序不理解本版新增管理能力，不应通过修改执行锁强行接续。安装、启用、安装副本 stdio 与目标聊天实际 health 分别核对；旧聊天可能继续持有旧进程。


# 1.9.0 分类排序与文件回收站

本版基于正式 1.8.0，保留媒体低清预览、名称分类编辑、历史资料展示、整集提示词阅读与源剧本/动态分场剧本说明。八个专业模块保持原版本。程序升级不扫描、导入或修改真实作品。

## 分类排序

创作内容分类、图片资产分类与视频分类支持拖动排序，同时提供不使用拖动的移动入口。排序以项目为单位持久化，其他聊天重新读取同一项目时取得相同顺序。“全部”筛选固定在首位，不作为业务类别参与排序。这里只调整分类显示次序，不改变创作路线、镜头、正文或任务的执行顺序。

film_dispatch 的 board.order.set 必填 op_id、expected_project_id、group、order、base_revision。group 只接受 content_categories、asset_types、video_categories；order 必须是该组所有类别 ID 的完整无重复排列；base_revision 为非负整数，布尔值不作为修订号。各组独立保存修订，旧窗口提交过期排序会收到冲突，不能静默覆盖后来修改。

默认类别：

- content_categories：idea、requirements、outline、novel、character_bio、style、source_script、script、director、vfx、asset、video_prompt。
- asset_types：character、scene、prop、other、unclassified。
- video_categories：take、clip、final、unclassified。

snapshot.board_order.groups[group] 返回 order 与 revision。首次读取返回默认排列且不写数据库。新建/重新加载面板以项目返回的设置为准，不把浏览器本地缓存当作权威。

## 删除与恢复

界面“删除”经过明确的“移入回收站”按钮确认后，只把选中的准确文件版本或登记媒体移出正常列表。项目回收站可查看身份和恢复。恢复只取消回收状态，不新增正文版本或重新导入原件。

这是逻辑回收站，不物理移动或永久删除磁盘文件，不释放磁盘空间，不调用系统删除或删除云端 Pages。原件、内容、摘要、批准、总稿、旧依赖和任务执行锁保持完整。被总稿、任务或已有成果引用的内容仍能按原精确版本读取；回收站不撤销批准或采用。管理回收状态与旧“归档到历史资料”分别保存，恢复时保留原来的展示分类、归档状态和审核状态。为新工作挑选常用素材或候选时排除回收站项；已有精确依赖读取保持完整，明确的历史核查和恢复按准确身份执行。

film_dispatch 的 trash.set 必填 op_id、expected_project_id、target_type、target_id、expected_sha256、base_revision、deleted。target_type 为 artifact 或 media；artifact 必填准确正整数 version，media 禁止提供 version。deleted 为布尔值，true 移入回收站、false 恢复。禁止任意文件路径或未登记目标。

目标身份以登记摘要核对，媒体原件已缺失也可管理其列表状态；此操作不读取或复核媒体原件字节，不返回字节核验成功。摘要不符、目标不存在、错误项目、过期修订或额外字段均拒绝。每个准确版本/媒体独立回收修订，不把一个版本的删除状态套用到同 ID 的新版本。

snapshot.trash.entries 包含 target_type、target_id、sha256、title、kind、revision、deleted、deleted_at、updated_at；artifact 另有 version。历史版本不必出现在 current_content 中，回收站仍应完整展示。UI 过滤正常列表时必须同时匹配准确目标和摘要，不能修改原 snapshot 的权威记录或推断业务状态改变。

返回及说明保留 management_only:true、disk_space_reclaimed:false，写入后读回核对。所有写操作沿用事务、同操作号幂等和审计事件；未知回执保留原请求、项目和操作号，先核查再恢复，不以新操作号盲目重复。拖动和确认窗口均冻结项目身份，切换项目或较晚返回的结果不能误写其他项目。

## 验证与升级

使用明确 test_only 的独立合成数据验证：项目设置重开、不同项目隔离、排序完整性、并发冲突、幂等、准确版本回收与恢复、原件/正文/审批/任务依赖不变、UI 迟到结果、未知写入回执与实际 stdio 协议。源数据和旧发行包保持不动。

数据 schema 保持 2。新增管理状态放在独立设置中，旧程序可能忽略新排序与回收状态，因此需实际运行 1.9.0 看板；不要把旧程序显示某记录误认为恢复，也不要为接续任务手改执行锁。安装、启用、安装副本 stdio、当前聊天版本以及原生面板验收分别记录。




# 1.9.1 资产提示词与连续阅读

本版基于正式 1.9.0，修正创作内容中的资产提示词入口，并改善阅读目录和滚动体验。分类排序、回收站、媒体预览、名称分类编辑和精确版本管理保持可用。不迁移作品数据，不更改 schema、工具写入协议或八个专业模块。

## 资产提示词与图片分开

创作内容 → 资产提示词用于制作人物、场景、道具等资产的文字提示词，显示文字成果、候选、审核与版本入口。此处不显示登记图片、不加载媒体缩略图，也不提供图片导入操作。

新增文字提示词以 kind=prompt 保存，metadata.category=asset。已有 prompt 与 asset 文字记录保持兼容；不因改变界面入口而修改旧记录类型、原文、审核或精确依赖。侧栏资产管理继续负责已有图片原件的导入、低清预览、分类、名称和回收站管理。已经存在的图片不会重新导入、搬移或删除。

创作内容中的资产提示词分类使用创作内容分类排序；侧栏资产管理使用图片资产分类排序，二者不混用。默认文字表单明确标识资产提示词，实际保存仍沿用原候选和审批协议。

## 目录与阅读

左侧目录以章节与简短小节标题为主，避免重复显示“未分章”、长文件名、字数、版本和大段说明。长标题可只在目录标签中提取冒号前的短主题或作省略显示，完整标题仍可查看；这不是修改正文标题。机械文件扩展名及版本后缀只在阅读显示标签中简化，登记名称、导出文件及原文保持不变。

普通内容及同一准确总稿范围中的章节，在右侧连续向下排列。左侧目录保持可见，右侧拥有独立滚动区域；点击章节或小节时只定位右侧内容，不替换整篇DOM或跳动外层页面。滚动时当前章节提示随位置更新，便于定位。

阅读使用打开时固定的准确版本集合。连续显示不创建合并文稿、不写入项目、不改变字数、正文、版本、批准或任务依赖。更新快照中的新候选不得静默替换正在阅读的正文。

审核仍限制在明确候选及其原有批准范围，历史版本切换也不把不同版本混成同一篇。复制、导出、删除和历史入口必须对应准确选中章节；回收站旧版本和正式总稿仍按既有规则保留提示。

搜索、原文查看和字号调整保持可用；安全Markdown与结构化记录继续采用既有渲染规则。跨章节标题锚点须带独立前缀，避免重复标题定位错误。项目切换、关闭阅读或嵌套返回时清理滚动监听，保留与准确阅读会话相符的位置。

## 验证边界

回归使用明确 test_only 合成数据，检查文字/图片入口分离、表单真实提交payload、连续章节完整渲染、目录简化、定位与选中项、搜索/复制/导出、准确审核、回收站和旧版本边界。

独立浏览器中的实际滚动和目视检查与客户端原生看板验收分别报告。正式发行、安装启用、安装副本 stdio 和当前聊天运行版本也分别核对；安装成功不等于已有聊天已重载。



# 1.9.2 项目登记删除

在「项目设置」加入「删除项目登记」。该操作仅移除所选影视项目在本机 catalog 中的登记及其本机保存的聊天、客户端项目关联。源目录、项目数据库、草稿、历史版本、图片、视频及实际客户端聊天保持不变；不调用文件物理删除或云端写入。

删除前显示准确的项目名称和源目录，用户确认后通过 film_projects 的 forget 动作提交。保留唯一 op_id、未决记录、只读结果核对和同请求重试机制。请求绑定 project_id、预期源目录和当前登记时间；目录关联更改或同 ID 重新登记后，拒绝过期确认。源目录当前不可用不妨碍移除其本机登记。

成功后刷新登记列表，并清理被删除项目的旧阅读内容、预览和表单上下文，不自动改写其他项目的聊天绑定。删除当前登记后展示未选择项目状态，用户可自行选择剩余项目。晚到旧快照不能重新打开刚删除的项目。

可通过「关联已有」选择原目录重新登记，接续原文件与历史；此前移除的聊天关联不会批量自动恢复。删除登记不进入文件回收站，不表示删除作品或撤销作品批准。

本轮不调整 schema，不自动扫描、迁移或删除真实项目，不修改八个专业模块。本地安装、独立 stdio 验证、合成浏览器验证和当前聊天运行版本分别报告。

# 1.9.4 Markdown 文件保存

`document.export` 保留只读正文协议：根据准确项目、成果 ID 和版本提供 UTF-8 原文、摘要及 base64，不写文件。新增 `document.save` 用于用户显式导出这一篇，要求 `op_id`、`expected_project_id`、`artifact_id`、精确正整数 `version` 和 `expected_sha256`。拒绝额外字段，不接受任意目标目录或文件名。客户端可通过 `snapshot.capabilities.document_save` 判断当前运行时是否支持真实落盘。

保存位置固定为明确作品根目录中的 `11-导出/Markdown`。文件名保留安全成果 ID、成果 ID 摘要和准确版本，再附原文 SHA-256 前 16 位；不以可编辑展示标题决定路径。导出字节是准确登记正文的 UTF-8 编码，保留原文中的 Markdown、BOM 和换行，不改变正文、候选/批准状态或历史。仅字符串正文可保存；结构化记录沿用只读导出的拒绝规则。

项目登记库通过 `Registry.open_readonly` 打开，不初始化、迁移、写入操作记录或事件，也不改变任何批准。这个接口的写入仅限派生文件。`op_id` 是请求与回执的关联标识，不属于登记库的幂等事务日志；重试结果以准确版本、内容摘要、固定路径和实际文件字节为准。相同请求第一次返回 `status=created`，已存在且字节相同返回 `status=reused`；相同文件有不同字节时拒绝并保留原文件，不覆盖或删除。

逐层检查固定导出目录，拒绝符号链接、Windows 重解析点/目录联接、非目录和路径逃逸。最终文件必须是独立普通文件，不接受符号链接、目录或硬链接。先在经过检查的目录中独占创建随机临时文件，完成写入、flush、fsync 和字节校验，再以禁止覆盖的原子发布方式建立最终文件。失败清理只涉及本次创建并且身份仍匹配的临时文件，不删除既有文件。

最终文件必须实际回读并通过大小与 SHA-256 核对，才返回 `saved_verified=true`、`readback_verified=true`，以及 `project_id`、`project_root`、`export_dir`、`local_path`、`filename`、`artifact_ref`、`sha256`、`size_bytes`、`status`、`op_id`、`registry_changed=false`。回执不包含巨大正文或 base64。若文件已落盘而传输/回执中断，客户端不能推断成功或失败，可保持原请求重试并核对该文件；没有核验回执不能显示保存成功。落盘不等于云端写入或任何创作批准。

目录检查在创建、读回和最终发布边界重复执行，读回同时比较文件身份、大小和修改时间。它拒绝已观察到的链接或替换，防止正常并发导出覆盖文件；没有使用操作系统目录句柄锁定整条路径，因此不作为抵御同权限恶意进程持续并发替换文件系统路径的安全沙箱。回执仅说明核验当时的文件状态，不阻止其他程序随后编辑导出副本。

回归仅在明确合成项目中验证：准确旧版本及混合换行、幂等复用、摘要和身份冲突、不覆盖现存文件、符号链接/重解析点/硬链接、权限与中断错误、并发保存、只读旧 schema 拒绝，以及 CLI 和 MCP stdio 的真实文件回读。真实作品不作为自动回归数据。

# 1.10 效率接口补充

原 snapshot、resume、task.create/checkpoint/submit、artifact.save 的请求及返回保持兼容。新 context.read 只读：summary 返回精确依赖、批准与候选的分开摘要，不带正文或历史检查点；resume 返回当前任务约束、执行兼容状态、精确输入摘要及最新检查点草稿一次；artifact 要求准确 ID 和正整数版本，按需返回完整记录。精简视图不改变执行锁、审批或真实性；旧版本锁不符仍只能只读接续。

task.checkpoint_file 与 artifact.save_file 要求 expected_project_id、source_path（作品根内相对文件路径）、expected_file_sha256 及对应旧动作除 draft/content 外的字段。仅读取普通 UTF-8 文件，保留 BOM 与换行，拒绝绝对路径、父目录、.project 内部路径、链接/重解析点、硬链接、错误摘要或读取中变化；不转换结构化登记/媒体为创作正文。文件操作不修改源文件；来源以 source:{path,sha256,size_bytes} 保留在回执/操作记录，文件检查点亦保留来源，不覆盖用户已有 metadata 来源。

task.submit_checkpoint 要求 task_id、checkpoint_id、expected_draft_sha256、artifact_id、kind、base_version、op_id、expected_project_id，metadata 可选。只提交该任务最新的准确检查点；后端取已持久化完整 draft，仍执行原有任务锁、独占范围、上游新鲜度和基础版本检查。不接受 content 覆盖检查点。新动作的回执不重复完整正文或历史草稿，也不代表审批。

新写动作通过原事务和幂等表执行：原文件/检查点引用参数构成请求摘要，成功重试先命中原结果，再考虑读文件。源文件后续改变或被删除不改变原操作结果；新操作号、版本或输入另行校验。文件读取的路径及身份检查描述读取时状态，不作为同权限恶意进程持续替换目录的操作系统安全沙箱。


## 1.11.0 工作对话与交付证据

film_workspace(action=read/resolve/prepare/record,root,payload) 与 film_delivery(action=read/define/review/complete,root,payload) 使用各模块共享的严格 schema，所有动作要求 expected_project_id；写入沿用 op_id、事务、准确基础修订和幂等缓存。workspace.read/resolve、delivery.read 用只读连接。snapshot 增加 workspace/delivery，精简 context summary 同样带不含正文的状态。正式字段与状态机见 docs/integration-workspace-1.11.0.md、docs/integration-delivery-1.11.0.md。

workspace.prepare 只准备职责槽位，宿主创建前领取并核对现状；重复或未知领取结果不授权再次外部创建。真实ID、排队ID、关联与打开观察分开，记录层不调用宿主或认证其回执。delivery允许保存不完整候选；交付完成须准确版本的覆盖与审查证据闭合，不能以字数、保存成功或作者自证代替审查。评审来自宿主报告，ready仅表示记录的条件满足，不改变批准总稿、旧任务锁或承诺艺术质量。


# 1.15 看板调用边界（覆盖旧版本UI入口描述）

看板仅经film_board_manage明确允许列表查询和管理；所有原业务工具为model-only。不存在看板业务执行、审批、任务发送或ui/message兼容通道。业务工具在工作对话正常使用。新管理action与snapshot.board_library见docs/integration-1.15.0.md；普通管理写settings并沿用事务、op_id和准确身份，正文/采用/依赖不改；导出与预览只写派生文件，schema仍为2。
