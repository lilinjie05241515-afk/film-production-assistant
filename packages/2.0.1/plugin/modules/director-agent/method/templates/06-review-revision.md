# 审核与修订记录 — 版本

文档头：project_id / task_id / artifact_id / version / script_refs+sha256 / is_sample / source_type / lifecycle / freshness_status / review_status / user_decision / media_evidence_status / 结构源、hash、修订入口。

## 审核对象与边界

submission_id、被审 artifact_id/version/hash、rubric_version、batch_id：填写。尚未发生审核写 not_requested，不能填造评委。

requested_level / achieved_level：填写 L1/L2/L3 或 unverified；隔离测试、实际可见范围、共享访问风险：填写。评委运行来源、独立上下文证据、原报告位置与 hash：逐人记录。文本/结构/媒体核读范围分别记录。

## 问题与原报告引用

| finding_id | 位置 | 严重度 | 问题/影响 | 具体证据 | 建议 | 置信/待核 | 原报告 |
| --- | --- | --- | --- | --- | --- | --- | --- |

评分：引用原报告八维评分、unknown 与依据；完整有效时才计算加权分。文本通过依据：必需交付、阻断项、维度门槛、重大分歧、媒体待核。

涉及具体拍法选择时，另记 [shot-choice-v1](../skills/director-orchestrator/references/shot-choice-evaluation.md) 的适用项、具体证据与 supported/needs_revision/inconclusive/not_applicable。局部结果不换算整片分数；条件变化检查不改冻结剧本，未看片的来源不记为媒体已验。

## 创作者处置（不得改原报告）

| finding_id | 采纳/部分采纳/不采纳/待用户 | 理由与影响 | 修订新版本/hash | 复核依据 | 残留问题 |
| --- | --- | --- | --- | --- | --- |

本次自动修订轮数：0/1/2；累计范围与上一版引用：填写。超过两轮不循环，用具体选项交用户取舍。新版本审核和用户决定不继承旧版。

## 用户决定与剩余工作

真实原话、source_ref、可核实作者/时间、target_id/version/hash、决定类别、本地回收状态：没有则写 none/pending。测试事件标 synthetic。待生成/待媒体验证/待云联调/待用户取舍逐项列清。
