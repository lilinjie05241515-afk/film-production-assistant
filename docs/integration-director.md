> 版本专题与兼容记录。接口细节按当前工具定义核对；旧版看板按钮、当时开发目录和执行安排只用于追溯。当前操作职责见 [现行规则](current-rules.md)，兼容边界见 [兼容说明](compatibility.md)。

# 包内导演方法接入 1.6.0

通过 `film_modules(module="director")` 解析 `modules/director-agent/SKILL.md`，再按当前任务读取完整的方法、模板和 schema。来源、逐文件原始与适配哈希、模块内容摘要见 `modules/manifest.json`。所有参考相对模块目录解析；专业源工程保持原样，包内不包含作品或数据库。

方法覆盖导演调度、构图、镜头选择、表演、声音、类型与形式、动作环境反馈、输出清晰度及交接审查。阶段创作使用当前宿主模型与完整专业方法。旧 prepare/deliver/状态命令仅是原引擎适配，不执行；统一使用当前 Registry 的 task.create/checkpoint/submit、精确版本依赖和明确用户批准，不再初始化第二套项目状态。详情见模块的 MODULE_INTEGRATION.md。
