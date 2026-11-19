"""Deterministic storefront-plus-detail groups for computer repair."""
from __future__ import annotations

import random
from typing import Any

import visual_style_profiles
from tools import variable_catalog


PROJECT_ID = "computer_repair"
STRUCTURE_VERSION = "computer_repair_v2_1cover_4random_details"
GENERATION_MODE = "independent_delivery_images"

COVER_SIGN_STYLES = [
    "略有使用痕迹的蓝白烤漆实体门头，板材接缝和固定螺丝自然可见",
    "普通红白铝塑板实体招牌，边缘有轻微褪色但文字区域整洁",
    "深蓝配浅灰的社区小店门头，亚克力字与板面投影关系真实",
    "白底蓝字的简洁灯箱门头，白天未开灯且不带科技感图标",
    "橙灰配色的普通街边招牌，包边、雨痕和墙面安装结构清楚",
]

COVER_FACADES = [
    "老小区底商的一间电脑维修小店，卷帘门半开，玻璃门旁有普通展示柜",
    "街边一层窄门面，门口摆着待检修主机和纸箱，通道保持可通行",
    "社区数码街里的独立维修铺，玻璃门和旧瓷砖墙保留真实使用痕迹",
    "居民区转角的小型电脑服务店，门前台阶和相邻商铺自然入镜",
    "普通沿街底商，开间不大，店内维修台和配件货架从门口可以看到",
]

COVER_INTERIORS = [
    "店内维修台上有一台拆开侧板的主机，师傅正在检查线材",
    "店内可见笔记本维修台、配件抽屉和少量待维修电脑",
    "店内一侧摆放普通显示器和配件货架，另一侧正在进行主机装机",
    "店内有一台适度RGB灯效的侧透高配主机正在做真实压力测试",
    "店内工作台有万用表、螺丝盒和拆开的电脑，物品自然但不杂乱失控",
]

COVER_CAMERAS = [
    "街对面略偏左的平视手机抓拍，门头与入口完整可见",
    "从门店右前方约三十度斜拍，保留相邻街面和真实透视",
    "站在店门外稍近距离拍摄，门头、玻璃门和部分店内工作区同时入镜",
    "路过门店时略微偏斜的手机随手拍，构图自然且门头仍清楚",
    "从左侧人行道稍高机位拍摄，门口台阶和营业状态自然可见",
]

COVER_LIGHTING = [
    "普通晴天散射光与店内日光灯混合",
    "阴天柔和自然光，玻璃反光不过曝",
    "傍晚街道自然亮度与店内白色日光灯混合，不使用电影感灯光",
    "上午侧光照到门面，招牌和店内仍保持正常曝光",
]

COVER_STREET_ELEMENTS = [
    "门前有普通电动车和少量纸箱，但不遮挡入口与招牌",
    "人行道有自然磨损和一两位模糊路人，不看镜头",
    "相邻商铺边缘与社区街景少量入镜，不出现可读店名",
    "门口有维修师傅搬运一台主机，动作自然且不摆拍",
    "街面较安静，保留台阶、排水沟和墙面旧痕等生活细节",
]

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
            "为配置较好的侧透主机安装独立显卡、一体式水冷和高速固态硬盘",
            "组装完成后检查各接口与风扇连接，准备通电测试",
        ],
        "settings": ["电脑维修店组装台", "社区数码店后方工作区", "普通家庭书房地面工作垫", "小型办公室设备间"],
        "props": ["普通台式机机箱、主板和内存", "侧透机箱、较大的独立显卡和一体式水冷排", "螺丝刀、扎带和零件盒", "电源、散热器和未通电的显示器"],
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
    {
        "slug": "high_end_gaming_build",
        "title": "高配主机组装",
        "actions": [
            "在侧透机箱内安装高性能独立显卡、双通道内存和高速固态硬盘",
            "为高配置主机安装一体式水冷并规范连接水泵、冷排和机箱风扇",
            "整理高功率电源模组线并检查显卡独立供电接口是否插紧",
            "完成高配整机装配后检查风扇方向、显卡支撑和线材空间",
        ],
        "settings": ["电脑维修店整机组装台", "社区数码店侧透主机展示旁的工作位", "普通装机工作室", "客户家中宽敞电脑桌"],
        "props": ["侧透中塔机箱、大尺寸独立显卡和一体式水冷", "模组电源、双条内存和高速固态硬盘", "显卡支撑架、扎带和精密螺丝刀", "已点亮但灯效克制的RGB风扇与维修工具"],
    },
    {
        "slug": "liquid_cooling_tuning",
        "title": "水冷主机调试",
        "actions": [
            "检查一体式水冷泵线、冷排风扇方向和处理器温度",
            "重新固定水冷头并规范涂覆导热材料，排查温度异常",
            "调试侧透主机风扇转速与散热风道并观察运行状态",
            "对完成装机的水冷主机进行温度和噪音检查，屏幕数据不可读",
        ],
        "settings": ["电脑维修店测试台", "普通装机工作室", "社区数码店后方检测位", "客户家中电脑桌"],
        "props": ["侧透机箱、一体式水冷头和冷排", "温度探头、导热材料和维修工具", "适度RGB风扇、显卡和整洁但真实的线材", "不可读监测界面与普通键盘鼠标"],
    },
    {
        "slug": "blue_screen_crash_diagnosis",
        "title": "蓝屏死机诊断",
        "actions": [
            "对频繁蓝屏的台式机逐项检查内存、固态硬盘和驱动状态",
            "交换测试内存插槽并进行稳定性检测，屏幕内容保持不可读",
            "检查蓝屏电脑的硬盘健康、供电连接和散热状态",
            "根据故障现象对主板、内存和显卡进行最小系统排查",
        ],
        "settings": ["电脑维修店故障检测台", "普通办公室空工位", "社区数码维修柜台", "客户家中电脑桌"],
        "props": ["内存条、检测U盘和防静电垫", "主板诊断卡、固态硬盘和螺丝刀", "拆开侧板的台式机与不可读测试界面", "标签清楚但无客户信息的替换测试部件"],
    },
    {
        "slug": "no_signal_diagnosis",
        "title": "黑屏无信号诊断",
        "actions": [
            "检查黑屏主机的显卡供电、视频接口和内存接触状态",
            "使用替换显卡和测试显示器排查开机无信号问题",
            "重新插装内存与显卡并观察主板诊断灯和风扇反应",
            "对能够通电但没有显示输出的主机进行最小系统检测",
        ],
        "settings": ["电脑维修店检测工位", "普通装机工作室", "小型办公室设备检修区", "社区维修铺内侧工作台"],
        "props": ["测试显示器、视频线和替换显卡", "拆开侧板的主机、内存和主板诊断灯", "电源测试器、螺丝刀和防静电垫", "无可读内容的黑屏显示器与普通键盘"],
    },
    {
        "slug": "thermal_throttling_diagnosis",
        "title": "过热降频诊断",
        "actions": [
            "检查高负载时频繁降频的主机散热器、风扇和机箱风道",
            "拆下处理器散热器清理旧导热材料并检查接触压力",
            "对显卡与处理器进行温度稳定性测试，界面数字不可读",
            "清理冷排和防尘网并重新规划进出风方向以排查过热",
        ],
        "settings": ["电脑维修店压力测试台", "普通装机工作室", "客户家中电脑桌", "社区数码店后方工作位"],
        "props": ["塔式散热器、机箱风扇和温度探头", "一体式水冷排、软刷和导热材料", "侧透高配主机与不可读压力测试界面", "积灰防尘网、气吹和维修工具"],
    },
)


@variable_catalog.managed(PROJECT_ID, "cover", finish_result="always")
def cover_prompt(group_index: int, phone: str) -> tuple[str, dict[str, Any]]:
    rng = random.Random(f"{PROJECT_ID}:cover:{group_index}")
    scene = {
        "sign_style": rng.choice(COVER_SIGN_STYLES),
        "facade": rng.choice(COVER_FACADES),
        "interior": rng.choice(COVER_INTERIORS),
        "camera": rng.choice(COVER_CAMERAS),
        "lighting": rng.choice(COVER_LIGHTING),
        "street": rng.choice(COVER_STREET_ELEMENTS),
        "visual_style_version": visual_style_profiles.visual_style_version(PROJECT_ID),
        "category_config_version": "computer_repair_category_content_v3",
    }
    scene["composition_signature"] = " | ".join(scene.values())
    prompt = (
        "一张真实中国街边电脑维修小门店的竖版普通手机随手拍照片，作为本组第一张门店封面。"
        "必须像顾客实际路过拍到的正在营业的小店，不是招牌设计稿、广告海报、门店效果图、科技展厅或高端连锁店。"
        f"建筑与门面：{scene['facade']}；实体门头：{scene['sign_style']}；店内状态：{scene['interior']}。"
        f"拍摄机位：{scene['camera']}；光线：{scene['lighting']}；街边生活元素：{scene['street']}。"
        "主招牌必须是建筑上真实安装的实体板面，清楚准确写有“电脑维修”四个中文大字；"
        f"同一块实体主招牌内还必须清楚完整写有“电话：{phone}”或“联系电话：{phone}”，每个数字准确可读。"
        "门头电话优先位于类目名称下方或右侧联系信息区，不得放在门下横幅、立柱、墙面、车辆、立牌、店内背景或悬浮字幕上。"
        "招牌文字和电话要与板面保持一致透视、光照、阴影、反光及安装关系，不生成其他店名、其他号码、价格、地区或服务承诺。"
        "店内外可以看到真实的笔记本、台式主机、显示器、配件货架和维修工具；若出现侧透高配主机或适度RGB灯效，"
        "必须处于装机、检测或维修状态，不能像电竞产品广告。允许一名穿普通深色工装的师傅自然工作且不看镜头。"
        "画面中部49%至58.5%保留连续且相对安静的真实背景，避开人脸、招牌电话和核心维修动作，供本地程序叠加醒目大电话；"
        "底部83.5%至97.5%保留街面、台阶或安静背景，供本地程序叠加五个品牌维修词和五个电脑服务词。"
        "原图不要生成中部电话条、底部服务词、按钮、卡片、宫格、二维码、水印、真实品牌Logo、可读系统界面或客户资料。"
        "严格排除手机维修、家电维修、汽车救援、货车维修、拖车、轮胎、搭电、欧美街景、豪华科技展厅、"
        "电竞广告海报、插画、CG、3D、乱码堆叠、畸形人物和不合理维修工具。"
    )
    prompt += visual_style_profiles.prompt_suffix(PROJECT_ID, "storefront_cover")
    return prompt, scene


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
        "category_config_version": "computer_repair_category_content_v3",
    }
    scene["composition_signature"] = " | ".join(scene.values())
    prompt = (
        f"真实中国本地电脑维修现场，竖版普通手机随手拍照片，唯一主题是“{detail['title']}”。"
        f"地点：{scene['setting']}；核心动作：{scene['action']}；现场工具与物件：{scene['props']}。"
        f"人物状态：{scene['worker']}；拍摄方式：{scene['camera']}；光线：{scene['lighting']}。"
        "电脑型号、拆装位置、接口、工具、双手和操作顺序必须符合真实电脑维修常识；环境保留普通店铺或家庭的真实使用痕迹，"
        "不过度洁净、不刻意摆拍、不像广告。高配主机、装机或水冷调试主题允许出现侧透机箱、大尺寸独立显卡、"
        "一体式水冷和适度RGB灯效，但必须表现正在装机、排障或压力测试的真实过程，不能只展示成品电脑。"
        "故障诊断主题必须清楚呈现故障对象、检测工具和排查动作之间的合理关系。顶部3.5%至10.5%保留简洁背景供本地添加当前维修类目；"
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
    roles = random.Random(f"{PROJECT_ID}:roles:{group_index}").sample(list(DETAILS), 4)
    cover_text, cover_scene = cover_prompt(group_index, phone)
    rows: list[dict[str, Any]] = [{
        "role": "cover",
        "generation_kind": "cover",
        "generation_role": "cover",
        "delivery_position": 1,
        "prompt": cover_text,
        "scene": cover_scene,
        "service_role": None,
        "final_size": "1024x1536",
        "height_profile_id": "full_1536",
        "structure_version": STRUCTURE_VERSION,
        "generation_mode": GENERATION_MODE,
    }]
    for position, detail in enumerate(roles, start=2):
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
