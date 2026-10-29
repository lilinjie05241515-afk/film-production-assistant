# 专业方法路由

只读取本轮实际工作对应的完整专业方法及必要参考。已在当前上下文完整读过且版本/摘要不变的方法可复用；方法尚未读过、上下文缺失或版本变化时重新读取。模块清单校验和本表不能代替完整方法。

当前完整内容与来源锁见系统 `modules/manifest.json`。调用 `film_modules(module=当前阶段,workflow_mode=项目已确认路线)`，使用返回的 task_module 创建任务（阶段名不一定是任务模块），按返回的包内入口读取完整方法及相关参考；文件校验不能替代方法阅读或创作审查。

| 工作 | 入口与边界 |
|---|---|
| 灵感探索 | `../../../modules/idea-explorer/SKILL.md`；调用 `film_modules(module="idea")` 获取准确 task_module，完整读取本轮探索、内容或应用、验证及记录参考；本总控不以摘要替代专业方法 |
| 需求与执行规划 | `../../../modules/requirements-planner/SKILL.md`；调用 `film_modules(module="requirements")`，读取完整澄清、领域、方案及存储方法；先读已知信息，方案和执行授权明确后直接推进 |
| 编剧／直接剧本／AI 短剧 | `../../../modules/screenwriter/SKILL.md`；默认直接分场创作，按项目形式、人物行动、对白、节奏与制作条件出稿；底稿可选。单项创作入口为 `$film-screenwriter` |
| 故事／小说 | 上述编剧入口的小说模式，读取模块内完整小说方法；保留叙述声音、原稿保护、Canon 与人物／读者知情约束 |
| 人物小传／大纲 | 编剧按小说或剧本上下文整理，基于实际材料和授权创作；事实、推断与新创作候选分开，人物／大纲不能替代正文 |
| 小说改编分场剧本 | 编剧的改编模式；完整读取指定底本与逐场差异方法，小说内心与原文功能不能因合并而丢失 |
| 导演意见与剧本修订 | 编剧修订方法及[意见登记](screenwriter-workflow.md)；准确剧本和场次、影响判断、完整候选、处理结果和复核分别记录，重大剧情由用户决定 |
| 导演 | 独立入口为 [`$film-director`](../../film-director/SKILL.md)，通过 `film_modules(module="director")` 读取包内 `../../../modules/director-agent/SKILL.md` 完整方法。结合剧本判断镜头、调度、节奏和特效必要性，具体特效方法按需加载；项目外纯文本可直接完成。项目任务、成果和依赖统一登记，不调用旧引擎初始化或另建状态。剧情/对白修订意见交编剧；预演仅按用户制作/修订请求读取包内 previs 规范执行。部门总控与执行话题按[分层会话管理](conversation-management.md)区分，跨职责工作按[归属与转交](request-routing.md)交接。专业接入见 `../../../docs/integration-director.md` |
| 特效 | `../../../modules/vfx-agent/SKILL.md`；剧情触发、形态空间时序、环境反馈、末态 |
| 资产提示词 | `../../../modules/seedance-prompt/SKILL.md`；盘点、三方向设计和选型按请求区分，成果保留 asset 类别 |
| AI 视频提示词 | 先读本技能[视频提示词创作与登记](video-prompts.md)，再加载上述 `seedance-prompt` 的视频模式及 `references/output-format.md`；生成独立完整三段式正文，登记 kind/category/stage=video_prompt，不生成实际视频 |
| 影视研究 | `../../../modules/film-analysis/SKILL.md`；学习卡、报告、独立限制词与证据；研究不能自动采用为项目风格 |
| 美术总监／全剧视觉风格 | `../../../modules/film-art-director/SKILL.md`；`film_modules(module="art_director")` 返回 task_module=art_director，style 路由同模块。按本剧进行视觉定调、设计指导与复核，按需调用影视研究；按[美术交接](art-direction-workflow.md)保存方案与唯一 style_bible 基准，保留导演、表演、声音及世界规则条款。采用剧本新版导致美术待复核时，先判断实际差异，基准内接续完整修订候选和独立采用，不重新定调或自动清除复核 |
| 头脑风暴输入与接入 | 加载同插件的 `$film-brainstorm-interface`，使用只读 `film_brainstorm` 准备精确输入、风格及未知项；当前 interface_only/not_connected/can_generate=false，不执行生成或批准 |
| 独立审查 | 宿主的独立上下文审查者，绑定精确送审版本、原始输入与审查问题；审核通过不等于用户采用 |
| 剪辑与交付 | 本系统登记 take→clip（源入出点）→sequence（时间线位置）→final；先读系统 `../../../docs/剪辑导出.md` 的当前执行范围，再调用本机工具执行。实际渲染结果单独登记，技术通过不等于真人审看、采用或发布 |
| 音乐 | 仅 cue、候选音频、来源权利、实际分轨/工程和对齐登记；音乐创作技能待用户接入，不声称已创作或生成音乐 |

当前有效专业清单为编剧、美术总监、导演、特效、资产／视频提示词、影视分析、灵感探索、需求规划八项。旧小说与改编名称兼容路由到编剧内部模式；完整方法和来源副本保留，原独立技能及旧版本运行环境不变，不能用新模块篡改旧任务执行锁。
