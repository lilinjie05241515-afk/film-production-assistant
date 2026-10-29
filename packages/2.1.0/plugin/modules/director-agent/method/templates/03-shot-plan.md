# 镜头方案 — 版本

文档头：project_id / task_id / artifact_id / version / script_refs+sha256 / is_sample / source_type / lifecycle / freshness_status / review_status / user_decision / media_evidence_status / 结构源、hash、修订入口。

每个镜头重复以下记录。shot_id 是稳定身份，order_index 是本版顺序。镜头数与时长按需要选择，未知时长和焦距为 null。

- shot_id / scene_id / beat_id / order_index / script_refs：填写。
- purpose：这个观看位置让观众获得、遗漏或重新理解什么。
- performance：人物 objective、action、reaction、adjustment。
- blocking：start_state、trajectory、end_state；含视线、遮挡、关键物。
- camera：size、composition、position、movement、lens_equivalent_mm（可 null）。
- light_art：光源/方向、环境/服化/材料/色彩与当前动作的关系。
- timing：estimated_seconds（可 null）、start_trigger、end_trigger。
- editing：cut_reason、下一镜连接、保留/省略的信息。
- sound：声源 cues、perspective、空间与对白/音乐层级。
- dependencies：具体 ID/版本/hash 与必要起止状态。
- continuity：人物/道具/知情/视听进出状态；有意越轴或省略的理解条件。
- production：风险、可生成单元、替代、人工工序。
- media_evidence_status：not_generated / not_viewed / partially_viewed / verified / failed，附实际证据；不可按文本效果推断。

## 逐镜内容核对表

下表用于设计和专业审校；按当前结构字段保存或作为有来源的附属记录，不代表新增 Schema 必填项。未知或不适用说明原因。

| 角色 | 起点/朝向/视线 | 画面位置/主次 | 动作顺序/接触 | 反应/调整 | 终点/切点状态 |
| --- | --- | --- | --- | --- | --- |

| 资产 | 原文事实/导演候选 | 本镜位置与状态 | 出现/变化时机 | 必须可见/背景/仅连续性/禁止显露 | 下镜保持条件 |
| --- | --- | --- | --- | --- | --- |

镜头选择理由：为何采用此景别、观看方向、运动或静止；这一镜让观众获得什么。明确左右的参照；整场规则分配到对应镜头，承接前镜末态不要求重演。声音按本镜实际分配的对白和声源发生时机填写。

关键手法写清触发和停止/切点、观众此刻能看到和听到什么、必要过程会不会被遮挡或时间效果抹去。区分运动/变焦/拉焦/曝光模糊/帧率/剪辑，目标外观与下游实现条件分开；见 [手法条件库](../skills/director-orchestrator/references/shot-techniques.md)。具体引用和比较另存依据；气氛与感官节律可作为 purpose，不强求每镜新增剧情。

关系戏加核：本镜关注发起者、听者、共同关系还是旁观者，依据哪个动作或信息变化；被强调的反应是否擅自确定了原文未知动机。拍法不必随每句台词切换。案例名称和比较留在附属依据，具体选择及作用写入 purpose / performance / editing 等已有字段。

其他类型按需加核：喜剧的信息与反应谁先；悬疑的物件可见到什么程度；动作的接触、受力和终态；恐怖的可见区与声源归属；世界规则的触发及解除；蒙太奇/闪回的时间关系；纪录/产品的素材和事实依据；画幅中的动作、人物与文字能否同时读清。只记录实际影响本镜的条件，详见 [类型与形式路由](../skills/director-orchestrator/references/genre-routing.md)；这些检查沿用已有字段和附属工作记录。

完成后检查镜头目的、跨镜状态及 JSON/Markdown 同源一致性。封存后重排或改意图均生成新版本，旧身份与报告保留。

动作与环境变化按需参照 [关键节拍拍摄卡](action-beat-card.md)：动作强调点、身体反馈、特写的进入/退出、环境前中后状态和剩余功能，分别写入上述已有语义。简单动作可直接在镜头正文说明，无须生成空表或增加新 Schema 字段。
