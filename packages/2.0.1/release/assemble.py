"""Assemble a portable payload from a completed explicit source snapshot."""
import argparse
import ast
import json
import shutil
from pathlib import Path

IGNORE=shutil.ignore_patterns('__pycache__','*.pyc','.DS_Store')
DOCS=('integration-pages.md','integration-workflow-1.3.md','integration-brainstorm-1.4.md',
      'integration-video-prompt-1.5.md','integration-1.6.md','integration-1.7.md','integration-1.7.2.md','integration-1.7.3.md','integration-1.7.4.md','integration-1.8.0.md','integration-1.9.0.md','integration-1.9.1.md','integration-1.9.2.md','integration-1.9.3.md','integration-1.9.4.md','integration-1.10.0.md','integration-1.11.0.md','integration-workspace-1.11.0.md','integration-delivery-1.11.0.md','integration-workspace-ui1110.md','integration-1.12.0.md','integration-cloud-1.12.0.md','integration-cloud-ui1120.md','integration-1.13.0.md','integration-art-1.13.0.md','integration-director.md','integration-1.14.0.md','integration-screenwriter-overview-1.14.0.md','integration-screenwriter-1.13.0.md','integration-style-feedback-1.14.0.md','integration-1.15.0.md','integration-1.15.1.md','integration-1.15.2.md','integration-1.16.0.md','integration-1.16.1.md','integration-1.17.0.md','integration-1.18.0.md','integration-1.19.0.md','integration-1.19.2.md','current-rules.md','compatibility.md')

DOCS = (*DOCS, 'integration-1.20.0.md', 'integration-2.0.0.md', 'integration-2.0.1.md', 'MACOS.md')

def assemble(source, output):
    source,output=Path(source).resolve(),Path(output).resolve()
    if output.exists():
        raise ValueError('输出目录已存在；使用新构建目录，禁止覆盖冻结发行')
    if not (source/'modules/manifest.json').is_file():
        raise ValueError('先用显式专业来源配置构建完整模块')
    version_nodes = ast.parse((source/'filmprod/__init__.py').read_text(encoding='utf-8')).body
    versions = [ast.literal_eval(node.value) for node in version_nodes
                if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == '__version__' for target in node.targets)]
    if len(versions) != 1 or not isinstance(versions[0], str):
        raise ValueError('运行版本必须有唯一的字符串来源')
    version = versions[0]
    source_manifest = json.loads((source/'plugin/.codex-plugin/plugin.json').read_text(encoding='utf-8'))
    if source_manifest.get('version') != version:
        raise ValueError('插件清单版本与运行版本不一致')
    plugin=output/'plugin'
    plugin.mkdir(parents=True)
    shutil.copy2(source/'plugin/mcp_server.py',plugin/'mcp_server.py')
    for origin,dest in [('filmprod','runtime/filmprod'),('modules','modules'),('skills','skills'),('plugin/ui','ui')]:
        shutil.copytree(source/origin,plugin/dest,ignore=IGNORE)
    shutil.copy2(source/'film.py',plugin/'runtime/film.py')
    for name in ('AGENTS.md','CONTRACT.md'):
        shutil.copy2(source/name,plugin/name)
    (plugin/'docs').mkdir()
    for name in DOCS:
        shutil.copy2(source/'docs'/name,plugin/'docs'/name)
    shutil.copy2(source/'docs/integration-2.0.1.md',plugin/'docs/integration.md')
    shutil.copy2(source/'docs/editing-portable.md',plugin/'docs/剪辑导出.md')
    shutil.copytree(source/'docs/history',plugin/'docs/history',ignore=IGNORE)
    for name in ('INSTALL.md','UPGRADE.md','FEATURES.md'):
        shutil.copy2(source/'docs'/name,plugin/'docs'/name)
    (plugin/'docs/integration-skills.json').write_text(json.dumps({'manifest':'../modules/manifest.json','scope':'bundled_methods','original_sources_unchanged':True},ensure_ascii=False,indent=2),encoding='utf-8',newline='\n')
    manifest={'name':'film-production-agent','version':version,'description':'影视创作助手：灵感、剧本、导演、美术、任务与素材管理',
      'skills':'./skills/','mcpServers':'./.mcp.json','requires_local_executor':True,
      'interface':{'displayName':'影视制作助手','shortDescription':'创作任务与对象素材管理','category':'Productivity','capabilities':['Read','Write']}}
    (plugin/'.codex-plugin').mkdir()
    (plugin/'.codex-plugin/plugin.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8',newline='\n')
    # Portable specification only. installer materializes a machine-local absolute config.
    server={'command':'python','args':['-X','utf8','${PLUGIN_ROOT}/mcp_server.py'],'cwd':'${PLUGIN_ROOT}',
            'env':{'PYTHONDONTWRITEBYTECODE':'1'}}
    (plugin/'.mcp.json').write_text(json.dumps({'mcpServers':{'film-production':server}},indent=2),encoding='utf-8',newline='\n')
    (output/'release').mkdir()
    for name in ('installer.py','bootstrap.ps1','bootstrap.sh','publisher.py','assemble.py','installer-guide.md','release-guide.md'):
        shutil.copy2(source/'release'/name,output/'release'/name)
    (output/'install.py').write_text('from release.installer import main\nif __name__ == "__main__":\n    main()\n',encoding='utf-8',newline='\n')
    (output/'README.md').write_text(f'''# 影视制作助手 {version} · Windows / macOS 本地发行

请先阅读 `release/installer-guide.md`，运行环境检查、校验和安装，再添加安装器生成的本机 marketplace。
当前执行职责见 `plugin/docs/current-rules.md`，旧接口与任务恢复见 `plugin/docs/compatibility.md`；历史记录不作为当前操作指引。
本版新增黑金夜间与磨砂白日间主题、紧凑任务列表和文稿阅读抽屉，用法见 `plugin/docs/integration-2.0.0.md`。保留与编剧平级的独立导演入口 `$film-director`，复用包内导演方法、按需特效设计和既有白模预演；五个公开技能共用原有八个专业方法模块和项目登记。用法见 `plugin/docs/integration-1.20.0.md`。
本包 `.mcp.json` 为可移植模板；兼容宿主必须经安装器生成本机配置，不能把模板成功解析当成实际启动。
创作数据、catalog 和用户配置独立于版本目录。首次安装为空项目列表；按明确目录新建或关联。
项目搭建说明见 `plugin/skills/film-production-agent/references/project-bootstrap.md`；授权搭建后用同技能 `scripts/scaffold_project.py` 生成项目入口和对话索引。个人默认授权不随包传播，宿主对话必须实际创建和核验。
本版看板提供项目总览、按创作环节与状态排列的任务、对象用途素材库和项目设置。用户明确点击可确认准确文稿、选用已登记方案及用途素材；不能创建任务、改稿、发送消息、创建聊天或渲染。图片、视频和音频分开管理，标签/分类/更名/逻辑回收不会改变正文和采用；回收不释放磁盘空间。
本版同时提供统一编剧与美术总监。编剧合并小说、改编与原创剧本，优先完整AI短剧分场正文，底稿为可选；导演反馈关联准确剧本，重大变化先交方案与用户选择。美术总监负责：主选/备选定调、统一视觉基准、场景资产指导与实际成果视觉复核，影视分析作为按需研究能力。项目已选择或用户已授权按轮云稿时，支持完整初稿与每轮明确修订的云端工作稿接续：准确成果关联、持久待同步记录、未知结果恢复与完整读回。按轮处理不代表后台实时双向同步。保留项目工作对话、完整成稿复核、Markdown 阅读导出与精简正文提交；云稿修改不自动批准内容。
本版内置八个方法模块（旧小说与改编合为编剧，原方法完整保留在其内部）；灵感探索与需求规划是可选入口，未立项可以直接讨论，持久化时明确选择外部灵感库。项目内统一使用 planning.record/read，不建立第二套状态。
本版支持显式启用项目总控、部门总控与专题／执行对话的分层机制。灵感可保留、回收、恢复或按准确版本转交编剧；创建、发送、归档和回报先登记稳定请求，再由宿主执行和记录观察。当前轮次按授权推进，未知结果先核查；没有后台常驻聊天调度。旧项目不因安装或读取自动迁移，旧任务锁与历史聊天保持。
更新检查不会切换正在运行的聊天。程序包不包含作品、私人 Pages 或账号绑定。
本地发布源与远端更新上线分别验证。本版支持 Windows 与 macOS 本地安装及运行；Mac 安装说明见 `plugin/docs/MACOS.md`。跨平台检查见发行页。原生 Mac 客户端看板与纯云 Work 尚未验收。
本包可从公开仓库下载并使用。模块来源与历史分发记录见 `plugin/modules/manifest.json`；第三方依赖保留各自许可状态，本次发布不将未声明的上游许可标为已核实。
音乐生成未实现，外部脑暴提供方未连接；宿主可使用内置 idea-explorer 实际讨论创意，Pages 访问条件以实际工具为准。
''',encoding='utf-8',newline='\n')
    return {'payload':str(output),'version':version}

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',required=True); parser.add_argument('--output',required=True)
    args=parser.parse_args()
    print(json.dumps(assemble(args.source,args.output),ensure_ascii=False))
