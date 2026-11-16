"""Native-image task ledger and deterministic three-cover export, without API calls."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps
from tools.contact_numbers import normalize_contact_number

ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = Path(os.environ.get('FACTORY_DATA_HOME') or ROOT).resolve()
SIGNBOARD_PROFILE_PATH = ROOT / 'projects/road_rescue/pinned_signboard_profiles.json'
SCENES = [
    'Two ordinary repair bays under a worn blue and red signboard, yellow flatbed tow truck partially visible at far left, white compact car at right with a mechanic changing its front wheel. Uneven concrete forecourt, bright overcast daylight, almost frontal casual street photo.',
    'A modest one-bay roadside rescue workshop with faded green sheet-metal signboard and a corrugated side shed. A small plain white service van at far right and a crouching mechanic checking a detached tire on the left. Dry pale concrete and a small gravel shoulder, soft morning light, slight left-side angle.',
    'A community ground-floor rescue garage under aging cream residential balconies, a simple deep blue signboard. Silver hatchback at left with open bonnet, mechanic using a portable jump starter, just the rear portion of a yellow recovery truck at right. Dry street, soft afternoon light, slight right-side angle.',
    'An ordinary red-brick roadside repair shop with muted orange rectangular signboard, one open bay and a partially lowered shutter. A mechanic checking tire pressure at a dark gray car on the left, a plain white tow truck partly visible on the far right. A few irregular concrete patches, normal daylight, candid eye-level street photo.',
    'A wider concrete neighborhood vehicle-recovery workshop with a faded burgundy signboard, two unequal bays and ordinary neighboring walls. A blue flatbed tow truck parked at far left, a small white car inside the right bay and one mechanic walking toward a toolbox near the entrance. Soft cloudy daylight, slightly off-center framing, modest everyday wear.'
]


def save(path, value):
    path = Path(path)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temp.replace(path)


def read_job(path):
    folder = Path(path).resolve()
    return folder, json.loads((folder / 'task.json').read_text(encoding='utf-8'))


def signboard_profile_for(index):
    if index < 0:
        raise ValueError('Style index must be nonnegative')
    library = json.loads(SIGNBOARD_PROFILE_PATH.read_text(encoding='utf-8'))
    sign = library['profiles'][index % len(library['profiles'])]
    cycle = index // len(library['profiles'])
    font = sign['typography_options'][cycle % len(sign['typography_options'])]
    sign.update(letter_style=font['id'], font_description=font['description'])
    return library['version'], sign


def camera_for(index):
    if index < 0:
        raise ValueError('Style index must be nonnegative')
    library = json.loads(SIGNBOARD_PROFILE_PATH.read_text(encoding='utf-8'))
    # Advance the viewpoint separately from the six physical sign constructions.
    return library['camera_presets'][(index + index // len(library['profiles'])) % len(library['camera_presets'])]


def store_identity(store_name=None, fictional_name=False):
    name = (store_name or '').strip()
    if not name:
        if fictional_name:
            raise ValueError('An explicit illustrative store name is required')
        return dict(name='【待确认店名】', basis='pending', generation_ready=False)
    if not re.fullmatch(r'[\u3400-\u9fffA-Za-z0-9·（）() -]{2,24}', name) or re.search(r'\d{7}', name):
        raise ValueError('Store name must be 2–24 plain characters, without phone numbers or instructions')
    return dict(name=name, basis='user_authorized_illustrative' if fictional_name else 'user_supplied',
                generation_ready=True)


def group_names(args):
    names = getattr(args, 'store_name', None)
    if not isinstance(names, list):
        names = [names]
    if len(names) not in (1, args.count):
        raise ValueError('Provide one shared name or exactly one name per group')
    for name in names:
        store_identity(name, getattr(args, 'fictional_name', False))
    return names * args.count if len(names) == 1 else names


def prompt_for(phone, index, store_name=None, fictional_name=False):
    phone = normalize_contact_number(phone)
    identity = store_identity(store_name, fictional_name)
    library = json.loads(SIGNBOARD_PROFILE_PATH.read_text(encoding='utf-8'))
    profile = json.loads((ROOT / 'projects/road_rescue/cover_visual_profile_v3.json').read_text(encoding='utf-8'))
    _, sign = signboard_profile_for(index)
    shot = next(item for item in profile['shot_presets'] if item['id'] == sign['shot_id'])
    light = next(item for item in profile['light_presets'] if item['id'] == sign['light_id'])
    event = next(item for item in library['event_presets'] if item['id'] == sign['event_id'])
    camera = camera_for(index)
    services = sign['service_separator'].join(sign['service_words'])
    category_text = '' if '道路救援' in identity['name'] else '、从属业务字“道路救援”'
    return (
        '生成一张中国道路救援门店的真实手机全景照片，横幅9:4（优先3240×1440），用于后期切成三个抖音置顶封面。'
        '整张必须是连续摄影画面，不是三格拼贴、海报、招牌设计稿或mockup，不画分割线。'
        f'场景：{shot["facade"]}。机位：{camera["description"]}。{light["description"]}。'
        f'立面空间关系必须清楚：{sign["facade_depth"]}。'
        '采用现有道路救援门头提示词的适中当代感：实体店维护正常，玻璃或卷帘门保持正常营业状态，'
        '不是废旧厂房、锈蚀棚屋或豪华展厅；只留少量正常灰尘与生活痕迹，不做剥落油漆、大面积污迹和斑驳复古效果。'
        f'本组只采用一种门头做法：{sign["label"]}。实体材料与字形工艺：{sign["surface"]}。'
        f'明确字体做法：{sign["font_description"]}。主色与文字保持对比，最多一处辅助强调色，不做渐变或彩虹描边。'
        f'门头结构随本店建筑而定：{sign["shape"]}。实际信息位置：{sign["layout"]}。'
        f'主招牌逐字允许的文字仅为店名“{identity["name"]}”{category_text}、服务词“{services}”和“电话：{phone}”。'
        '店名是有辨识度的完整经营名称，业务词只说明做什么；不要把店名拆成四个等大业务词，不扩写或改名。'
        '如果店名已含道路救援四字，不再重复一行道路救援；普通店名可用一行，从属业务与服务根据本组布局安排，避免每行等大等宽。'
        f'电话号码位置：{sign["phone_position"]}。店名远看可辨，电话11位完整横排；电话不是最小装饰字，宽度不足时减少服务区面积，不挤成细长乱码。'
        f'本组文字取舍与物理安装：{sign["text_fit"]}。{sign["installation_detail"]}。'
        f'招牌细节关键词：{sign["sign_detail"]}。服务小字是经营信息，不是装饰纹理，三项都写清楚。'
        '主招牌位于画面上部，所有必需文字在高度42%以内，四周留真实墙面、电线、雨棚或邻铺边缘。'
        '重要招牌文字保留在画面横向中央84%内。店面应有前后退进和侧面厚度，不能把整条街画成一张齐平的平面广告墙；不是要求故意把招牌板扭曲或凹凸化。'
        '不要追加老板姓氏、地区、老字号、24小时、连锁、速度承诺、维修认证或额外号码；不复制调研门店的品牌或商标。'
        '招牌只体现本组指定的一种工艺和一处正常安装细节，不把所有材质、发光、包边或旧化效果堆到一起。'
        '所有中文和号码属于同一实体招牌，透视、光照一致，不能悬浮，不能贴到墙、车、柱子或门下横幅。'
        '普通大陆街边门店，未指定地区与季节，不加入对联、灯笼、福字或仿古书法牌匾。'
        f'本组只发生这一件事：{event["description"]}。车辆与工具限制：{event["physical_constraints"]}。'
        '正常大小的人和车可以跨越下半部，关键手部接触点和工作对象位于画面一侧较低处；不要把整个人或整辆车压扁塞进底部30%。'
        '画面高度约49%至68%是后期电话叠字带，仍有连续真实背景，不在这里安排脸、手、主招牌文字或核心操作；不生成人工空白带。'
        '不要生成任何照片外的大号电话、字幕、底板、服务按钮或贴纸，后期程序会自行处理。'
        '普通手机自动曝光，轻微不对称及自然梯形透视，不做正交校正，不用极端广角、电影光、HDR或高端商业精修。'
        '室外招牌清楚而店内比室外稍暗，远处细节自然减少；不要全景每处同样锐利、塑料皮肤、描边轮胎或均匀颗粒滤镜。'
        '所有车辆均无品牌标志和字母型号，避免拍到车头车尾徽标，车牌完全不可读；不在车间深处放带车标的汽车。'
        '工具车、轮胎、千斤顶、手部结构要真实合理。无水印、二维码、图标矩阵、复杂logo、霓虹、矢量设计感。'
    )


def prompt_record(phone, index, style_index, store_name=None, fictional_name=False):
    version, sign = signboard_profile_for(style_index)
    identity = store_identity(store_name, fictional_name)
    return dict(index=index, style_index=style_index,
                prompt=prompt_for(phone, style_index, store_name, fictional_name), status='pending',
                store_identity=identity, generation_ready=identity['generation_ready'],
                camera_profile=camera_for(style_index),
                variation_axes=dict(font=sign['letter_style'], color=sign['palette_family'],
                                    text_layout=sign['layout_family'], store_name=identity['name']),
                signboard_profile_version=version, signboard_profile=sign,
                signboard_signature=hashlib.sha256(json.dumps(sign, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest())


def plan(args):
    phone = normalize_contact_number(args.phone)
    if len(phone) != 11 or not 1 <= args.count <= 100 or args.style_start < 0:
        raise ValueError('Requires mobile number, count 1–100 and nonnegative style start')
    target = Path(args.output)
    if target.exists():
        raise ValueError('Do not overwrite an existing prompt plan')
    target.parent.mkdir(parents=True, exist_ok=True)
    names = group_names(args)
    groups = [prompt_record(phone, i+1, args.style_start+i, names[i],
                            getattr(args, 'fictional_name', False)) for i in range(args.count)]
    save(target, dict(mode='local_prompt_plan', api_called=False, creates_license=False, phone=phone,
                      store_identity=groups[0]['store_identity'] if len(set(names)) == 1 else None,
                      identity_mode='shared' if len(set(names)) == 1 else 'per_group',
                      generation_ready=all(g['generation_ready'] for g in groups),
                      prompt_profile=groups[0]['signboard_profile_version'], groups=groups))
    print(json.dumps(dict(plan=str(target.resolve()), groups=args.count, api_called=False), ensure_ascii=False))
    return 0


def prepare(args):
    phone = normalize_contact_number(args.phone)
    if len(phone) != 11 or not 1 <= args.count <= 100 or args.style_start < 0 or not args.confirm:
        raise ValueError('Requires confirmed mobile number, count 1–100 and scoped authorization')
    names = group_names(args)
    groups = [prompt_record(phone, i+1, args.style_start+i, names[i],
                            getattr(args, 'fictional_name', False)) for i in range(args.count)]
    if not all(g['generation_ready'] for g in groups):
        raise ValueError('Store identity is pending: use the user supplied name or an explicitly authorized illustrative name')
    task_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    folder = DATA_ROOT / 'output' / 'road_rescue_pinned' / task_id
    folder.mkdir(parents=True, exist_ok=False)
    task = dict(version=1, task_id=task_id, phone=phone, category='road_rescue', count=args.count,
                store_identity=groups[0]['store_identity'] if len(set(names)) == 1 else None,
                identity_mode='shared' if len(set(names)) == 1 else 'per_group',
                tile_size=[1080, 1440], master_size=[3240, 1440], status='prepared',
                authorization=args.authorization, generation_tool='image_gen', model='host_managed',
                api_key_slots=[], one_time=True, max_requests=args.count * 2, requests=[],
                prompt_profile=signboard_profile_for(args.style_start)[0], style_start=args.style_start,
                prompt_sources=['projects/road_rescue/pinned_signboard_profiles.json', 'projects/road_rescue/cover_visual_profile_v3.json',
                                'projects/road_rescue/pinned_triptych_style_profile.md'],
                groups=groups)
    save(folder / 'task.json', task)
    (folder / 'prompts.txt').write_text('\n\n'.join(f"GROUP {g['index']}\n{g['prompt']}" for g in task['groups']), encoding='utf-8')
    print(json.dumps(dict(job_dir=str(folder), groups=args.count, covers=args.count * 3, max_requests=task['max_requests']), ensure_ascii=False))
    return 0


def claim(args):
    folder, task = read_job(args.job_dir)
    if task.get('status') == 'superseded':
        raise ValueError('Task superseded by a newer user instruction')
    group = next(g for g in task['groups'] if g['index'] == args.group)
    if group.get('generation_ready') is False:
        raise ValueError('Store identity is pending')
    previous = [r for r in task['requests'] if r['group'] == args.group]
    if group['status'] == 'composed' or any(r['status'] == 'requesting' for r in previous):
        raise ValueError('Completed group or an unresolved request cannot be started again')
    if len(task['requests']) >= task['max_requests'] or len(previous) >= 2:
        raise ValueError('One-time request budget exhausted')
    if len(task['requests']) >= 2 and all(r['status'] == 'failed' for r in task['requests'][-2:]):
        raise ValueError('Consecutive failures: stop and preserve checkpoint')
    task['requests'].append(dict(group=args.group, attempt=len(previous)+1, status='requesting', tool='image_gen', model='host_managed', key_slot=None))
    task['status'] = 'generating'
    save(folder / 'task.json', task)
    print(group['prompt'])
    return 0


def render_panorama(source, phone, style=0, phone_y=835, font_size=330):
    if not 200 <= font_size <= 330 or not 400 <= phone_y <= 1100:
        raise ValueError('Phone overlay parameters outside reviewed layout range')
    master = ImageOps.fit(source.convert('RGB'), (3240, 1440), method=Image.Resampling.LANCZOS, centering=(.5, .5))
    draw = ImageDraw.Draw(master)
    pieces = [phone[:3], phone[3:7], phone[7:]]
    font_path = 'C:/Windows/Fonts/arialbd.ttf'
    while True:
        font = ImageFont.truetype(font_path, font_size)
        if max(draw.textbbox((0, 0), p, font=font, stroke_width=8)[2] for p in pieces) <= 910:
            break
        font_size -= 2
    colors = ['#FFF200', '#FFFFFF', '#FFDD18', '#FF8A18', '#F6F8FA']
    boxes = []
    for i, piece in enumerate(pieces):
        cx = 540 + i * 1080
        draw.text((cx + 4, phone_y + 7), piece, font=font, anchor='mm', fill='#111111', stroke_width=12, stroke_fill='#111111')
        draw.text((cx, phone_y), piece, font=font, anchor='mm', fill=colors[style % len(colors)], stroke_width=7, stroke_fill='#171717')
        box = list(draw.textbbox((cx, phone_y), piece, font=font, anchor='mm', stroke_width=12))
        if not i * 1080 + 50 <= box[0] < box[2] <= (i+1)*1080-50:
            raise ValueError('Phone segment too close to a seam')
        boxes.append(box)
    for seam in [1080, 2160]:
        draw.text((seam, phone_y), '-', font=font, anchor='mm', fill=colors[style % len(colors)], stroke_width=7, stroke_fill='#171717')
    return master, boxes


def compose(args):
    folder, task = read_job(args.job_dir)
    group = next(g for g in task['groups'] if g['index'] == args.group)
    request = next((r for r in reversed(task['requests']) if r['group'] == args.group and r['status'] == 'requesting'), None)
    if request is None or group['status'] == 'composed':
        raise ValueError('Requires one claimed unresolved request')
    group_dir = folder / f'group_{args.group:02d}'
    group_dir.mkdir(exist_ok=False)
    source_path = group_dir / 'source.png'
    with Image.open(args.source) as source:
        source.load()
        source.save(source_path)
        master, boxes = render_panorama(source, task['phone'], args.group - 1)
        source_size = list(source.size)
    master.save(group_dir / 'panorama.png')
    paths = []
    for i, name in enumerate(['01_left.png', '02_center.png', '03_right.png']):
        target = group_dir / name
        master.crop((i*1080, 0, (i+1)*1080, 1440)).save(target)
        paths.append(name)
    preview = Image.new('RGB', (3248, 1440), 'white')
    for i in range(3):
        preview.paste(master.crop((i*1080, 0, (i+1)*1080, 1440)), (i*1084, 0))
    preview.resize((1624, 720), Image.Resampling.LANCZOS).save(group_dir / 'preview.jpg', quality=94)
    group.update(status='composed', source_size=source_size, phone_boxes=boxes, phone_segments=[task['phone'][:3], task['phone'][3:7], task['phone'][7:]],
                 source_sha256=hashlib.sha256(source_path.read_bytes()).hexdigest(), tiles=paths, visual_review='pending')
    request['status'] = 'succeeded'
    if all(g['status'] == 'composed' for g in task['groups']):
        task['status'] = 'awaiting_visual_review'
    save(folder / 'task.json', task)
    print(json.dumps(dict(group=args.group, directory=str(group_dir), request_count=len(task['requests'])), ensure_ascii=False))
    return 0


def fail(args):
    folder, task = read_job(args.job_dir)
    request = next((r for r in reversed(task['requests']) if r['group'] == args.group and r['status'] == 'requesting'), None)
    if request is None:
        raise ValueError('No unresolved request for this group')
    request.update(status='failed', error_type=args.error_type)
    task['status'] = 'checkpoint_after_failure'
    save(folder / 'task.json', task)
    print('Failure saved; counts and budget retained')
    return 0


def layout(args):
    folder, task = read_job(args.job_dir)
    group = next(g for g in task['groups'] if g['index'] == args.group)
    if group['status'] != 'composed' or task.get('archive'):
        raise ValueError('Local layout needs a composed, unpackaged group')
    directory = folder / f'group_{args.group:02d}'
    with Image.open(directory / 'source.png') as source:
        master, boxes = render_panorama(source, task['phone'], args.group-1, args.phone_y, args.font_size)
    history = group.get('overlay_history', [])
    backup = folder / 'revisions' / f'group_{args.group:02d}_overlay_{len(history)+1}'
    if not directory.resolve().is_relative_to(folder) or not backup.resolve().is_relative_to(folder):
        raise ValueError('Layout paths must stay inside this task')
    backup.mkdir(parents=True, exist_ok=False)
    for name in ['panorama.png', 'preview.jpg'] + group['tiles']:
        shutil.copy2(directory / name, backup / name)
    master.save(directory / 'panorama.png')
    preview = Image.new('RGB', (3248, 1440), 'white')
    for i, name in enumerate(group['tiles']):
        tile = master.crop((i*1080, 0, (i+1)*1080, 1440))
        tile.save(directory / name)
        preview.paste(tile, (i*1084, 0))
    preview.resize((1624, 720), Image.Resampling.LANCZOS).save(directory / 'preview.jpg', quality=94)
    history.append(dict(previous_boxes=group['phone_boxes'], preserved_directory=str(backup.relative_to(folder)),
                        reason=args.reason))
    group.update(phone_boxes=boxes, phone_y=args.phone_y, phone_font_size=args.font_size,
                 overlay_history=history, visual_review='pending')
    save(folder / 'task.json', task)
    print(json.dumps(dict(group=args.group, phone_y=args.phone_y, font_size=args.font_size, api_called=False)))
    return 0


def reject(args):
    folder, task = read_job(args.job_dir)
    request = next((r for r in reversed(task['requests']) if r['group'] == args.group and r['status'] == 'requesting'), None)
    if request is None:
        raise ValueError('No unresolved request for this group')
    directory = folder / 'attempts'
    directory.mkdir(exist_ok=True)
    path = directory / f"group_{args.group:02d}_attempt_{request['attempt']:02d}.png"
    with Image.open(args.source) as image:
        image.save(path)
    request.update(status='quality_rejected', reason=args.reason, source=str(path.relative_to(folder)))
    save(folder / 'task.json', task)
    print('Rejected source retained; retry remains within original budget')
    return 0


def supersede(args):
    folder, task = read_job(args.job_dir)
    task['status'] = 'superseded'
    task['superseded_reason'] = args.reason
    for request in task['requests']:
        if request['status'] == 'requesting':
            request['status'] = 'interrupted_result_unknown'
    save(folder / 'task.json', task)
    print('Superseded task retained; further claims blocked')
    return 0


def revise(args):
    """Apply explicit feedback within the original request cap; retain every version."""
    folder, task = read_job(args.job_dir)
    if task.get('status') == 'superseded' or task.get('archive'):
        raise ValueError('Cannot revise a superseded or packaged task')
    group = next(g for g in task['groups'] if g['index'] == args.group)
    previous = [r for r in task['requests'] if r['group'] == args.group]
    if len(previous) >= 2 or len(task['requests']) >= task['max_requests']:
        raise ValueError('Original request budget exhausted; revision cannot reset it')
    identity = group['store_identity']
    updated = prompt_record(task['phone'], args.group, group['style_index'], identity['name'],
                            identity['basis'] == 'user_authorized_illustrative')
    version = len(group.get('previous_versions', [])) + 1
    history = dict(group)
    history.pop('previous_versions', None)
    history.update(revision_reason=args.reason)
    source = folder / f'group_{args.group:02d}'
    target = folder / 'revisions' / f'group_{args.group:02d}_v{version}'
    if source.exists():
        if not source.resolve().is_relative_to(folder) or not target.resolve().is_relative_to(folder):
            raise ValueError('Revision paths must stay inside this task')
        if target.exists():
            raise ValueError('Preserved revision already exists')
        target.parent.mkdir(exist_ok=True)
        source.rename(target)
        history['preserved_directory'] = str(target.relative_to(folder))
    for request in previous:
        if request['status'] == 'requesting':
            request.update(status='interrupted_result_unknown', revision_reason=args.reason)
    updated['previous_versions'] = group.get('previous_versions', []) + [history]
    task['groups'][task['groups'].index(group)] = updated
    task['status'] = 'prepared_after_feedback'
    versions = sorted({g['signboard_profile_version'] for g in task['groups']})
    task['prompt_profile'] = versions[0] if len(versions) == 1 else 'mixed_pending_revision'
    save(folder / 'task.json', task)
    (folder / 'prompts_current.txt').write_text('\n\n'.join(
        f"GROUP {g['index']}\n{g['prompt']}" for g in task['groups']), encoding='utf-8')
    print(json.dumps(dict(group=args.group, requests_retained=len(previous), version=version+1), ensure_ascii=False))
    return 0


def package(args):
    folder, task = read_job(args.job_dir)
    if any(g['status'] != 'composed' for g in task['groups']):
        raise ValueError('All groups must be complete')
    files = []
    for group in task['groups']:
        directory = folder / f"group_{group['index']:02d}"
        for name in group['tiles'] + ['preview.jpg']:
            path = directory / name
            with Image.open(path) as image:
                image.verify()
            files.append(path)
    target = Path(args.destination)
    target.mkdir(parents=True, exist_ok=True)
    suffix = '_preview' if task.get('delivery_mode') == 'style_preview' else ''
    archive = target / f"road_rescue_pinned_{task['phone']}_{task['count']}groups{suffix}_{task['task_id']}.zip"
    needs_fix = {f"group_{g['index']:02d}" for g in task['groups'] if g.get('visual_review') == 'needs_fix'}
    with zipfile.ZipFile(archive, 'x', zipfile.ZIP_DEFLATED) as package_file:
        for path in files:
            relative = path.relative_to(folder)
            name = relative.parts[0] + ('_needs_fix' if relative.parts[0] in needs_fix else '')
            package_file.write(path, (Path(name) / relative.name).as_posix())
        package_file.writestr('README.txt', task.get('delivery_note', '') + '\n每组分别使用01_left、02_center、03_right作为左、中、右三个作品封面。\npreview.jpg仅用于查看拼接效果，不作为第四张发布。\n单张1080×1440（3:4）。在实际账号封面编辑中核对裁切与位置；置顶后按左中右检查，发布先后顺序不保证最终排列。\n手机号：' + task['phone'] + '\n')
    with zipfile.ZipFile(archive) as package_file:
        if package_file.testzip() is not None or len(package_file.namelist()) != task['count'] * 4 + 1:
            raise ValueError('Archive verification failed')
    task['archive'] = str(archive)
    task['package_verified'] = True
    save(folder / 'task.json', task)
    print(json.dumps(dict(archive=str(archive), image_count=len(files), bytes=archive.stat().st_size), ensure_ascii=False))
    return 0


def add_arguments(parser):
    sub = parser.add_subparsers(dest='pinned_action', required=True)
    p = sub.add_parser('plan')
    p.add_argument('--phone', required=True)
    p.add_argument('--count', type=int, required=True)
    p.add_argument('--style-start', type=int, default=0)
    p.add_argument('--output', required=True)
    p.add_argument('--store-name', action='append', help='One shared name or repeat once per group')
    p.add_argument('--fictional-name', action='store_true', help='Attest user authorization for this illustrative name')
    p.set_defaults(handler=plan)
    p = sub.add_parser('prepare')
    p.add_argument('--phone', required=True)
    p.add_argument('--count', type=int, required=True)
    p.add_argument('--style-start', type=int, default=0)
    p.add_argument('--authorization', required=True)
    p.add_argument('--store-name', action='append', required=True, help='One shared name or repeat once per group')
    p.add_argument('--fictional-name', action='store_true', help='Attest user authorization for this illustrative name')
    p.add_argument('--confirm', action='store_true')
    p.set_defaults(handler=prepare)
    for name, handler in [('claim', claim), ('compose', compose), ('layout', layout), ('fail', fail), ('reject', reject), ('revise', revise), ('supersede', supersede), ('package', package)]:
        p = sub.add_parser(name)
        p.add_argument('--job-dir', required=True)
        if name not in ('package', 'supersede'):
            p.add_argument('--group', type=int, required=True)
        if name in ('compose', 'reject'):
            p.add_argument('--source', required=True)
        if name in ('reject', 'revise', 'layout', 'supersede'):
            p.add_argument('--reason', required=True)
        if name == 'layout':
            p.add_argument('--phone-y', type=int, required=True)
            p.add_argument('--font-size', type=int, required=True)
        if name == 'fail':
            p.add_argument('--error-type', required=True, choices=['tool_error', 'invalid_image', 'interrupted'])
        if name == 'package':
            p.add_argument('--destination', default='E:/Downloads')
        p.set_defaults(handler=handler)
