"""Append deterministic home-appliance 1-cover + 8-detail production groups."""

from __future__ import annotations
from tools import runtime_paths

from tools import variable_catalog

import argparse
import hashlib
import json
import random
from pathlib import Path
from typing import Any

import visual_style_profiles


ROOT = Path(__file__).resolve().parent
PROJECT_ID = "home_appliance_repair"
PROJECT_DIR = ROOT / "projects" / PROJECT_ID
BUSINESS_PATH = ROOT / ".runtime" / "projects" / PROJECT_ID / "business.json"


COVER_SIGN_STYLES = [
    "蓝底白字的普通旧灯箱，边缘有轻微灰尘和固定螺丝",
    "白底深蓝字的铝塑板招牌，边框略有使用痕迹",
    "暗红底米白字的喷绘灯箱，颜色有自然轻微褪色",
    "墨绿底白字的亚克力立体字门头，材质朴素",
    "灰白底红蓝双色字的铝塑板门头",
    "黄底黑字的普通吸塑灯箱，不做高端品牌感",
    "米白底深绿字的社区小店招牌，边缘略旧",
    "橙灰拼色的普通门头板，文字为实体贴装字",
    "浅蓝底深蓝字的旧式灯箱，表面有自然反光",
    "砖红底白字的窄长招牌，安装在卷帘门上方",
    "白底红字配深灰服务条的实用型门头",
    "深灰底亮黄字的普通招牌，不使用黑金奢华风格",
]

COVER_FACADES = [
    "老小区一楼白色小瓷砖底商，玻璃双开门已经打开",
    "临街窄门面，半开的旧卷帘门和铝合金玻璃门并存",
    "县城生活街普通门店，门口有两级水泥台阶",
    "社区沿街店铺，墙面有空调外机和自然老化痕迹",
    "城中村街边小店，门框、雨棚和电线都符合真实生活状态",
    "住宅楼底层转角门面，一侧能看到相邻商铺边缘",
    "普通商业街单开间店铺，门口铺着略旧的防滑垫",
    "旧居民楼下的小维修铺，门口空间不大但正在营业",
    "街巷入口处的家电维修门店，招牌与建筑墙体一体安装",
    "靠近菜市场的普通小店，玻璃门上有自然反光和使用痕迹",
    "小区外围底商，门口有低矮台阶和金属门框",
    "道路转角处的窄长门脸，店内纵深可见",
]

COVER_INTERIORS = [
    "店内能看到旧柜台、万用表、螺丝刀和拆开的洗衣机后盖",
    "店内摆着洗衣机、热水器外壳、工具箱和零件架",
    "玻璃柜台后方是手机维修台，旁边还有家电检测工具",
    "门内能看到空调压力表、铜管盘、真空泵和工作台",
    "维修台上有电路板、烙铁、检测仪，墙边放着一台旧冰箱",
    "店内有油烟机滤网、燃气灶零件、清洗盆和普通货架",
    "柜台边放着电脑主机和显示器，后方是家电零件抽屉",
    "门口附近有拆开面板的洗衣机，师傅正整理维修工具",
    "店内纵深处可见空调内机、热水器和一排常用工具",
    "狭小店内有真实杂物、纸箱、零件盒和正在维修的电器",
    "柜台旁有清洗机、软管、刷具和待处理的油烟机部件",
    "门内工作区能看到电视后盖、电源板和普通维修灯",
]

COVER_CAMERAS = [
    "路人站在街对面略偏左的平视手机抓拍，门头完整",
    "从门店左前方约三十度斜拍，能看到门内纵深",
    "从门店右前方略近距离斜拍，保留街道前景",
    "站在门口外侧轻微仰拍，门头和店内同时清楚",
    "从台阶下方稍微抬高手机拍摄，透视自然",
    "经过店门时的随手拍角度，画面有轻微生活化偏斜",
    "从停放电动车旁边向店门拍摄，前景自然遮挡少量边缘",
    "站在街沿稍远位置拍摄，门面与相邻墙体共同入镜",
    "靠近玻璃门的近景拍摄，仍保留完整门头和街道边缘",
    "从店门右侧台阶上轻微俯拍，店内设备更明显",
]

COVER_STREET_ELEMENTS = [
    "门口停着一辆无品牌普通电动车，车牌不可读",
    "画面边缘有一辆普通轿车车头，车牌模糊不可读",
    "门前有塑料凳、工具包和日常街道路面",
    "街沿停着电动三轮车，不能出现可读车牌",
    "门口有快递箱、扫帚和真实使用中的台阶",
    "相邻墙边停着自行车，路面有自然修补痕迹",
    "玻璃门外有一只普通工具箱和盘好的软管",
    "街道边缘有树影、井盖和少量生活杂物",
    "门旁能看到小区门牌和空调外机，但不出现具体地址宣传",
    "前景经过一辆模糊的电动车，主体门店仍清楚",
]

COVER_LIGHTING = [
    "普通多云白天，自然散射光",
    "上午侧光，店内日光灯已经打开",
    "午后树影落在墙面和台阶上",
    "阴天街景，玻璃门反光柔和",
    "傍晚前的自然光，门头灯箱刚刚亮起",
    "雨后但未下雨，路面略湿并有真实反光",
]

LOGO_SYMBOLS = [
    "扳手与插头组合",
    "齿轮与闪电组合",
    "洗衣机门圈与小扳手组合",
    "空调风叶与螺丝刀组合",
    "房屋轮廓与电源插头组合",
    "水滴与齿轮组合",
    "工具箱与电源键组合",
    "风扇叶片与维修钳组合",
    "电路板线条与扳手组合",
    "显示屏轮廓与小齿轮组合",
]

LOGO_FRAMES = [
    "圆形线框",
    "直角方框",
    "六边形线框",
    "简化盾牌轮廓",
    "横向椭圆铭牌",
    "无外框的紧凑图形",
]

LOGO_ACCENTS = [
    "单色实心",
    "双色线描",
    "主图形加一个小圆点",
    "主图形加短横线底座",
    "轻微立体凸字材质",
]

SERVICE_LINES = [
    "空调维修｜洗衣机维修｜冰箱维修｜热水器维修｜油烟机维修",
    "家电清洗｜空调加氟｜空调移机｜燃气灶维修｜电视维修",
    "空调维修｜冰箱维修｜洗衣机维修｜电脑维修｜手机维修",
    "热水器维修｜油烟机维修｜燃气灶维修｜家电清洗｜上门检修",
    "洗衣机维修｜空调安装｜冰箱检修｜电视维修｜数码维修",
]

DETAIL_CAMERA_STYLES = [
    "平视近景手机拍摄，重点动作清楚",
    "从师傅左后方轻微俯拍，工具与设备同框",
    "从设备右侧斜拍，保留真实室内环境",
    "稍远的工作现场全景，人物动作自然",
    "靠近工作台的手部特写，但设备结构仍可辨认",
    "门口方向拍向室内，带少量生活环境前景",
    "从较低机位斜向上拍摄，透视不过分",
    "站在客户视角随手拍摄，画面不刻意摆拍",
    "设备正侧面构图，师傅不看镜头",
    "轻微高机位记录整个维修步骤，画面稳定",
]

DETAIL_LIGHTING = [
    "普通室内顶灯与窗外自然光混合",
    "阴天自然光，亮度真实不过度通透",
    "上午侧光进入房间，阴影自然",
    "傍晚室内灯光，色温略暖但细节清楚",
    "阳台自然光，设备表面有轻微反光",
    "维修灯补光，周围环境仍保持普通生活感",
    "厨房或卫生间常见冷白灯光",
    "店内日光灯照明，背景略显杂乱但可信",
]

DETAIL_WORKER_STATES = [
    "一名穿深蓝普通工装的师傅专注操作，不看镜头",
    "一名穿灰色工作马甲的师傅半蹲检查设备",
    "一名穿旧蓝色工服的师傅戴普通防护手套操作",
    "一名维修师傅侧身工作，工具包放在脚边",
    "一名师傅跪坐在防护垫上检修，姿势自然",
    "一名穿深色长袖工装的师傅用检测仪读数",
    "一名维修人员背对镜头拆装零件，衣服无品牌标志",
    "一名师傅与设备保持真实工作距离，手部结构自然",
]

DETAILS = [
    {
        "slug": "washing_machine_repair",
        "title": "洗衣机维修",
        "actions": [
            "拆开滚筒洗衣机下部面板检查排水泵和过滤器",
            "更换洗衣机进水阀并检查进水管接口",
            "处理滚筒洗衣机门封圈渗水并重新压紧卡箍",
            "打开洗衣机后盖检查皮带、电机和接线端子",
            "更换洗衣机减震器并检查内筒晃动",
            "诊断洗衣机轴承异响，检查皮带轮与固定螺丝",
            "用万用表检测洗衣机控制板和电源线路",
            "疏通洗衣机排水管并清理积水和毛絮",
            "调整波轮洗衣机水平脚并做脱水平衡检查",
            "拆下波轮盘清理底部污垢并检查传动轴",
        ],
        "settings": [
            "普通老小区卫生间洗衣角",
            "住宅阳台洗衣区",
            "出租屋狭小厨房旁的洗衣机位置",
            "家电维修店门内工作位",
            "一楼住宅后阳台的水泥地面",
            "社区自助洗衣房的单台设备旁",
        ],
        "props": ["接水盆和旧毛巾", "万用表和螺丝盒", "钳子与手电筒", "拆下的后盖和小零件盘", "软管与清洁刷"],
    },
    {
        "slug": "ac_refrigerant",
        "title": "空调加氟",
        "actions": [
            "将压力表组连接到空调室外机服务阀进行压力检测",
            "在铜管喇叭口处使用检漏液检查制冷剂泄漏",
            "修复管路后连接真空泵进行抽真空和保压",
            "检查空调室外机高低压阀和阀帽密封状态",
            "使用电子检漏仪沿铜管接头逐段排查泄漏点",
            "更换破损保温棉后复测铜管温度和运行压力",
            "清理冷凝器附近杂物并检测制冷系统运行状态",
            "检查室内机结霜现象并结合压力表进行诊断",
            "在楼顶多台外机区域为其中一台做制冷剂检测",
            "按电子秤读数为阳台空调外机规范补充制冷剂",
        ],
        "settings": [
            "普通住宅阳台的空调外机旁",
            "老小区一楼院内的外机位置",
            "居民楼公共平台的安全作业区域",
            "沿街小店门外的低位空调外机旁",
            "楼顶平整平台上的空调机组旁",
            "封闭阳台窗边的外机检修位置",
        ],
        "props": ["双表压力表和制冷剂软管", "真空泵与工具包", "电子秤和无品牌制冷剂瓶", "检漏液喷壶与扳手", "电子检漏仪和保温棉"],
    },
    {
        "slug": "ac_installation",
        "title": "空调移机安装",
        "actions": [
            "测量墙面并校正空调室内机安装挂板",
            "使用集尘罩在墙面开空调管线孔",
            "整理铜管、排水管和电源线后穿过墙孔",
            "两人配合将空调室内机挂上安装板并检查水平",
            "在安全阳台内固定空调外机支架和减震垫",
            "移机连接完成后用真空泵对新管路抽真空",
            "调整排水管坡度并进行排水测试",
            "拆除旧空调室内机并分类收好螺丝和挂板",
            "使用密封泥填补空调管线墙孔并整理包扎带",
            "安装结束后测试送风温度、摆风和遥控功能",
        ],
        "settings": [
            "普通住宅客厅",
            "老小区卧室",
            "沿街小店内墙",
            "出租房简洁房间",
            "封闭阳台与客厅交界处",
            "社区办公室普通工作间",
        ],
        "props": ["水平尺和电钻", "铜管盘与排水软管", "真空泵和压力表", "帆布工具包与螺丝盒", "防尘布和密封泥"],
    },
    {
        "slug": "range_hood_repair",
        "title": "油烟机维修",
        "actions": [
            "拆下油烟机滤网检查风轮和电机积油情况",
            "更换油烟机启动电容并整理内部接线",
            "拆卸风轮进行深度除油并检查固定螺母",
            "打开控制面板检查按键板和电源线路",
            "更换油烟机照明灯和老化线束",
            "检查排烟软管接口松脱和漏风问题",
            "处理油烟机运行振动并校正风轮位置",
            "检测油烟机电源板保险和输出电压",
            "清洗油杯、滤网和内腔油污后重新装配",
            "测试油烟机不同档位的吸力和噪声",
        ],
        "settings": [
            "普通家庭中式厨房",
            "老小区狭窄厨房",
            "出租屋小厨房",
            "街边小餐馆非营业时的后厨",
            "家电维修店清洗工作台",
            "开放式厨房灶台区域",
        ],
        "props": ["除油剂和旧毛巾", "螺丝刀与零件盘", "拆下的滤网和油杯", "万用表与接线端子", "清洗盆和软毛刷"],
    },
    {
        "slug": "water_heater_repair",
        "title": "热水器维修",
        "actions": [
            "打开电热水器检修盖检查温控器和线路",
            "拆下电热水器加热管并清理水垢",
            "更换电热水器镁棒并展示自然水垢沉积",
            "检查热水器进出水阀和安全阀是否渗漏",
            "清理燃气热水器燃烧排并检查点火针",
            "检查燃气热水器排烟管接口和固定卡箍",
            "用万用表检测热水器温度传感器和电源板",
            "更换热水器老化密封圈并重新紧固法兰",
            "清理热水器进水过滤网并测试水流",
            "维修完成后检查加热、温度显示和漏水情况",
        ],
        "settings": [
            "普通家庭卫生间",
            "住宅生活阳台",
            "老小区厨房外的小阳台",
            "出租屋浴室门口",
            "家电维修店内检测架",
            "社区公寓的洗浴间",
        ],
        "props": ["水桶和接水布", "万用表与绝缘螺丝刀", "拆下的检修盖和螺丝", "扳手与密封圈", "清洁刷和水垢碎屑"],
    },
    {
        "slug": "gas_stove_repair",
        "title": "燃气灶维修",
        "actions": [
            "检查燃气灶点火针位置并更换损坏点火组件",
            "更换燃气灶熄火保护热电偶并固定线路",
            "清理燃烧器火孔并重新放正火盖",
            "拆开灶具底壳检查喷嘴和进气通道",
            "检查燃气灶阀体和旋钮连接机构",
            "调整燃气灶风门并观察稳定蓝色火焰",
            "用肥皂水检查灶具软管接头的密封状态",
            "更换变形炉架并检查灶面固定点",
            "清理燃气灶电池盒锈蚀并更换连接片",
            "维修后逐个测试点火、火焰和熄火保护功能",
        ],
        "settings": [
            "普通家庭厨房灶台",
            "老小区瓷砖厨房",
            "出租屋小型灶台",
            "家电维修店门内工作台",
            "社区餐饮小店停业检修时的后厨",
            "开放式厨房操作台",
        ],
        "props": ["肥皂水喷瓶和扳手", "螺丝刀与点火配件", "软毛刷和拆下的火盖", "万用表和小零件盒", "手套与旧抹布"],
    },
    {
        "slug": "phone_repair",
        "title": "手机维修",
        "actions": [
            "使用吸盘和塑料撬片拆开手机破损屏幕",
            "拆开手机后盖更换鼓包电池并清理残胶",
            "在维修灯下清理并更换手机充电接口",
            "拆装手机后置摄像头模组并检查排线",
            "更换手机听筒和扬声器防尘网",
            "在显微镜下检查手机主板焊点和受损元件",
            "加热并拆除破损后盖玻璃，准备重新粘合",
            "重新连接手机屏幕排线并进行显示触控测试",
            "对轻微进水手机主板做规范清洁和检测",
            "更换手机侧键排线并整理微型螺丝",
        ],
        "settings": [
            "普通街边维修店玻璃柜台",
            "家电维修店内的数码维修角",
            "狭小手机维修工作台",
            "社区底商柜台后的维修位",
            "普通电子维修铺的显微镜工作位",
            "靠窗的小型维修桌",
        ],
        "props": ["防静电垫和微型螺丝", "吸盘与塑料撬片", "维修灯和镊子", "热台与排线盒", "显微镜和小刷子"],
    },
    {
        "slug": "computer_repair",
        "title": "电脑维修",
        "actions": [
            "打开台式电脑机箱清理灰尘并检查风扇",
            "安装固态硬盘和内存并整理数据线",
            "检测台式电脑电源输出并检查供电插头",
            "重新插装显卡并清理金手指和插槽灰尘",
            "拆开笔记本后盖清理风扇并更换导热材料",
            "更换笔记本键盘并连接排线",
            "维修笔记本转轴和松动外壳固定点",
            "检查笔记本屏幕排线和显示接口",
            "在维修台进行系统故障诊断，屏幕文字不可读",
            "组装台式电脑并规范整理机箱内部线材",
        ],
        "settings": [
            "普通家电维修店电脑工作台",
            "社区电脑维修小店",
            "客户家中的普通书桌旁",
            "玻璃柜台后的防静电工作位",
            "狭小店铺内的台式机检测区",
            "普通办公室空工位",
        ],
        "props": ["螺丝盒和除尘刷", "防静电垫与螺丝刀", "万用表和电源测试器", "硅脂与清洁布", "键盘和无文字测试显示器"],
    },
]


V3_STRUCTURE_VERSION = "home_appliance_repair_v3_1cover_1triptych_3details"
V3_GENERATION_MODE = "independent_triptych_panels"
RANDOM_POOL_STRUCTURE_VERSION = "home_appliance_repair_v4_random_5_images"
RANDOM_POOL_GENERATION_MODE = "independent_delivery_images"
V3_HEIGHTS = (
    {"id": "height_1408", "width": 1024, "height": 1408},
    {"id": "height_1472", "width": 1024, "height": 1472},
    {"id": "height_1536", "width": 1024, "height": 1536},
)
V3_LAYOUTS = (
    {"id": "stacked_equal", "panels": (
        {"panel_index": 1, "x": 0.0, "y": 0.0, "width": 1.0, "height": 0.333333},
        {"panel_index": 2, "x": 0.0, "y": 0.333333, "width": 1.0, "height": 0.333334},
        {"panel_index": 3, "x": 0.0, "y": 0.666667, "width": 1.0, "height": 0.333333},
    )},
    {"id": "top_feature_bottom_pair", "panels": (
        {"panel_index": 1, "x": 0.0, "y": 0.0, "width": 1.0, "height": 0.56},
        {"panel_index": 2, "x": 0.0, "y": 0.56, "width": 0.5, "height": 0.44},
        {"panel_index": 3, "x": 0.5, "y": 0.56, "width": 0.5, "height": 0.44},
    )},
    {"id": "top_pair_bottom_feature", "panels": (
        {"panel_index": 1, "x": 0.0, "y": 0.0, "width": 0.5, "height": 0.44},
        {"panel_index": 2, "x": 0.5, "y": 0.0, "width": 0.5, "height": 0.44},
        {"panel_index": 3, "x": 0.0, "y": 0.44, "width": 1.0, "height": 0.56},
    )},
)
STORE_NAME_PREFIXES = (
    "诚信", "顺达", "万家", "安心", "便民", "佳诚", "恒信", "惠民", "兴旺", "速达",
    "宏达", "永兴", "精诚", "邻家", "百顺", "鑫诚", "诚鑫", "佳乐", "同城", "放心",
    "利民", "众诚", "好帮手", "新诚", "安顺",
)
STORE_NAME_SUFFIXES = ("家电维修", "家电服务", "家电维修服务部", "家电综合维修")

V3_EXTRA_DETAILS = (
    {
        "slug": "ac_cleaning",
        "title": "空调清洗",
        "actions": [
            "拆下空调室内机滤网并使用防水罩清洗蒸发器",
            "在接水防护完整的情况下清洗壁挂空调风轮和导风板",
            "清理空调外机换热器表面灰尘并检查散热状态",
            "清洗完成后装回滤网并测试送风和排水",
        ],
        "settings": ["普通住宅客厅", "老小区卧室", "沿街小店室内", "出租房空调位置"],
        "props": ["空调清洗罩和接水管", "软毛刷和清洗机", "防水布与工具包", "拆下的滤网和接水桶"],
    },
    {
        "slug": "refrigerator_repair",
        "title": "冰箱维修",
        "actions": [
            "拆开冰箱后部检修盖检查压缩机启动器与线路",
            "检查冰箱冷藏室排水孔和蒸发器结霜情况",
            "用万用表检测冰箱温控器、风扇和电源线路",
            "更换冰箱门封条并检查箱门密封状态",
            "检查冰箱制冷管路后进行规范检漏和运行测试",
        ],
        "settings": ["普通家庭厨房", "住宅餐厅冰箱位置", "社区家电维修店工作位", "出租屋生活区"],
        "props": ["万用表与螺丝盒", "检漏工具和维修灯", "拆下的后盖与零件盘", "温度计和普通工具包"],
    },
    {
        "slug": "television_repair",
        "title": "电视维修",
        "actions": [
            "拆开液晶电视后盖检查电源板和主板连接",
            "用万用表检测电视电源板输出与保险部件",
            "检查电视背光排线和灯条连接状态",
            "更换电视老化电容并整理内部线束",
            "装回电视后盖前进行通电和显示测试，屏幕内容不可读",
        ],
        "settings": ["普通家庭客厅", "家电维修店工作台", "社区维修铺检测区", "住宅餐厅靠墙电视位置"],
        "props": ["万用表与绝缘螺丝刀", "维修灯和零件盒", "拆下的后盖和螺丝盘", "防静电垫与检测线"],
    },
)


def v3_detail_definitions() -> list[dict[str, Any]]:
    legacy = {item["slug"]: item for item in DETAILS}
    selected = [
        {**legacy["ac_refrigerant"], "title": "空调维修"},
        V3_EXTRA_DETAILS[0],
        {**legacy["ac_installation"], "title": "空调移机"},
        legacy["washing_machine_repair"],
        V3_EXTRA_DETAILS[1],
        legacy["water_heater_repair"],
        legacy["range_hood_repair"],
        legacy["gas_stove_repair"],
        V3_EXTRA_DETAILS[2],
        legacy["computer_repair"],
    ]
    return [dict(item) for item in selected]


def load_json(path: Path) -> dict[str, Any]:
    return runtime_paths.read_json(path)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def atomic_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    temporary.replace(path)


def prompt_hash(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def logo_description(group_index: int) -> str:
    combination_count = len(LOGO_SYMBOLS) * len(LOGO_FRAMES) * len(LOGO_ACCENTS)
    value = (group_index - 1) % combination_count
    symbol = LOGO_SYMBOLS[value % len(LOGO_SYMBOLS)]
    value //= len(LOGO_SYMBOLS)
    frame = LOGO_FRAMES[value % len(LOGO_FRAMES)]
    value //= len(LOGO_FRAMES)
    accent = LOGO_ACCENTS[value % len(LOGO_ACCENTS)]
    return f"{frame}内的{symbol}，{accent}"


@variable_catalog.managed('home_appliance_repair','cover',finish_result='always')
def cover_prompt(group_index: int, phone: str, variant: int = 0) -> tuple[str, dict[str, Any]]:
    rng = random.Random(f"{PROJECT_ID}:cover:{group_index}:{variant}")
    visual_version = visual_style_profiles.visual_style_version(PROJECT_ID)
    # Legacy 1+8 records remain immutable history even after the dashboard
    # moves new batches to the v3 five-image structure.
    category_version = "home_appliance_repair_category_content_v1"
    scene = {
        "sign_style": rng.choice(COVER_SIGN_STYLES),
        "facade": rng.choice(COVER_FACADES),
        "interior": rng.choice(COVER_INTERIORS),
        "camera": rng.choice(COVER_CAMERAS),
        "street": rng.choice(COVER_STREET_ELEMENTS),
        "lighting": rng.choice(COVER_LIGHTING),
        "logo": logo_description(group_index + variant * 61),
        "service_line": SERVICE_LINES[(group_index - 1 + variant) % len(SERVICE_LINES)],
        "visual_style_version": visual_version,
        "category_config_version": category_version,
    }
    scene["composition_signature"] = " | ".join(scene.values())
    prompt = (
        "一张真实中国街边家电维修小门店的竖版9:16手机随手拍照片。画面必须像普通顾客在街边实际拍到的门店，"
        "不是AI概念设计图，不是广告海报，不是高端连锁品牌店，不使用影棚布光或电影感构图。"
        f"建筑与门面：{scene['facade']}。门头材质：{scene['sign_style']}。"
        "门头招牌必须是实际安装在建筑上的真实物理招牌，文字、图形、边框与招牌板材具有一致透视、光照、阴影、反光和固定结构，"
        "绝不能像后期平面贴字或悬浮字幕。"
        "门头主标题必须清楚准确写成“家电维修”四个中文大字；主标题旁或左侧放一个店铺自制的简洁图形标识，"
        f"本组标识设计为“{scene['logo']}”，不带品牌名、不模仿任何现有品牌。"
        f"门头下方服务范围必须清楚横排写成“{scene['service_line']}”。"
        f"同一块主门头板面内必须清楚完整印有“联系电话：{phone}”或“电话：{phone}”，手机号每个数字都要正确、可读，"
        "优先位于主标题下方或门头右侧联系信息块。门头手机号不能放在门下方横幅、立柱、墙面、车身、立牌或店内背景。"
        f"店内状态：{scene['interior']}。{scene['street']}。光线：{scene['lighting']}。拍摄机位：{scene['camera']}。"
        "可以有一名正在工作的维修师傅，深色或蓝灰工服上若出现文字，只能正确写“家电维修”，人物不看镜头，手部和动作自然。"
        "画面中间约一条横向区域要留给本地后期叠加醒目电话条，避免关键人脸和核心维修动作落在正中；"
        "画面底部约四分之一要保留较规整的街道路面、台阶或较安静背景，供本地后期叠加两行五列透明服务项目区。"
        "真实保留玻璃反光、墙面旧痕、普通杂物和营业状态，但主体清楚。"
        "严格排除豪华装修、黑金高端门头、科技展厅、网页按钮、游戏UI、二维码、水印、价格、真实品牌标志、"
        "未确认的店名、其他电话号码、可读车牌、具体区域全覆盖宣传语、乱码堆叠和欧美街景。"
    )
    prompt += visual_style_profiles.prompt_suffix(PROJECT_ID, "storefront_cover")
    return prompt, scene


@variable_catalog.managed('home_appliance_repair','detail',finish_result='always')
def detail_prompt(group_index: int, detail: dict[str, Any], variant: int = 0) -> tuple[str, dict[str, Any]]:
    rng = random.Random(f"{PROJECT_ID}:detail:{detail['slug']}:{group_index}:{variant}")
    visual_version = visual_style_profiles.visual_style_version(PROJECT_ID)
    category_version = "home_appliance_repair_category_content_v1"
    scene = {
        "action": rng.choice(detail["actions"]),
        "setting": rng.choice(detail["settings"]),
        "props": rng.choice(detail["props"]),
        "camera": rng.choice(DETAIL_CAMERA_STYLES),
        "lighting": rng.choice(DETAIL_LIGHTING),
        "worker": rng.choice(DETAIL_WORKER_STATES),
        "visual_style_version": visual_version,
        "category_config_version": category_version,
    }
    scene["composition_signature"] = " | ".join(scene.values())
    prompt = (
        f"真实中国本地上门或街边维修现场，竖版9:16普通手机随手拍照片，主题是{detail['title']}。"
        f"地点：{scene['setting']}。核心动作：{scene['action']}。现场能看到{scene['props']}。"
        f"人物状态：{scene['worker']}。拍摄方式：{scene['camera']}。光线：{scene['lighting']}。"
        "设备结构、工具、手部和操作关系要符合真实维修常识，环境可以有自然生活杂物，不刻意摆拍，不过度洁净，不像广告。"
        f"画面上部约五分之一尽量保留一块较安静背景，供本地程序后期添加“{detail['title']}”类目文字，"
        "不要让关键人脸或最重要的维修部件被该区域遮挡。"
        "原始图片内不要生成中文标题、电话号码、价格、二维码、水印、真实品牌标志或可读车牌，显示屏文字必须不可读。"
        "排除插画、3D渲染、宣传海报、豪华工作室、欧美环境、畸形手指、不合理工具和危险操作。"
    )
    prompt += visual_style_profiles.prompt_suffix(PROJECT_ID, "service_detail")
    return prompt, scene


@variable_catalog.managed('home_appliance_repair', 'cover', finish_result='always')
def v3_cover_prompt(group_index: int, phone: str, variant: int = 0) -> tuple[str, dict[str, Any]]:
    rng = random.Random(f"{PROJECT_ID}:v3:cover:{group_index}:{variant}")
    store_name = (
        STORE_NAME_PREFIXES[(group_index - 1 + variant * 7) % len(STORE_NAME_PREFIXES)]
        + STORE_NAME_SUFFIXES[((group_index - 1) // len(STORE_NAME_PREFIXES) + variant) % len(STORE_NAME_SUFFIXES)]
    )
    scene = {
        "store_name": store_name,
        "sign_style": rng.choice(COVER_SIGN_STYLES),
        "facade": rng.choice(COVER_FACADES),
        "interior": rng.choice(COVER_INTERIORS),
        "camera": rng.choice(COVER_CAMERAS),
        "street": rng.choice(COVER_STREET_ELEMENTS),
        "lighting": rng.choice(COVER_LIGHTING),
        "logo": logo_description(group_index + variant * 61),
        "service_line": SERVICE_LINES[(group_index - 1 + variant) % len(SERVICE_LINES)],
        "visual_style_version": visual_style_profiles.visual_style_version(PROJECT_ID),
        "category_config_version": "home_appliance_repair_category_content_v2",
    }
    scene["composition_signature"] = " | ".join(scene.values())
    prompt = (
        "中国街边正在营业的普通家电维修门店，普通顾客用手机随手拍下的单张竖幅真实照片。"
        "必须像真实本地生活服务记录，不是招牌设计稿、广告海报、门店效果图、影棚广告或高端连锁品牌。"
        f"建筑与门面：{scene['facade']}；门头材质：{scene['sign_style']}；店内状态：{scene['interior']}。"
        f"拍摄机位：{scene['camera']}；光线：{scene['lighting']}；周边生活元素：{scene['street']}。"
        "建筑、门面、店内设备和街道路面必须属于同一真实地点，保留自然玻璃反光、墙面旧痕、固定螺丝、"
        "板材拼缝、普通杂物和正常营业痕迹，画面实用、克制、可信，不豪华也不过度破败。"
        f"主招牌唯一完整店名清楚准确写成“{store_name}”，店名中“家电维修”或“家电服务”类目文字必须完整保留。"
        f"主招牌配一个本地小店自制图形标识“{scene['logo']}”，不模仿任何现有品牌；服务小字写成“{scene['service_line']}”。"
        f"同一块实体主招牌板面内必须清楚完整写有“联系电话：{phone}”或“电话：{phone}”，每个数字准确可读，"
        "联系电话优先位于招牌底部或右侧联系信息区，不得放在墙面、门柱、车辆、立牌、店内背景或悬浮字幕上。"
        "门头文字、电话号码、边框和图形必须与招牌板面具有一致透视、光照、阴影、反光与安装结构，"
        "不能像后期贴字，不能生成其他店名、其他电话号码、价格、地区、时效或服务承诺。"
        "门店内外只能出现家电、厨电、空调、电视、电脑及其维修工具，不得出现救援车、拖车、货车维修、轮胎、"
        "搭电或道路救援业务证据。可以有一名穿普通蓝灰工装的维修师傅自然工作，不看镜头。"
        "画面中部50%至60%保持连续、相对简洁的真实场景，避开人脸和关键维修动作，供本地程序叠加醒目大电话；"
        "画面底部83%至98%保留街面、台阶或安静背景，供本地程序叠加两行五列的十个家电服务词。"
        "原图不要生成中部电话条、底部服务词、按钮、卡片、宫格、边框或任何UI面板。"
        "严格排除汽车救援、道路救援、货车救援、拖车、补胎换胎、搭电救援、救援车、汽车维修车间、"
        "欧美环境、豪华展厅、3D渲染、插画、二维码、水印、乱码、可读车牌和真实品牌标志。"
    )
    prompt += visual_style_profiles.prompt_suffix(PROJECT_ID, "storefront_cover")
    return prompt, scene


@variable_catalog.managed('home_appliance_repair', 'detail', finish_result='always')
def v3_detail_prompt(
    group_index: int,
    detail: dict[str, Any],
    relative_index: int,
    generation_kind: str,
) -> tuple[str, dict[str, Any]]:
    variant = relative_index - 1
    rng = random.Random(f"{PROJECT_ID}:v3:detail:{detail['slug']}:{group_index}:{variant}")
    scene = {
        "action": rng.choice(detail["actions"]),
        "setting": rng.choice(detail["settings"]),
        "props": rng.choice(detail["props"]),
        "camera": rng.choice(DETAIL_CAMERA_STYLES),
        "lighting": rng.choice(DETAIL_LIGHTING),
        "worker": rng.choice(DETAIL_WORKER_STATES),
        "visual_style_version": visual_style_profiles.visual_style_version(PROJECT_ID),
        "category_config_version": "home_appliance_repair_category_content_v2",
    }
    scene["composition_signature"] = " | ".join(scene.values())
    panel_rule = (
        "本图是三拼图中的一个独立实景面板，只表现当前一种维修动作，不自行生成拼贴、边框、标题或分栏；"
        "主体放在中央安全区，四周保留少量可裁切背景。"
        if generation_kind == "triptych_panel"
        else "顶部3.5%至10.5%保留简洁背景供本地添加当前服务角色标签。"
    )
    prompt = (
        f"真实中国本地家电维修现场，竖版普通手机随手拍照片，唯一主题是“{detail['title']}”。"
        f"地点：{scene['setting']}；核心动作：{scene['action']}；现场工具与物件：{scene['props']}。"
        f"人物状态：{scene['worker']}；拍摄方式：{scene['camera']}；光线：{scene['lighting']}。"
        "家电结构、拆装位置、工具、双手和操作关系必须符合真实维修常识；人物不看镜头，环境有自然生活杂物，"
        "不刻意摆拍，不过度洁净，不像广告。"
        f"{panel_rule}"
        "画面中部49%至58.5%保留横向可读背景，底部83.5%至97.5%保留较安静背景，供本地程序添加电话和十个服务词；"
        "关键人脸、手部、设备故障点和核心操作不得被这些区域遮挡。"
        "原始图片不要生成电话号码、中文标题、价格、二维码、水印、真实品牌标志或可读屏幕文字。"
        "严格排除汽车救援、道路救援、货车救援、拖车、轮胎、搭电、救援车辆、汽车维修工具、欧美环境、"
        "插画、CG、3D、宣传海报、豪华工作室、畸形手指、不合理工具和危险操作。"
    )
    prompt += visual_style_profiles.prompt_suffix(PROJECT_ID, "service_detail")
    return prompt, scene


def build_v3_rows(group_index: int, phone: str) -> list[dict[str, Any]]:
    height = V3_HEIGHTS[(group_index - 1) % len(V3_HEIGHTS)]
    layout = V3_LAYOUTS[((group_index - 1) // len(V3_HEIGHTS)) % len(V3_LAYOUTS)]
    final_size = f"{height['width']}x{height['height']}"
    roles = random.Random(f"{PROJECT_ID}:v3:roles:{group_index}").sample(v3_detail_definitions(), 6)
    cover_text, cover_scene = v3_cover_prompt(group_index, phone)
    rows: list[dict[str, Any]] = [{
        "role": "cover",
        "generation_kind": "cover",
        "generation_role": "cover",
        "delivery_position": 1,
        "prompt": cover_text,
        "scene": cover_scene,
        "service_role": None,
        "final_size": final_size,
        "height_profile_id": height["id"],
        "structure_version": V3_STRUCTURE_VERSION,
        "generation_mode": V3_GENERATION_MODE,
    }]
    for relative_index, detail in enumerate(roles, start=1):
        kind = "triptych_panel" if relative_index <= 3 else "detail"
        delivery_position = 2 if kind == "triptych_panel" else relative_index - 1
        prompt, scene = v3_detail_prompt(group_index, detail, relative_index, kind)
        rows.append({
            "role": kind,
            "generation_kind": kind,
            "generation_role": kind,
            "delivery_position": delivery_position,
            "panel_index": relative_index if kind == "triptych_panel" else None,
            "triptych_panel_index": relative_index if kind == "triptych_panel" else None,
            "triptych_layout_id": layout["id"] if kind == "triptych_panel" else None,
            "triptych_panel_box": dict(layout["panels"][relative_index - 1]) if kind == "triptych_panel" else None,
            "prompt": prompt,
            "scene": scene,
            "service_role": detail["title"],
            "title": detail["title"],
            "final_size": final_size,
            "height_profile_id": height["id"],
            "structure_version": V3_STRUCTURE_VERSION,
            "generation_mode": V3_GENERATION_MODE,
        })
    return rows


def build_random_pool_rows(group_index: int, phone: str) -> list[dict[str, Any]]:
    """Build five unrelated repair photos; every delivery receives local text overlays."""
    roles = random.Random(f"{PROJECT_ID}:v4:random-pool:{group_index}").sample(
        v3_detail_definitions(),
        5,
    )
    rows: list[dict[str, Any]] = []
    for position, detail in enumerate(roles, start=1):
        prompt, scene = v3_detail_prompt(group_index, detail, position, "detail")
        scene = dict(scene)
        scene["category_config_version"] = "home_appliance_repair_category_content_v3"
        scene["composition_signature"] = " | ".join(
            str(value) for key, value in scene.items() if key != "composition_signature"
        )
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
            "structure_version": RANDOM_POOL_STRUCTURE_VERSION,
            "generation_mode": RANDOM_POOL_GENERATION_MODE,
        })
    return rows


def unique_cover(group_index: int, phone: str, used: set[str]) -> tuple[str, dict[str, Any]]:
    for variant in range(1000):
        prompt, scene = cover_prompt(group_index, phone, variant)
        if scene["composition_signature"] not in used:
            used.add(scene["composition_signature"])
            return prompt, scene
    raise RuntimeError(f"cannot create unique cover composition for group {group_index}")


def unique_detail(
    group_index: int,
    detail: dict[str, Any],
    used: set[str],
) -> tuple[str, dict[str, Any]]:
    for variant in range(1000):
        prompt, scene = detail_prompt(group_index, detail, variant)
        if scene["composition_signature"] not in used:
            used.add(scene["composition_signature"])
            return prompt, scene
    raise RuntimeError(f"cannot create unique detail composition for group {group_index}: {detail['slug']}")


@variable_catalog.managed('home_appliance_repair',finish_result=False)
def build_records(
    group_start: int,
    group_count: int,
    phone: str,
    output_dir: str = "output/home_appliance_repair",
    used_cover_signatures: set[str] | None = None,
    used_detail_signatures: dict[str, set[str]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    cover_signatures = set(used_cover_signatures or set())
    detail_signatures = {
        item["slug"]: set((used_detail_signatures or {}).get(item["slug"], set()))
        for item in DETAILS
    }
    covers: list[dict[str, Any]] = []
    details: list[dict[str, Any]] = []
    groups: list[dict[str, Any]] = []
    production: list[dict[str, Any]] = []
    output_root = Path(output_dir)

    for group_index in range(group_start, group_start + group_count):
        group_dir = output_root / f"group_{group_index:04d}"
        prompt, scene = unique_cover(group_index, phone, cover_signatures)
        cover_sha = prompt_hash(prompt)
        covers.append({
            "project_id": PROJECT_ID,
            "group_index": group_index,
            "role": "cover",
            "prompt": prompt,
            "prompt_sha256": cover_sha,
            "visual_style_version": scene["visual_style_version"],
            "category_config_version": scene["category_config_version"],
            "phone_bar": True,
            "phones": [phone],
            "scene": scene,
        })
        production.append({
            "project_id": PROJECT_ID,
            "group_index": group_index,
            "position": 1,
            "role": "cover",
            "filename": "01_cover.png",
            "target": str(group_dir / "01_cover.png"),
            "prompt": prompt,
            "prompt_sha256": cover_sha,
            "visual_style_version": scene["visual_style_version"],
            "category_config_version": scene["category_config_version"],
            "source": None,
            "expected_text": ["家电维修", phone],
            "phone_bar_text": phone,
        })

        detail_refs: list[dict[str, Any]] = []
        for offset, detail in enumerate(DETAILS, start=1):
            position = offset + 1
            detail_index = (group_index - 1) * len(DETAILS) + offset
            detail_text, detail_scene = unique_detail(
                group_index,
                detail,
                detail_signatures[detail["slug"]],
            )
            detail_sha = prompt_hash(detail_text)
            details.append({
                "project_id": PROJECT_ID,
                "index": detail_index,
                "group_index": group_index,
                "position": position,
                "role": "detail",
                "title": detail["title"],
                "slug": detail["slug"],
                "scene": detail_scene,
                "prompt": detail_text,
                "prompt_sha256": detail_sha,
                "visual_style_version": detail_scene["visual_style_version"],
                "category_config_version": detail_scene["category_config_version"],
            })
            filename = f"{position:02d}_detail_{detail['slug']}.png"
            production.append({
                "project_id": PROJECT_ID,
                "group_index": group_index,
                "position": position,
                "role": "detail",
                "detail_index": detail_index,
                "filename": filename,
                "target": str(group_dir / filename),
                "prompt": detail_text,
                "prompt_sha256": detail_sha,
                "visual_style_version": detail_scene["visual_style_version"],
                "category_config_version": detail_scene["category_config_version"],
                "source": None,
                "expected_text": [],
                "local_label": detail["title"],
            })
            detail_refs.append({
                "index": detail_index,
                "position": position,
                "title": detail["title"],
                "slug": detail["slug"],
            })
        groups.append({
            "project_id": PROJECT_ID,
            "group_index": group_index,
            "cover": {"group_index": group_index, "position": 1},
            "details": detail_refs,
            "total_images": 1 + len(detail_refs),
        })
    return covers, details, groups, production


def existing_signatures(records: list[dict[str, Any]]) -> set[str]:
    return {
        str(item.get("scene", {}).get("composition_signature"))
        for item in records
        if item.get("scene", {}).get("composition_signature")
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, required=True)
    args = parser.parse_args()
    if args.count < 1:
        raise ValueError("group count must be positive")
    if not BUSINESS_PATH.is_file():
        raise RuntimeError("CONTACT_CONFIRMATION_REQUIRED: confirm telephone number before creating groups")
    business = load_json(BUSINESS_PATH)
    phones = [str(value) for value in business.get("contact_phones", [])]
    if not business.get("user_confirmed") or not phones:
        raise RuntimeError("CONTACT_CONFIRMATION_REQUIRED: telephone number is not confirmed")
    if business.get("placeholder_only"):
        raise RuntimeError("FORMAL_CONTACT_REQUIRED: placeholder telephone numbers cannot be used for formal groups")
    phone = phones[0]

    definition_path = PROJECT_DIR / "project.json"
    registry_path = PROJECT_DIR / "groups" / "registry.json"
    definition = load_json(definition_path)
    registry = load_json(registry_path)
    group_start = int(registry["next_group_index"])
    group_end = group_start + args.count - 1

    cover_path = PROJECT_DIR / "prompts" / "cover_prompts.jsonl"
    detail_path = PROJECT_DIR / "prompts" / "detail_prompts.jsonl"
    group_path = PROJECT_DIR / "groups" / "group_manifest.jsonl"
    production_path = PROJECT_DIR / "groups" / "production_manifest.jsonl"
    existing_covers = load_jsonl(cover_path)
    existing_details = load_jsonl(detail_path)
    existing_groups = load_jsonl(group_path)
    existing_production = load_jsonl(production_path)

    requested_indices = set(range(group_start, group_end + 1))
    for name, records in [
        ("cover prompts", existing_covers),
        ("detail prompts", existing_details),
        ("group manifest", existing_groups),
        ("production manifest", existing_production),
    ]:
        overlap = sorted(requested_indices & {int(item["group_index"]) for item in records})
        if overlap:
            raise RuntimeError(f"{name} already contains requested groups: {overlap}")

    detail_signature_map: dict[str, set[str]] = {item["slug"]: set() for item in DETAILS}
    for item in existing_details:
        slug = item.get("slug")
        signature = item.get("scene", {}).get("composition_signature")
        if slug in detail_signature_map and signature:
            detail_signature_map[str(slug)].add(str(signature))

    new_covers, new_details, new_groups, new_production = build_records(
        group_start,
        args.count,
        phone,
        output_dir=definition["output_dir"],
        used_cover_signatures=existing_signatures(existing_covers),
        used_detail_signatures=detail_signature_map,
    )
    new_hashes = [item["prompt_sha256"] for item in [*new_covers, *new_details]]
    existing_hashes = {
        str(item["prompt_sha256"])
        for item in [*existing_covers, *existing_details]
        if item.get("prompt_sha256")
    }
    if len(new_hashes) != len(set(new_hashes)):
        raise RuntimeError("new home-appliance prompts are not unique")
    collisions = sorted(set(new_hashes) & existing_hashes)
    if collisions:
        raise RuntimeError(f"new home-appliance prompts collide with existing prompts: {collisions}")

    atomic_jsonl(cover_path, [*existing_covers, *new_covers])
    atomic_jsonl(detail_path, [*existing_details, *new_details])
    atomic_jsonl(group_path, [*existing_groups, *new_groups])
    atomic_jsonl(production_path, [*existing_production, *new_production])

    registry["groups"].extend({"group_index": item["group_index"]} for item in new_groups)
    registry["created_groups"] = int(registry["created_groups"]) + args.count
    registry["next_group_index"] = group_end + 1
    atomic_json(registry_path, registry)

    definition["status"] = "active"
    definition["prompt_sources"]["detail_prompt_count"] = len(existing_details) + len(new_details)
    definition["prompt_sources"]["available_complete_detail_sets"] = len(existing_groups) + len(new_groups)
    atomic_json(definition_path, definition)
    print(
        f"CONTENT_GROUPS_READY project={PROJECT_ID} groups={args.count} "
        f"group_start={group_start} group_end={group_end} images={len(new_production)} "
        "api_called=false llm_called=false"
    )


if __name__ == "__main__":
    main()
