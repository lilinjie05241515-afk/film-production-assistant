# Blender 预演执行与审看

仅在用户要求制作或修订预演时执行。只有剧情时，由导演给出若干有区别的拍法并等待用户选择；已有明确分镜时把准确拍法转换为计划，直接执行已授权部分。禁止把刷新、看板浏览、保存问题或打开工作对话作为渲染授权。使用当前包内执行器，不启动旧个人导演引擎。

## 从导演方案到几何

先读准确 Registry task、冻结 script 引用及本轮 director 引用。剧本事件、对白、角色身份与导演允许的变化保持对应。场景参考图登记项目内原件与 SHA-256；在 `space` 分别填写 `visible_structure`（可见结构）、`assumed_dimensions`（推定尺度）、`unseen_areas`（图外未知）、`allowed_adjustments`（获准调整）。不可从一张图宣称精确重建。只有影响走位、机位和遮挡的结构才需建模。

坐标以米为计划单位，Z 向上，角色正面为本地 +Y，yaw 为绕 Z 的角度。角色 id/颜色在全场和修订版本固定；地面方向条和白色面部标记表示朝向。每个角色只有一条覆盖全段的轨迹，镜头不会重新初始化人物。用重复位置关键帧表达停顿。运动线性插值，转身取最短角；动作表现仅到空间判断所需。

计划为 JSON：`schema_version:1, fps, frames, width, height, reference_image:{path,sha256}, space:{上述四字段,boxes:[{id,position:[x,y,z],size:[x,y,z]}]}, actors:[{id,name,color:'#rrggbb',keys:[{frame,position:[x,y,z],yaw}]}], shots:[{id,start,end,method,lens,camera:[{frame,position:[x,y,z],target:[x,y,z]}]}]`。

所有帧范围是从 0 开始的半开区间 `[start,end)`；每条轨迹含结束边界关键帧。镜头必须覆盖整段且无重叠/间隙。稳定镜头编号例如 S01_SH010，不用列表位置替代。焦距单位 mm，摄影机关键帧应体现导演给出的景别、角度、移动起止、观察目标与切点。画幅先用 640×360/12 fps 做可审看白模，按任务提高。普通视频 seek 不是逐帧工具。

## 明确执行

先用 CLI 核实 Blender、FFmpeg、FFprobe；不猜路径。执行器不联网，也不自动登记或选择成果：

```powershell
python -X utf8 <本模块>/previs/execute.py --plan <准确计划.json> --out <项目目录/02-导演方案/预演/范围/v001> --blender <已核实的blender.exe>
```

macOS 使用本机已核实的应用内可执行文件，例如 `/Applications/Blender.app/Contents/MacOS/Blender`，不是 `.app` 目录本身；路径含空格时加引号。以下示例中的计划和输出须替换为准确项目范围：

```sh
python3 -X utf8 /path/to/previs/execute.py --plan "/path/to/plan.json" --out "/path/to/new-v001" --blender "/Applications/Blender.app/Contents/MacOS/Blender"
```

`--ffmpeg` 和 `--ffprobe` 可传入准确可执行文件路径。省略时优先查 PATH；macOS 还检查 Apple Silicon 与 Intel 的 Homebrew `ffmpeg-full` 及标准 `bin` 目录，兼容从 Finder 启动时的精简 PATH。显式错误路径或缺少工具会在新建输出、启动 Blender 前停止，不会换用其他程序；不会自动安装依赖或修改环境变量。

默认 `--engine WORKBENCH` 使用 Blender 白模显示引擎，需要可用的图形环境。没有可用 GPU 的 Mac 或其他运行环境可明确使用 `--engine CYCLES`，执行低采样 CPU 白模渲染；它使用同一几何、轨迹、机位和帧范围，材质与光照呈现可能不同。引擎选择记录在回执中，失败不会静默换用另一种引擎。先验证短片段再决定长场次是否采用该模式。

输出目录必须不存在。执行失败保留日志与部分产物，先查原目录，不覆盖或冒称完成。输出 `scene.blend` 可编辑工程（内嵌计划）、`plan.json`、`camera.mp4`、`top.mp4`、`receipt.json`、图像帧与日志。回执验证帧数/时长，不证明画面或导演效果。必须打开实际画面、检查遮挡/朝向/切点，并把内容问题报告为待修订。

## 登记、反馈与交接

用 `film_dispatch` / 包内 `film.py dispatch` 调用 `previs.register`。payload 必须包含 `op_id, expected_project_id, previs_id, task_id, scope, title, base_revision, manifest, sources:{script:{artifact_id,version,sha256},director:{artifact_id,version,sha256}}, files:{blend,camera,top,plan,receipt}, change_note, feedback_ids`。每个文件引用为项目内相对 `{path,sha256}`。`manifest` 必须等于 plan.json。先 `previs.read` 读取该序列当前 revision；未知结果先用原 op_id 查证，不能换号重复登记。首次 base_revision=0，序列 revision 同时覆盖版本、反馈和用户决定。

`previs.read` 返回全部准确版本、问题原话、shot_choices、approved_version、decisions、stale_reasons。当前导演任务只能在匹配的模块锁下登记；旧任务留在旧运行环境。不要新建任务绕过未决锁。最新候选与整段已通过指针独立；测试项目所有决定自动为 synthetic。

反馈是唯一交接依据：用户要求修订时先读取 Registry 中准确版本/镜头/时间的原话。将空间参数修改及其对拍法的影响同步保存为新的 director 成果（保留原版及脚本依赖），新预演 sources.director 指向此版，feedback_ids 指向被处理的准确问题。不能只改 Blender 留下相互矛盾的导演方案。更改剧本需先按编剧/导演既有流程处理，再调整任务冻结输入；预演登记不会改写它。

镜头混选不自动等于整段通过。用 `compose.py` 从 Registry 当前准确选择生成新计划，检查角色身份/颜色、空间一致性与切点位置/朝向；冲突停止，由导演解决并生成衔接。混选不允许仅把同秒画面拼成“已对齐”。新计划仍须执行、登记并由用户明确选择整段。不同版本比较按稳定镜头定位起点，时长不同提示动作未自动对齐。

## 看板

创作任务 → 导演 → 对应任务 → 预演审看。完整视频通过受限分块通道读回并核验完整 SHA-256，在宿主页面生成 Blob 播放。单个审看视频上限 128 MiB；超过时降低码率/画幅保持完整时长，或按合理场次拆段。无截取前 12 秒的后备冒充。实际宿主不支持时报告未验收，保留本地视频和工程；不把外部网页当内嵌验收。

浏览、比较、保存问题和打开已关联对话均不创建任务、不渲染、不发送消息。只有用户明确点击通过写入版本范围决定。自然语言修订由工作对话接续，没有后台自动执行器。
