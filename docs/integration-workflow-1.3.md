> 版本专题与兼容记录。接口细节按当前工具定义核对；旧版看板按钮、当时开发目录和执行安排只用于追溯。当前操作职责见 [现行规则](current-rules.md)，兼容边界见 [兼容说明](compatibility.md)。

# 长篇创作与风格接入 1.3.0

1.3 增加显式创作路线、人物小传、独立剧本底稿、全剧风格及长篇章节/分集阅读。沿用既有 schema 2、审批、历史、目录映射和宿主 Pages 边界；不自动升级旧内容语义，不触碰其他项目。

## 路线和阶段启动

project.workflow.set 使用 op_id、expected_project_id、base_revision、mode 和可选 outline_order。mode 为 novel_only/novel_to_screen/screenplay；outline_order 为 before_novel/after_novel。默认没有路线，snapshot.workflow 明确 unset。它是用户选择和建议状态，不是生成引擎，也不意味着某阶段已完成。

小说转影视包含大纲正式阶段：默认小说→研究与全剧风格→大纲→人物小传→动态剧本→导演→特效→资产；也可先大纲，再小说、风格及后续。纯小说与直接剧本的大纲可选，纯小说可停。直接剧本建议底稿→影视研究与全剧风格→人物小传→动态剧本→导演→特效→资产，不需要虚构小说；缺少已通过风格时可做候选并提示缺口，不强制阻塞。用户可以跳阶段或只完成指定部分，宿主说明真实缺失输入。

面板启动阶段通过 ui/message 发出用户明确点击的当前聊天请求，包含实际项目身份与阶段。宿主读回项目后创作；该点击不调用 create_thread，不向其他聊天发消息，不通过任何候选。已有研究对话的明确创建入口仍按用户另行授权执行，不能混同阶段启动。

依赖建议依据当前路线区分所需来源和可选资料：直接剧本不把不存在的小说提示为缺口，可选大纲未出现时不制造待办。已有可选候选或需复核条目可以提示，但分别列 candidate_refs/review_refs；只有已通过且无需复核的版本进入 refs。候选标签不能作为正式输入可用证明。

## 内容身份

| 内容 | kind / category | 阶段与兼容 |
| --- | --- | --- |
| 人物小传 | character_bio / character_bio | 与 novel 分开；旧 character 继续原 outline 映射 |
| 剧本底稿 | source_script / source_script | 独立总稿，可与 script 同 scope |
| 动态剧本 | script / script | metadata.workflow_stage=dynamic_script |
| 全剧风格 | style_bible / style | scope=project/style；research 不自动转入 |

旧 script 没有 workflow_stage 时为 unclassified；旧 script 标注 source_script 也不自动迁移 category。不修改历史来满足新界面。每一章、集、场次保留稳定 ID、scope、完整正文和版本；顺序使用实际 metadata.order 或自然范围顺序，不为了分页重编号。

旧 character 没有声明阶段时，workflow.unclassified 标记 legacy_character_stage_not_declared；原 outline 分类、通过指针和总稿不变，不自动计为大纲或人物小传阶段的成果。

阅读器以 metadata.chapter/episode/scene 的字符串或对象（id/title 等）生成目录标签，全缺则未分章。整稿明确 ATX Markdown 标题可作只读目录锚点，忽略代码块中的标题；这不会切段、改 scope 或创建新版本。阅读区提供正文宽屏、跨段前后、目录/正文搜索高亮、非空白字数及字号；历史、候选和总稿沿用同一布局，总稿导航使用自身精确 segments 元数据。

## 全剧风格与精确依赖

影视研究保存 research 候选，随后提炼 style_bible 候选。用户确认精确版本/范围后调用同一 content.approve。风格内容涵盖视觉与质感光色、镜头节奏、表演对白、世界物理与特效边界、资产造型原则、参考来源与使用范围；缺失未知，不能把单一参考的所有内容继承为全剧约束。

snapshot.workflow.global_style 与顶层 global_style 提供 status、approved_ref、pending_refs、scope 和 semantic_compliance。status 可为 missing/candidate/approved/needs_review；semantic_compliance 固定 not_assessed，不能把版本通过等同于下游作品已符合风格。

适用下游任务自动冻结已通过风格精确引用；显式旧引用与当前通过版冲突时拒绝。尚无风格允许候选创作并登记 missing_context。宿主交接和审查仍必须逐项核对语义、参考使用范围及本次例外。新风格候选不使正式下游失效；新风格批准后相关依赖需复核，改写后再次形成候选。资产提示词综合全部实际适用已确认的小说/底稿、人物、动态剧本、风格、导演和特效版本。

当前内容视图的顶层 style_context 表示此刻绑定缺口；metadata.style_context 保留版本保存时状态，读取不会修改历史。两者都不代替风格语义审查。

## 发布与验证

系统版本为 1.3.0，六个原专业技能不改。plugin/build.py 打包新的 runtime 文件和 creation-workflow.md；新版本使用独立 cache 路径，避免覆盖正在加载的 1.2.1。安装前保留旧完整缓存 ZIP、逐成员哈希及源码基线，旧交付与历史报告不覆盖。

构建、安装登记、目标聊天工具版本、原生长篇阅读/阶段点击和真实创作分别核验。协议通过不等于新看板已在既有聊天重载；本机 Codex 验证不等于 Work 或纯云访问已验证。当前报告按 reports/1.3.0 保存，旧 1.2 报告仍是其当时证据。
