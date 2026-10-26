# 原创剧本兼容入口

1.14 起原创剧本方法由统一编剧维护。使用 film_modules(module="screenwriter") 取得准确入口，完整读取 [编剧](../../../modules/screenwriter/SKILL.md)，再加载其剧本创作与适用 AI 短剧参考。当前文件只保留旧链接兼容，不另维护第二套原创规则。

直接剧本从创意、人物、梗概或已有稿件进入完整分场正文，底稿、大纲和人物资料按需辅助。保存 kind/category=script、metadata.workflow_stage=dynamic_script；可选 source_script 和旧历史保留，不自动改分类。

小说改编和小说创作也从编剧入口进入各自专用模式，不把原著审计套给无原著的原创工作。接续准确任务时仍核验 execution_lock；旧任务使用创建时的运行环境，不因兼容链接而改锁。

导演反馈修订使用 [编剧意见登记](screenwriter-workflow.md)；正文保存、复核、用户采用与按轮云稿分别沿用总控流程。
