"""Executed only by explicit Blender CLI. Shared scene, frame-exact key sampling."""
import bpy
import json
import math
import sys
from pathlib import Path
from mathutils import Vector


def sample(keys, frame, name):
    a,b=keys[0],keys[-1]
    for i in range(len(keys)-1):
        if keys[i]['frame']<=frame<=keys[i+1]['frame']:
            a,b=keys[i:i+2];break
    t=max(0,min(1,(frame-a['frame'])/(b['frame']-a['frame'])))
    if isinstance(a[name],list):return [x+(y-x)*t for x,y in zip(a[name],b[name])]
    delta=(b[name]-a[name]+180)%360-180 if name=='yaw' else b[name]-a[name]
    return a[name]+delta*t


def material(name,color):
    m=bpy.data.materials.new(name);m.diffuse_color=(*color,1)
    # Workbench uses diffuse_color; explicit Cycles CPU mode uses these nodes.
    m.use_nodes=True
    bsdf=m.node_tree.nodes.get('Principled BSDF')
    bsdf.inputs['Base Color'].default_value=(*color,1)
    bsdf.inputs['Roughness'].default_value=0.8
    return m


def cube(name,position,size,mat):
    bpy.ops.mesh.primitive_cube_add(size=1,location=position)
    o=bpy.context.object;o.name=name;o.dimensions=size;o.data.materials.append(mat)
    bpy.ops.object.transform_apply(location=False,rotation=False,scale=True)
    return o


def sphere(name,position,scale,mat,parent):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=12,ring_count=8,location=position)
    o=bpy.context.object;o.name=name;o.scale=scale;o.data.materials.append(mat);o.parent=parent
    return o


def camera(name):
    d=bpy.data.cameras.new(name);o=bpy.data.objects.new(name,d);bpy.context.collection.objects.link(o);return o


def point(cam,target):
    cam.rotation_euler=(Vector(target)-cam.location).to_track_quat('-Z','Y').to_euler()


def main():
    args=sys.argv[sys.argv.index('--')+1:]
    if len(args) not in (2,3):raise ValueError('Expected plan, output and optional engine')
    plan_path,out_path=args[:2];engine=args[2] if len(args)==3 else 'WORKBENCH'
    if engine not in {'WORKBENCH','CYCLES'}:raise ValueError('Unsupported explicit render engine')
    m=json.loads(Path(plan_path).read_text(encoding='utf-8'));out=Path(out_path)
    bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
    scene=bpy.context.scene;scene.render.engine='CYCLES' if engine=='CYCLES' else 'BLENDER_WORKBENCH'
    if engine=='CYCLES':
        scene.cycles.device='CPU';scene.cycles.samples=8;scene.cycles.use_denoising=False
        scene.world.use_nodes=True
        background=scene.world.node_tree.nodes.get('Background')
        background.inputs['Color'].default_value=(0.65,0.65,0.65,1)
        background.inputs['Strength'].default_value=0.8
    scene.render.resolution_x=m.get('width',640);scene.render.resolution_y=m.get('height',360);scene.render.resolution_percentage=100
    scene.render.fps=m['fps'];scene.frame_start=1;scene.frame_end=m['frames']
    scene.render.image_settings.file_format='PNG'
    scene.world.color=(0.15,0.15,0.15)
    sh=scene.display.shading;sh.light='STUDIO';sh.color_type='MATERIAL';sh.show_shadows=True;sh.show_cavity=True
    sh.cavity_type='BOTH';sh.background_type='WORLD';sh.show_specular_highlight=True
    grey=material('Whitebox',(0.55,0.59,0.63));floor=material('Ground',(0.28,0.32,0.36))
    for b in m['space']['boxes']:
        cube(b['id'],b['position'],b['size'],floor if b['id']=='floor' else grey)
    nose=material('Facing marker',(0.95,0.95,0.9))
    for a in m['actors']:
        color=tuple(int(a['color'][i:i+2],16)/255 for i in (1,3,5));mat=material(a['id'],color)
        root=bpy.data.objects.new(a['id']+'-root',None);bpy.context.collection.objects.link(root)
        sphere(a['id']+'-body',(0,0,0.95),(0.23,0.19,0.48),mat,root)
        sphere(a['id']+'-head',(0,0,1.58),(0.19,0.19,0.22),mat,root)
        for x in (-0.14,0.14):sphere(a['id']+'-leg',(x,0,0.32),(0.10,0.11,0.32),mat,root)
        for x in (-0.31,0.31):sphere(a['id']+'-arm',(x,0,0.95),(0.10,0.10,0.31),mat,root)
        sphere(a['id']+'-face',(0,0.2,1.6),(0.09,0.09,0.06),nose,root)
        arrow=cube(a['id']+'-direction',(0,0.4,0.06),(0.1,0.6,0.08),mat);arrow.parent=root
        for f in range(m['frames']+1):
            root.location=sample(a['keys'],f,'position');root.rotation_euler[2]=math.radians(sample(a['keys'],f,'yaw'))
            root.keyframe_insert(data_path='location',frame=f+1);root.keyframe_insert(data_path='rotation_euler',frame=f+1)
    for s in m['shots']:
        cam=camera(s['id']);cam.data.lens=s.get('lens',40)
        for f in range(s['start'],s['end']+1):
            cam.location=sample(s['camera'],f,'position');point(cam,sample(s['camera'],f,'target'))
            cam.keyframe_insert(data_path='location',frame=f+1);cam.keyframe_insert(data_path='rotation_euler',frame=f+1)
        marker=scene.timeline_markers.new(s['id'],frame=s['start']+1);marker.camera=cam
    scene.camera=bpy.data.objects[m['shots'][0]['id']]
    top=camera('TOP');top.location=(0,0,16);point(top,(0,0,0));top.data.type='ORTHO';top.data.ortho_scale=14
    # Plan embedded in editable .blend; external plan is byte-hashed in receipt.
    block=bpy.data.texts.new('PREVIS_PLAN.json');block.write(json.dumps(m,ensure_ascii=False,indent=2))
    scene['previs_notice']='Whitebox candidate; user selection is held only in project Registry'
    scene.frame_set(1);bpy.ops.wm.save_as_mainfile(filepath=str(out/'scene.blend'))
    scene.render.filepath=str(out/'camera'/'frame_');bpy.ops.render.render(animation=True)
    for marker in scene.timeline_markers:marker.camera=None
    scene.camera=top;scene.render.filepath=str(out/'top'/'frame_');bpy.ops.render.render(animation=True)


if __name__=='__main__':main()
