"""Deterministic five-image groups for the computer repair category."""
from __future__ import annotations

import random
from typing import Any

import visual_style_profiles
from tools import variable_catalog


PROJECT_ID = "computer_repair"
STRUCTURE_VERSION = "computer_repair_v1_random_5_images"
GENERATION_MODE = "independent_delivery_images"

DETAIL_CAMERA_STYLES = [
    "维修台前平视近景手机随手拍，完整看到设备、双手和工具",
    "从师傅肩侧约三十度斜拍，突出拆机位置和真实操作关系",
    "略高机位俯拍工作台，零件与工具摆放自然但不刻意整齐",
    "靠近设备的局部中景，保留足够环境说明真实维修地点",
    "从柜台外侧抓拍正在进行的维修动作，画面略有生活化偏斜",
    "低于视线少许的近距离拍摄，设备主体清楚且透视自然",
]

DETAIL_LIGHTING = [
    "普通白天窗光与室内日光灯混合",
    "维修台工作灯照亮拆机区域，背景保持普通店铺亮度",
    "阴天自然散射光，金属零件反光柔和",
    "傍晚店内日光灯照明，不使用电影感彩色灯光",
    "普通办公室顶灯与显示器微弱环境光，屏幕内容不可读",
]

DETAIL_WORKER_STATES = [
    "一名穿普通深色工装的维修师傅专注操作，不看镜头",
    "维修师傅戴防静电腕带，双手动作自然且符合拆装顺序",
    "师傅坐在普通工作凳上检查设备，桌面保留真实使用痕迹",
    "只出现维修人员的手臂和双手，避免摆拍式人物正脸",
    "一名师傅操作，旁边客户仅作为模糊生活背景且不看镜头",
]

DETAILS = (
    {
        "slug": "laptop_cleaning",
        "title": "笔记本清灰",
        "actions": [
            "拆开笔记本后盖清理风扇、散热鳍片和出风口积灰",
            "取下笔记本散热模组清理旧导热材料并规范重新涂覆",
            "使用软刷和气吹清理笔记本内部灰尘并检查风扇转动",
            "完成清灰后装回散热器和后盖并做基础温度检查",
        ],
        "settings": ["社区电脑维修小店", "客户家中的普通书桌", "玻璃柜台后的防静电工作位", "普通办公室空工位"],
        "props": ["防静电垫、精密螺丝刀和软毛刷", "拆下的风扇、螺丝盒和清洁布", "气吹、硅脂和分类摆放的小螺丝"],
    },
    {
        "slug": "desktop_assembly",
        "title": "台式机组装",
        "actions": [
            "在普通机箱内安装主板、电源、内存和固态硬盘",
            "安装处理器散热器并整理机箱内部供电线和数据线",
            "将显卡规范插入主板插槽并固定机箱挡板螺丝",
            "组装完成后检查各接口与风扇连接，准备通电测试",
        ],
        "settings": ["电脑维修店组装台", "社区数码店后方工作区", "普通家庭书房地面工作垫", "小型办公室设备间"],
        "props": ["普通台式机机箱、主板和内存", "螺丝刀、扎带和零件盒", "电源、散热器和未通电的显示器"],
    },
    {
        "slug": "data_recovery",
        "title": "数据恢复",
        "actions": [
            "连接故障硬盘到只读检测设备并检查硬盘识别状态",
            "拆下台式机硬盘连接到维修工作站进行只读诊断",
            "对移动硬盘接口和电路板进行外观检测与连接测试",
            "将客户硬盘与备用存储设备分别连接并核对数据复制流程",
        ],
        "settings": ["安静的电脑维修检测台", "普通数码维修店工作区", "小型数据检测工位", "社区维修铺内侧工作桌"],
        "props": ["硬盘转接底座和两块不同外形的硬盘", "防静电垫、数据线和标签纸", "只读检测盒与普通维修工作站"],
    },
    {
        "slug": "slow_computer",
        "title": "电脑卡顿诊断",
        "actions": [
            "检查台式机内存和固态硬盘连接并排查卡顿原因",
            "在不可读的检测界面下检查系统资源与硬盘健康状态",
            "拆开笔记本后盖检查散热、内存和存储部件",
            "对卡顿电脑进行硬件检测并记录需要进一步处理的部件",
        ],
        "settings": ["客户家中普通电脑桌", "维修店检测区", "小型公司办公桌", "社区电脑服务柜台"],
        "props": ["检测U盘、螺丝刀和不可读屏幕", "内存条、固态硬盘和防静电垫", "键盘鼠标与普通检测线"],
    },
    {
        "slug": "system_installation",
        "title": "系统重装",
        "actions": [
            "连接启动介质为电脑进行系统安装，屏幕文字保持不可读",
            "在系统安装前检查硬盘分区与客户资料备份设备",
            "完成系统安装后连接网络和常用外设进行基础测试",
            "在维修台为笔记本进行驱动与硬件状态检查，界面不可读",
        ],
        "settings": ["电脑维修店检测台", "客户家中普通书桌", "小型办公室工位", "社区数码服务柜台"],
        "props": ["启动U盘、移动硬盘和普通鼠标", "笔记本电源适配器与网线", "台式机显示器和有线键盘"],
    },
    {
        "slug": "boot_failure",
        "title": "电脑不开机维修",
        "actions": [
            "检测台式机电源输出并检查主板供电插头",
            "拆开笔记本后盖检查电池、充电接口和主板供电",
            "使用万用表测量不开机电脑的关键供电位置",
            "重新插装内存并检查主板诊断灯和风扇反应",
        ],
        "settings": ["社区电脑维修台", "普通电子维修铺", "客户家中书桌旁", "办公室设备检修区"],
        "props": ["万用表、电源测试器和绝缘螺丝刀", "拆开的机箱与供电线", "笔记本电池、充电器和螺丝盒"],
    },
    {
        "slug": "storage_memory_upgrade",
        "title": "硬盘内存升级",
        "actions": [
            "为笔记本安装固态硬盘和内存并固定后盖",
            "为台式机增加内存条并整理固态硬盘连接线",
            "核对新旧硬盘接口后安装升级部件",
            "完成硬件升级后进行基础识别测试，屏幕内容不可读",
        ],
        "settings": ["电脑维修店防静电工作台", "客户家中普通书桌", "公司办公电脑检修位", "社区数码店柜台后方"],
        "props": ["内存条、固态硬盘和精密螺丝刀", "硬盘托架、数据线和螺丝盒", "防静电垫与拆下的旧硬盘"],
    },
    {
        "slug": "screen_hinge_repair",
        "title": "屏幕转轴维修",
        "actions": [
            "拆开笔记本屏幕边框检查排线与转轴固定点",
            "更换损坏的笔记本屏幕并规范连接显示排线",
            "维修松动转轴和外壳固定柱并检查开合状态",
            "装回屏幕边框前测试显示与转轴阻尼，画面内容不可读",
        ],
        "settings": ["电脑维修店软垫工作台", "普通电子维修柜台", "社区维修铺内侧桌面", "客户家中宽敞书桌"],
        "props": ["屏幕组件、塑料撬片和精密螺丝刀", "显示排线、螺丝盒和清洁布", "笔记本上盖与防刮软垫"],
    },
    {
        "slug": "motherboard_repair",
        "title": "主板维修",
        "actions": [
            "在维修灯下检查电脑主板接口、供电区域和受损元件",
            "使用万用表检测主板关键供电点并记录异常位置",
            "在防静电工作台清理主板腐蚀与灰尘后进行检测",
            "更换明显损坏的小型元件并检查周边焊点",
        ],
        "settings": ["普通电脑主板维修台", "社区电子维修铺", "小型数码维修工作室", "玻璃柜台后的检测位"],
        "props": ["维修灯、万用表和防静电垫", "主板支架、镊子和零件盒", "烙铁架、清洁刷和检测线"],
    },
    {
        "slug": "network_peripheral",
        "title": "网络外设维修",
        "actions": [
            "检查电脑网口、网线和路由器连接并排查断网问题",
            "检测键盘、鼠标和USB接口的连接状态",
            "更换损坏的电脑网卡并整理机箱内部线路",
            "检查打印机连接与电脑接口，设备文字和文件内容不可读",
        ],
        "settings": ["普通家庭电脑桌", "小型办公室工位", "电脑维修店测试区", "社区商铺收银电脑旁"],
        "props": ["网线测试器、路由器和网线", "键盘鼠标与USB检测器", "普通网卡、螺丝刀和连接线"],
    },
)


@variable_catalog.managed(PROJECT_ID, "detail", finish_result="always")
def detail_prompt(group_index: int, detail: dict[str, Any], relative_index: int) -> tuple[str, dict[str, Any]]:
    rng = random.Random(f"{PROJECT_ID}:detail:{detail['slug']}:{group_index}:{relative_index}")
    scene = {
        "action": rng.choice(detail["actions"]),
        "setting": rng.choice(detail["settings"]),
        "props": rng.choice(detail["props"]),
        "camera": rng.choice(DETAIL_CAMERA_STYLES),
        "lighting": rng.choice(DETAIL_LIGHTING),
        "worker": rng.choice(DETAIL_WORKER_STATES),
        "visual_style_version": visual_style_profiles.visual_style_version(PROJECT_ID),
        "category_config_version": "computer_repair_category_content_v1",
    }
    scene["composition_signature"] = " | ".join(scene.values())
    prompt = (
        f"真实中国本地电脑维修现场，竖版普通手机随手拍照片，唯一主题是“{detail['title']}”。"
        f"地点：{scene['setting']}；核心动作：{scene['action']}；现场工具与物件：{scene['props']}。"
        f"人物状态：{scene['worker']}；拍摄方式：{scene['camera']}；光线：{scene['lighting']}。"
        "电脑型号、拆装位置、接口、工具、双手和操作顺序必须符合真实电脑维修常识；环境保留普通店铺或家庭的真实使用痕迹，"
        "不过度洁净、不刻意摆拍、不像广告。顶部3.5%至10.5%保留简洁背景供本地添加当前维修类目；"
        "画面中部49%至58.5%保留横向可读背景供本地添加醒目手机号；底部83.5%至97.5%保留安静背景，"
        "供本地添加联想、戴尔、惠普、华硕、苹果维修及清灰、组装、数据恢复、电脑卡顿、系统重装服务词。"
        "关键人脸、双手、设备故障点和核心操作不得被这些区域遮挡。"
        "原始图片不要生成电话号码、中文标题、价格、二维码、水印、品牌Logo、可读系统界面、文件名或客户资料。"
        "严格排除手机维修、家电维修、汽车救援、货车维修、拖车、轮胎、搭电、欧美环境、豪华科技展厅、"
        "电竞广告海报、插画、CG、3D、畸形手指、不合理工具和危险带电操作。"
    )
    prompt += visual_style_profiles.prompt_suffix(PROJECT_ID, "service_detail")
    return prompt, scene


def build_random_pool_rows(group_index: int, phone: str) -> list[dict[str, Any]]:
    roles = random.Random(f"{PROJECT_ID}:roles:{group_index}").sample(list(DETAILS), 5)
    rows: list[dict[str, Any]] = []
    for position, detail in enumerate(roles, start=1):
        prompt, scene = detail_prompt(group_index, detail, position)
        rows.append({
            "role": "detail",
            "generation_kind": "detail",
            "generation_role": "detail",
            "delivery_position": position,
            "prompt": prompt,
            "scene": scene,
            "service_role": detail["title"],
            "title": detail["title"],
            "final_size": "1024x1536",
            "height_profile_id": "full_1536",
            "structure_version": STRUCTURE_VERSION,
            "generation_mode": GENERATION_MODE,
        })
    return rows
