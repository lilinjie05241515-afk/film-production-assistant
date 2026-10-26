# AI 视频提示词接入 1.5.0

本版增加独立文字创作板块，不接入视频生成提供方。沿用 12 个 MCP 工具：创建任务、保存候选、审批和版本读取走 film_dispatch/film_snapshot/film_history，Pages 观察走 film_pages_import，云端实际读写由宿主完成。

## 身份与兼容

| 项目 | 约定 |
| --- | --- |
| 展示名称 | AI 视频提示词 |
| kind/category/workflow_stage | video_prompt |
| 任务 module | video_prompt，或已有 seedance-prompt |
| 总稿与 Page 绑定 | 独立 category=video_prompt |
| 旧 prompt | 继续归 asset，不重分类、不迁移历史 |
| 影视路线 | novel_to_screen 与 screenplay 在 asset 后建议 video_prompt |
| 纯小说 | 不强推视频阶段 |

用户可跳阶段，从已有资料创作候选。缺少可选图片或资产不是自动生成假资料的理由，也不必阻止文本锚定足够的任务。阶段开始继续当前聊天，不新建聊天、不批准结果。

## 输入、正文与元数据

先核读当前项目、实际范围、精确通过版本和全剧风格。剧本、导演、特效、人物小传、已采用资产按适用范围参与；来源引用存入 deps/inputs。task.create 使用现有风格冻结规则，上游更新后相关依赖需复核；风格绑定本身不能证明语义一致。

总控技能加载既有 seedance-prompt 视频模式与 output-format.md，交付每次独立生成所需的完整纯正文，可包含多镜头。顺序固定为【风格总控】【场景与角色锚定】【分镜】，每块可独立复制。正文不包含来源清单、版本/哈希、项目参数表、审批状态或操作说明。没有真实图片与绑定就不写 @图片、已上传等声明；文本足够时直接使用文字锚定。

可选 metadata 为 target_platform、target_model、generation_unit、shot，另有已有 chapter/episode/scene/title/order。缺失可省略或 null，不以专业技能默认平台推定用户项目选择；generation_unit 可含多镜头，shot 不强制填写。metadata.workflow_stage 明确为 video_prompt。正文与元数据分别保存，专业技能源文件不改。

## 保存、审批与 Pages

artifact.save/task.submit 保存新候选与精确依赖；expected_project_id、op_id、base_version 继续校验。批准使用原有精确 content.approve，TEST 使用 synthetic=true。候选不覆盖已通过版，历史恢复生成新候选；video_prompt 总稿与 asset 总稿相互独立。

完整 Pages 观察使用 category=video_prompt，按真实 Page 身份导入独立 cloud_working_draft 来源快照。不能把导入结果直接算作已批准提示词。master.bind_page 使用 video_prompt 类别；sync.intent 指定对应 master_category/master_version 和完全相同总稿正文。宿主执行云端编辑并完整读回 sync.observe；未知结果先核查，失败不撤销本地批准。协议详见 [Pages 宿主协作](integration-pages.md)。

导出保留独立分类与完整正文。film_export 的 video_prompt_texts 返回每个精确单元的 artifact_id、version、path、relative_path、status、sha256；UTF-8 TXT 只含该单元纯正文，不把组装总稿冒称可单独提交的生成单元。status 区分当前通过、需复核、候选和历史身份，不能用导出动作替代审批。只有正文提示词已经形成，不能说素材已上传、视频已经生成或成片已经通过。

## 发布核验边界

1.5.0 构建复制新总控技能及其 video-prompts.md；独立脑暴接口技能仍为 1.4.0 内容版本。发行 runtime 随包冻结，源代码与安装缓存分开核对；专业技能保留原哈希。新增 MCP 回归验证独立提示词候选/批准总稿、风格冻结、旧 prompt 分类及 Pages 边界。

构建和安装仅在源冻结后执行。独立 stdio 通过、插件安装成功、当前聊天实际 film_health、原生界面可见与点击各自报告，不把任一层代替另一层。安装旧缓存清理的防护见 [客户端接入](integration.md)。
