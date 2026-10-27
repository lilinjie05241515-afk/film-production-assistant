# 制作接口 — 版本

文档头：project_id / task_id / artifact_id / version / script_refs+sha256 / is_sample / source_type / lifecycle / freshness_status / review_status / user_decision / media_evidence_status / 结构源、hash、修订入口。

## 制作单元（逐 unit_id 填写）

- unit_id / scene_id / shot_ids / script_refs：填写，shot_ids 为镜头 ID 列表。
- director_purpose：原导演目的与依据。
- start_state / action_chain / end_state：可检验状态和因果链。
- camera_composition：机位、构图、运动及可见/遮挡条件。
- asset_refs：资产 ID、版本、hash、权利/用途、实际核读范围、验证状态。
- locked_conditions / allowed_variations：不变条件与变动余地。
- duration_range_seconds：最小/最大值列表，未知分量为 null，注明估计来源与未决条件。
- sound_cues / editing_connections：声音工序及镜头连接。
- risks / fallback / human_tasks：风险触发、保留意图的替代与待人工事项。
- dependencies：可生成前必须满足的精确条件。

## 独立工序

| 工序 | 输入依赖 | 输出 | 保持条件 | 当前证据 | 待人工/工具能力 |
| --- | --- | --- | --- | --- | --- |
| 画面 | | | | not_generated | |
| 对白/声音 | | | | not_generated | |
| 剪辑/合成/调色 | | | | not_generated | |

## 交给提示词执行 Agent

入口为指定版本的 `execution-agent-brief.md`。附冻结剧本、导演主方案、逐镜卡及技术包、逐字对白和来源清单。标明哪些是必须保持的导演条件、哪些允许平台适配、哪些缺项需要先返回导演补齐。用户采用状态照实记录。

## 平台适配（由执行 Agent 在选定平台后填写）

adapter_id/version：填写或 unknown。能力来源、日期与实际验证：填写。支持/不支持/未知字段：分开。派生提示词/参数：填写。转换损失、人工补偿与原导演引用：填写。适配不能修改 locked，不预设 API key、时长上限或参数。

导演交付时允许此节保持未配置，不据此判定导演任务未完成。具体平台提示词与生成结果不由此模板伪造。
