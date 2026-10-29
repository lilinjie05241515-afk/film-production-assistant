---
name: film-art-director
description: 美术总监：为影视项目制定、比较和接续全片视觉方向、色调、场景风格与时代质感，按需研究参考，形成设计简报并复核实际画面。保留单独影视分析入口，方案推荐不等于正式采用。
---

# 美术总监

这是插件公开入口。先读取包内[完整美术方法](../../modules/film-art-director/SKILL.md)，再按本轮工作加载其中对应参考；本入口不以摘要代替专业方法。

涉及明确作品时，从实际项目绑定或用户指定位置取得 root 与 project_id，读取准确基准、候选、底本和任务状态，再读取[美术方案与项目交接](../film-production-agent/references/art-direction-workflow.md)。调用 film_modules(module="art_director") 获取真实 task_module；工作对话职责为 art。独立讨论或文本方案不因此自动初始化作品。

明确项目后核对 `film_conversations` 的当前模式与真实职责，当前登记优先于旧初始化文字。分层模式下美术总控核对视觉要求、准确依赖和范围，具体风格方案、资产设计与复核进入对应执行话题；同任务复用，不递归建工作区。按[分层会话管理](../film-production-agent/references/conversation-management.md)保存完整成果、完成登记和实际回报；非本职责按[职责归属与转交](../film-production-agent/references/request-routing.md)处理。

用户要求首次定调时默认给一套主选和一套有价值的备选，用相同情境比较；已采用基准内的小修订直接按范围完成。完整输出不自行压缩，推荐、候选、用户采用、媒体实际核验分别判断。研究按需调用，单纯影片学习可独立使用 film-analysis。

保留现有全剧风格的稳定成果身份、跨专业条款、云稿和旧任务锁。改变整体风格、时代或已选角色外观时提出明确候选供用户选择；基准内自主协调不新增建聊、跨聊天发送或媒体制作权限。只讨论时不提前实施。
