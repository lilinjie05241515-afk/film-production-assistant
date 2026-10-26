# 任务输入包（内容模板，实际登记使用当前 JSON Schema）

- project_id / task_id / role / scope：填写。
- project_root / entry / expected_revision：填写实际目录与登记修订。
- read_scope / write_scope：列获准相对路径与只读输入根。
- input_manifest：逐项记录 ID、版本、SHA-256、实际路径、场次范围、核读范围、权利/用途、缺失影响。
- frozen_constraints：locked / director_open / proposal_required / intentionally_ambiguous。
- applicable_decisions：真实来源、目标版本/hash、原话与批准范围；没有则 none。
- goals：观众信息、关系变化、场次结果、表现重点。
- conditions：画幅、时长、预算、工具、现有资产；未知 null，不冒充用户要求。
- dependencies：上游与下游稳定 ID、版本、状态及原因。
- deliverables：六组或明确局部范围；每组路径与完成条件。
- status / freshness_status：独立填写。
- checkpoint：当前已保存位置及引用草稿。
- assumptions / open_questions / risks / next_action：逐项填写。
- execution_source：host_model / deterministic_tool / fixture / mock / human 等实际来源；测试样本 is_sample=true。
- saved_at / readback_evidence：实际时间及校验结果。

提交前转换到当前正式 Schema；不要将本说明模板直接作为已冻结、已保存或已完成的证据。
