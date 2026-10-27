"""Explicit local previs renderer. Never called on a board read or feedback save."""
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

HERE=Path(__file__).resolve().parent
for parent in HERE.parents:
    for candidate in (parent,parent/'runtime'):
        if (candidate/'filmprod').is_dir():sys.path.insert(0,str(candidate));break
    else:continue
    break
from filmprod.previs1190 import validate_plan, sha
from filmprod.render import _exe


def run(cmd,log):
    with log.open('w',encoding='utf-8') as f:
        result=subprocess.run(cmd,stdout=f,stderr=subprocess.STDOUT)
    if result.returncode:raise RuntimeError(f'执行失败，请查看 {log}')


def probe(path,ffprobe):
    d=json.loads(subprocess.check_output([ffprobe,'-v','error','-select_streams','v:0','-count_frames','-show_entries',
        'stream=nb_read_frames,width,height,r_frame_rate,duration','-of','json',str(path)],text=True,encoding='utf-8'))['streams'][0]
    return {'frames':int(d['nb_read_frames']),'duration':float(d['duration']),'width':int(d['width']),'height':int(d['height']),'fps':d['r_frame_rate']}


def execute(plan,out,blender,ffmpeg=None,ffprobe=None,engine='WORKBENCH'):
    plan=Path(plan).resolve();out=Path(out).resolve();m=validate_plan(json.loads(plan.read_text(encoding='utf-8')))
    if out.exists():raise ValueError('输出已存在；检查原执行结果或使用新的版本目录，禁止覆盖')
    if engine not in {'WORKBENCH','CYCLES'}:
        raise ValueError('预演引擎仅支持 WORKBENCH 或 CYCLES；不会自动降级')
    if not isinstance(blender,(str,Path)) or not str(blender).strip():
        raise ValueError('请传入已核实 Blender 可执行文件')
    # Resolve every dependency before creating output or starting a render. The
    # shared resolver preserves explicit choices and supports Finder's limited
    # PATH without changing the process environment or downloading anything.
    if ffmpeg == '' or ffprobe == '':
        raise ValueError('显式媒体工具路径不能为空；省略参数可使用本机查找')
    blender=_exe('blender',blender)
    ffmpeg=_exe('ffmpeg',ffmpeg)
    ffprobe=_exe('ffprobe',ffprobe)
    out.mkdir(parents=True);(out/'camera').mkdir();(out/'top').mkdir();shutil.copyfile(plan,out/'plan.json')
    run([str(blender),'--background','--factory-startup','--python-exit-code','1','--python',str(HERE/'blender_scene.py'),'--',str(out/'plan.json'),str(out),engine],out/'blender.log')
    probes={}
    for view in ('camera','top'):
        run([ffmpeg,'-hide_banner','-nostdin','-n','-framerate',str(m['fps']),'-start_number','1','-i',str(out/view/'frame_%04d.png'),
             '-frames:v',str(m['frames']),'-c:v','libx264','-preset','fast','-crf','23','-pix_fmt','yuv420p','-movflags','+faststart',str(out/(view+'.mp4'))],out/(view+'-encode.log'))
        probes[view]=probe(out/(view+'.mp4'),ffprobe)
        if probes[view]['frames']!=m['frames'] or abs(probes[view]['duration']-m['frames']/m['fps'])>1/m['fps']:
            raise ValueError('完整视频校验失败')
    receipt={'schema_version':1,'plan_sha256':sha(out/'plan.json'),'frames':m['frames'],'fps':m['fps'],
             'files':{k:sha(out/name) for k,name in {'blend':'scene.blend','camera':'camera.mp4','top':'top.mp4'}.items()},
             'probes':probes,'validation':'encoded_frames_and_duration_only','subjective_review':'pending',
             'render_engine':'CYCLES' if engine=='CYCLES' else 'BLENDER_WORKBENCH',
             'render_device':'CPU' if engine=='CYCLES' else 'WORKBENCH_BACKEND',
             'blender_version':subprocess.check_output([blender,'--version'],text=True,encoding='utf-8').splitlines()[0]}
    (out/'receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    return receipt


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--plan',required=True);p.add_argument('--out',required=True);p.add_argument('--blender',required=True)
    p.add_argument('--ffmpeg');p.add_argument('--ffprobe');p.add_argument('--engine',choices=('WORKBENCH','CYCLES'),default='WORKBENCH');a=p.parse_args()
    print(json.dumps(execute(a.plan,a.out,a.blender,a.ffmpeg,a.ffprobe,a.engine),ensure_ascii=False,indent=2))
