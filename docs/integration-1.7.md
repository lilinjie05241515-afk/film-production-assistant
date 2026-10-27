> 版本专题与兼容记录。接口细节按当前工具定义核对；旧版看板按钮、当时开发目录和执行安排只用于追溯。当前操作职责见 [现行规则](current-rules.md)，兼容边界见 [兼容说明](compatibility.md)。

# 1.7.1 灵感与需求接入

本版在原有六专业模块之外加入完整 `idea-explorer` 和 `requirements-planner`。`film_modules(module="idea")` 与 `film_modules(module="requirements")` 分别解析到实际模块，并返回用于任务的 `task_module`。总控读取模块完整入口及适用参考，不以路由表摘要代替专业方法。系统版本、模块内容版本与任务冻结锁仍独立核验。

看板新增“灵感与需求”入口，包含两个独立可选阶段卡。所有路线和 unset 状态都可使用，未绑定作品时也可以向当前宿主聊天发出讨论请求；不会因此建立影视项目、选择路线、创建新聊天或启动后续制作。两阶段互不强制前置：已有明确需求可以直接规划，方案与执行授权均明确时直接进入已授权执行。用户仅登记、暂时搁置或未安排下一步时可以完整结束。

## 记录与候选

项目内原始讨论、分支、决定和授权统一进入 Registry：

- `planning.record {op_id, expected_project_id, record_id, scope, base_version, change, deps?}`。首建的 `change` 为 `{record_kind: "idea"|"requirements", title, state?, entries?}`；`record_kind` 不在顶层。更新支持 `title/set/append/item_updates/branch_updates/entries`。
- `planning.read {record_id, version?, since_version?, limit?}` 只读返回完整状态与原始 entries、精确 `artifact_ref` 和有界变化。
- 保存结果中的 `saved/readback_verified/record/version/artifact_ref/project_root` 与真实读回共同构成保存证据。原话保留实际来源；授权必须有准确 scope 和 source.quote。缺失事实保持未知。

`planning_record` 不允许普通 artifact.save/approve；看板只显示 `planning_records` 摘要并提供专用只读入口，不纳入待审候选统计，也不提供通用编辑或历史恢复按钮。需要可审核方案时，通过准确模块的 `task.submit` 形成独立 kind/category/stage=idea 或 requirements 候选。内容采用与执行授权分别判断。

未立项内容不自动进入影视 Registry。完整模块脚本保留用于用户明确的外库，强制 `--root` 并拒绝安装树及影视项目父链；项目内拒绝使用它产生第二套状态。`promote` 被禁用。授权跨库关联由宿主分别保存精确引用并读回，保留原支；不能宣称原子迁移，遇到一侧结果未知先核查。

跨库选入先在外库执行 verify/show 指定版本；目标记录使用带 source.type/reference 的 frozen_selection entry。selection 必须保留 store_id、record_id、version、head_hash、branch_id、transfer_id、history_coverage、attachment_coverage 及完整 snapshot。快照身份与哈希、分支须匹配；仅取得快照不声明 complete_events，附件仅引用不声明 copied_verified。源历史授权不升级为当前授权。同一 transfer_id 的目标 op_id 和源 request-id 固定，源反链失败保持部分状态；本地 planning.record 读回不能冒充外库核验。

详细操作例与交接边界见 `skills/film-production-agent/references/planning-workflow.md`，字段约束以当前 CONTRACT 及专业模块记录实现为准。

## 与脑暴接口的关系

当前宿主加载 idea-explorer 后可以进行创意碰撞；这与外部提供方接口不同。`film_brainstorm` 保持只读 `interface_only/not_connected/can_generate=false`，不因新增方法而连接生成服务，也不会保存候选或批准内容。看板保留“脑暴接口”单独入口，并指向“灵感与需求”用于实际宿主讨论。

## 界面请求与验证

阶段按钮仅发 `ui/message` 给当前聊天，请求包含具体阶段、明确项目身份（如有）、精确输入、完整方法读取、记录真源和授权边界；不直接写规划记录、创建任务或作品。完整记录读取调用 `film_dispatch planning.read`，冻结打开时的项目 ID、root 和版本，planning.read 的 payload 带 expected_project_id，由后端拒绝同路径换成另一作品；异步返回后再次核查项目身份，切项目或切模块的迟到结果不显示。

`tests/test_planning170.cjs` 使用模拟宿主验证真实面板 JavaScript 的渲染、请求与防误编辑行为。此类协议及界面代码测试不代替原生面板可视验收、模型创意质量、真实账号动作或异机安装验收。


## 1.7.1 补丁与回退范围

声明 `complete_events` 的来源必须带第 1 版至冻结版本的完整连续事件，逐条匹配来源库和记录身份、schema、版本、唯一请求号、内容摘要及 prev_hash 链，最终摘要等于冻结 head_hash。只提供末条、缺前缀、改动内容或身份均拒绝。该结构和哈希验证不能代替宿主读取实际来源并确认用户授权。

Windows 安装器按解析后的实际路径比较旧配置、数据和登记库位置；同一位置的系统路径别名可以归一化，真正换目录仍拒绝。只归一化安装状态，不改写现有 user.json、不搬迁数据。

数据 schema 仍为 2，不代表 1.6.0 能理解新增的 planning_record。已写入 1.7 记录的作品应继续使用 1.7，或使用升级时明确列入的作品快照配合程序一起回退。只回程序且保留新记录不能声称与 1.6 兼容。空作品清单只覆盖程序、配置和登记库；未列入的作品不扫描、不恢复、不宣称已验证兼容。
