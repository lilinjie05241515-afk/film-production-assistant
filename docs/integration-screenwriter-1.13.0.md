# 编剧 1.0.0 与影视总控 1.14.0 接入

编剧是八项有效专业模块之一，以 AI 短剧直接创作为默认方向，统一原创、小说改编、可选小说和修订方法。可发现技能入口为 `skills/film-screenwriter/SKILL.md`；实际内容位于 `modules/screenwriter/`。原小说、改编方法完整保留在其 methods 子目录，按需读取。模块内容版本与系统版本分别锁定。

接口文件名保留开发期编号以兼容既有链接，当前行为属于正式合并版本 1.14.0。编剧与美术的分工和接续见[编剧总览](integration-screenwriter-overview-1.14.0.md)，美术方案契约见[美术接口](integration-art-1.13.0.md)。

## 路由与数据

总控 `film_modules` 解析当前编剧与兼容名称，返回真实 task_module；调用者使用返回值，不猜任务枚举。三个项目路线仍保留，旧项目不根据升级隐式改路线。新直接剧本可以直接保存 script + metadata.workflow_stage=dynamic_script，source_script 是可选底稿，旧分类、总稿和任务历史保持。

完整正文继续经过既有 task/checkpoint/submit 或文件保存；同一成果形成新候选，候选不覆盖通过指针。旧任务按旧 execution_lock 恢复，新方法不改旧锁。云稿继续使用 1.12 的完整读回、保留手改、按轮同步与未决恢复机制。本次没有新增实时双向同步、生成媒体或自动发送聊天。

## film_screenwriting

专用工具形状为 `{root,action,payload}`；action 为 read、record、resolve。`film_dispatch` 也可使用 screenwriting.read、screenwriting.record、screenwriting.resolve。此记录层不生成或修改正文，不自动批准，不调用云端。

### 读取

read payload：

```json
{"expected_project_id":"实际项目身份","artifact_id":"可选准确成果身份","feedback_id":"可选准确意见身份"}
```

返回当前 revision 和 feedbacks，写前读取。不要将 revision 与成果 version 或云端修订号混用。

### 登记意见

所有写入均需 op_id、expected_project_id、base_revision。record 另外需要：

| 字段 | 含义 |
| --- | --- |
| feedback_id | 本条意见的稳定身份 |
| script | `{artifact_id,version,sha256}`，本项目准确完整剧本 |
| scope | 与 script 成果范围相同 |
| scene_id | 被指向场次，须由宿主核对实际正文 |
| anchor | 剧本内准确非空原句 |
| problem / expected_effect | 问题与希望产生的效果 |
| must_keep | 必须保留项字符串数组 |
| impact | staging / expression / structure / major |
| source | `{role:director|user|review,reference:string}`，真实来源 |
| suggestion | 可选建议手法，编剧可以提供更合适方案 |

major 初始状态 needs_user_choice，其他 open。分类依内容实际影响，客户端填写 impact 不证明语义判断正确。准确 anchor 可检查文字存在，但不能独自证明 scene_id 或意见理解正确；宿主仍须读正文。

### 记录处理

resolve 除公共写字段外需要 feedback_id、status、response。status 为 addressed、partially_addressed、deferred、declined、needs_user_choice。

涉及 expression、structure、major 的 addressed/partially_addressed，必须提供 revised_script 准确引用，指向同成果 ID、更高且当前最新的已保存剧本版本。staging 只调整拍法时不强制新剧本。保存完整稿件与记录意见处理是分别执行的操作，任何一步未完成都不能称闭环完成。

重大修改的上述处理还需 user_decision：

```json
{
  "source":"conversation",
  "reference":"真实选择来源",
  "quote":"真实用户原话",
  "scope":"与本条意见相符的范围",
  "feedback_id":"本条准确意见身份",
  "script":{"artifact_id":"原意见成果","version":1,"sha256":"实际摘要"},
  "actor":"human",
  "synthetic":false
}
```

source 也可为 panel。例中数值是字段示意，不是作品或授权。不得把例子直接提交；测试用独立 test_only 作品且 synthetic=true。普通导演建议不能代替 user_decision；用户明确要求比较版但没有选择实施时，保留需要选择及候选身份。结构性修改也必须遵守用户已约定范围；程序只对已声明的重大级别做必要字段检查，不能取代语义审查。

## 并发、接续和证据

同操作原 op_id 与完整原 payload 重试；不同请求不能借同号覆盖。base_revision 冲突先重读。旧意见 script 冻结，read/snapshot 的 source_changed 提示当前源已变，需要重新判断影响，不静默改绑。

流程为准确旧剧本 → 意见记录 → 完整新剧本候选 → 处理与复核 → 用户选择 → 下游接续。每次引用准确版本，禁止依靠互相追随的“最新”引用无限触发返修。修改主剧本只有一个编辑者；导演对白继续逐字来自其冻结剧本。

候选保存、意见 addressed、质量复核、云稿同步、用户采用及实际视频效果是不同证据。开发测试使用合成作品；本说明不证明任一真实作品、云稿或媒体已被修改。
