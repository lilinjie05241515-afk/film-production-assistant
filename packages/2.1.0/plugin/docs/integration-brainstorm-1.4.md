> 版本专题与兼容记录。接口细节按当前工具定义核对；旧版看板按钮、当时开发目录和执行安排只用于追溯。当前操作职责见 [现行规则](current-rules.md)，兼容边界见 [兼容说明](compatibility.md)。

# 1.4 头脑风暴接口接入

本版交付可发现的 `$film-brainstorm-interface` 技能和可调用的 `film_brainstorm` 工具。它们完成真实的只读输入准备与开发交接，尚无生成提供方：`interface_only / not_connected / can_generate=false`。它不是付费模型入口，不执行创意生成，也不建立新聊天。

## 用户流程与真实能力

用户先明确项目与讨论问题，再选择精确内容版本；已通过、候选、历史通过及需复核内容保持原标签。默认不接受候选上下文；用户明确选择后才开启 allow_candidate_context。未知范围、主底本、限制与必保项保持 null，未选内容为 []。接口仅附带当前有效已通过风格；风格缺失或需复核仍显示缺口。

准备完成后显示“输入已准备，生成提供方尚未接入”，并可查看完整上下文、版本和哈希。该结果没有 candidate_output；不能显示已生成方向、自动采用、已批准或已写回总稿。普通创作讨论仍由宿主按用户要求进行，不能冒称由本接口的提供方生成。

## 工具契约

`film_brainstorm {action:"interface"}` 无需 root，返回当前能力和完整 JSON Schema。`film_brainstorm {action:"prepare",root,payload}` 的 payload 必填 expected_project_id、topic；可带 scope、context_refs、base_ref、must_keep、constraints、allow_candidate_context。base_ref 必须是已选择 context_refs 中的一个精确引用；未指定为 null。详情与字段语义见插件技能 [接口约定](../skills/film-brainstorm-interface/references/interface-contract.md)。

工具 annotations.readOnlyHint=true。prepare 在打开 Registry 前核验磁盘项目身份及 catalog 已登记身份，随后用 SQLite mode=ro 与 query_only 读取一致快照；不存在的项目不创建，schema 1 不迁移。兼容的 film_dispatch brainstorm.interface/prepare 也转入此只读路径。无 op_id、写入日志、任务、成果、决定、云写入或生成事件，面板不得把它加入 WriteJournal。

返回包含 contexts 的完整正文/sha256/精确版本/状态、global_style、approved_style、unknown_inputs，以及未来 candidate_output_schema；当前 generation_performed=false、candidate_output=null。候选输出 schema 是提供方未来应满足的契约，不是生成产物或保证。

## 技能发布与检查

build.py 将总控技能与新接口技能分别复制到 plugin/skills，并打包当前 filmprod/brainstorm.py。个人总控入口继续同步；新增接口技能通过插件安装，避免另放一份个人同名技能形成版本歧义。六个专业技能源入口保持不变。

验证分别记录技能结构校验、MCP 子进程只读回归、安装文件哈希、独立 app-server 的技能发现与目标聊天真实工具加载。独立进程发现技能不证明现有聊天已热加载；旧聊天版本以其真实 film_health 为准。没有实际原生渲染和点击时，不声明视觉或操作验收。禁止以 HTTP 或 file URL 绕过宿主的浏览器限制。

## 后续生成实现

后续提供方需单独实现和验证实际生成调用、来源绑定、成本与失败语义，再明确更新能力声明。输出仍为候选，保留假设、未知、精确 source_refs；用户选择、保存候选、批准和 Pages 同步继续走现有授权与版本流程。当前版本不接外部模型，不实现音乐生成，不以界面按钮替代实际能力。
