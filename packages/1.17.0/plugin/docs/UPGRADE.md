# 更新与换电脑

完整操作命令在**源码根或发行 ZIP 根的 `release/installer-guide.md`**。当前稳定发行目标为 `1.17.0`，插件技术身份继续是 `film-production-agent@film-production-local`。

## 更新现有安装

从公开仓库的 Releases 取得并校验新发行 ZIP 后，沿用原 `app-root`、`data-root`、`config-root`，依次检查 `check-update`、准备 `stage`。保存工作、确认相关登记与配置已停止写入后，才执行带 `--quiescent` 的 `switch`。随后重新生成 `host-plan`，接入目标桌面并在新会话核对实际版本。

程序版本、项目数据、用户配置分别保留。已有任务仍受其创建时冻结的运行版本和方法约束；新增版本不能借机改写旧执行锁。遇到未完成的旧任务，按原环境接续或先明确处理任务，不通过重建任务绕过约束。

`git pull`、下载 ZIP、安装副本存在及活动版本指针改变，都不证明正在运行的聊天已升级。不要删除旧版本目录来强制切换；它可能仍被既有任务使用。

## Windows 与 Mac 之间迁移

1.17.0 的同一发行包提供两种系统的安装入口。Mac 使用 `python3` 或 `bash release/bootstrap.sh`；目录示例见 [Mac 安装指南](MACOS.md)。在 Mac 上重新安装以生成本机 Python 与 MCP 路径，不复制 Windows 的 `state.json`、部署 `.mcp.json` 或带盘符的 catalog 路径作为可直接运行的配置。

安装器显式设置的 catalog 路径始终优先。未配置路径的 Mac 运行时使用 `~/Library/Application Support/FilmProduction/projects.sqlite3`；旧版可能位于 `~/AppData/Local/FilmProduction/projects.sqlite3`。如果此前在 Mac 手工试用过旧版，先备份并显式传 `--catalog-path` 沿用已核实的旧库，不通过文件名猜测或自动合并登记。

## 换一台电脑

1. 在新电脑单独安装程序，核实当前桌面的插件接入。
2. 按明确范围迁移作品备份和所需个人规则，保留项目 ID 与历史。
3. 用项目关联／重新定位流程核对作品身份和新路径。
4. 重新核实原聊天、客户端项目和云稿是否仍可访问；旧关联只是历史证据。

同账号登录不会自动把本机程序、作品媒体、SQLite 登记库和个人规则复制到另一台电脑。程序包本身也不包含这些数据。新电脑的用户名、路径或工具位置不同，应使用安装器重新生成本机配置。

## 恢复

切换事务保留恢复快照。需要恢复时，先停止相关写入，再按安装指南使用 `rollback` 或处理未完成事务。恢复程序选择与数据快照后，仍须重新接入宿主并核对新会话实际版本。用户升级后的新增修改应先保留，不能以删除新版目录代替完整恢复。
