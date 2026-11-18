"""Isolated paid image production for 5-image category batches.

The worker is intentionally separate from legacy 1+8 production. Raw images and
production evidence stay below the selected batch; approved workflow callers may
direct final images only to the fixed ``output/<category>`` inventory root.
"""

from __future__ import annotations
from tools import runtime_paths

from tools import variable_catalog

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

import image_generate
import visual_style_profiles
from tools import category_generation_profile
from tools import image_download_receipts
from tools import truck_cover_typography
from tools.contact_numbers import (
    contains_contact_number,
    extract_contact_numbers,
    is_canonical_contact_number,
    normalize_contact_number,
)
from tools.prompt_engine import CATEGORY_BATCH_ROOT, CategoryPromptError, load_category_config
from tools.truck_rescue_signage import (
    NAMING_EPOCH_GROUP,
    load_signage_library,
    normalize_signage_typography,
    resolve_signage_variant,
    signage_override_text,
)


ROOT = Path(__file__).resolve().parent.parent
OVERLAY_SCHEMA_VERSION = 4
COVER_STYLE_VERSION = 2
PIPE_COVER_OVERLAY_STYLE_VERSION = 3
ROAD_RESCUE_COVER_STYLE_VERSION = 8
ROAD_RESCUE_COVER_V3_FIRST_GROUP = 1089
ROAD_RESCUE_COVER_V3_STYLE_VERSION = 10
ROAD_RESCUE_MULTI_FOOTER_FIRST_GROUP = 1090
ROAD_RESCUE_MULTI_FOOTER_STYLE_VERSION = 11
PET_TRANSPORT_COVER_STYLE_VERSION = 3
TRUCK_RESCUE_COVER_STYLE_VERSION = 2
PRODUCTION_SCHEMA_VERSION = 3
GROUP_STRUCTURE_VERSION = "pipe_unclogging_v2_1cover_1triptych_3details"
GENERATION_MODE = "independent_triptych_panels"
RAW_API_SIZE = (1024, 1536)
SUPPORTED_CATEGORY_IDS = {
    "ktv",
    "pipe_unclogging",
    "road_rescue",
    "home_appliance_repair",
    "pet_transport",
    "truck_rescue",
}
DEFAULT_CATEGORY_ID = "pipe_unclogging"
CATEGORY_SIGNBOARD_TITLES = {
    "pipe_unclogging": "管道疏通",
    "road_rescue": "汽车救援",
    "home_appliance_repair": "家电维修",
    "pet_transport": "宠物托运",
    "truck_rescue": "货车救援维修",
}
MODEL_GENERATED_SIGNBOARD_CATEGORIES = {
    "road_rescue",
    "home_appliance_repair",
    "pet_transport",
    "truck_rescue",
}
ACTIVE_JOB_PATH: Path | None = None
ACTIVE_LICENSE_PATH: Path | None = None
ACTIVE_LOCK_PATH: Path | None = None
SCOPES = {"all", "covers", "details"}
GENERATION_KINDS = {"cover", "triptych_panel", "detail"}
TRIPTYCH_LAYOUTS = {"stacked_equal", "top_feature_bottom_pair", "top_pair_bottom_feature"}
TRIPTYCH_PHONE_PREFIX = "电话："
TRIPTYCH_SERVICE_SEPARATOR = " · "
TRIPTYCH_PANEL_ANCHOR_Y = 0.4
ADAPTIVE_CONCURRENCY_POLICY = "adaptive_ramp_v1"
FIXED_TEN_CONCURRENCY_POLICY = "fixed_10_after_probe_v1"
ADAPTIVE_CONCURRENCY_RAMP = (4, 6, 8, 10)
NO_RETRY_POLICY = "none"
CLASSIFIED_RETRY_POLICY = "classified_once_v1"
MAX_AUTO_RETRIES = 1
RETRY_BACKOFF_SECONDS = 2.0
CONTENT_POLICY_CIRCUIT_BREAKER_MIN_FAILURES = 2
CONTENT_POLICY_CIRCUIT_BREAKER_FAILURE_RATE = 0.5
CONSECUTIVE_API_ERROR_LIMIT = 3
TRUCK_CONTENT_POLICY_SAFE_V2_ACTIONS = {
    "货车没油救援": (
        "工作人员核对油表、油箱口和燃油规格，使用合规燃油容器与防静电输油软管"
        "完成应急补充并复查接口。"
    ),
    "货车爆胎救援": (
        "工作人员布置轮挡和警示锥，检查爆裂轮胎、轮辋、胎体破口与异物并确认更换方案。"
    ),
    "货车换轮胎": (
        "工作人员设置轮挡和支撑，拆下旧车轮，对位安装匹配备胎并按交叉顺序紧固螺母。"
    ),
    "货车发动机故障": (
        "维修人员连接货车诊断设备，读取故障码和数据流，检查启动回路、燃油供给、"
        "传感器与线束连接。"
    ),
    "卡车搭电": (
        "工作人员核对额定电压、极性和端子状态，使用匹配规格的辅助电源与粗规格跨接线"
        "完成搭电启动。"
    ),
    "货车刹车故障": (
        "工作人员确认驻车与支撑状态，检查制动压力、管路连接和轮端制动部件并记录检测结果。"
    ),
}
TRUCK_CONTENT_POLICY_SAFE_V2_NEGATIVE_MARKERS = (
    "不要",
    "不得",
    "不能",
    "不应",
    "不出现",
    "不表现",
    "无洒漏",
    "避免",
    "排除",
    "禁止",
    "不",
    "无",
)
TRUCK_CONTENT_POLICY_SAFE_V2_FORBIDDEN_TERMS = ("伤害", "不安全", "冲突")
TUNING_SAMPLE_PROJECT_ENV = "CATEGORY_IMAGE_TUNING_SAMPLE_PROJECT"
TUNING_SAMPLE_GROUP_ENV = "CATEGORY_IMAGE_TUNING_SAMPLE_GROUP"
_TRIPTYCH_LOCK_GUARD = threading.Lock()
_TRIPTYCH_TARGET_LOCKS: dict[str, threading.Lock] = {}


class RawImageContractError(RuntimeError):
    """A decodable provider image violated the raw-image contract."""

    def __init__(self, message: str, evidence: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.evidence = evidence or {}


@dataclass(frozen=True)
class RequestBatchResult:
    """Boolean-compatible request result with optional scheduler metadata."""

    success: bool
    final_error_kind: str | None = None
    attempt_count: int = 1
    content_policy_rejection_count: int = 0

    def __bool__(self) -> bool:
        return self.success

ROLE_PRODUCTION_SPECS = {
    "厨房下水道疏通": "普通中国居民楼厨房，水槽和水槽下排水支管清楚入画，师傅蹲在水槽下操作软轴疏通机处理油污堵塞。",
    "马桶疏通": "普通中国居民楼卫生间，马桶必须完整入画，师傅使用专业疏通工具处理马桶弯管堵塞，动作真实克制。",
    "地漏疏通": "普通中国居民楼或社区商铺卫生间，地漏盖已打开，地漏口、堵点、软轴和防水手套清楚可见。",
    "主管道疏通": "中国老小区楼宇或社区商铺公共排水主管道，师傅操作软轴疏通机正在疏通主管道，不能只做检测。",
    "高压清洗管道": "中国社区商铺排水管施工现场，高压清洗机、高压软管和高压水枪清楚入画，师傅正在冲洗管道，不能只有吸污管。",
    "管道内窥镜检测": "普通中国居民楼卫生间，内窥镜探头和线缆进入管道口，师傅操作管道内窥镜检测设备，屏幕无需可读文字。",
    "抽粪清淤/化粪池清理": "中国老小区化粪池或排污井作业区，打开的井盖、吸污管和吸污车连接动作清楚，污物表现克制不过度恶心。",
    "餐饮店后厨油污管道": "普通中国小餐馆后厨，排水沟或隔油池排水管清楚入画，师傅用软轴或高压设备处理油污堵塞，不能变成住宅厨房。",
}

COVER_VARIATION_STEPS = {
    "storefront": 1,
    "signboard": 1,
    "camera": 1,
    "distance": 1,
    "shop_state": 2,
    "worker_layout": 3,
    "equipment_anchor": 1,
    "lighting": 3,
    "ground": 1,
}


def select_cover_variant(record: dict[str, Any], category: dict[str, Any] | None = None) -> dict[str, str]:
    """Choose a deterministic multi-axis cover variant without changing the legal work scene."""
    current_category = category or load_category_config("pipe_unclogging")
    axes = current_category.get("cover_variation_axes")
    if not isinstance(axes, dict):
        raise CategoryPromptError("管道疏通类目缺少 cover_variation_axes")
    sequence_value = record.get("group_index") or record.get("index") or 1
    sequence_index = max(0, int(sequence_value) - 1)
    selected: dict[str, str] = {}
    for axis, step in COVER_VARIATION_STEPS.items():
        options = axes.get(axis)
        if not isinstance(options, list) or not options or not all(isinstance(item, str) and item for item in options):
            raise CategoryPromptError(f"管道疏通首图变化轴 {axis} 缺少有效选项")
        # The quotient term prevents paired axes from falling back to the same
        # camera/distance combination as soon as one short list wraps around.
        option_index = (sequence_index * step + sequence_index // len(options)) % len(options)
        selected[axis] = options[option_index]
    return selected


def cover_variant_signature(record: dict[str, Any], variant: dict[str, str] | None = None) -> str:
    current_variant = variant or select_cover_variant(record)
    scene = record.get("scene") if isinstance(record.get("scene"), dict) else {}
    material = {
        "scene": {
            key: scene.get(key)
            for key in ("location", "customer_problem", "pipe_type", "tool", "worker_action")
        },
        "variant": current_variant,
    }
    serialized = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def cover_specification(record: dict[str, Any]) -> str:
    scene = record.get("scene")
    if not isinstance(scene, dict):
        raise CategoryPromptError("管道疏通首图缺少源业务场景")
    required = ("location", "customer_problem", "pipe_type", "tool", "worker_action", "environment_detail")
    missing = [key for key in required if not scene.get(key)]
    if missing:
        raise CategoryPromptError(f"管道疏通首图源场景缺少字段：{', '.join(missing)}")
    variant = select_cover_variant(record)
    vehicle_rule = (
        "源业务组合涉及吸污管，可在画面边缘低频出现吸污车局部，但车牌不得入画或必须完全不可读。"
        if scene.get("tool") == "吸污管" or "吸污管" in str(scene.get("worker_action"))
        else "本组不出现吸污车或其他大型车辆，以便与含车辆的首图区分。"
    )
    return (
        "真实门店与真实施工必须在同一张照片中自然同框。"
        f"门店原型：{variant['storefront']}；主招牌结构：{variant['signboard']}；门店状态：{variant['shop_state']}。"
        "主招牌是建筑上真实安装的板面，不是悬浮横幅、墙贴、立牌或UI面板；板面保持无字，供本地程序叠加已确认内容。"
        f"源业务施工组合必须保留：地点为{scene['location']}，问题为{scene['customer_problem']}，管道为{scene['pipe_type']}，"
        f"师傅执行{scene['worker_action']}，真实工具为{scene['tool']}；环境细节为{scene['environment_detail']}。"
        f"人物安排：{variant['worker_layout']}；设备位置：{variant['equipment_anchor']}。{vehicle_rule}"
        f"拍摄站位：{variant['camera']}；距离：{variant['distance']}；光线：{variant['lighting']}；地面：{variant['ground']}。"
        "上部5.5%至30.5%完整保留真实主招牌板面；中部43%至53.5%留出可读背景；下部70%至96.5%以街面或地面为主。"
        "人物脸、手、关键工具和施工接触点集中在中下部清楚区域，不能落入电话或服务词的主要叠字位置。"
    )


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _io_path(path: Path) -> Path:
    from tools.task_library import io_path
    return io_path(path)


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path = _io_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


@variable_catalog.document_loader
def load_json(path: Path) -> dict[str, Any]:
    return runtime_paths.read_json(path)


def safe_batch_dir(category_id: str, value: str | Path) -> Path:
    candidate = Path(value).expanduser().resolve()
    allowed = (CATEGORY_BATCH_ROOT / category_id).resolve()
    if candidate == allowed or allowed not in candidate.parents:
        raise CategoryPromptError(f"批次目录必须是 {allowed} 下的具体 batch 目录")
    if not candidate.is_dir():
        raise CategoryPromptError(f"找不到批次目录：{candidate}")
    if not candidate.name.startswith("batch_"):
        raise CategoryPromptError("批次目录名必须以 batch_ 开头")
    return candidate


def production_dir(batch_dir: Path) -> Path:
    return batch_dir / "production"


def _safe_license_id(value: str) -> str:
    license_id = str(value).strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", license_id):
        raise ValueError("license_id 只能包含字母、数字、下划线和连字符")
    return license_id


def safe_output_root(category_id: str, value: str | Path) -> Path:
    if category_id not in SUPPORTED_CATEGORY_IDS:
        raise CategoryPromptError(f"unsupported category: {category_id}")
    candidate = Path(value).expanduser().resolve()
    allowed = (ROOT / "output" / category_id).resolve()
    if candidate != allowed:
        raise CategoryPromptError(f"正式成品目录必须是 {allowed}")
    return candidate


def license_path(
    category_id: str,
    batch_dir: Path,
    group_start: int,
    group_count: int,
    license_id: str | None = None,
) -> Path:
    del category_id
    if license_id is not None:
        return production_dir(batch_dir) / "licenses" / f"{_safe_license_id(license_id)}.json"
    return production_dir(batch_dir) / f"authorization_groups_{group_start:04d}_{group_count:04d}.json"


def manifest_path(
    batch_dir: Path,
    group_start: int,
    group_count: int,
    license_id: str | None = None,
) -> Path:
    if license_id is not None:
        return production_dir(batch_dir) / "manifests" / f"{_safe_license_id(license_id)}.jsonl"
    return production_dir(batch_dir) / f"production_manifest_groups_{group_start:04d}_{group_count:04d}.jsonl"


def overlay_plan_path(
    batch_dir: Path,
    group_start: int,
    group_count: int,
    license_id: str | None = None,
) -> Path:
    if license_id is not None:
        return production_dir(batch_dir) / "overlay_plans" / f"{_safe_license_id(license_id)}.json"
    return production_dir(batch_dir) / f"overlay_plan_groups_{group_start:04d}_{group_count:04d}.json"


def summary_path(
    batch_dir: Path,
    group_start: int,
    group_count: int,
    license_id: str | None = None,
    *,
    readable: bool = False,
) -> Path:
    suffix = "_readable.txt" if readable else ".json"
    if license_id is not None:
        return production_dir(batch_dir) / "summaries" / f"{_safe_license_id(license_id)}{suffix}"
    name = f"summary_groups_{group_start:04d}_{group_count:04d}"
    return production_dir(batch_dir) / f"{name}{suffix}"


def write_new_license(path: Path, payload: dict[str, Any]) -> None:
    """Create a license exactly once; an existing path is never overwritten."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as error:
        raise RuntimeError(f"许可证文件已存在，禁止覆盖：{path}") from error
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    except Exception:
        try:
            path.unlink()
        except OSError:
            pass
        raise


def jobs_dir(batch_dir: Path) -> Path:
    return production_dir(batch_dir) / "jobs"


def read_prompts(batch_dir: Path) -> list[dict[str, Any]]:
    path = batch_dir / "prompts.jsonl"
    if not path.is_file():
        raise CategoryPromptError(f"缺少提示词文件：{path}")
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    if not rows:
        raise CategoryPromptError("prompts.jsonl 为空")
    return rows


def _generation_kind(record: dict[str, Any]) -> str:
    value = record.get("generation_kind")
    if value is None:
        value = record.get("role")
    kind = str(value or "").strip()
    if kind not in GENERATION_KINDS:
        raise CategoryPromptError(f"不支持的生成角色：{kind or '<empty>'}")
    return kind


def _service_role(record: dict[str, Any]) -> str | None:
    value = record.get("service_role")
    if value is None and record.get("generation_kind") is not None:
        legacy_role = str(record.get("role") or "").strip()
        if legacy_role not in GENERATION_KINDS:
            value = legacy_role
    role = str(value or "").strip()
    return role or None


def _panel_index(record: dict[str, Any]) -> int | None:
    value = record.get("panel_index")
    if value is None:
        value = record.get("triptych_panel_index")
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as error:
        raise CategoryPromptError(f"无效的三拼 panel_index：{value}") from error


def _size_text(value: Any) -> str:
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return f"{int(value[0])}x{int(value[1])}"
    return str(value or "").strip()


def _record_final_size(record: dict[str, Any]) -> str:
    value = _size_text(record.get("final_size"))
    if not value:
        raise CategoryPromptError(
            f"第 {record.get('group_index')} 组第 {record.get('index')} 条记录缺少 final_size"
        )
    width, height = parse_size(value)
    if record.get("category_id") == "ktv" and (width, height) == (864, 1536):
        return value
    if width != RAW_API_SIZE[0] or height <= 0 or height > RAW_API_SIZE[1]:
        raise CategoryPromptError(
            f"final_size 必须是宽 {RAW_API_SIZE[0]}、高度不超过 {RAW_API_SIZE[1]} 的竖图：{value}"
        )
    return value


def _layout_config_map(
    structure: dict[str, Any] | None = None,
    category_id: str = DEFAULT_CATEGORY_ID,
) -> dict[str, dict[str, Any]]:
    current = structure
    if current is None:
        category = load_category_config(category_id)
        current = category.get("image_group_structure")
    if not isinstance(current, dict):
        raise CategoryPromptError("管道疏通类目缺少 image_group_structure")
    layouts = current.get("triptych_layouts")
    if not isinstance(layouts, list):
        raise CategoryPromptError("管道疏通 v2 缺少 triptych_layouts")
    result: dict[str, dict[str, Any]] = {}
    for item in layouts:
        if not isinstance(item, dict):
            raise CategoryPromptError("triptych_layouts 必须是带 id 和 panels 的对象列表")
        layout_id = str(item.get("id") or "").strip()
        panels = item.get("panels")
        if layout_id not in TRIPTYCH_LAYOUTS or not isinstance(panels, list) or len(panels) != 3:
            raise CategoryPromptError(f"三拼布局配置无效：{layout_id or '<empty>'}")
        panel_indices = [int(panel.get("panel_index", -1)) for panel in panels if isinstance(panel, dict)]
        if panel_indices != [1, 2, 3]:
            raise CategoryPromptError(f"三拼布局 {layout_id} 的 panel_index 必须为 1、2、3")
        for panel in panels:
            for field in ("x", "y", "width", "height"):
                try:
                    value = float(panel[field])
                except (KeyError, TypeError, ValueError) as error:
                    raise CategoryPromptError(f"三拼布局 {layout_id} 面板缺少有效 {field}") from error
                if value < 0 or value > 1:
                    raise CategoryPromptError(f"三拼布局 {layout_id} 的 {field} 必须在 0 到 1 之间")
            if float(panel["width"]) <= 0 or float(panel["height"]) <= 0:
                raise CategoryPromptError(f"三拼布局 {layout_id} 的面板宽高必须大于 0")
            if float(panel["x"]) + float(panel["width"]) > 1.000001:
                raise CategoryPromptError(f"三拼布局 {layout_id} 的面板横向越界")
            if float(panel["y"]) + float(panel["height"]) > 1.000001:
                raise CategoryPromptError(f"三拼布局 {layout_id} 的面板纵向越界")
        result[layout_id] = item
    expected_layouts = {"stacked_equal"} if category_id == "ktv" else TRIPTYCH_LAYOUTS
    if set(result) != expected_layouts:
        raise CategoryPromptError("管道疏通 v2 必须配置三种固定三拼布局")
    return result


def _height_profile_map(structure: dict[str, Any]) -> dict[str, str]:
    profiles = structure.get("height_profiles")
    if not isinstance(profiles, list) or not profiles:
        raise CategoryPromptError("管道疏通 v2 缺少 height_profiles")
    result: dict[str, str] = {}
    for item in profiles:
        if not isinstance(item, dict):
            raise CategoryPromptError("height_profiles 必须是带 id、width、height 的对象列表")
        profile_id = str(item.get("id") or "").strip()
        try:
            size = f"{int(item['width'])}x{int(item['height'])}"
        except (KeyError, TypeError, ValueError) as error:
            raise CategoryPromptError(f"高度档位 {profile_id or '<empty>'} 缺少有效宽高") from error
        if not profile_id or profile_id in result:
            raise CategoryPromptError("height_profiles 的 id 必须非空且唯一")
        width, height = parse_size(size)
        if width != RAW_API_SIZE[0] or height <= 0 or height > RAW_API_SIZE[1]:
            raise CategoryPromptError(f"高度档位 {profile_id} 超出本地安全裁切范围")
        result[profile_id] = size
    if set(result.values()) != {"1024x1408", "1024x1472", "1024x1536"}:
        raise CategoryPromptError("管道疏通 v2 高度档位必须是 1024x1408、1024x1472、1024x1536")
    return result


def _validate_v2_structure_config(structure: dict[str, Any]) -> None:
    expected = {
        "generation_unit_count": 7,
        "triptych_panel_count": 3,
    }
    for field, value in expected.items():
        if int(structure.get(field, -1)) != value:
            raise CategoryPromptError(f"管道疏通 v2 的 {field} 必须是 {value}")
    delivery_roles = structure.get("delivery_roles")
    if delivery_roles != ["cover", "triptych", "detail", "detail", "detail"]:
        raise CategoryPromptError("管道疏通 v2 delivery_roles 必须是 cover、triptych、3 个 detail")
    _layout_config_map(structure)
    _height_profile_map(structure)


def _validate_independent_delivery_structure_config(structure: dict[str, Any], category_id: str) -> None:
    if str(structure.get("generation_mode") or "") != "independent_delivery_images":
        raise CategoryPromptError(f"{category_id} generation_mode must be independent_delivery_images")
    generation_unit_count = int(structure.get("generation_unit_count", -1))
    delivery_unit_count = int(structure.get("delivery_unit_count", -1))
    if generation_unit_count < 2 or delivery_unit_count != generation_unit_count:
        raise CategoryPromptError(f"{category_id} independent structure requires matching generation/delivery unit counts")
    delivery_roles = structure.get("delivery_roles")
    if (
        not isinstance(delivery_roles, list)
        or len(delivery_roles) != delivery_unit_count
        or delivery_roles[0] != "cover"
        or any(role != "detail" for role in delivery_roles[1:])
    ):
        raise CategoryPromptError(f"{category_id} delivery_roles must be one cover followed by details")
    service_role_pool = structure.get("service_role_pool")
    detail_count = delivery_unit_count - 1
    if (
        not isinstance(service_role_pool, list)
        or len(service_role_pool) < detail_count
        or not all(isinstance(item, str) and item for item in service_role_pool)
        or len(set(service_role_pool)) != len(service_role_pool)
    ):
        raise CategoryPromptError(f"{category_id} service_role_pool must contain enough unique detail roles")


def selected_records(
    batch_dir: Path,
    group_start: int,
    group_count: int,
    category_id: str = DEFAULT_CATEGORY_ID,
) -> list[dict[str, Any]]:
    if group_start < 1 or group_count < 1:
        raise CategoryPromptError("group_start 和 group_count 必须为正整数")
    end = group_start + group_count - 1
    rows = [
        row for row in read_prompts(batch_dir)
        if row.get("group_index") is not None and group_start <= int(row["group_index"]) <= end
    ]
    category = load_category_config(category_id)
    structure = category.get("image_group_structure")
    if not isinstance(structure, dict):
        raise CategoryPromptError("管道疏通类目缺少 image_group_structure")
    if category_id == "ktv":
        from tools.ktv_project import validate_rows

        _layout_config_map(structure, category_id)
        return validate_rows(rows, structure, group_start, group_count)
    if str(structure.get("generation_mode") or "") == "independent_delivery_images":
        _validate_independent_delivery_structure_config(structure, category_id)
        unit_count = int(structure["generation_unit_count"])
        detail_count = unit_count - 1
        expected_count = group_count * unit_count
        if len(rows) != expected_count:
            raise CategoryPromptError(f"selected range must contain {expected_count} prompts, found {len(rows)}")
        service_role_pool = list(structure["service_role_pool"])
        result: list[dict[str, Any]] = []
        for group_index in range(group_start, end + 1):
            group = sorted(
                [row for row in rows if int(row["group_index"]) == group_index],
                key=lambda row: int(row["index"]),
            )
            kinds = [_generation_kind(row) for row in group]
            if kinds != ["cover", *["detail"] * detail_count]:
                raise CategoryPromptError(f"group {group_index} must contain one cover followed by {detail_count} details")
            if any(row.get("category_id") not in {None, category_id} for row in group):
                raise CategoryPromptError(f"group {group_index} mixes prompts from another category")
            delivery_positions = [int(row.get("delivery_position", -1)) for row in group]
            if delivery_positions != list(range(1, unit_count + 1)):
                raise CategoryPromptError(f"group {group_index} delivery_position must be 1..{unit_count}")
            group_sizes = {_record_final_size(row) for row in group}
            if group_sizes != {"1024x1536"}:
                raise CategoryPromptError(f"group {group_index} independent delivery images must use final_size 1024x1536")
            service_roles = [_service_role(row) for row in group[1:]]
            if any(role is None or role not in service_role_pool for role in service_roles):
                raise CategoryPromptError(f"group {group_index} contains service_role outside service_role_pool")
            if len(set(service_roles)) != detail_count:
                raise CategoryPromptError(f"group {group_index} detail service roles must be unique")
            normalized_group: list[dict[str, Any]] = []
            for row in group:
                normalized = dict(row)
                normalized["generation_kind"] = _generation_kind(row)
                normalized["service_role"] = _service_role(row)
                normalized["panel_index"] = None
                normalized["height_profile_id"] = str(row.get("height_profile_id") or "full_1536")
                normalized["final_size"] = _record_final_size(row)
                normalized_group.append(normalized)
            result.extend(normalized_group)
        return result
    _validate_v2_structure_config(structure)
    expected_count = group_count * 7
    if len(rows) != expected_count:
        raise CategoryPromptError(f"所选范围应有 {expected_count} 条组图提示词，实际找到 {len(rows)} 条")
    service_role_pool = structure.get("service_role_pool")
    if (
        not isinstance(service_role_pool, list)
        or len(service_role_pool) < 6
        or not all(isinstance(item, str) and item for item in service_role_pool)
        or len(set(service_role_pool)) != len(service_role_pool)
    ):
        raise CategoryPromptError("管道疏通 v2 service_role_pool 至少需要 6 个有效服务角色")
    height_profiles = _height_profile_map(structure)
    height_profile_order = [
        str(item["id"]) for item in structure["height_profiles"]
    ]
    layout_order = [
        str(item["id"]) for item in structure["triptych_layouts"]
    ]
    result: list[dict[str, Any]] = []
    for group_index in range(group_start, end + 1):
        group = sorted(
            [row for row in rows if int(row["group_index"]) == group_index],
            key=lambda row: int(row["index"]),
        )
        kinds = [_generation_kind(row) for row in group]
        if kinds != ["cover", "triptych_panel", "triptych_panel", "triptych_panel", "detail", "detail", "detail"]:
            raise CategoryPromptError(
                f"第 {group_index} 组不符合 1 个封面生成单元 + 3 个三拼面板 + 3 个详情生成单元"
            )
        if any(row.get("category_id") not in {None, category_id} for row in group):
            raise CategoryPromptError(f"第 {group_index} 组混入了其他类目提示词")
        panel_indices = [_panel_index(row) for row in group if _generation_kind(row) == "triptych_panel"]
        if panel_indices != [1, 2, 3]:
            raise CategoryPromptError(f"第 {group_index} 组三拼 panel_index 必须依次为 1、2、3")
        delivery_positions = [int(row.get("delivery_position", -1)) for row in group]
        if delivery_positions != [1, 2, 2, 2, 3, 4, 5]:
            raise CategoryPromptError(f"第 {group_index} 组 delivery_position 必须是 1,2,2,2,3,4,5")
        service_roles = [_service_role(row) for row in group[1:]]
        if any(role is None or role not in service_role_pool for role in service_roles):
            raise CategoryPromptError(f"第 {group_index} 组包含 service_role_pool 之外的服务角色")
        if len(set(service_roles)) != 6:
            raise CategoryPromptError(f"第 {group_index} 组的 6 个服务角色必须互不相同")
        panel_layouts = {str(row.get("triptych_layout_id") or "") for row in group[1:4]}
        if len(panel_layouts) != 1 or next(iter(panel_layouts)) not in TRIPTYCH_LAYOUTS:
            raise CategoryPromptError(f"第 {group_index} 组三拼面板必须共享一个有效 triptych_layout_id")
        panel_sizes = {_record_final_size(row) for row in group[1:4]}
        if len(panel_sizes) != 1:
            raise CategoryPromptError(f"第 {group_index} 组三拼面板必须共享同一个 final_size")
        group_sizes = {_record_final_size(row) for row in group}
        group_profiles = {str(row.get("height_profile_id") or "") for row in group}
        if len(group_sizes) != 1 or len(group_profiles) != 1:
            raise CategoryPromptError(f"第 {group_index} 组 5 张成品必须共享同一高度档位")
        expected_profile = height_profile_order[(group_index - 1) % len(height_profile_order)]
        if group_profiles != {expected_profile}:
            raise CategoryPromptError(
                f"第 {group_index} 组高度档位必须按轮换规则使用 {expected_profile}"
            )
        expected_layout = layout_order[
            ((group_index - 1) // len(height_profile_order)) % len(layout_order)
        ]
        if panel_layouts != {expected_layout}:
            raise CategoryPromptError(
                f"第 {group_index} 组三拼布局必须按轮换规则使用 {expected_layout}"
            )
        configured_panels = _layout_config_map(structure)[expected_layout]["panels"]
        recorded_panels = [row.get("triptych_panel_box") for row in group[1:4]]
        if _json_sha256(recorded_panels) != _json_sha256(configured_panels):
            raise CategoryPromptError(
                f"第 {group_index} 组三拼面板坐标与 {expected_layout} 配方不一致"
            )
        normalized_group: list[dict[str, Any]] = []
        for row in group:
            height_profile_id = str(row.get("height_profile_id") or "").strip()
            final_size = _record_final_size(row)
            if height_profile_id not in height_profiles:
                raise CategoryPromptError(
                    f"第 {group_index} 组包含未知 height_profile_id：{height_profile_id or '<empty>'}"
                )
            if height_profiles[height_profile_id] != final_size:
                raise CategoryPromptError(
                    f"第 {group_index} 组 {height_profile_id} 与 final_size {final_size} 不一致"
                )
            normalized = dict(row)
            normalized["generation_kind"] = _generation_kind(row)
            normalized["service_role"] = _service_role(row)
            normalized["panel_index"] = _panel_index(row)
            normalized["height_profile_id"] = height_profile_id
            normalized["final_size"] = final_size
            normalized_group.append(normalized)
        result.extend(normalized_group)
    return result


def output_filename(position: int, role: str) -> str:
    if role == "cover":
        return "01_cover.png"
    if role in {"triptych", "triptych_panel"}:
        return "02_triptych.png"
    return f"{position:02d}_detail.png"


def record_targets(
    batch_dir: Path,
    records: list[dict[str, Any]],
    output_root: str | Path | None = None,
    category_id: str = DEFAULT_CATEGORY_ID,
) -> list[dict[str, Any]]:
    formal_root = safe_output_root(category_id, output_root) if output_root is not None else None
    counters: dict[int, int] = {}
    result: list[dict[str, Any]] = []
    for record in records:
        group_index = int(record["group_index"])
        counters[group_index] = counters.get(group_index, 0) + 1
        generation_position = counters[group_index]
        if int(record.get("generation_position", -1)) != generation_position:
            raise CategoryPromptError(
                f"第 {group_index} 组 generation_position 必须连续为 1 到 7"
            )
        generation_kind = _generation_kind(record)
        delivery_position = int(record["delivery_position"])
        filename = output_filename(delivery_position, generation_kind)
        legacy_target = batch_dir / "images" / f"group_{group_index:04d}" / filename
        target = (formal_root / f"group_{group_index:04d}" / filename) if formal_root else legacy_target
        supplied_delivery = record.get("delivery_target")
        if supplied_delivery:
            supplied_path = Path(str(supplied_delivery))
            if not supplied_path.is_absolute():
                supplied_path = ROOT / supplied_path
            if supplied_path.resolve() != target.resolve():
                raise CategoryPromptError(
                    f"第 {group_index} 组 delivery_target 与固定成品路径不一致"
                )
        supplied_raw = record.get("raw_target")
        if not supplied_raw:
            raise CategoryPromptError(f"第 {group_index} 组第 {generation_position} 个生成单元缺少 raw_target")
        raw_target = Path(str(supplied_raw))
        if not raw_target.is_absolute():
            raw_target = ROOT / raw_target
        raw_target = raw_target.resolve()
        allowed_raw = (batch_dir / "raw" / f"group_{group_index:04d}").resolve()
        if raw_target.parent != allowed_raw or raw_target.suffix.lower() != ".png":
            raise CategoryPromptError(f"raw_target 必须位于固定批次组目录：{allowed_raw}")
        if _size_text(record.get("raw_size")) != f"{RAW_API_SIZE[0]}x{RAW_API_SIZE[1]}":
            raise CategoryPromptError("生成记录 raw_size 必须固定为 1024x1536")
        generation_target_id = str(record.get("generation_id") or "").strip()
        structure_version = str(record.get("structure_version", ""))
        if structure_version.startswith(("road_rescue_v3", "truck_rescue_v3")):
            version_tag = "v3"
        elif structure_version.startswith(("pet_transport_v1", "ktv_v1")):
            version_tag = "v1"
        else:
            version_tag = "v2"
        expected_generation_id = f"{category_id}:{version_tag}:g{group_index:04d}:u{generation_position:02d}"
        if generation_target_id != expected_generation_id:
            raise CategoryPromptError(
                f"第 {group_index} 组 generation_id 必须是 {expected_generation_id}"
            )
        delivery_kind = "triptych" if generation_kind == "triptych_panel" else generation_kind
        delivery_target_id = f"{category_id}:{version_tag}:g{group_index:04d}:d{delivery_position:02d}"
        result.append({
            **record,
            "role": generation_kind,
            "generation_kind": generation_kind,
            "position": generation_position,
            "generation_position": generation_position,
            "delivery_position": delivery_position,
            "target_id": generation_target_id,
            "generation_target_id": generation_target_id,
            "delivery_target_id": delivery_target_id,
            "target": str(target),
            "legacy_target": str(legacy_target),
            "raw_target": str(raw_target),
            "final_size": _record_final_size(record),
        })
    return result


def parse_size(value: str) -> tuple[int, int]:
    match = re.fullmatch(r"(\d+)x(\d+)", str(value))
    if not match:
        raise CategoryPromptError(f"不支持的图片尺寸格式：{value}")
    return int(match.group(1)), int(match.group(2))


def valid_png(path: Path, expected_size: tuple[int, int]) -> bool:
    path = _io_path(path)
    if not path.is_file() or path.stat().st_size <= 0:
        return False
    try:
        from PIL import Image

        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            return image.format == "PNG" and image.size == expected_size
    except Exception:
        return False


def target_review_status(target: Path) -> str | None:
    validation_path = target.with_suffix(".validation.json")
    if not validation_path.is_file():
        return None
    try:
        status = load_json(validation_path).get("status")
    except (OSError, ValueError, TypeError):
        return None
    return str(status) if status else None


def reusable_target(target: Path, expected_size: tuple[int, int]) -> bool:
    return valid_png(target, expected_size) and target_review_status(target) not in {"needs_fix", "rejected"}


def record_review_status(record: dict[str, Any]) -> str | None:
    target = Path(record["target"])
    status = target_review_status(target)
    if status:
        return status
    legacy_target = Path(record.get("legacy_target") or target)
    if legacy_target.resolve() != target.resolve():
        return target_review_status(legacy_target)
    return None


def _artifact_reference(path_value: str | Path, batch_dir: Path) -> str:
    path = Path(path_value).resolve()
    for base in (batch_dir.resolve(), ROOT.resolve()):
        try:
            return str(path.relative_to(base)).replace("\\", "/")
        except ValueError:
            continue
    return str(path)


def _tuning_sample_binding() -> tuple[str, int] | None:
    project_id = os.environ.get(TUNING_SAMPLE_PROJECT_ENV, "").strip()
    group_text = os.environ.get(TUNING_SAMPLE_GROUP_ENV, "").strip()
    if not project_id and not group_text:
        return None
    if not project_id or not re.fullmatch(r"[a-z0-9_]+", project_id):
        raise CategoryPromptError("调优样片项目环境变量无效")
    if not re.fullmatch(r"[1-9]\d*", group_text):
        raise CategoryPromptError("调优样片组号环境变量必须是正整数")
    return project_id, int(group_text)


def _validate_tuning_sample_scope(
    category_id: str,
    group_start: int,
    group_count: int,
    scope: str,
) -> None:
    binding = _tuning_sample_binding()
    if binding is None:
        return
    project_id, sample_group = binding
    if (
        project_id != category_id
        or scope != "covers"
        or group_count != 1
        or group_start != sample_group
    ):
        raise CategoryPromptError(
            "调优草稿只允许注入指定项目的一组首图样片，不能用于多组、详情或其他类目"
        )


def _load_active_tuning_sample_drafts(project_id: str) -> list[dict[str, Any]]:
    path = ROOT / ".runtime" / "projects" / project_id / "prompt_tuning_drafts.jsonl"
    if not path.is_file():
        raise CategoryPromptError(f"找不到 {project_id} 的调优样片草稿")
    drafts = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    ]
    active = [item for item in drafts if item.get("status") == "active"]
    if len(active) != 1:
        raise CategoryPromptError("调优样片必须且只能有一条 active 草稿")
    return active


def _tuning_sample_suffix(record: dict[str, Any]) -> str:
    binding = _tuning_sample_binding()
    if binding is None:
        return ""
    project_id, sample_group = binding
    category_id = str(record.get("category_id") or DEFAULT_CATEGORY_ID)
    generation_kind = str(record.get("generation_kind") or record.get("role") or "")
    if (
        category_id != project_id
        or generation_kind != "cover"
        or int(record.get("group_index") or 0) != sample_group
    ):
        return ""
    draft = _load_active_tuning_sample_drafts(project_id)[0]
    if draft.get("project_id") != project_id or draft.get("role") != "cover":
        raise CategoryPromptError("调优样片草稿与当前项目或首图角色不匹配")
    note = str(draft.get("note") or "").strip()
    if not note or contains_contact_number(note):
        raise CategoryPromptError("调优样片草稿为空或包含联系电话")
    dimension = str(draft.get("dimension") or "").strip()
    action = str(draft.get("action") or "").strip()
    return (
        f"\n本次单张调优样片覆盖规则（只调整一个维度，不得削弱其他安全规则）："
        f"维度为“{dimension}”，动作为“{action}”。{note}"
        "门店精致度来自较新的真实建筑维护、通透玻璃、干净实体材料和整齐营业状态，"
        "不是豪华装修、影棚布光、网红店、品牌VI、广告效果图或卡通设计。"
    )


def _validate_project_tuning_note(project_id: str, note: str) -> None:
    if project_id != "truck_rescue":
        return
    library = load_signage_library(
        ROOT / "projects" / "truck_rescue" / "cover_scene_library.json"
    )
    leaked_names = [
        item["full_store_name"]
        for item in library["brand_name_candidates"]
        if item["full_store_name"] in note
    ]
    if leaked_names:
        raise CategoryPromptError(
            "货车项目长期调优规则不得固化某一组完整店名："
            + "、".join(leaked_names)
        )


def _approved_project_tuning_suffix(record: dict[str, Any]) -> str:
    project_id = str(record.get("category_id") or DEFAULT_CATEGORY_ID)
    path = ROOT / "projects" / project_id / "preferences" / "prompt_tuning_rules.jsonl"
    if not path.is_file():
        return ""
    rules = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    ]
    active = [
        item
        for item in rules
        if item.get("status") == "active"
        and item.get("scope") == "project"
        and item.get("project_id") == project_id
        and item.get("role") == "cover"
    ]
    if not active:
        return ""
    parts: list[str] = []
    for item in active:
        note = str(item.get("note") or "").strip()
        if not note or contains_contact_number(note):
            raise CategoryPromptError("已批准的项目调优规则为空或包含联系电话")
        _validate_project_tuning_note(project_id, note)
        dimension = str(item.get("dimension") or "").strip()
        action = str(item.get("action") or "").strip()
        parts.append(f"维度“{dimension}”、动作“{action}”：{note}")
    return "\n项目已批准的长期门头规则：" + "；".join(parts)


PET_STORE_NAMES = ("安宠托运", "顺宠托运", "安心宠运", "畅宠托运", "家宠出行")

PET_VEHICLES = (
        "一辆中国常见白色小型MPV停在门店侧方，只占画面约四分之一，车身有正常使用痕迹",
        "一辆中国常见银灰色小型厢式服务车斜停在门前，不遮挡招牌和店门",
        "只在画面边缘露出普通白色SUV的侧后部，门店外景仍是绝对主体",
        "一辆维护正常的白色小型面包车停在路边，后门关闭，不做物流品牌展示",
        "不出现完整车辆，只在门店一侧露出普通服务车局部，避免车辆压过门店外景",
    )

PET_ACTIONS = (
        "一名穿普通耐脏工装的中国工作人员在店门外检查关闭运输笼的门锁和固定卡扣",
        "两名中国工作人员在店门口用笼具推车平稳移动关闭的运输笼，动作自然且不看镜头",
        "工作人员在停稳的普通服务车旁核对运输笼和固定带，门店完整外立面清楚保留在背景",
        "工作人员在店门外整理空运输笼、吸水垫和牵引装备，所有物品有正常使用痕迹",
        "工作人员与客户在门店入口旁完成照护交接，猫位于关闭运输箱内，狗使用合身牵引装备",
    )

@variable_catalog.managed('pet_transport','cover')
def _pet_transport_cover_prompt(record: dict[str, Any], phone: str) -> str:
    """Build pet covers from the approved road-rescue storefront language.

    Pet-specific source prompts are intentionally not reused here.  The first
    batch over-emphasised pets and signboard design, which made the results
    look illustrated.  This builder reuses the road-rescue storefront axes and
    changes only the service evidence, text and ordinary service vehicle.
    """
    library = load_json(ROOT / "projects" / "road_rescue" / "cover_scene_library.json")
    pet_library = load_json(ROOT / "projects" / "pet_transport" / "cover_scene_library.json")
    group_index = max(1, int(record.get("group_index") or record.get("index") or 1))
    offset = group_index - 1

    def choose(key: str, step: int = 1, shift: int = 0) -> str:
        values = library.get(key)
        if not isinstance(values, list) or not values or not all(
            isinstance(item, str) and item.strip() for item in values
        ):
            raise CategoryPromptError(f"汽车救援门店风格库缺少有效变化轴：{key}")
        return values[(offset * step + shift) % len(values)].strip()

    era_profiles = library.get("era_profiles")
    if not isinstance(era_profiles, list) or not era_profiles:
        raise CategoryPromptError("汽车救援门店风格库缺少 era_profiles")
    era = era_profiles[offset % len(era_profiles)]
    if not isinstance(era, dict):
        raise CategoryPromptError("汽车救援门店风格库 era_profiles 格式无效")

    store_names = PET_STORE_NAMES
    vehicle_variants = PET_VEHICLES
    action_variants = PET_ACTIONS

    store_name = store_names[offset % len(store_names)]
    vehicle = vehicle_variants[(offset * 2) % len(vehicle_variants)]
    action = action_variants[(offset * 3) % len(action_variants)]
    facade = choose("facade_archetypes", step=2)
    storefront_layout = choose("storefront_layouts", step=3, shift=1)
    signboard_variants = pet_library.get("signboard_variants")
    if not isinstance(signboard_variants, list) or not signboard_variants or not all(
        isinstance(item, str) and item.strip() for item in signboard_variants
    ):
        raise CategoryPromptError("宠物托运门店风格库缺少 signboard_variants")
    # Group 1 already holds the approved density sample.  Start the next five
    # covers with the warm-brown reference-inspired option, then rotate through
    # distinct coordinated palettes instead of repeating white signboards.
    signboard_variant = signboard_variants[(offset - 1) % len(signboard_variants)].strip()
    sign_shape = choose("sign_shapes", step=3)
    sign_condition = choose("sign_conditions", step=2)
    sign_installation = choose("sign_installation_details", step=5)
    camera_composition = choose("camera_compositions", step=5)
    camera_style = choose("camera_styles", step=3)
    shop_state = choose("shop_states", step=2)
    weather = choose("weather_atmospheres", step=3)
    lighting = choose("lighting", step=3)
    street_activity = choose("street_activity_levels", step=3)
    foreground = choose("foreground_elements", step=2)

    base_prompt = (
        "一张完全依靠文字描述生成、不使用任何参考图片的写实中国宠物托运门店照片。"
        "整体视觉、真实程度、门店年代感、街道层次、手机镜头和构图逻辑必须与真实中国汽车救援门店工作记录照一致，"
        "只把汽车救援业务元素替换为宠物托运业务元素。"
        f"年代基准：{era.get('period')}，整体属于“{era.get('label')}”；{era.get('scene_cues')}。"
        "最高优先级构图是门店外景全景，不是招牌特写、室内照、宠物肖像或广告海报。"
        "相机必须退到人行道或街对面，完整拍到主招牌、店门或卷帘门、门店一层外立面、门前台阶或地面、人行道和路缘，"
        "并至少带入一侧邻店边缘、墙体、雨棚、电线管线或部分二层外墙，证明门头真实安装在建筑上。"
        "门店从招牌上沿到门前街面必须形成连续真实空间，不能裁成孤立门头，不能让猫狗、运输箱或车辆遮住大部分门店。"
        f"门店建筑：{facade}；门面布局：{storefront_layout}；营业状态：{shop_state}。"
        f"天气与光线：{weather}；{lighting}。街道状态：{street_activity}；前景关系：{foreground}。"
        f"门头底色不固定为白色，本组采用{signboard_variant}；结构为{sign_shape}；材质与使用状态为{sign_condition}；"
        f"安装细节为{sign_installation}。门头必须有普通实体板材、拼缝、包边、固定结构、轻微灰尘雨痕和自然投影，"
        "颜色、字色和环境光必须协调耐看，可以借鉴现代商场宠物店的暖棕或深灰底板与立体发光字材质语言，"
        "但仍是本项目自己的真实门店，不复制任何参考店名、图标、logo或完整招牌设计，不生成截图黑边、手机状态栏或相册界面。"
        "不能像品牌VI、招牌设计稿、网页横幅或发光UI面板，也不能做成黑金高端会所、霓虹科技展厅或五颜六色广告牌。"
        f"门头上层使用较小的泛化店名“{store_name}”，最大主业务词必须清晰准确写成“宠物托运”，"
        "下层服务小字必须清晰准确写成“猫咪托运 · 狗狗托运 · 上门接送 · 照护交接”。"
        f"同一主招牌板面内部必须清晰准确写出“联系电话：{phone}”，优先放在板面底部或右侧联系区；"
        "店名、主业务词、服务小字和联系电话必须具有同一透视、同一板材、同一环境光和自然实体字厚度，"
        "不得成为悬浮字幕、贴纸、横幅、立柱文字、墙面文字、车身文字或独立立牌。"
        f"现场业务证据：{action}；{vehicle}。运输笼、推车、固定带和牵引装备比例与结构真实，"
        "人物手部必须真实接触笼具或装备，衣服有自然褶皱和轻微工作痕迹。"
        "猫狗只作为真实交接现场中的次要服务对象，不看镜头摆拍，不做大头特写，不作为萌宠主视觉；"
        "毛发、眼睛、四肢和身体比例必须像真实摄影，绝不允许卡通化、动漫化、拟人化、玩偶化或吉祥物化。"
        f"拍摄方式：{camera_style}；镜头构图：{camera_composition}。竖屏2:3原图，按9:16安全区构图，"
        "像工作人员或路人用普通智能手机临时拍下的真实营业记录，允许轻微手持偏斜、广角透视、边缘遮挡、"
        "自动曝光不均、自然白平衡偏差、轻微手机噪点、玻璃反光、墙面旧痕、路面灰尘水迹和真实环境杂物；"
        "色彩平淡自然，不做商业广告摄影或电影调色。"
        "画面中部43%至53.5%为本地后期电话保留可读背景，下部70%至96.5%以门前街面或地面为主，"
        "供本地后期添加八个服务词；人物脸、宠物头部、笼门锁扣、手部接触点和门头核心文字不得落入主要覆盖区。"
        "原图不要提前生成中部电话条、底部服务按钮、卡片、边框或宫格UI。"
        "严格排除：卡通、动漫、漫画、插画、二维绘画、三维动画、CG、3D渲染、游戏画面、儿童绘本、"
        "萌宠海报、宠物头像海报、拟人宠物、吉祥物、玩偶质感、塑料毛发、夸张大眼睛；"
        "排除广告设计稿、品牌VI提案、门店效果图、精致连锁店、豪华宠物酒店、科技展厅、影棚布光、"
        "绝对对称、正交立面、过度干净、过度锐化、强HDR、霓虹光效、橙青电影调色和大片金色逆光；"
        "排除欧美街景、机场航空宣传、铁路物流宣传、真实品牌logo、复杂图标、爪印卡通图标、二维码、水印、价格、"
        "可读车牌、其他电话号码、未确认服务承诺和乱码文字；排除塑料皮肤、蜡像脸、畸形手指、畸形宠物、"
        "笼具穿模、错误车体比例、宠物惊恐受伤、危险装载和广告模特摆拍。"
    )
    return (
        base_prompt
        + _approved_project_tuning_suffix(record)
        + _tuning_sample_suffix(record)
    )


def _pet_transport_detail_realism_suffix() -> str:
    return (
        "\n宠物托运全局写实硬规则：画面必须是中国本地服务人员用普通手机拍摄的真实工作记录，"
        "使用自然光或普通环境灯，允许轻微手持偏斜、手机噪点、玻璃反光、墙地面旧痕、车辆和笼具使用痕迹；"
        "人物不看镜头、不摆造型，手部与笼具、固定带、牵引装备或车辆接触关系真实。"
        "猫狗的毛发、眼睛、四肢和身体比例必须符合真实摄影，绝不允许卡通、动漫、漫画、插画、CG、3D动画、"
        "拟人宠物、吉祥物、玩偶、萌宠海报、夸张大眼、塑料毛发、品牌VI、广告设计稿或商业影棚效果。"
    )


def _sanitize_road_rescue_cover_prompt(prompt: str) -> str:
    """Remove legacy copy that teaches the image model to draw local overlays."""
    cleaned = prompt
    legacy_patterns = (
        r"画面中部偏下必须为后期电话条保留干净横向区域，[^。]*。",
        r"画面底部必须为本地后处理十宫格服务项目区保留规整空间，[^。]*。",
        r"最终电话号码还会在图片生成完成后由本地图像处理程序居中叠加，[^。]*。",
        r"图片底部还会由本地图像处理程序叠加[^。]*。",
    )
    for pattern in legacy_patterns:
        cleaned = re.sub(pattern, "", cleaned, count=1)
    return cleaned.replace(
        "门头号码由模型原生生成并人工验收，中部电话和底部服务词以后期本地叠加与人工验收为准；",
        "门头号码由模型原生生成并人工验收；画面中部和底部必须保持未排版的连续真实场景；",
    )


def effective_prompt(record: dict[str, Any], phone: str) -> str:
    if "frozen_effective_prompt" in record:
        raise CategoryPromptError(
            "冻结生产清单运行时记录禁止重算 original prompt；请直接使用 frozen_effective_prompt"
        )
    prepared = record.get("prompt")
    if isinstance(prepared, str) and prepared.strip():
        category_id = str(record.get("category_id") or DEFAULT_CATEGORY_ID)
        generation_kind = str(record.get("generation_kind") or record.get("role") or "")
        prompt_phones = set(extract_contact_numbers(prepared))
        native_signboard_phone = (
            category_id in MODEL_GENERATED_SIGNBOARD_CATEGORIES
            and generation_kind == "cover"
        )
        if native_signboard_phone:
            unexpected = prompt_phones - {phone}
            if unexpected:
                raise CategoryPromptError("门头提示词包含未经确认的其他联系电话")
        elif prompt_phones:
            raise CategoryPromptError("最终生成提示词不得包含联系电话；号码只能由本地程序叠加")
        if category_id == "pet_transport" and generation_kind == "cover":
            if record.get('catalog_prepared_prompt'):
                return visual_style_profiles.ensure_target_mode(prepared.replace('{已确认电话}', phone), category_id)
            token = variable_catalog.DISABLED.set(True)
            try:
                return visual_style_profiles.ensure_target_mode(_pet_transport_cover_prompt(record, phone), category_id)
            finally:
                variable_catalog.DISABLED.reset(token)
        prepared = prepared.strip()
        if native_signboard_phone:
            prepared = prepared.replace(
                "\n道路救援 v3 补充规则：原始生图画面不要生成任何真实电话号码、二维码、水印、价格或可读车牌；"
                "门头联系电话、中心电话条和底部十宫格服务词全部由本地图像处理程序叠加。",
                "\n道路救援 v6 补充规则：门头联系电话使用生产时注入的当前已确认号码，由模型作为实体招牌排版自然生成；"
                "不要生成其他电话号码、二维码、水印、价格、可读车牌、中心电话条或底部十宫格服务词。",
            )
        if category_id == "pipe_unclogging" and generation_kind == "cover":
            prepared += (
                "\n管道疏通封面最高优先级覆盖规则：原始照片只保留建筑上真实安装、板材纹理和透视完整的哑光实体招牌板面。"
                "板面保持无字，不得生成灯箱、LED灯带、霓虹字、发光字、发光叠加板、半透明彩色板或另一块覆盖原门头的新底板。"
                "不要生成任何可读文字、数字、按钮、卡片、悬浮字幕或UI面板。门头标题、门头业务词、门头联系电话、"
                "中心电话和底部服务词全部由本地图像处理程序后加。"
            )
        if category_id == "road_rescue" and generation_kind == "cover":
            prepared = _sanitize_road_rescue_cover_prompt(prepared)
            if record.get("cover_template_version") == "road_rescue_storefront_mobile_v3":
                prepared += (
                    "\n道路救援未来首图最高优先级规则：本组只使用提示词指定的一种门店、机位、天气和救援车可见度，"
                    "严格执行指定车辆的位置和大小，不额外添加车辆，不把人物排成广告照。"
                    f"门头实体板面内只使用确认号码“{phone}”，号码完整清楚地处于原图上方百分之四十以内，"
                    "中部百分之五十至六十是后期电话条区域，两处不能重叠。"
                    "门头文字与材质透视一致；除指定店名、业务词和号码外，车辆、工作服和邻店不得出现伪字、"
                    "乱码号码、虚构品牌或可读车牌。车辆和工服可以不带字。"
                    "中部和底部仍是连续真实照片，不预先生成电话横幅、服务方格或UI。"
                )
            else:
                prepared += (
                "\n道路救援封面最高优先级覆盖规则：门头联系电话必须由图像模型作为真实实体招牌排版的一部分自然生成，"
                f"号码必须清楚准确写成“{phone}”，并与门头店名、汽车救援主业务词和服务小字使用同一板面、"
                "同一透视、同一材质与同一环境光。"
                "推荐从上到下形成店名、汽车救援主业务词、服务小字、联系电话四层信息，"
                "联系电话优先位于主招牌板面底部或右侧联系信息区，不得成为悬浮字幕或后期贴纸。"
                "实体门头至少形成主标题、业务信息和真实安装细节三个层级，可使用窄服务信息带、板材拼缝、"
                "金属收边、小面积强调色或普通门头筒灯增加丰富度，但不要做成空白大板，也不要堆满内容。"
                "不得在实体招牌外再叠加彩色半透明板、发光叠加板或另一块覆盖原门头的新底板。"
                "不要生成联系电话占位符、错误号码、额外号码、悬浮字幕、卡片、按钮、内外边框或 UI 面板。"
                "本地图像处理程序不再向门头区域添加任何文字或底板；只有画面中部大电话和底部服务词由本地后加，"
                "画面中部横向预留区和画面底部服务区只能保留连续真实的门店、车辆、街景或地面，"
                "不得出现电话号码、电话图标、电话胶囊、横幅、色条、服务列表、蓝色服务方格、十宫格、按钮、卡片、海报或 UI。"
                "即使前文提到预留区域，也只能留空实景，不得提前画出本地后期版式。"
                )
        if category_id == "home_appliance_repair" and generation_kind == "cover":
            prepared += (
                "\n家电维修封面最高优先级覆盖规则：门头联系电话必须由图像模型作为实体招牌排版的一部分自然生成，"
                f"号码必须清楚准确写成“{phone}”，并与本组指定家电维修店名、服务小字使用同一块实体板面、"
                "同一透视、同一材质和同一环境光；不得成为悬浮字幕、墙面贴纸或额外广告牌。"
                "只允许出现家电、厨电、空调、电视、电脑及其维修工具，严格排除汽车救援、货车救援、拖车、"
                "轮胎、搭电和救援车辆。画面中部与底部保持连续真实场景，不提前生成电话横幅、服务方格、按钮、卡片或UI。"
            )
        if category_id == "truck_rescue" and generation_kind == "cover":
            tuning_sample_suffix = _tuning_sample_suffix(record)
            group_index = int(record.get("group_index") or 0)
            if group_index >= NAMING_EPOCH_GROUP:
                truck_signage = resolve_signage_variant(
                    record,
                    ROOT / "projects" / "truck_rescue" / "cover_scene_library.json",
                )
                prepared = prepared.replace(
                    "主招牌最大业务词必须清楚准确写成“货车救援维修”，",
                    "主招牌的两字寓意字号与行业尾缀必须按本组指定完整名称执行，",
                )
                prepared = prepared.replace(
                    "货车救援维修主字",
                    "完整主名称实体字",
                )
                prepared = normalize_signage_typography(prepared, truck_signage)
                if truck_signage["full_store_name"] not in prepared:
                    prepared += "\n货车门头命名最高优先级覆盖规则：" + signage_override_text(
                        truck_signage
                    )
                if tuning_sample_suffix:
                    title_relationship = "门头寓意字号、行业尾缀和服务小字"
                    hierarchy = "寓意字号、行业尾缀、六类服务小字、联系电话四层信息"
                else:
                    title_relationship = "门头两字寓意字号、行业尾缀和服务小字"
                    hierarchy = "两字寓意字号、行业尾缀、六类服务小字、联系电话四层信息"
            else:
                title_relationship = "门头店名、货车救援维修主业务词和服务小字"
                hierarchy = "泛化店名、货车救援维修主业务词、六类服务小字、联系电话四层信息"
            hierarchy_rule = f"推荐从上到下形成{hierarchy}；"
            if group_index >= 374:
                from tools.truck_cover_typography import cover_plan

                variant = record.get("cover_variant") or record.get("scene") or {}
                if variant.get("reference_learning_version") != "truck_reference_learning_v1_g0374":
                    raise CategoryPromptError("新货车首图缺少已确认的参考学习规则版本")
                local_plan = cover_plan(group_index)
                phone_region = local_plan["center_phone_region"]
                service_region = local_plan["bottom_service_region"]
                reserve_text = (
                    f"中部{phone_region[1] * 100:g}%至{phone_region[3] * 100:g}%是本组本地电话文字安全区，"
                    f"底部{service_region[1] * 100:g}%至{service_region[3] * 100:g}%是本地十服务词安全区。"
                )
                prepared = prepared.replace(
                    "中部43%至53.5%是本地电话条安全区，下部70%至96.5%是本地十服务词安全区。",
                    reserve_text,
                )
                hierarchy_rule = (
                    f"实体招牌按本组指定信息布局执行：{truck_signage['sign_information_layout']}；"
                    "完整店名使用普通顺口字号和货车行业尾缀，字高协调、行业清楚，不把两字字号夸张放大。"
                    "不统一套用从上到下四层信息，也不强制门头、车间、前景工人三层同框；"
                    f"画面遵循本组构图侧重点“{variant['composition_emphasis']}”。"
                    "本地加字样式仅是附加，原图仍为连续实景，不生成描边字幕或服务词碎字。"
                    f"{reserve_text}安全区不能放人脸、手与工具接触点或核心维修部位；"
                )
            prepared += (
                "\n货车救援维修封面最高优先级覆盖规则：门头联系电话必须由图像模型作为真实实体招牌排版的一部分自然生成，"
                f"号码必须清楚准确写成“{phone}”，并与{title_relationship}使用同一板面、"
                "同一透视、同一材质与同一环境光。"
                f"{hierarchy_rule}"
                "电话应在主招牌板面底部或右侧联系区，不得放在横幅、立柱、墙面、车辆、立牌或店内背景。"
                "不得出现汽车救援、轿车救援、乘用车快修文字，也不得生成其他号码、价格、二维码、水印、"
                "中心电话条、底部服务按钮、悬浮字幕、卡片或 UI 面板。"
            )
            if group_index >= NAMING_EPOCH_GROUP:
                prepared += _approved_project_tuning_suffix(record)
                prepared += tuning_sample_suffix
        if category_id == "pet_transport":
            prepared += _pet_transport_detail_realism_suffix()
        return visual_style_profiles.ensure_target_mode(prepared, category_id)
    generation_kind = _generation_kind(record)
    service_role = _service_role(record)
    role = "cover" if generation_kind == "cover" else str(service_role or "")
    specification = cover_specification(record) if generation_kind == "cover" else ROLE_PRODUCTION_SPECS.get(role)
    if not isinstance(specification, str) or not specification:
        raise CategoryPromptError(f"没有找到角色的生产提示词规则：{role}")
    reserve_top = (
        "详情图顶部3.5%至10.5%留出简洁背景，供本地程序添加角色标签；"
        if generation_kind == "detail" else ""
    )
    reserve_zones = (
        "画面中部43%至53.5%留出横向可读背景，下部70%至96.5%以街面或地面为主，供本地程序添加电话和服务词；"
        if generation_kind == "cover"
        else (
            "画面主体保持在中央安全区，四周保留少量可裁切背景，供本地程序裁切并组成三拼图；"
            if generation_kind == "triptych_panel"
            else "画面中部49%至58.5%留出横向简洁背景，底部83.5%至97.5%留出简洁背景，供本地程序添加电话条和服务词；"
        )
    )
    cover_layout = (
        "首图叠字风格参考真实本地服务短视频封面：中部电话将使用大号高对比描边字直接叠在场景上，"
        "底部服务词将直接排在街面或地面上；原图不要生成黑色整条电话带、圆角卡片、网页按钮或宫格UI。"
        if generation_kind == "cover" else ""
    )
    unit_note = (
        "本图是三拼图的一个独立实景面板，只表现一个明确施工现场；不要自行生成拼贴、边框、标题或分栏。"
        if generation_kind == "triptych_panel"
        else ""
    )
    common = (
        "用途：管道疏通本地生活服务组图。真实中国本地生活服务现场，普通手机随手拍质感，"
        "自然光或普通室内灯光，真实材质、正常人体与施工动作，轻微水渍和使用痕迹，画面实用、克制、可信。"
        f"固定服务角色：{role}。必须入画：{specification}{unit_note}"
        "输出2:3竖图，按9:16安全裁切区构图；关键人物、工具和施工接触点不要贴近左右边缘。"
        f"{reserve_top}{reserve_zones}关键动作不得被这些区域遮挡。"
        f"{cover_layout}"
        "原始画面不要生成任何电话号码、可读文字、品牌、价格、商标、水印或二维码。"
    )
    return visual_style_profiles.ensure_target_mode(
        f"{common}\n严格排除：{record['negative_prompt']}",
        str(record.get("category_id") or DEFAULT_CATEGORY_ID),
    )


def build_manifest_entries(
    batch_dir: Path,
    records: list[dict[str, Any]],
    phone: str,
    service_items: list[str],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for record in records:
        prompt = effective_prompt(record, phone)
        overlay_service_items = _record_overlay_service_items(record, service_items)
        generation_profile = category_generation_profile.config_profile(
            config, str(record.get("category_id") or DEFAULT_CATEGORY_ID),
        )
        entry = {
            "schema_version": PRODUCTION_SCHEMA_VERSION,
            "structure_version": str(record.get("structure_version") or GROUP_STRUCTURE_VERSION),
            "generation_mode": str(record.get("generation_mode") or GENERATION_MODE),
            "category_id": str(record.get("category_id") or DEFAULT_CATEGORY_ID),
            "batch_id": batch_dir.name,
            "target_id": str(record["generation_target_id"]),
            "generation_target_id": str(record["generation_target_id"]),
            "delivery_target_id": str(record["delivery_target_id"]),
            "source_index": int(record["index"]),
            "group_index": int(record["group_index"]),
            "position": int(record["generation_position"]),
            "generation_position": int(record["generation_position"]),
            "delivery_position": int(record["delivery_position"]),
            "generation_kind": str(record["generation_kind"]),
            "role": str(record["generation_kind"]),
            "service_role": record.get("service_role"),
            "panel_index": record.get("panel_index"),
            "height_profile_id": record.get("height_profile_id"),
            "final_size": str(record["final_size"]),
            "triptych_layout_id": record.get("triptych_layout_id"),
            "source_positive_prompt": str(record.get("positive_prompt") or record.get("source_positive_prompt") or record.get("prompt") or ""),
            "negative_prompt": str(record.get("negative_prompt") or ""),
            "effective_prompt": prompt,
            "effective_prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "target": _artifact_reference(record["target"], batch_dir),
            "legacy_target": _artifact_reference(record["legacy_target"], batch_dir),
            "raw_target": _artifact_reference(record["raw_target"], batch_dir),
            "model": config["model"],
            "quality": config["quality"],
            "size": config["api_size"],
            "raw_api_size": generation_profile["working_raw_size"] if generation_profile else config["api_size"],
            **({"generation_profile": generation_profile} if generation_profile else {}),
            "confirmed_phone": phone,
            "service_items": overlay_service_items,
            "overlay_schema_version": OVERLAY_SCHEMA_VERSION,
            "target_mode": visual_style_profiles.target_mode_metadata(
                str(record.get("category_id") or DEFAULT_CATEGORY_ID)
            ),
            "status": "pending",
        }
        if str(record["generation_kind"]) == "cover":
            category_id = str(record.get("category_id") or DEFAULT_CATEGORY_ID)
            group_index = int(record.get("group_index") or 0)
            style_version = cover_style_version(category_id, group_index)
            if category_id == "truck_rescue" and group_index >= NAMING_EPOCH_GROUP:
                variant = dict(record.get("cover_variant") or {})
                variant.update(
                    resolve_signage_variant(
                        record,
                        ROOT / "projects" / "truck_rescue" / "cover_scene_library.json",
                    )
                )
                if isinstance(variant.get("signboard_variant"), str):
                    variant["signboard_variant"] = variant["signboard_variant"].replace(
                        "货车救援维修主字",
                        "完整主名称实体字",
                    )
                material = json.dumps(
                    variant,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                signature = hashlib.sha256(material.encode("utf-8")).hexdigest()
            elif record.get("cover_variant_signature"):
                variant = dict(record.get("cover_variant") or {})
                signature = str(record["cover_variant_signature"])
            else:
                variant = select_cover_variant(record)
                signature = cover_variant_signature(record, variant)
            entry.update({
                "cover_style_version": style_version,
                "cover_variant_id": f"cover-v{style_version}-{signature[:12]}",
                "cover_variant_signature": signature,
                "cover_variant": variant,
            })
            typography_plan = _truck_cover_typography_plan(category_id, group_index)
            if typography_plan is not None:
                entry["cover_typography_plan"] = typography_plan
            if category_id in {"road_rescue", "home_appliance_repair"} and group_index >= ROAD_RESCUE_COVER_V3_FIRST_GROUP:
                entry["cover_center_phone_region"] = cover_center_phone_region(category_id, group_index)
                entry["cover_bottom_service_region"] = road_rescue_bottom_service_region(group_index)
                entry["bottom_service_style_id"] = road_rescue_bottom_service_style(group_index)["style_id"]
        entries.append(entry)
    return entries


def _record_overlay_service_items(
    record: dict[str, Any],
    default_items: list[str],
) -> list[str]:
    category_id = str(record.get("category_id") or DEFAULT_CATEGORY_ID)
    generation_kind = str(record.get("generation_kind") or record.get("role") or "")
    if category_id != "pet_transport" or generation_kind != "detail":
        return list(default_items)
    category = load_category_config(category_id)
    configured = category.get("detail_service_keyword_pool")
    if (
        not isinstance(configured, list)
        or len(configured) < 11
        or not all(isinstance(item, str) and item.strip() for item in configured)
        or len(set(configured)) != len(configured)
    ):
        raise CategoryPromptError(
            "pet_transport detail_service_keyword_pool must contain at least 11 unique items"
        )
    service_role = str(record.get("service_role") or "").strip()
    candidates = [item.strip() for item in configured if item.strip() != service_role]
    if len(candidates) < 10:
        raise CategoryPromptError("宠物托运详情词池排除顶部角色后不足10项")
    group_index = max(1, int(record.get("group_index") or 1))
    position = max(2, int(record.get("delivery_position") or record.get("position") or 2))
    offset = ((group_index - 1) * 5 + position - 2) % len(candidates)
    selected = [candidates[(offset + index) % len(candidates)] for index in range(10)]
    if len(set(selected)) != 10 or service_role in selected:
        raise CategoryPromptError("宠物托运详情本地关键词发生重复或复用了顶部角色")
    forbidden = ("汽车救援", "搭电", "拖车", "补胎", "换胎", "送油", "地库救援", "高速救援")
    if any(any(term in item for term in forbidden) for item in selected):
        raise CategoryPromptError("宠物托运详情本地关键词混入道路救援词")
    return selected


def manifest_sha256(entries: list[dict[str, Any]]) -> str:
    material = json.dumps(entries, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _truck_cover_typography_plan(category_id: str, group_index: int) -> dict[str, Any] | None:
    from tools import truck_cover_typography

    if category_id != "truck_rescue" or group_index < truck_cover_typography.FIRST_GROUP:
        return None
    # JSON-native lists make in-memory, on-disk and rendered plans comparable.
    return json.loads(json.dumps(truck_cover_typography.cover_plan(group_index)))


def _bound_cover_typography_plans(entries: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if entry.get("generation_kind") != "cover":
            continue
        group_index = int(entry["group_index"])
        expected = _truck_cover_typography_plan(str(entry["category_id"]), group_index)
        if expected is None:
            continue
        if entry.get("cover_typography_plan") != expected:
            raise CategoryPromptError("新货车首图完整叠字计划缺失、被篡改或已变化；请重新核算")
        result[str(group_index)] = expected
    return result


def validate_frozen_cover_typography(run_plan: dict[str, Any], license_data: dict[str, Any]) -> None:
    """Read-only guard before start/worker; old covers are deliberately untouched."""
    if (run_plan.get("category_id") != "truck_rescue"
            or int(run_plan.get("group_start", 0)) + int(run_plan.get("group_count", 0)) <= 374
            or run_plan.get("scope") == "details"):
        return
    plans = _bound_cover_typography_plans(run_plan["manifest_entries"])
    if not plans:
        return
    if run_plan.get("cover_styles_by_group") != plans:
        raise CategoryPromptError("新货车首图计划与manifest的完整叠字参数不一致")
    batch = Path(run_plan["batch_dir"])
    license_id = str(license_data.get("license_id") or "")
    frozen_manifest = manifest_path(batch, run_plan["group_start"], run_plan["group_count"], license_id)
    frozen_overlay = overlay_plan_path(batch, run_plan["group_start"], run_plan["group_count"], license_id)
    for key, path in (("production_manifest", frozen_manifest), ("overlay_plan", frozen_overlay)):
        if (str(license_data.get(key) or "") != str(path) or not path.is_file()):
            raise CategoryPromptError("新货车首图冻结生产证据缺失或路径身份不一致")
    entries = [json.loads(line) for line in frozen_manifest.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    if (manifest_sha256(entries) != license_data.get("manifest_sha256")
            or entries != json.loads(json.dumps(run_plan["manifest_entries"]))):
        raise CategoryPromptError("新货车首图冻结manifest与许可证或最新计划不一致")
    overlay = load_json(frozen_overlay)
    if (overlay.get("plan_sha256") != run_plan["plan_sha256"]
            or overlay.get("license_id") != license_id
            or overlay.get("cover_styles_by_group") != plans):
        raise CategoryPromptError("新货车首图冻结overlay的完整叠字参数与计划不一致")


def _resolve_frozen_manifest_artifact(
    value: Any,
    *,
    base: Path,
    allowed_root: Path,
    required_prefix: tuple[str, ...],
    field: str,
) -> Path:
    reference = str(value or "").strip()
    if not reference or "\\" in reference or re.match(r"^[A-Za-z]:", reference):
        raise CategoryPromptError(f"冻结生产清单 {field} 必须是 POSIX 相对路径")
    relative = PurePosixPath(reference)
    if (
        relative.is_absolute()
        or len(relative.parts) <= len(required_prefix)
        or tuple(relative.parts[: len(required_prefix)]) != required_prefix
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise CategoryPromptError(
            f"冻结生产清单 {field} 必须位于 {'/'.join(required_prefix)}/ 下"
        )
    resolved = (base / Path(*relative.parts)).resolve()
    allowed = allowed_root.resolve()
    if resolved == allowed or allowed not in resolved.parents:
        raise CategoryPromptError(f"冻结生产清单 {field} 越过允许目录")
    return resolved


def load_frozen_manifest_runtime_records(
    batch_dir: str | Path,
    frozen_manifest: str | Path,
    expected_manifest_sha256: str | None = None,
) -> list[dict[str, Any]]:
    """Load resume records without recomputing a licensed original prompt.

    Resume callers must send ``record['frozen_effective_prompt']`` for the
    original attempt. Passing a returned record to :func:`effective_prompt`
    raises instead of silently rebuilding it from mutable project state.
    """

    current_batch = Path(batch_dir).resolve()
    manifest_file = Path(frozen_manifest).resolve()
    expected_parent = (production_dir(current_batch) / "manifests").resolve()
    if manifest_file.parent != expected_parent or manifest_file.suffix.lower() != ".jsonl":
        raise CategoryPromptError(
            f"冻结生产清单必须位于批次 manifests 目录：{expected_parent}"
        )
    if not manifest_file.is_file():
        raise CategoryPromptError(f"冻结生产清单不存在：{manifest_file}")
    try:
        entries = [
            json.loads(line)
            for line in manifest_file.read_text(encoding="utf-8-sig").splitlines()
            if line.strip()
        ]
    except (OSError, ValueError, TypeError) as error:
        raise CategoryPromptError("冻结生产清单不是有效 JSONL") from error
    if not entries or any(not isinstance(entry, dict) for entry in entries):
        raise CategoryPromptError("冻结生产清单必须包含至少一条对象记录")
    actual_manifest_sha256 = manifest_sha256(entries)
    if expected_manifest_sha256 is not None:
        expected_hash = str(expected_manifest_sha256).strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
            raise CategoryPromptError("expected_manifest_sha256 必须是 64 位 SHA-256")
        if actual_manifest_sha256 != expected_hash:
            raise CategoryPromptError("冻结生产清单 SHA-256 与许可证不一致")

    source_by_index: dict[int, dict[str, Any]] = {}
    for source in read_prompts(current_batch):
        try:
            source_index = int(source["index"])
        except (KeyError, TypeError, ValueError) as error:
            raise CategoryPromptError("源提示词包含无效 index") from error
        if source_index in source_by_index:
            raise CategoryPromptError(f"源提示词 index 重复：{source_index}")
        source_by_index[source_index] = source

    result: list[dict[str, Any]] = []
    generation_ids: set[str] = set()
    delivery_bindings: dict[str, tuple[Any, ...]] = {}
    for entry in entries:
        try:
            source_index = int(entry["source_index"])
            group_index = int(entry["group_index"])
            generation_position = int(entry["generation_position"])
            delivery_position = int(entry["delivery_position"])
        except (KeyError, TypeError, ValueError) as error:
            raise CategoryPromptError("冻结生产清单包含无效身份序号") from error
        source = source_by_index.get(source_index)
        if source is None:
            raise CategoryPromptError(
                f"冻结生产清单找不到源提示词 index：{source_index}"
            )
        category_id = str(entry.get("category_id") or "").strip()
        structure_version = str(entry.get("structure_version") or "").strip()
        generation_kind = str(entry.get("generation_kind") or "").strip()
        service_role = _service_role(entry)
        panel_index = _panel_index(entry)
        generation_id = str(entry.get("generation_target_id") or "").strip()
        delivery_id = str(entry.get("delivery_target_id") or "").strip()
        if category_id not in SUPPORTED_CATEGORY_IDS:
            raise CategoryPromptError("冻结生产清单 category_id 无效")
        if "generation_profile" in entry:
            profile = category_generation_profile.validate_profile(entry["generation_profile"], category_id)
            if any(entry.get(key) != value for key, value in {
                "model": profile["model"], "quality": profile["quality"],
                "size": profile["api_size"], "raw_api_size": profile["working_raw_size"],
            }.items()):
                raise CategoryPromptError("冻结生产清单的4K生成参数与profile不一致")
        elif entry.get("model") == "gpt-image-2-4k":
            raise CategoryPromptError("冻结4K生产清单缺少显式profile")
        if generation_kind == "cover":
            expected_typography = _truck_cover_typography_plan(category_id, group_index)
            if expected_typography is not None and entry.get("cover_typography_plan") != expected_typography:
                raise CategoryPromptError("冻结新货车首图的完整叠字计划不一致")
        if str(entry.get("batch_id") or "") != current_batch.name:
            raise CategoryPromptError("冻结生产清单 batch_id 与批次目录不一致")
        try:
            if int(entry.get("position", -1)) != generation_position:
                raise CategoryPromptError(
                    "冻结生产清单 position 与 generation_position 不一致"
                )
        except (TypeError, ValueError) as error:
            raise CategoryPromptError("冻结生产清单 position 无效") from error
        if generation_id in generation_ids:
            raise CategoryPromptError(
                f"冻结生产清单 generation_target_id 重复：{generation_id}"
            )
        generation_ids.add(generation_id)

        source_positive = str(
            source.get("positive_prompt")
            or source.get("source_positive_prompt")
            or source.get("prompt")
            or ""
        )
        source_negative = str(source.get("negative_prompt") or "")
        try:
            identity_checks = {
                "category_id": (
                    str(source.get("category_id") or source.get("project_id") or ""),
                    category_id,
                ),
                "structure_version": (
                    str(source.get("structure_version") or ""),
                    structure_version,
                ),
                "generation_mode": (
                    str(source.get("generation_mode") or ""),
                    str(entry.get("generation_mode") or ""),
                ),
                "group_index": (int(source.get("group_index", -1)), group_index),
                "generation_position": (
                    int(source.get("generation_position", -1)),
                    generation_position,
                ),
                "delivery_position": (
                    int(source.get("delivery_position", -1)),
                    delivery_position,
                ),
                "generation_kind": (_generation_kind(source), generation_kind),
                "service_role": (_service_role(source), service_role),
                "panel_index": (_panel_index(source), panel_index),
                "height_profile_id": (
                    str(source.get("height_profile_id") or ""),
                    str(entry.get("height_profile_id") or ""),
                ),
                "final_size": (
                    _record_final_size(source),
                    str(entry.get("final_size") or ""),
                ),
                "triptych_layout_id": (
                    str(source.get("triptych_layout_id") or ""),
                    str(entry.get("triptych_layout_id") or ""),
                ),
                "source_positive_prompt": (
                    source_positive,
                    str(entry.get("source_positive_prompt") or ""),
                ),
                "negative_prompt": (
                    source_negative,
                    str(entry.get("negative_prompt") or ""),
                ),
                "raw_api_size": (
                    _size_text(source.get("raw_size")),
                    str(entry.get("raw_api_size") or ""),
                ),
            }
        except (TypeError, ValueError, CategoryPromptError) as error:
            raise CategoryPromptError(
                f"源提示词身份字段无效：{generation_id or source_index}"
            ) from error
        for field, (source_value, frozen_value) in identity_checks.items():
            if source_value != frozen_value:
                raise CategoryPromptError(
                    f"冻结生产清单与源提示词身份不一致：{generation_id or source_index} / {field}"
                )
        if str(entry.get("role") or "") != generation_kind:
            raise CategoryPromptError("冻结生产清单 role 与 generation_kind 不一致")
        if str(entry.get("target_id") or "") != generation_id:
            raise CategoryPromptError(
                "冻结生产清单 target_id 与 generation_target_id 不一致"
            )
        if str(source.get("generation_id") or "") != generation_id:
            raise CategoryPromptError(
                "冻结生产清单 generation_target_id 与源 generation_id 不一致"
            )

        version_tag = (
            "v3"
            if structure_version.startswith(("road_rescue_v3", "truck_rescue_v3"))
            else "v1"
            if structure_version.startswith(("pet_transport_v1", "ktv_v1"))
            else "v2"
        )
        expected_generation_id = (
            f"{category_id}:{version_tag}:g{group_index:04d}:u{generation_position:02d}"
        )
        expected_delivery_id = (
            f"{category_id}:{version_tag}:g{group_index:04d}:d{delivery_position:02d}"
        )
        if generation_id != expected_generation_id or delivery_id != expected_delivery_id:
            raise CategoryPromptError(
                "冻结生产清单 generation/delivery ID 不符合结构规则"
            )

        frozen_prompt = str(entry.get("effective_prompt") or "")
        frozen_prompt_sha256 = str(
            entry.get("effective_prompt_sha256") or ""
        ).lower()
        if (
            not frozen_prompt
            or hashlib.sha256(frozen_prompt.encode("utf-8")).hexdigest()
            != frozen_prompt_sha256
        ):
            raise CategoryPromptError(f"冻结 original prompt 哈希无效：{generation_id}")
        service_items = entry.get("service_items")
        confirmed_phone = str(entry.get("confirmed_phone") or "")
        if (
            not isinstance(service_items, list)
            or not service_items
            or not all(isinstance(item, str) and item.strip() for item in service_items)
        ):
            raise CategoryPromptError(f"冻结生产清单 service_items 无效：{generation_id}")
        if not is_canonical_contact_number(confirmed_phone):
            raise CategoryPromptError(f"冻结生产清单 confirmed_phone 无效：{generation_id}")

        raw_target = _resolve_frozen_manifest_artifact(
            entry.get("raw_target"),
            base=current_batch,
            allowed_root=current_batch / "raw",
            required_prefix=("raw",),
            field="raw_target",
        )
        legacy_target = _resolve_frozen_manifest_artifact(
            entry.get("legacy_target"),
            base=current_batch,
            allowed_root=current_batch / "images",
            required_prefix=("images",),
            field="legacy_target",
        )
        target = _resolve_frozen_manifest_artifact(
            entry.get("target"),
            base=ROOT,
            allowed_root=ROOT / "output" / category_id,
            required_prefix=("output", category_id),
            field="target",
        )
        source_raw = Path(str(source.get("raw_target") or ""))
        if not source_raw.is_absolute():
            source_raw = ROOT / source_raw
        if source_raw.resolve() != raw_target:
            raise CategoryPromptError(
                "冻结生产清单 raw_target 与源提示词不一致"
            )
        expected_filename = output_filename(delivery_position, generation_kind)
        expected_legacy = (
            current_batch
            / "images"
            / f"group_{group_index:04d}"
            / expected_filename
        ).resolve()
        expected_target = (
            ROOT
            / "output"
            / category_id
            / f"group_{group_index:04d}"
            / expected_filename
        ).resolve()
        if legacy_target != expected_legacy or target != expected_target:
            raise CategoryPromptError(
                "冻结生产清单交付路径与结构规则不一致"
            )
        source_delivery = str(source.get("delivery_target") or "").strip()
        if source_delivery:
            source_delivery_path = Path(source_delivery)
            if not source_delivery_path.is_absolute():
                source_delivery_path = ROOT / source_delivery_path
            if source_delivery_path.resolve() != target:
                raise CategoryPromptError(
                    "冻结生产清单 target 与源 delivery_target 不一致"
                )

        scene = source.get("scene")
        if scene is not None and not isinstance(scene, dict):
            raise CategoryPromptError(f"源提示词 scene 必须是对象：{generation_id}")
        if category_id == "truck_rescue" and generation_kind != "cover":
            if not isinstance(scene, dict):
                raise CategoryPromptError(
                    f"货车详情源提示词缺少 scene：{generation_id}"
                )
            for field in ("vehicle", "location", "action", "tools"):
                value = str(scene.get(field) or "").strip()
                if not value or value not in source_positive:
                    raise CategoryPromptError(
                        "货车详情 scene 未绑定到冻结 source_positive_prompt："
                        f"{generation_id} / {field}"
                    )

        delivery_binding = (
            str(target),
            str(legacy_target),
            str(entry.get("final_size") or ""),
            str(entry.get("triptych_layout_id") or ""),
        )
        previous_binding = delivery_bindings.setdefault(delivery_id, delivery_binding)
        if previous_binding != delivery_binding:
            raise CategoryPromptError(
                f"冻结生产清单 delivery_target_id 绑定冲突：{delivery_id}"
            )

        runtime = dict(source)
        runtime.update(
            {
                "source_index": source_index,
                "category_id": category_id,
                "batch_id": current_batch.name,
                "role": generation_kind,
                "generation_kind": generation_kind,
                "service_role": service_role,
                "panel_index": panel_index,
                "position": generation_position,
                "generation_position": generation_position,
                "delivery_position": delivery_position,
                "generation_target_id": generation_id,
                "delivery_target_id": delivery_id,
                "target_id": generation_id,
                "raw_target": str(raw_target),
                "legacy_target": str(legacy_target),
                "target": str(target),
                "service_items": list(service_items),
                "confirmed_phone": confirmed_phone,
                "frozen_effective_prompt": frozen_prompt,
                "frozen_effective_prompt_sha256": frozen_prompt_sha256,
                "frozen_manifest_sha256": actual_manifest_sha256,
                "frozen_manifest_entry_sha256": _json_sha256(entry),
                "prompt_source": "frozen_production_manifest",
                "scene": dict(scene) if isinstance(scene, dict) else None,
            }
        )
        runtime.pop("effective_prompt", None)
        if "generation_profile" in entry:
            runtime["generation_profile"] = dict(entry["generation_profile"])
        if "cover_typography_plan" in entry:
            runtime["cover_typography_plan"] = dict(entry["cover_typography_plan"])
        result.append(runtime)
    return result


def validate_cover_variation(entries: list[dict[str, Any]]) -> None:
    covers = sorted(
        [entry for entry in entries if entry.get("role") == "cover"],
        key=lambda entry: int(entry["group_index"]),
    )
    if len(covers) < 2:
        return
    category_ids = {str(entry.get("category_id") or DEFAULT_CATEGORY_ID) for entry in covers}
    if category_ids in ({"road_rescue"}, {"pet_transport"}, {"truck_rescue"}, {"ktv"}):
        signatures = [str(entry.get("cover_variant_signature") or "") for entry in covers]
        if len(set(signatures)) != len(signatures):
            raise CategoryPromptError(f"{next(iter(category_ids))} cover_variant_signature must be unique in the selected range")
        return
    profile = load_category_config("pipe_unclogging").get("cover_visual_profile", {})
    rules = profile.get("anti_homogenization", {}) if isinstance(profile, dict) else {}
    adjacent_min = int(rules.get("adjacent_major_dimensions_min", 3))
    for previous, current in zip(covers, covers[1:]):
        previous_variant = previous.get("cover_variant", {})
        current_variant = current.get("cover_variant", {})
        difference_count = sum(
            previous_variant.get(axis) != current_variant.get(axis)
            for axis in COVER_VARIATION_STEPS
        )
        if difference_count < adjacent_min:
            raise CategoryPromptError(
                f"第 {previous['group_index']} 与第 {current['group_index']} 组首图只有 {difference_count} 个主要维度不同"
            )

    window_size = int(rules.get("window_size", 10))
    camera_distance_min = int(rules.get("camera_distance_combinations_min", 6))
    if len(covers) < window_size:
        return
    for start in range(0, len(covers) - window_size + 1):
        window = covers[start:start + window_size]
        signatures = [str(entry.get("cover_variant_signature", "")) for entry in window]
        if len(set(signatures)) != len(signatures):
            raise CategoryPromptError("十组首图中出现重复的完整视觉组合签名")
        camera_distance = {
            (entry["cover_variant"]["camera"], entry["cover_variant"]["distance"])
            for entry in window
        }
        if len(camera_distance) < camera_distance_min:
            raise CategoryPromptError(
                f"十组首图只有 {len(camera_distance)} 种机位与距离组合，低于要求的 {camera_distance_min} 种"
            )


def _json_sha256(value: Any) -> str:
    material = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with _io_path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _records_for_scope(records: list[dict[str, Any]], scope: str) -> list[dict[str, Any]]:
    normalized = str(scope).strip().lower()
    if normalized not in SCOPES:
        raise CategoryPromptError(f"不支持的生产范围：{scope}；必须是 all、covers 或 details")
    if normalized == "covers":
        return [record for record in records if record.get("role") == "cover"]
    if normalized == "details":
        return [record for record in records if record.get("role") != "cover"]
    return list(records)


def _delivery_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    order: list[str] = []
    for record in records:
        delivery_id = str(record["delivery_target_id"])
        if delivery_id not in grouped:
            order.append(delivery_id)
            grouped[delivery_id] = []
        grouped[delivery_id].append(record)
    deliveries: list[dict[str, Any]] = []
    for delivery_id in order:
        units = sorted(grouped[delivery_id], key=lambda item: int(item["generation_position"]))
        first = units[0]
        kinds = {str(item["generation_kind"]) for item in units}
        if kinds == {"triptych_panel"}:
            if len(units) != 3 or [int(item["panel_index"]) for item in units] != [1, 2, 3]:
                raise CategoryPromptError(f"三拼成品 {delivery_id} 必须绑定 3 个有序面板")
            delivery_kind = "triptych"
        elif len(units) == 1 and len(kinds) == 1:
            delivery_kind = next(iter(kinds))
        else:
            raise CategoryPromptError(f"成品 {delivery_id} 的生成单元绑定无效")
        final_sizes = {str(item["final_size"]) for item in units}
        if len(final_sizes) != 1:
            raise CategoryPromptError(f"成品 {delivery_id} 的生成记录 final_size 不一致")
        deliveries.append({
            "delivery_target_id": delivery_id,
            "category_id": str(first.get("category_id") or DEFAULT_CATEGORY_ID),
            "structure_version": str(first.get("structure_version") or GROUP_STRUCTURE_VERSION),
            "generation_mode": str(first.get("generation_mode") or GENERATION_MODE),
            "group_index": int(first["group_index"]),
            "delivery_position": int(first["delivery_position"]),
            "delivery_kind": delivery_kind,
            "target": str(first["target"]),
            "legacy_target": str(first["legacy_target"]),
            "final_size": next(iter(final_sizes)),
            "height_profile_id": first.get("height_profile_id"),
            "triptych_layout_id": first.get("triptych_layout_id") if delivery_kind == "triptych" else None,
            "generation_target_ids": [str(item["generation_target_id"]) for item in units],
            "records": units,
        })
    return deliveries


def _triptych_recipe(delivery: dict[str, Any]) -> dict[str, Any]:
    if delivery.get("delivery_kind") != "triptych":
        raise ValueError("triptych recipe requires a triptych delivery")
    layout_id = str(delivery.get("triptych_layout_id") or "")
    if layout_id not in TRIPTYCH_LAYOUTS:
        raise CategoryPromptError(f"不支持的三拼布局：{layout_id}")
    category_id = str(delivery.get("category_id") or DEFAULT_CATEGORY_ID)
    category = load_category_config(category_id)
    structure = category.get("image_group_structure")
    if not isinstance(structure, dict):
        raise CategoryPromptError("管道疏通类目缺少 image_group_structure")
    layout_config = _layout_config_map(structure, category_id)[layout_id]
    gutter_px = int(structure.get("triptych_gutter_px", 8))
    if gutter_px < 0 or gutter_px > 64:
        raise CategoryPromptError("triptych_gutter_px 必须在 0 到 64 之间")
    records = list(delivery["records"])
    return {
        "recipe_version": 1,
        "mode": GENERATION_MODE,
        "layout_id": layout_id,
        "layout_panels": layout_config["panels"],
        "final_size": str(delivery["final_size"]),
        "content_height_ratio": 0.82,
        "gutter_px": gutter_px,
        "panel_order": [str(record["generation_target_id"]) for record in records],
        "panel_indices": [int(record["panel_index"]) for record in records],
        "panel_service_roles": [str(record["service_role"]) for record in records],
        "crop_mode": "center_fill_per_cell",
        "overlay": "triptych_labels_phone_footer_v1",
    }


def _group_recipes(deliveries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[int, list[dict[str, Any]]] = {}
    for delivery in deliveries:
        grouped.setdefault(int(delivery["group_index"]), []).append(delivery)
    result: list[dict[str, Any]] = []
    for group_index in sorted(grouped):
        group_deliveries = sorted(grouped[group_index], key=lambda item: int(item["delivery_position"]))
        triptych = next(
            (item for item in group_deliveries if item["delivery_kind"] == "triptych"),
            None,
        )
        height_profile_ids = {
            str(item.get("height_profile_id") or "") for item in group_deliveries
        }
        final_sizes = sorted({str(item["final_size"]) for item in group_deliveries})
        if len(height_profile_ids) != 1 or len(final_sizes) != 1:
            raise CategoryPromptError(f"第 {group_index} 组所选成品的高度档位不一致")
        structure_versions = {str(item.get("structure_version") or GROUP_STRUCTURE_VERSION) for item in group_deliveries}
        generation_modes = {str(item.get("generation_mode") or GENERATION_MODE) for item in group_deliveries}
        if len(structure_versions) != 1 or len(generation_modes) != 1:
            raise CategoryPromptError(f"group {group_index} has mixed structure versions")
        result.append({
            "group_index": group_index,
            "structure_version": next(iter(structure_versions)),
            "generation_mode": next(iter(generation_modes)),
            "height_profile_id": next(iter(height_profile_ids)),
            "final_sizes": final_sizes,
            "triptych_layout_id": (
                str(triptych.get("triptych_layout_id")) if triptych is not None else None
            ),
            "height_profiles": [
                {
                    "delivery_target_id": item["delivery_target_id"],
                    "height_profile_id": item.get("height_profile_id"),
                    "final_size": item["final_size"],
                }
                for item in group_deliveries
            ],
            "triptych_recipe": _triptych_recipe(triptych) if triptych is not None else None,
        })
    return result


def plan(
    category_id: str,
    batch_dir_value: str | Path,
    group_start: int,
    group_count: int,
    phone: str,
    config: dict[str, Any] | None = None,
    scope: str = "all",
    output_root: str | Path | None = None,
    generation_target_id: str | None = None,
) -> dict[str, Any]:
    if category_id not in SUPPORTED_CATEGORY_IDS:
        raise CategoryPromptError(f"unsupported category: {category_id}")
    try:
        phone = normalize_contact_number(phone)
    except ValueError as error:
        raise CategoryPromptError(
            "联系电话必须是有效的中国大陆手机号码或400服务号码"
        ) from error
    batch_dir = safe_batch_dir(category_id, batch_dir_value)
    current_config = config or image_generate.apply_provider_config(image_generate.load_json(ROOT / "config.json"))
    generation_profile = category_generation_profile.config_profile(current_config, category_id)
    expected_size = parse_size(str(generation_profile["working_raw_size"] if generation_profile else current_config["api_size"]))
    if expected_size != RAW_API_SIZE:
        raise CategoryPromptError(
            f"管道疏通 v2 原图 API 尺寸固定为 {RAW_API_SIZE[0]}x{RAW_API_SIZE[1]}"
        )
    normalized_scope = str(scope).strip().lower()
    _validate_tuning_sample_scope(
        category_id,
        group_start,
        group_count,
        normalized_scope,
    )
    requested_output_root = output_root if output_root is not None else ROOT / "output" / category_id
    formal_root = safe_output_root(category_id, requested_output_root)
    all_records = record_targets(
        batch_dir,
        selected_records(batch_dir, group_start, group_count, category_id),
        formal_root,
        category_id,
    )
    records = _records_for_scope(all_records, normalized_scope)
    normalized_generation_target_id = str(generation_target_id or "").strip() or None
    if normalized_generation_target_id is not None:
        if normalized_scope != "details":
            raise CategoryPromptError("单图探针只允许用于 details 范围")
        matching_records = [
            record
            for record in records
            if str(record.get("generation_target_id")) == normalized_generation_target_id
        ]
        if len(matching_records) != 1:
            raise CategoryPromptError(
                f"单图探针目标不在当前组范围内：{normalized_generation_target_id}"
            )
        if str(matching_records[0].get("generation_kind")) != "detail":
            raise CategoryPromptError("单图探针只能选择独立详情图，不能选择首图或三拼组件")
        records = matching_records
    category = load_category_config(category_id)
    service_items = list(category["service_buttons"])
    expected_service_count = 10 if category_id in {"road_rescue", "truck_rescue", "home_appliance_repair"} else 8
    if len(service_items) != expected_service_count:
        raise CategoryPromptError(f"{category_id} service_buttons must contain {expected_service_count} items")
    entries = build_manifest_entries(batch_dir, records, phone, service_items, current_config)
    validate_cover_variation(entries)
    cover_typography_plans = _bound_cover_typography_plans(entries)
    deliveries = _delivery_records(records)
    existing_deliveries: list[dict[str, Any]] = []
    recoverable_deliveries: list[dict[str, Any]] = []
    pending_deliveries: list[dict[str, Any]] = []
    existing: list[dict[str, Any]] = []
    recoverable: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    for delivery in deliveries:
        target = Path(delivery["target"])
        final_size = parse_size(str(delivery["final_size"]))
        review_status = target_review_status(target)
        units = list(delivery["records"])
        if reusable_target(target, final_size):
            existing_deliveries.append(delivery)
            existing.extend(units)
            continue
        pending_deliveries.append(delivery)
        raw_validity = [
            valid_png(Path(record["raw_target"]), expected_size)
            for record in units
        ]
        if review_status not in {"needs_fix", "rejected"} and all(raw_validity):
            recoverable_deliveries.append(delivery)
            recoverable.extend(units)
        else:
            for record, raw_valid in zip(units, raw_validity):
                if review_status not in {"needs_fix", "rejected"} and raw_valid:
                    recoverable.append(record)
                else:
                    pending.append(record)
    generation_target_ids = [str(record["generation_target_id"]) for record in records]
    pending_generation_target_ids = [str(record["generation_target_id"]) for record in pending]
    delivery_target_ids = [str(delivery["delivery_target_id"]) for delivery in deliveries]
    pending_delivery_target_ids = [
        str(delivery["delivery_target_id"]) for delivery in pending_deliveries
    ]
    generation_targets_sha256 = _json_sha256([
        {
            "generation_target_id": record["generation_target_id"],
            "delivery_target_id": record["delivery_target_id"],
            "group_index": int(record["group_index"]),
            "generation_position": int(record["generation_position"]),
            "delivery_position": int(record["delivery_position"]),
            "generation_kind": str(record["generation_kind"]),
            "service_role": record.get("service_role"),
            "panel_index": record.get("panel_index"),
            "height_profile_id": record.get("height_profile_id"),
            "final_size": str(record["final_size"]),
            "triptych_layout_id": record.get("triptych_layout_id"),
            "target": _artifact_reference(record["target"], batch_dir),
            "raw_target": _artifact_reference(record["raw_target"], batch_dir),
        }
        for record in records
    ])
    delivery_targets_sha256 = _json_sha256([
        {
            "delivery_target_id": delivery["delivery_target_id"],
            "group_index": int(delivery["group_index"]),
            "delivery_position": int(delivery["delivery_position"]),
            "delivery_kind": str(delivery["delivery_kind"]),
            "height_profile_id": delivery.get("height_profile_id"),
            "final_size": str(delivery["final_size"]),
            "triptych_layout_id": delivery.get("triptych_layout_id"),
            "target": _artifact_reference(delivery["target"], batch_dir),
            "generation_target_ids": list(delivery["generation_target_ids"]),
        }
        for delivery in deliveries
    ])
    pending_generation_targets_sha256 = _json_sha256(pending_generation_target_ids)
    pending_delivery_targets_sha256 = _json_sha256(pending_delivery_target_ids)
    group_recipes = _group_recipes(deliveries)
    group_recipes_sha256 = _json_sha256(group_recipes)
    selected_manifest_sha256 = manifest_sha256(entries)
    structure_versions = {str(record.get("structure_version") or GROUP_STRUCTURE_VERSION) for record in records}
    generation_modes = {str(record.get("generation_mode") or GENERATION_MODE) for record in records}
    if len(structure_versions) != 1 or len(generation_modes) != 1:
        raise CategoryPromptError("selected records must share one structure_version and generation_mode")
    current_structure_version = next(iter(structure_versions))
    current_generation_mode = next(iter(generation_modes))
    generation_unit_count = len(records) // group_count if group_count else 0
    delivery_unit_count = len(deliveries) // group_count if group_count else 0
    plan_sha256 = _json_sha256({
        "production_schema_version": PRODUCTION_SCHEMA_VERSION,
        "structure_version": current_structure_version,
        "generation_mode": current_generation_mode,
        "category_id": category_id,
        "batch_id": batch_dir.name,
        "batch_dir": str(batch_dir),
        "group_start": group_start,
        "group_count": group_count,
        "scope": normalized_scope,
        "generation_target_id": normalized_generation_target_id,
        "output_root": str(formal_root) if formal_root else None,
        "contact_sha256": hashlib.sha256(phone.encode("utf-8")).hexdigest(),
        "provider": current_config.get("provider"),
        "base_url": current_config.get("base_url", ""),
        "model": current_config.get("model"),
        "quality": current_config.get("quality"),
        "size": current_config.get("api_size"),
        **({"generation_profile": generation_profile} if generation_profile else {}),
        **({"cover_styles_by_group": cover_typography_plans} if cover_typography_plans else {}),
        "manifest_sha256": selected_manifest_sha256,
        "generation_targets_sha256": generation_targets_sha256,
        "delivery_targets_sha256": delivery_targets_sha256,
        "pending_generation_target_ids": pending_generation_target_ids,
        "pending_generation_targets_sha256": pending_generation_targets_sha256,
        "pending_delivery_target_ids": pending_delivery_target_ids,
        "pending_delivery_targets_sha256": pending_delivery_targets_sha256,
        "group_recipes_sha256": group_recipes_sha256,
    })
    return {
        "production_schema_version": PRODUCTION_SCHEMA_VERSION,
        "structure_version": current_structure_version,
        "generation_mode": current_generation_mode,
        "category_id": category_id,
        "batch_dir": str(batch_dir),
        "batch_id": batch_dir.name,
        "group_start": group_start,
        "group_count": group_count,
        "scope": normalized_scope,
        "generation_target_id": normalized_generation_target_id,
        "output_root": str(formal_root) if formal_root else None,
        "generation_unit_count": generation_unit_count,
        "delivery_unit_count": delivery_unit_count,
        "group_total_images": group_count * delivery_unit_count,
        "total_images": len(deliveries),
        "delivery_count": len(deliveries),
        "total_generation_targets": len(records),
        "total_delivery_targets": len(deliveries),
        "existing_images": len(existing_deliveries),
        "existing_delivery_count": len(existing_deliveries),
        "recoverable_images": len(recoverable_deliveries),
        "recoverable_delivery_count": len(recoverable_deliveries),
        "pending_delivery_count": len(pending_deliveries),
        "pending_api_requests": len(pending),
        "pending_api_images": len(pending),
        "manifest_sha256": selected_manifest_sha256,
        "targets_sha256": generation_targets_sha256,
        "pending_targets_sha256": pending_generation_targets_sha256,
        "generation_targets_sha256": generation_targets_sha256,
        "delivery_targets_sha256": delivery_targets_sha256,
        "pending_generation_targets_sha256": pending_generation_targets_sha256,
        "pending_delivery_targets_sha256": pending_delivery_targets_sha256,
        "group_recipes_sha256": group_recipes_sha256,
        "plan_sha256": plan_sha256,
        "target_ids": generation_target_ids,
        "pending_target_ids": pending_generation_target_ids,
        "generation_target_ids": generation_target_ids,
        "delivery_target_ids": delivery_target_ids,
        "pending_generation_target_ids": pending_generation_target_ids,
        "pending_delivery_target_ids": pending_delivery_target_ids,
        "records": records,
        "delivery_records": deliveries,
        "existing_records": existing,
        "recoverable_records": recoverable,
        "pending_records": pending,
        "existing_delivery_records": existing_deliveries,
        "recoverable_delivery_records": recoverable_deliveries,
        "pending_delivery_records": pending_deliveries,
        "group_recipes": group_recipes,
        "manifest_entries": entries,
        "service_items": service_items,
        "expected_size": list(expected_size),
        **({"generation_profile": generation_profile} if generation_profile else {}),
        **({"cover_styles_by_group": cover_typography_plans} if cover_typography_plans else {}),
    }


def _write_text_artifact(path: Path, content: str, *, immutable: bool) -> None:
    if immutable and path.exists():
        if path.read_text(encoding="utf-8-sig") != content:
            raise RuntimeError(f"不可覆盖的生产证据已存在且内容不同：{path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def write_production_files(
    run_plan: dict[str, Any],
    phone: str,
    license_id: str | None = None,
) -> tuple[Path, Path]:
    batch_dir = Path(run_plan["batch_dir"])
    category_id = str(run_plan.get("category_id") or DEFAULT_CATEGORY_ID)
    model_generated_signboard = category_id in MODEL_GENERATED_SIGNBOARD_CATEGORIES
    signboard_title = CATEGORY_SIGNBOARD_TITLES.get(category_id, str(run_plan.get("category_name") or category_id))
    target_manifest = manifest_path(
        batch_dir, run_plan["group_start"], run_plan["group_count"], license_id
    )
    manifest_content = "".join(
        json.dumps(entry, ensure_ascii=False) + "\n"
        for entry in run_plan["manifest_entries"]
    )
    _write_text_artifact(target_manifest, manifest_content, immutable=license_id is not None)
    target_overlay = overlay_plan_path(
        batch_dir, run_plan["group_start"], run_plan["group_count"], license_id
    )
    overlay_payload = {
        "schema_version": OVERLAY_SCHEMA_VERSION,
        "production_schema_version": PRODUCTION_SCHEMA_VERSION,
        "structure_version": str(run_plan.get("structure_version") or GROUP_STRUCTURE_VERSION),
        "generation_mode": str(run_plan.get("generation_mode") or GENERATION_MODE),
        "category_id": category_id,
        "license_id": license_id,
        "scope": run_plan.get("scope", "all"),
        "plan_sha256": run_plan.get("plan_sha256"),
        "generation_target_ids": run_plan.get("generation_target_ids", []),
        "delivery_target_ids": run_plan.get("delivery_target_ids", []),
        "pending_generation_target_ids": run_plan.get("pending_generation_target_ids", []),
        "pending_delivery_target_ids": run_plan.get("pending_delivery_target_ids", []),
        "generation_targets_sha256": run_plan.get("generation_targets_sha256"),
        "delivery_targets_sha256": run_plan.get("delivery_targets_sha256"),
        "group_recipes_sha256": run_plan.get("group_recipes_sha256"),
        "group_recipes": run_plan.get("group_recipes", []),
        "output_root": run_plan.get("output_root"),
        "phone": phone,
        "center_phone_text": f"电话：{phone}",
        "signboard_title": None if model_generated_signboard else signboard_title,
        "signboard_phone_text": f"联系电话：{phone}",
        "signboard_overlay_enabled": not model_generated_signboard,
        "signboard_overlay_scope": (
            "model_generated_physical_signboard_phone"
            if model_generated_signboard
            else "title_services_and_phone"
        ),
        "signboard_service_items": (
            [] if model_generated_signboard else _cover_signboard_service_items(category_id)
        ),
        "service_items": run_plan["service_items"],
        "cover_style_version": cover_style_version(category_id),
        "cover_typography_version": COVER_TYPOGRAPHY_VERSION,
        "cover_typographies": [item[0] for item in COVER_TYPOGRAPHIES],
        "cover_signboard_region": (
            None if model_generated_signboard else [0.055, 0.055, 0.945, 0.305]
        ),
        "cover_signboard_region_mode": (
            "source_generated_physical_signboard_phone"
            if model_generated_signboard
            else "detect_physical_signboard_then_perspective_warp_text"
        ),
        "cover_center_phone_region": [0.0, 0.43, 1.0, 0.535],
        "cover_bottom_service_region": [0.045, 0.70, 0.955, 0.965],
        "detail_center_phone_region": [0.0, 0.49, 1.0, 0.585],
        "detail_bottom_service_region": [0.025, 0.835, 0.975, 0.975],
        "triptych_content_region": [0.0, 0.0, 1.0, 0.82],
        "triptych_footer_region": [0.0, 0.82, 1.0, 1.0],
        "triptych_layouts": sorted(TRIPTYCH_LAYOUTS),
        "cover_overlay_style": (
            "source-generated-signboard-phone_no-local-signboard-overlay_rotating-high-contrast-typography"
            if model_generated_signboard
            else "direct-text-on-physical-signboard_rotating-high-contrast-typography"
        ),
        "approval_status": "needs_user_review",
    }
    if category_id == "ktv":
        overlay_payload.update(
            signboard_title=None, signboard_phone_text=None,
            signboard_overlay_enabled=False, signboard_overlay_scope="not_applicable_interior",
            signboard_service_items=[], cover_signboard_region=None,
            cover_signboard_region_mode="not_applicable_interior",
            cover_bottom_service_region=[0.045, 0.80, 0.955, 0.965],
            triptych_layouts=["stacked_equal"],
            cover_overlay_style="interior_phone_and_eight_services",
        )
    group_start = int(run_plan["group_start"])
    group_end = group_start + int(run_plan["group_count"])
    truck_styles = _bound_cover_typography_plans(run_plan["manifest_entries"])
    if truck_styles:
        if truck_styles != run_plan.get("cover_styles_by_group"):
            raise CategoryPromptError("首图叠字计划与manifest绑定不一致")
        overlay_payload["cover_styles_by_group"] = truck_styles
        overlay_payload["cover_style_version"] = 3 if len(truck_styles) == int(run_plan["group_count"]) else None
        overlay_payload["cover_typography_version"] = 2
        overlay_payload["cover_typographies"] = sorted({item["family"] for item in truck_styles.values()})
        overlay_payload["cover_center_phone_region"] = None
        overlay_payload["cover_bottom_service_region"] = None
        overlay_payload["cover_overlay_style"] = "truck-cover-v3-full-per-group-plan"
    if category_id in {"road_rescue", "home_appliance_repair"} and group_end > ROAD_RESCUE_COVER_V3_FIRST_GROUP:
        group_styles = {
            str(index): {
                "version": cover_style_version(category_id, index),
                "center_phone_region": cover_center_phone_region(category_id, index),
            }
            for index in range(group_start, group_end)
        }
        versions = {item["version"] for item in group_styles.values()}
        for index, style in group_styles.items():
            if int(index) >= ROAD_RESCUE_COVER_V3_FIRST_GROUP:
                style["bottom_service_region"] = road_rescue_bottom_service_region(int(index))
                style["bottom_service_style_id"] = road_rescue_bottom_service_style(int(index))["style_id"]
        overlay_payload["cover_styles_by_group"] = group_styles
        overlay_payload["cover_style_version"] = next(iter(versions)) if len(versions) == 1 else None
        overlay_payload["cover_center_phone_region"] = (
            next(iter(group_styles.values()))["center_phone_region"] if len(versions) == 1 else None
        )
        bottom_regions = {tuple(item.get("bottom_service_region", [])) for item in group_styles.values()}
        overlay_payload["cover_bottom_service_region"] = (
            list(next(iter(bottom_regions))) if len(bottom_regions) == 1 else None
        )
    overlay_content = json.dumps(overlay_payload, ensure_ascii=False, indent=2) + "\n"
    _write_text_artifact(target_overlay, overlay_content, immutable=license_id is not None)
    return target_manifest, target_overlay


def pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        # ``os.kill(pid, 0)`` is not a harmless existence probe on Windows:
        # CPython implements non-console signals with TerminateProcess, so a
        # read-only status/plan command can terminate the worker it inspects.
        # Query the process handle instead and fail closed when Windows cannot
        # determine the state (for example, because access is denied).
        import ctypes

        process_query_limited_information = 0x1000
        still_active = 259
        error_invalid_parameter = 87
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.GetExitCodeProcess.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_ulong),
        ]
        kernel32.GetExitCodeProcess.restype = ctypes.c_int
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_int

        handle = kernel32.OpenProcess(
            process_query_limited_information,
            False,
            pid,
        )
        if not handle:
            return ctypes.get_last_error() != error_invalid_parameter
        try:
            exit_code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return True
            return exit_code.value == still_active
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def acquire_lock(batch_dir: Path, job_id: str) -> Path:
    path = production_dir(batch_dir) / "generation.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            stale = load_json(path)
            stale_pid = int(stale.get("pid", 0))
        except Exception as error:
            raise RuntimeError(f"生产锁文件无法识别，请人工检查：{path}") from error
        if pid_is_running(stale_pid):
            raise RuntimeError(f"该批次已有生产任务运行，PID={stale_pid}")
        path.unlink()
    try:
        handle = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as error:
        raise RuntimeError(f"该批次已有生产任务锁：{path}") from error
    try:
        payload = json.dumps({"pid": os.getpid(), "job_id": job_id, "created_at": now_iso()}, ensure_ascii=False)
        os.write(handle, payload.encode("utf-8"))
    finally:
        os.close(handle)
    return path


def validate_worker_paths(
    batch_dir: Path,
    group_start: int,
    group_count: int,
    license_value: str | Path,
    job_value: str | Path,
    license_id: str | None = None,
) -> tuple[Path, Path]:
    actual_license = Path(license_value).resolve()
    expected_license = license_path(
        "pipe_unclogging", batch_dir, group_start, group_count, license_id
    ).resolve()
    if actual_license != expected_license:
        raise RuntimeError(f"许可证路径必须是批次内固定路径：{expected_license}")
    actual_job = Path(job_value).resolve()
    expected_jobs = jobs_dir(batch_dir).resolve()
    if actual_job.parent != expected_jobs or actual_job.suffix.lower() != ".json":
        raise RuntimeError(f"任务文件必须位于批次内：{expected_jobs}")
    if not actual_license.is_file() or not actual_job.is_file():
        raise RuntimeError("批次内许可证或任务文件不存在")
    if license_id is not None and load_json(actual_license).get("license_id") != license_id:
        raise RuntimeError("许可证文件名与许可证内容不一致")
    return actual_license, actual_job


def update_job(path: Path | None, lock: threading.Lock | None = None, **changes: Any) -> None:
    if path is None:
        return
    if lock:
        with lock:
            update_job(path, None, **changes)
        return
    current = load_json(path) if path.is_file() else {}
    current.update(changes)
    current["updated_at"] = now_iso()
    atomic_json(path, current)


def _request_stage_result(results: list[Any], request_count: int) -> dict[str, Any]:
    """Summarize a fully drained stage and its independent stop conditions."""

    failed_count = sum(not bool(result) for result in results)
    balance_exhausted_count = sum(
        isinstance(result, RequestBatchResult)
        and not result.success
        and result.final_error_kind == "balance_exhausted"
        for result in results
    )
    double_policy_failures = sum(
        isinstance(result, RequestBatchResult)
        and not result.success
        and result.final_error_kind == "content_policy"
        and result.content_policy_rejection_count >= 2
        for result in results
    )
    double_policy_failure_rate = (
        double_policy_failures / request_count if request_count else 0.0
    )
    circuit_breaker_triggered = (
        double_policy_failures >= CONTENT_POLICY_CIRCUIT_BREAKER_MIN_FAILURES
        and double_policy_failure_rate
        >= CONTENT_POLICY_CIRCUIT_BREAKER_FAILURE_RATE
    )
    return {
        "failed_count": failed_count,
        "image_download_failed": any(
            isinstance(result, RequestBatchResult) and result.final_error_kind == "image_download_failed"
            for result in results
        ),
        "dispatched_target_count": request_count,
        "drained_result_count": len(results),
        "in_flight_drained": len(results) == request_count,
        "balance_exhausted_count": balance_exhausted_count,
        "balance_circuit_breaker_triggered": balance_exhausted_count > 0,
        "content_policy_double_failure_count": double_policy_failures,
        "content_policy_double_failure_rate": double_policy_failure_rate,
        "circuit_breaker_triggered": circuit_breaker_triggered,
    }


def _consecutive_api_error_stage_result(
    results: list[Any], previous_failures: int,
) -> dict[str, Any]:
    """Count drained targets in dispatch order, excluding slot balance failures."""

    consecutive_failures = previous_failures
    peak_failures = previous_failures
    for result in results:
        if bool(result):
            consecutive_failures = 0
        elif not (
            isinstance(result, RequestBatchResult)
            and result.final_error_kind == "balance_exhausted"
        ):
            consecutive_failures += 1
            peak_failures = max(peak_failures, consecutive_failures)
    contract_rejected = any(
        isinstance(result, RequestBatchResult) and result.final_error_kind == "raw_contract_rejected"
        for result in results
    )
    budget_exhausted = any(
        isinstance(result, RequestBatchResult) and result.final_error_kind == "request_budget_exhausted"
        for result in results
    )
    triggered = contract_rejected or budget_exhausted or peak_failures >= CONSECUTIVE_API_ERROR_LIMIT
    return {
        "consecutive_api_failure_count": consecutive_failures,
        "consecutive_api_failure_peak": peak_failures,
        "api_error_circuit_breaker_triggered": triggered,
        "api_error_circuit_breaker_reason": (
            "raw_contract_rejected" if contract_rejected else
            "request_budget_exhausted" if budget_exhausted else
            "consecutive_non_balance_api_failures" if triggered else None
        ),
    }


def run_adaptive_request_batches(
    records: list[dict[str, Any]],
    clients: list[tuple[int, Any]],
    max_workers: int,
    run_one: Any,
    stage_callback: Any | None = None,
    balance_failover: bool = False,
) -> list[dict[str, Any]]:
    """Ramp concurrency and optionally quarantine only balance-exhausted slots."""

    active_clients = list(clients)
    worker_limit = min(int(max_workers), len(active_clients))
    if worker_limit < 1:
        raise RuntimeError("自适应并发至少需要一个可用 API Key")
    history: list[dict[str, Any]] = []
    queue = list(records)
    desired_workers = min(ADAPTIVE_CONCURRENCY_RAMP[0], worker_limit)
    degraded = False
    consecutive_api_failures = 0
    while queue and active_clients:
        worker_limit = min(int(max_workers), len(active_clients))
        stage_workers = min(desired_workers, len(queue), worker_limit)
        stage_records = queue[:stage_workers]
        del queue[:stage_workers]
        stage_clients = active_clients[:stage_workers]
        with ThreadPoolExecutor(max_workers=stage_workers) as executor:
            futures = [
                executor.submit(run_one, slot, client, record)
                for (slot, client), record in zip(stage_clients, stage_records)
            ]
            results = [future.result() for future in futures]
        stage_result = _request_stage_result(results, len(stage_records))
        stage_result.update(
            _consecutive_api_error_stage_result(results, consecutive_api_failures)
        )
        consecutive_api_failures = int(stage_result["consecutive_api_failure_count"])
        quarantined_slots: list[int] = []
        failover_records: list[dict[str, Any]] = []
        if balance_failover:
            for (slot, _client), record, result in zip(
                stage_clients, stage_records, results
            ):
                if (
                    isinstance(result, RequestBatchResult)
                    and not result.success
                    and result.final_error_kind == "balance_exhausted"
                ):
                    quarantined_slots.append(int(slot))
                    record["_balance_failover_count"] = int(
                        record.get("_balance_failover_count", 0)
                    ) + 1
                    failover_records.append(record)
            if quarantined_slots:
                blocked = set(quarantined_slots)
                active_clients = [
                    pair for pair in active_clients if int(pair[0]) not in blocked
                ]
                queue = failover_records + queue
                stage_result["balance_circuit_breaker_triggered"] = not active_clients
        failed_count = int(stage_result["failed_count"])
        stage = {
            "worker_count": stage_workers,
            "request_count": len(stage_records),
            **stage_result,
            "quarantined_api_key_slots": sorted(set(quarantined_slots)),
            "balance_failover_target_count": len(failover_records),
            "remaining_api_key_slot_count": len(active_clients),
            "undispatched_target_count": len(queue),
        }
        history.append(stage)
        if stage_callback is not None:
            stage_callback(dict(stage))
        if (
            stage["balance_circuit_breaker_triggered"]
            or stage["circuit_breaker_triggered"]
            or stage["api_error_circuit_breaker_triggered"]
            or stage["image_download_failed"]
        ):
            break
        non_balance_failures = failed_count - (
            int(stage_result["balance_exhausted_count"])
            if balance_failover
            else 0
        )
        if non_balance_failures:
            degraded = True
            fallback = 5 if stage_workers >= 6 else 2
            desired_workers = min(worker_limit, fallback)
        elif not degraded:
            desired_workers = min(int(max_workers), len(active_clients))
            for candidate in ADAPTIVE_CONCURRENCY_RAMP:
                if candidate > stage_workers:
                    desired_workers = min(
                        int(max_workers), len(active_clients), candidate
                    )
                    break
    return history


def run_fixed_request_batches(
    records: list[dict[str, Any]],
    clients: list[tuple[int, Any]],
    max_workers: int,
    run_one: Any,
    stage_callback: Any | None = None,
    balance_failover: bool = False,
) -> list[dict[str, Any]]:
    """Keep licensed width and optionally fail over balance-exhausted slots."""

    active_clients = list(clients)
    worker_limit = min(int(max_workers), len(active_clients))
    if worker_limit < 1:
        raise RuntimeError("固定并发至少需要一个可用 API Key")
    history: list[dict[str, Any]] = []
    queue = list(records)
    while queue and active_clients:
        worker_limit = min(int(max_workers), len(active_clients))
        stage_records = queue[:worker_limit]
        del queue[:worker_limit]
        stage_workers = len(stage_records)
        stage_clients = active_clients[:stage_workers]
        with ThreadPoolExecutor(max_workers=stage_workers) as executor:
            futures = [
                executor.submit(run_one, slot, client, record)
                for (slot, client), record in zip(stage_clients, stage_records)
            ]
            results = [future.result() for future in futures]
        stage_result = _request_stage_result(results, len(stage_records))
        quarantined_slots: list[int] = []
        failover_records: list[dict[str, Any]] = []
        if balance_failover:
            for (slot, _client), record, result in zip(
                stage_clients, stage_records, results
            ):
                if (
                    isinstance(result, RequestBatchResult)
                    and not result.success
                    and result.final_error_kind == "balance_exhausted"
                ):
                    quarantined_slots.append(int(slot))
                    record["_balance_failover_count"] = int(
                        record.get("_balance_failover_count", 0)
                    ) + 1
                    failover_records.append(record)
            if quarantined_slots:
                blocked = set(quarantined_slots)
                active_clients = [
                    pair for pair in active_clients if int(pair[0]) not in blocked
                ]
                queue = failover_records + queue
                stage_result["balance_circuit_breaker_triggered"] = not active_clients
        stage = {
            "worker_count": stage_workers,
            "request_count": len(stage_records),
            **stage_result,
            "quarantined_api_key_slots": sorted(set(quarantined_slots)),
            "balance_failover_target_count": len(failover_records),
            "remaining_api_key_slot_count": len(active_clients),
        }
        history.append(stage)
        if stage_callback is not None:
            stage_callback(dict(stage))
        if (
            stage["balance_circuit_breaker_triggered"]
            or stage["circuit_breaker_triggered"]
            or stage["image_download_failed"]
        ):
            break
    return history


def validate_license(
    path: Path,
    run_plan: dict[str, Any],
    config: dict[str, Any],
    key_slots: list[int],
    max_workers: int | None = None,
) -> dict[str, Any]:
    payload = load_json(path)
    if payload.get("status") != "active" or payload.get("kind") != "category-image-production" or not payload.get("one_time"):
        raise RuntimeError("管道疏通一次性许可证不是 active 状态")
    generation_profile = category_generation_profile.config_profile(config, run_plan["category_id"])
    if (payload.get("generation_profile") != generation_profile
            or run_plan.get("generation_profile") != generation_profile
            or (generation_profile is None and "generation_profile" in payload)):
        raise RuntimeError("一次性许可证、计划与有效generation-profile不一致")
    expected = {
        "production_schema_version": PRODUCTION_SCHEMA_VERSION,
        "structure_version": run_plan["structure_version"],
        "generation_mode": run_plan["generation_mode"],
        "category_id": run_plan["category_id"],
        "batch_dir": run_plan["batch_dir"],
        "group_start": run_plan["group_start"],
        "group_count": run_plan["group_count"],
        "scope": run_plan.get("scope", "all"),
        "generation_target_id": run_plan.get("generation_target_id"),
        "output_root": run_plan.get("output_root"),
        "manifest_sha256": run_plan["manifest_sha256"],
        "plan_sha256": run_plan["plan_sha256"],
        "generation_targets_sha256": run_plan["generation_targets_sha256"],
        "delivery_targets_sha256": run_plan["delivery_targets_sha256"],
        "pending_generation_targets_sha256": run_plan["pending_generation_targets_sha256"],
        "pending_delivery_targets_sha256": run_plan["pending_delivery_targets_sha256"],
        "group_recipes_sha256": run_plan["group_recipes_sha256"],
        "provider": config["provider"],
        "base_url": config.get("base_url", ""),
        "model": config["model"],
        "quality": config["quality"],
        "size": config["api_size"],
        "api_key_slots": key_slots,
        "sdk_max_retries": 0,
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            raise RuntimeError(f"一次性许可证与当前任务不一致：{key}")
    if config.get("provider") == "relay" and not payload.get("third_party_confirmed"):
        raise RuntimeError("第三方中转信任尚未确认")
    pending_api = int(run_plan["pending_api_requests"])
    pending_delivery = int(run_plan["pending_delivery_count"])
    if payload.get("approved_generation_target_ids") != run_plan["pending_generation_target_ids"]:
        raise RuntimeError("许可证授权生成目标与当前待 API 目标集合不一致")
    if payload.get("approved_delivery_target_ids") != run_plan["pending_delivery_target_ids"]:
        raise RuntimeError("许可证授权成品目标与当前待交付目标集合不一致")
    if int(payload.get("approved_api_request_count", -1)) != pending_api:
        raise RuntimeError("授权 API 请求数必须与当前待 API 请求数完全一致")
    if int(payload.get("approved_delivery_count", -1)) != pending_delivery:
        raise RuntimeError("授权成品数必须与当前待生成成品数完全一致")
    if int(payload.get("approved_image_count", -1)) != pending_delivery:
        raise RuntimeError("授权图片数必须与当前待生成成品数完全一致")
    max_attempts = int(payload.get("max_attempts", 1) or 1)
    retry_policy = str(payload.get("retry_policy") or NO_RETRY_POLICY)
    if max_attempts not in {1, 2}:
        raise RuntimeError("许可证每个目标最多只能尝试 1 或 2 次")
    expected_retry_policy = (
        CLASSIFIED_RETRY_POLICY if max_attempts == 2 else NO_RETRY_POLICY
    )
    if retry_policy != expected_retry_policy:
        raise RuntimeError("许可证重试策略与最大尝试次数不一致")
    expected_request_budget = pending_api * max_attempts
    if int(payload.get("approved_request_budget", -1)) != expected_request_budget:
        raise RuntimeError(
            "授权请求预算必须等于待 API 目标数乘以每目标最大尝试次数"
        )
    licensed_workers = int(payload.get("max_workers", 0) or 0)
    if max_workers is not None and licensed_workers != int(max_workers):
        raise RuntimeError("许可证并发数与当前任务不一致")
    upper_bound = min(len(key_slots), max(1, pending_api))
    if licensed_workers < 1 or licensed_workers > upper_bound:
        raise RuntimeError(f"许可证 max_workers 必须在 1 到 {upper_bound} 之间")
    concurrency_policy = payload.get("concurrency_policy", "legacy_fixed")
    if generation_profile is not None and (
        concurrency_policy != ADAPTIVE_CONCURRENCY_POLICY or licensed_workers > 10
    ):
        raise RuntimeError("新4K profile仅允许adaptive并发且最多10路")
    if concurrency_policy not in {
        "legacy_fixed",
        ADAPTIVE_CONCURRENCY_POLICY,
        FIXED_TEN_CONCURRENCY_POLICY,
    }:
        raise RuntimeError("许可证包含不支持的并发策略")
    if concurrency_policy == FIXED_TEN_CONCURRENCY_POLICY and (
        licensed_workers != 10 or len(key_slots) < 10 or pending_api < 10
    ):
        raise RuntimeError("固定10路许可证必须绑定10个 Key、10路并发和至少10个待请求")
    return payload


def consume_license(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("status") != "active":
        raise RuntimeError("许可证已经被消费或失效")
    payload = dict(payload)
    payload.update({"status": "consumed", "consumed_at": now_iso(), "requests_used": 0})
    atomic_json(path, payload)
    return payload


def openai_clients_by_slot(config: dict[str, Any], slots: list[int]) -> list[tuple[int, Any]]:
    image_generate.load_project_env()
    from openai import OpenAI

    keys = image_generate.configured_api_keys()
    if not keys:
        raise RuntimeError("没有已配置的 API Key")
    if not slots:
        slots = list(range(1, len(keys) + 1))
    if len(slots) != len(set(slots)) or any(slot < 1 or slot > len(keys) for slot in slots):
        raise RuntimeError("API Key 槽位必须唯一，并且位于已配置范围内")
    clients: list[tuple[int, Any]] = []
    for slot in slots:
        kwargs: dict[str, Any] = {
            "api_key": keys[slot - 1],
            # The one-time license budgets actual HTTP attempts, so SDK-level
            # retries must stay disabled as well as application-level retries.
            "max_retries": 0,
        }
        if config.get("base_url"):
            kwargs["base_url"] = config["base_url"]
        clients.append((slot, OpenAI(**kwargs)))
    return clients


def _font(size: int, family: str | None = None) -> Any:
    from PIL import ImageFont

    windows = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    preferred = {"msyh_bold":"msyhbd.ttc","msyh":"msyh.ttc","simhei":"simhei.ttf"}
    candidates = ([windows / preferred[family]] if family in preferred else []) + [windows / "msyhbd.ttc", windows / "msyh.ttc", windows / "simhei.ttf", windows / "arialbd.ttf"]
    for candidate in candidates:
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()


def _fit_font(draw: Any, text: str, max_width: int, start_size: int, min_size: int = 18, stroke: int = 0, max_height: int | None = None, family: str | None = None) -> Any:
    size = start_size
    font = _font(size, family)
    while size > min_size:
        box = draw.textbbox((0, 0), text, font=font, stroke_width=stroke)
        if box[2] - box[0] <= max_width and (max_height is None or box[3] - box[1] <= max_height):
            break
        size -= 2
        font = _font(size, family)
    return font


def _centered_text(
    draw: Any,
    box: tuple[int, int, int, int],
    text: str,
    font: Any,
    fill: Any,
    stroke: int = 0,
    stroke_fill: Any = None,
) -> None:
    bounds = draw.textbbox((0, 0), text, font=font, stroke_width=stroke)
    x = box[0] + (box[2] - box[0] - (bounds[2] - bounds[0])) // 2 - bounds[0]
    y = box[1] + (box[3] - box[1] - (bounds[3] - bounds[1])) // 2 - bounds[1]
    draw.text((x, y), text, font=font, fill=fill, stroke_width=stroke, stroke_fill=stroke_fill)


COVER_OVERLAY_STYLES: list[dict[str, Any]] = [
    {
        "name": "orange_cyan",
        "sign_fill": (205, 91, 18, 218),
        "sign_title": (32, 32, 28, 255),
        "sign_phone": (255, 248, 230, 255),
        "border": (255, 214, 126, 255),
        "phone": (27, 235, 242, 255),
        "services": [(30, 225, 238, 255), (242, 79, 69, 255), (91, 224, 97, 255), (185, 104, 255, 255), (255, 171, 36, 255), (245, 245, 245, 255), (255, 224, 56, 255), (39, 210, 225, 255)],
    },
    {
        "name": "red_yellow",
        "sign_fill": (184, 24, 24, 220),
        "sign_title": (255, 225, 48, 255),
        "sign_phone": (255, 255, 255, 255),
        "border": (255, 230, 180, 255),
        "phone": (255, 255, 255, 255),
        "services": [(255, 255, 255, 255), (255, 224, 45, 255), (30, 219, 239, 255), (245, 78, 70, 255), (89, 224, 96, 255), (185, 104, 255, 255), (255, 169, 35, 255), (235, 235, 235, 255)],
    },
    {
        "name": "blue_white",
        "sign_fill": (24, 94, 153, 216),
        "sign_title": (255, 255, 255, 255),
        "sign_phone": (255, 226, 65, 255),
        "border": (199, 231, 255, 255),
        "phone": (255, 226, 65, 255),
        "services": [(255, 255, 255, 255), (31, 222, 237, 255), (255, 194, 53, 255), (109, 228, 112, 255), (249, 100, 88, 255), (203, 126, 255, 255), (255, 232, 92, 255), (225, 245, 255, 255)],
    },
    {
        "name": "green_cream",
        "sign_fill": (31, 111, 77, 216),
        "sign_title": (255, 240, 176, 255),
        "sign_phone": (255, 255, 255, 255),
        "border": (196, 239, 208, 255),
        "phone": (40, 236, 221, 255),
        "services": [(255, 240, 176, 255), (255, 255, 255, 255), (43, 229, 218, 255), (255, 126, 92, 255), (137, 231, 111, 255), (212, 151, 255, 255), (255, 203, 68, 255), (228, 247, 232, 255)],
    },
    {
        "name": "brown_cream",
        "sign_fill": (117, 49, 35, 218),
        "sign_title": (255, 237, 194, 255),
        "sign_phone": (255, 220, 92, 255),
        "border": (239, 192, 140, 255),
        "phone": (255, 255, 255, 255),
        "services": [(255, 220, 92, 255), (255, 255, 255, 255), (39, 222, 235, 255), (245, 92, 82, 255), (104, 226, 107, 255), (196, 125, 255, 255), (255, 172, 45, 255), (238, 226, 205, 255)],
    },
]

COVER_SERVICE_LAYOUTS = ("three_rows", "two_columns", "four_by_two")

ROAD_RESCUE_BOTTOM_SERVICE_PALETTES: tuple[dict[str, Any], ...] = (
    {
        "name": "charcoal_signal",
        "background": (12, 18, 24, 255),
        "text_colors": ((255, 255, 255, 255), (255, 222, 45, 255)),
        "stroke_fill": (0, 0, 0, 235),
        "accent_color": (255, 188, 42, 255),
    },
    {
        "name": "warm_paper",
        "background": (244, 240, 229, 255),
        "text_colors": ((45, 48, 51, 255), (166, 28, 35, 255)),
        "stroke_fill": (255, 255, 255, 220),
        "accent_color": (181, 34, 39, 255),
    },
    {
        "name": "navy_cyan",
        "background": (18, 43, 66, 255),
        "text_colors": ((244, 248, 250, 255), (69, 220, 224, 255)),
        "stroke_fill": (4, 20, 31, 240),
        "accent_color": (77, 210, 218, 255),
    },
    {
        "name": "vermilion_cream",
        "background": (111, 27, 31, 255),
        "text_colors": ((255, 245, 219, 255), (255, 205, 64, 255)),
        "stroke_fill": (52, 10, 12, 240),
        "accent_color": (255, 217, 103, 255),
    },
    {
        "name": "forest_ivory",
        "background": (25, 67, 52, 255),
        "text_colors": ((249, 246, 230, 255), (255, 219, 79, 255)),
        "stroke_fill": (7, 31, 23, 240),
        "accent_color": (220, 231, 181, 255),
    },
    {
        "name": "steel_orange",
        "background": (57, 62, 68, 255),
        "text_colors": ((250, 250, 248, 255), (255, 151, 47, 255)),
        "stroke_fill": (17, 19, 21, 240),
        "accent_color": (255, 157, 59, 255),
    },
    {
        "name": "indigo_mint",
        "background": (41, 45, 78, 255),
        "text_colors": ((245, 247, 255, 255), (132, 232, 198, 255)),
        "stroke_fill": (15, 17, 38, 240),
        "accent_color": (137, 225, 198, 255),
    },
    {
        "name": "burgundy_gold",
        "background": (78, 31, 43, 255),
        "text_colors": ((255, 247, 231, 255), (239, 194, 89, 255)),
        "stroke_fill": (36, 10, 18, 240),
        "accent_color": (226, 183, 86, 255),
    },
)
ROAD_RESCUE_BOTTOM_SERVICE_ACCENTS = (
    "none",
    "top_rule",
    "left_rule",
    "top_left",
    "double_top",
)
ROAD_RESCUE_BOTTOM_SERVICE_FONT_SCALES = (1.0, 0.94, 1.05, 0.98)
ROAD_RESCUE_COMPACT_SERVICE_PALETTES = (
    ("porcelain_red", (250, 250, 248, 255), (39, 43, 46, 255), (181, 36, 42, 255), (218, 221, 219, 255)),
    ("white_evergreen", (246, 250, 247, 255), (29, 66, 52, 255), (34, 111, 80, 255), (207, 223, 214, 255)),
    ("white_cobalt", (246, 249, 252, 255), (30, 53, 82, 255), (41, 99, 166, 255), (206, 217, 230, 255)),
    ("graphite_silver", (40, 44, 48, 255), (248, 249, 250, 255), (210, 218, 222, 255), (78, 84, 90, 255)),
    ("white_vermilion", (253, 249, 248, 255), (63, 41, 39, 255), (195, 70, 51, 255), (230, 211, 205, 255)),
    ("white_teal", (245, 250, 250, 255), (28, 66, 69, 255), (30, 119, 126, 255), (204, 223, 224, 255)),
)
ROAD_RESCUE_SERVICE_TEMPLATES = {
    "service_two_rows": {"rows": (5, 5), "top": 0.855},
    "service_staggered": {"rows": (4, 3, 3), "top": 0.83},
    "service_centered": {"rows": (3, 4, 3), "top": 0.83},
    "service_wide_base": {"rows": (3, 3, 4), "top": 0.83},
    "service_featured_top": {"rows": (2, 4, 4), "top": 0.83},
    "service_wide_top": {"rows": (4, 4, 2), "top": 0.83},
    "service_title_rail": {"rows": (), "top": 0.83},
    "service_split_columns": {"rows": (), "top": 0.83},
}
ROAD_RESCUE_SERVICE_TEMPLATE_ORDER = (
    "service_staggered", "service_featured_top", "service_title_rail", "service_centered",
    "service_split_columns", "service_two_rows", "service_wide_base", "service_wide_top",
)

# Shared local typography, independent of category/signboard styling.
COVER_TYPOGRAPHY_VERSION = 1
COVER_TYPOGRAPHIES = (
    ("red_white", "four_by_two", (185, 25, 29, 245), (255, 255, 255, 255)),
    ("yellow_black", "three_rows", (255, 216, 44, 245), (18, 18, 18, 255)),
    ("white_red", "two_columns", (255, 255, 245, 245), (173, 18, 25, 255)),
    ("outlined", "three_rows", None, (255, 235, 60, 255)),
)


def cover_overlay_style(group_index: int, category_id: str | None = None) -> dict[str, Any]:
    style = dict(COVER_OVERLAY_STYLES[(group_index - 1) % len(COVER_OVERLAY_STYLES)])
    typography, layout, fill, ink = COVER_TYPOGRAPHIES[(group_index - 1) % len(COVER_TYPOGRAPHIES)]
    style.update(typography=typography, service_layout=layout, phone_fill=fill, phone=ink)
    if category_id == "truck_rescue" and group_index >= truck_cover_typography.FIRST_GROUP:
        plan = truck_cover_typography.cover_plan(group_index)
        style.update(
            name=plan["style_id"], typography=plan["phone_style"],
            service_layout=plan["bottom_service_style"]["layout"],
            phone_fill=plan["phone_fill"], phone=plan["phone_ink"],
        )
    return style


def road_rescue_bottom_service_style(group_index: int) -> dict[str, Any]:
    if group_index >= ROAD_RESCUE_MULTI_FOOTER_FIRST_GROUP:
        offset = group_index - ROAD_RESCUE_MULTI_FOOTER_FIRST_GROUP
        template_count = len(ROAD_RESCUE_SERVICE_TEMPLATE_ORDER)
        palette_count = len(ROAD_RESCUE_COMPACT_SERVICE_PALETTES)
        layout = ROAD_RESCUE_SERVICE_TEMPLATE_ORDER[offset % template_count]
        # Every block uses each layout once; colors and accents vary independently.
        palette_index = (offset // template_count + offset % template_count) % palette_count
        name, background, ink, accent_color, separator = ROAD_RESCUE_COMPACT_SERVICE_PALETTES[palette_index]
        accent = ("short_rule", "edge_rule", "row_rule")[(offset // (template_count * palette_count)) % 3]
        return {
            "version": 3, "name": name, "background": background,
            "text_colors": (ink,), "stroke_fill": background, "accent_color": accent_color,
            "separator": separator, "layout": layout, "accent": accent,
            "font_scale": 1.0, "style_id": f"multi-v3__{layout}__{name}__{accent}",
        }
    if group_index >= ROAD_RESCUE_COVER_V3_FIRST_GROUP:
        offset = group_index - ROAD_RESCUE_COVER_V3_FIRST_GROUP
        name, background, ink, accent_color, separator = ROAD_RESCUE_COMPACT_SERVICE_PALETTES[
            offset % len(ROAD_RESCUE_COMPACT_SERVICE_PALETTES)
        ]
        accent = ("short_rule", "edge_rule", "row_rule")[(offset // 6) % 3]
        return {
            "version": 2, "name": name, "background": background,
            "text_colors": (ink,), "stroke_fill": background, "accent_color": accent_color,
            "separator": separator, "layout": "compact_five_by_two", "accent": accent,
            "font_scale": 1.0, "style_id": f"compact-v2__{name}__{accent}",
        }
    offset = max(0, group_index - 1)
    palette = dict(
        ROAD_RESCUE_BOTTOM_SERVICE_PALETTES[
            offset % len(ROAD_RESCUE_BOTTOM_SERVICE_PALETTES)
        ]
    )
    layout = COVER_SERVICE_LAYOUTS[(offset * 2) % len(COVER_SERVICE_LAYOUTS)]
    accent = ROAD_RESCUE_BOTTOM_SERVICE_ACCENTS[
        (offset * 3) % len(ROAD_RESCUE_BOTTOM_SERVICE_ACCENTS)
    ]
    font_scale = ROAD_RESCUE_BOTTOM_SERVICE_FONT_SCALES[
        offset % len(ROAD_RESCUE_BOTTOM_SERVICE_FONT_SCALES)
    ]
    palette.update(
        layout=layout,
        accent=accent,
        font_scale=font_scale,
        style_id=f"{palette['name']}__{layout}__{accent}__{font_scale:.2f}",
    )
    return palette


def cover_style_version(category_id: str, group_index: int = 0) -> int:
    if category_id == "pet_transport":
        return PET_TRANSPORT_COVER_STYLE_VERSION
    if category_id == "truck_rescue":
        return (
            truck_cover_typography.STYLE_VERSION
            if group_index >= truck_cover_typography.FIRST_GROUP
            else TRUCK_RESCUE_COVER_STYLE_VERSION
        )
    if category_id in {"road_rescue", "home_appliance_repair"} and group_index >= ROAD_RESCUE_MULTI_FOOTER_FIRST_GROUP:
        return ROAD_RESCUE_MULTI_FOOTER_STYLE_VERSION
    if category_id in {"road_rescue", "home_appliance_repair"} and group_index >= ROAD_RESCUE_COVER_V3_FIRST_GROUP:
        return ROAD_RESCUE_COVER_V3_STYLE_VERSION
    return (
        ROAD_RESCUE_COVER_STYLE_VERSION
        if category_id in {"road_rescue", "home_appliance_repair"}
        else PIPE_COVER_OVERLAY_STYLE_VERSION
    )


def cover_center_phone_region(category_id: str, group_index: int) -> list[float]:
    if category_id == "truck_rescue" and group_index >= truck_cover_typography.FIRST_GROUP:
        return truck_cover_typography.cover_plan(group_index)["center_phone_region"]
    if category_id in {"road_rescue", "home_appliance_repair"} and group_index >= ROAD_RESCUE_COVER_V3_FIRST_GROUP:
        return [0.025, 0.50, 0.975, 0.60]
    return [0.025, 0.43, 0.975, 0.535]


def road_rescue_bottom_service_region(group_index: int) -> list[float]:
    layout = road_rescue_bottom_service_style(group_index)["layout"]
    return [0.0, ROAD_RESCUE_SERVICE_TEMPLATES.get(layout, {}).get("top", 0.855), 1.0, 1.0]


def _road_service_template_boxes(width: int, height: int, layout: str) -> list[tuple[int, int, int, int]]:
    preset = ROAD_RESCUE_SERVICE_TEMPLATES[layout]
    top, bottom = height * (preset["top"] + 0.015), height * 0.983

    def rows_box(left: float, right: float, counts: tuple[int, ...], centered: bool = True) -> list[tuple[int, int, int, int]]:
        result = []
        row_height = (bottom - top) / len(counts)
        widest = max(counts)
        for row, count in enumerate(counts):
            span = (right - left) * (1 - (widest - count) * 0.075) if centered else right - left
            row_left = left + (right - left - span) / 2
            for column in range(count):
                result.append((
                    int(row_left + span * column / count), int(top + row * row_height),
                    int(row_left + span * (column + 1) / count), int(top + (row + 1) * row_height),
                ))
        return result

    if layout == "service_title_rail":
        return [(int(width * 0.04), int(top), int(width * 0.22), int(bottom))] + rows_box(width * 0.265, width * 0.965, (3, 3, 3))
    if layout == "service_split_columns":
        return rows_box(width * 0.035, width * 0.47, (2, 2, 1)) + rows_box(width * 0.53, width * 0.965, (2, 2, 1))
    return rows_box(width * 0.045, width * 0.955, preset["rows"])


def _draw_road_service_template(draw: Any, width: int, height: int, boxes: list[tuple[int, int, int, int]], style: dict[str, Any]) -> None:
    layout = style["layout"]
    top = int(height * ROAD_RESCUE_SERVICE_TEMPLATES[layout]["top"])
    ink, accent = style["separator"], style["accent_color"]
    line_width = max(1, width // 700)
    body = boxes
    left = int(width * 0.045)
    if layout == "service_title_rail":
        draw.rectangle((0, top, int(width * 0.245), height), fill=accent)
        body = boxes[1:]
        left = int(width * 0.28)
    if layout == "service_split_columns":
        draw.line((width // 2, boxes[0][1], width // 2, boxes[-1][3]), fill=ink, width=line_width)
    sections = (body[:5], body[5:]) if layout == "service_split_columns" else (body,)
    for section in sections:
        rows: dict[int, list[tuple[int, int, int, int]]] = {}
        for box in section:
            rows.setdefault(box[1], []).append(box)
        ordered_rows = sorted(rows.values(), key=lambda row: row[0][1])
        for row_index, row in enumerate(ordered_rows):
            if row_index < len(ordered_rows) - 1:
                draw.line((row[0][0], row[0][3], row[-1][2], row[0][3]), fill=ink, width=line_width)
            for box in row[:-1]:
                center_y = (box[1] + box[3]) // 2
                half_line = max(5, width // 105)
                draw.line((box[2], center_y - half_line, box[2], center_y + half_line), fill=ink, width=line_width)
    rule_y = top + max(4, width // 120)
    if style["accent"] == "edge_rule":
        draw.line((0, top, width, top), fill=accent, width=max(3, width // 240))
    elif style["accent"] == "row_rule":
        draw.line((left, body[0][3], left + int(width * 0.12), body[0][3]), fill=accent, width=max(2, width // 350))
    else:
        draw.line((left, rule_y, left + int(width * 0.12), rule_y), fill=accent, width=max(3, width // 240))


def _cover_service_boxes(
    width: int,
    height: int,
    layout: str,
    count: int = 8,
) -> list[tuple[int, int, int, int]]:
    margin_left, margin_right = int(width * 0.045), int(width * 0.955)
    if count == 10 and layout in ROAD_RESCUE_SERVICE_TEMPLATES:
        return _road_service_template_boxes(width, height, layout)
    if count == 10 and layout == "compact_five_by_two":
        cell_width = (margin_right - margin_left) / 5
        top, bottom = int(height * 0.87), int(height * 0.98)
        row_height = (bottom - top) / 2
        return [
            (
                int(margin_left + cell_width * (index % 5)),
                int(top + row_height * (index // 5)),
                int(margin_left + cell_width * (index % 5 + 1)),
                int(top + row_height * (index // 5 + 1)),
            )
            for index in range(10)
        ]
    if count == 10:
        if layout in ("three_rows", "two_columns"):
            counts = (4, 3, 3) if layout == "three_rows" else (2, 2, 2, 2, 2)
            top, bottom = int(height * 0.765), int(height * 0.965)
            row_height = (bottom - top) / len(counts)
            boxes = []
            for row, columns in enumerate(counts):
                cell_width = (margin_right - margin_left) / columns
                for column in range(columns):
                    boxes.append((
                        int(margin_left + cell_width * column), int(top + row_height * row),
                        int(margin_left + cell_width * (column + 1)), int(top + row_height * (row + 1)),
                    ))
            return boxes
        top, bottom = int(height * 0.765), int(height * 0.965)
        gap = max(4, int(width * 0.006))
        cell_width = (margin_right - margin_left - gap * 4) / 5
        cell_height = (bottom - top - gap) / 2
        return [
            (
                int(margin_left + (cell_width + gap) * (index % 5)),
                int(top + (cell_height + gap) * (index // 5)),
                int(margin_left + (cell_width + gap) * (index % 5) + cell_width),
                int(top + (cell_height + gap) * (index // 5) + cell_height),
            )
            for index in range(10)
        ]
    if layout == "two_columns":
        top, bottom = int(height * 0.70), int(height * 0.965)
        row_height = (bottom - top) / 4
        center = width // 2
        gap = int(width * 0.025)
        return [
            (
                margin_left if index % 2 == 0 else center + gap,
                int(top + row_height * (index // 2)),
                center - gap if index % 2 == 0 else margin_right,
                int(top + row_height * (index // 2 + 1)),
            )
            for index in range(8)
        ]
    if layout == "three_rows":
        counts = (3, 3, 2)
        row_tops = (0.715, 0.805, 0.895)
        row_bottoms = (0.785, 0.875, 0.965)
        result: list[tuple[int, int, int, int]] = []
        for count, top_ratio, bottom_ratio in zip(counts, row_tops, row_bottoms):
            usable_left = int(width * (0.06 if count == 3 else 0.14))
            usable_right = int(width * (0.94 if count == 3 else 0.86))
            cell_width = (usable_right - usable_left) / count
            for column in range(count):
                result.append((
                    int(usable_left + cell_width * column),
                    int(height * top_ratio),
                    int(usable_left + cell_width * (column + 1)),
                    int(height * bottom_ratio),
                ))
        return result
    if layout == "four_by_two":
        top, bottom = int(height * 0.80), int(height * 0.965)
        cell_width = (margin_right - margin_left) / 4
        cell_height = (bottom - top) / 2
        return [
            (
                int(margin_left + cell_width * (index % 4)),
                int(top + cell_height * (index // 4)),
                int(margin_left + cell_width * (index % 4 + 1)),
                int(top + cell_height * (index // 4 + 1)),
            )
            for index in range(8)
        ]
    raise ValueError(f"unknown cover service layout: {layout}")


def _fit_image(source: Any, size: tuple[int, int], anchor_y: float = 0.5) -> Any:
    from PIL import Image

    target_width, target_height = size
    source_width, source_height = source.size
    scale = max(target_width / source_width, target_height / source_height)
    resized = source.resize(
        (max(target_width, round(source_width * scale)), max(target_height, round(source_height * scale))),
        Image.Resampling.LANCZOS,
    )
    extra_x = max(0, resized.width - target_width)
    extra_y = max(0, resized.height - target_height)
    left = extra_x // 2
    top = round(extra_y * max(0.0, min(1.0, anchor_y)))
    return resized.crop((left, top, left + target_width, top + target_height))


def _cover_signboard_service_items(category_id: str) -> list[str]:
    category = load_category_config(category_id)
    configured = category.get("cover_signboard_service_items")
    if isinstance(configured, list) and configured and all(
        isinstance(item, str) and item.strip() for item in configured
    ):
        return [item.strip() for item in configured]
    if category_id == "road_rescue":
        return ["搭电救援", "拖车服务", "补胎换胎", "送油救援"]
    return ["马桶疏通", "地漏疏通", "主管道疏通", "高压清洗"]


def _detect_signboard_quad(image: Any) -> tuple[list[tuple[int, int]], str]:
    """Find the largest saturated, wide signboard in the upper photo area.

    Cover prompts deliberately request one broad, blank, coloured fascia.  A
    small Pillow-only detector is enough for that constrained input and avoids
    adding OpenCV as a runtime dependency.  It never paints a replacement
    board; a conservative fixed region is used only as a text-only fallback.
    """
    from PIL import Image

    width, height = image.size
    sample_width = min(256, width)
    sample_height = max(1, round(height * sample_width / width))
    sample = image.convert("RGB").resize(
        (sample_width, sample_height), Image.Resampling.BILINEAR
    )
    search_height = max(1, min(sample_height, round(sample_height * 0.40)))
    pixels = sample.load()
    mask = bytearray(sample_width * search_height)
    for y in range(search_height):
        for x in range(sample_width):
            red, green, blue = pixels[x, y]
            highest = max(red, green, blue)
            lowest = min(red, green, blue)
            if highest >= 75 and highest - lowest >= 48:
                mask[y * sample_width + x] = 1

    best_points: list[tuple[int, int]] | None = None
    best_score = 0.0
    for start in range(len(mask)):
        if mask[start] != 1:
            continue
        mask[start] = 2
        stack = [start]
        points: list[tuple[int, int]] = []
        min_x = max_x = start % sample_width
        min_y = max_y = start // sample_width
        while stack:
            current = stack.pop()
            x = current % sample_width
            y = current // sample_width
            points.append((x, y))
            min_x = min(min_x, x)
            max_x = max(max_x, x)
            min_y = min(min_y, y)
            max_y = max(max_y, y)
            for neighbor_y in range(max(0, y - 1), min(search_height, y + 2)):
                row = neighbor_y * sample_width
                for neighbor_x in range(max(0, x - 1), min(sample_width, x + 2)):
                    neighbor = row + neighbor_x
                    if mask[neighbor] == 1:
                        mask[neighbor] = 2
                        stack.append(neighbor)
        box_width = max_x - min_x + 1
        box_height = max_y - min_y + 1
        if (
            box_width < sample_width * 0.42
            or box_height < sample_height * 0.035
            or box_width / max(1, box_height) < 1.6
            or len(points) < sample_width * search_height * 0.018
        ):
            continue
        score = len(points) * (box_width / sample_width) * (
            1.15 - 0.15 * min_y / search_height
        )
        if score > best_score:
            best_score = score
            best_points = points

    if not best_points:
        return [
            (int(width * 0.07), int(height * 0.07)),
            (int(width * 0.93), int(height * 0.07)),
            (int(width * 0.93), int(height * 0.30)),
            (int(width * 0.07), int(height * 0.30)),
        ], "fallback_text_region"

    top_left = min(best_points, key=lambda point: point[0] + point[1])
    top_right = max(best_points, key=lambda point: point[0] - point[1])
    bottom_right = max(best_points, key=lambda point: point[0] + point[1])
    bottom_left = min(best_points, key=lambda point: point[0] - point[1])
    scale_x = width / sample_width
    scale_y = height / sample_height
    corners = [
        (round(point[0] * scale_x), round(point[1] * scale_y))
        for point in (top_left, top_right, bottom_right, bottom_left)
    ]
    center_x = sum(point[0] for point in corners) / 4
    center_y = sum(point[1] for point in corners) / 4
    inset = 0.90
    return [
        (
            round(center_x + (point[0] - center_x) * inset),
            round(center_y + (point[1] - center_y) * inset),
        )
        for point in corners
    ], "upper_color_component"


def _solve_linear_system(rows: list[list[float]]) -> list[float]:
    size = len(rows)
    matrix = [list(row) for row in rows]
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(matrix[row][column]))
        if abs(matrix[pivot][column]) < 1e-10:
            raise ValueError("singular perspective transform")
        matrix[column], matrix[pivot] = matrix[pivot], matrix[column]
        divisor = matrix[column][column]
        matrix[column] = [value / divisor for value in matrix[column]]
        for row in range(size):
            if row == column:
                continue
            factor = matrix[row][column]
            if abs(factor) < 1e-12:
                continue
            matrix[row] = [
                value - factor * pivot_value
                for value, pivot_value in zip(matrix[row], matrix[column])
            ]
    return [matrix[row][-1] for row in range(size)]


def _perspective_coefficients(
    destination: list[tuple[int, int]],
    source: list[tuple[int, int]],
) -> tuple[float, ...]:
    rows: list[list[float]] = []
    for (x, y), (u, v) in zip(destination, source):
        rows.append([x, y, 1, 0, 0, 0, -u * x, -u * y, u])
        rows.append([0, 0, 0, x, y, 1, -v * x, -v * y, v])
    return tuple(_solve_linear_system(rows))


def _raised_signboard_text(
    draw: Any,
    box: tuple[int, int, int, int],
    text: str,
    font: Any,
    *,
    fill: tuple[int, int, int, int] = (248, 248, 242, 255),
    shadow_offset: int = 5,
) -> None:
    shadow_box = (
        box[0] + shadow_offset,
        box[1] + shadow_offset,
        box[2] + shadow_offset,
        box[3] + shadow_offset,
    )
    _centered_text(draw, shadow_box, text, font, (0, 0, 0, 125))
    _centered_text(draw, box, text, font, fill, 1, (82, 82, 76, 210))


def _direct_signboard_overlay(
    image: Any,
    title: str,
    service_items: list[str],
    phone: str,
) -> tuple[Any, list[tuple[int, int]], str]:
    from PIL import Image, ImageDraw

    quad, detection = _detect_signboard_quad(image)
    panel_width, panel_height = 1400, 430
    panel = Image.new("RGBA", (panel_width, panel_height), (0, 0, 0, 0))
    panel_draw = ImageDraw.Draw(panel)
    filtered_services = [item for item in service_items if item and item != title]
    split = min(3, max(1, (len(filtered_services) + 1) // 2))
    service_lines = [
        " · ".join(filtered_services[:split]),
        " · ".join(filtered_services[split:]),
    ]
    title_font = _fit_font(panel_draw, title, int(panel_width * 0.86), 150, min_size=72)
    line_one_font = _fit_font(
        panel_draw, service_lines[0], int(panel_width * 0.92), 48, min_size=25
    )
    line_two_font = _fit_font(
        panel_draw, service_lines[1], int(panel_width * 0.92), 46, min_size=25
    ) if service_lines[1] else None
    sign_phone = f"联系电话：{phone}"
    phone_font = _fit_font(panel_draw, sign_phone, int(panel_width * 0.88), 72, min_size=34)
    _raised_signboard_text(panel_draw, (0, 0, panel_width, 205), title, title_font, shadow_offset=6)
    _raised_signboard_text(
        panel_draw, (0, 195, panel_width, 270), service_lines[0], line_one_font, shadow_offset=3
    )
    if service_lines[1] and line_two_font is not None:
        _raised_signboard_text(
            panel_draw, (0, 260, panel_width, 330), service_lines[1], line_two_font, shadow_offset=3
        )
    _raised_signboard_text(
        panel_draw, (0, 325, panel_width, panel_height), sign_phone, phone_font, shadow_offset=4
    )
    source = [
        (0, 0),
        (panel_width - 1, 0),
        (panel_width - 1, panel_height - 1),
        (0, panel_height - 1),
    ]
    try:
        coefficients = _perspective_coefficients(quad, source)
        warped = panel.transform(
            image.size,
            Image.Transform.PERSPECTIVE,
            coefficients,
            Image.Resampling.BICUBIC,
            fillcolor=(0, 0, 0, 0),
        )
        return warped, quad, detection
    except ValueError:
        left = min(point[0] for point in quad)
        top = min(point[1] for point in quad)
        right = max(point[0] for point in quad)
        bottom = max(point[1] for point in quad)
        fallback = Image.new("RGBA", image.size, (0, 0, 0, 0))
        fallback.alpha_composite(
            panel.resize((max(1, right - left), max(1, bottom - top)), Image.Resampling.LANCZOS),
            (left, top),
        )
        return fallback, quad, f"{detection}_axis_aligned_fallback"


def apply_overlays(
    raw_path: Path,
    target: Path,
    phone: str,
    role: str,
    group_index: int,
    position: int,
    service_items: list[str],
    final_size: str | tuple[int, int] | list[int] | None = None,
    *,
    service_role: str | None = None,
    height_profile_id: str | None = None,
    generation_target_id: str | None = None,
    delivery_target_id: str | None = None,
    category_id: str = DEFAULT_CATEGORY_ID,
    structure_version: str | None = None,
    generation_mode: str | None = None,
    overlay_profile: str | None = None,
    postprocess_rules: dict | None = None,
    preserve_signboard: bool = False,
    signboard_phone_required: bool | None = None,
) -> dict[str, Any]:
    from PIL import Image, ImageDraw

    if overlay_profile not in (None, "interior_phone_eight_services"):
        raise CategoryPromptError(f"不支持的本地叠字配置：{overlay_profile}")
    from tools.postprocess_rules import parameters
    pp = parameters(postprocess_rules)
    crop_rules = pp.get("crop", {})
    text_rules = pp.get("cover" if role == "cover" else "detail", {})
    interior_profile = overlay_profile == "interior_phone_eight_services"
    if interior_profile:
        if role != "cover":
            raise CategoryPromptError("室内电话与八词叠字仅支持 cover 布局")
        if len(service_items) != 8 or not all(isinstance(item, str) and item.strip() for item in service_items):
            raise CategoryPromptError("室内电话与八词叠字必须提供恰好八个非空服务词")
        if raw_path.resolve() == target.resolve():
            raise CategoryPromptError("本地叠字成品不能覆盖原图")
    with Image.open(_io_path(raw_path)) as source:
        source.load()
        source_image = source.convert("RGBA")
    requested_size = source_image.size if final_size is None else parse_size(_size_text(final_size))
    ktv_portrait = category_id == "ktv" and requested_size == (864, 1536)
    if interior_profile:
        if requested_size != source_image.size or not all(512 <= side <= 8192 for side in source_image.size):
            raise CategoryPromptError("室内叠字必须保持原图尺寸，原图每边需在512至8192像素之间")
    elif not ktv_portrait and (requested_size[0] != RAW_API_SIZE[0] or requested_size[1] > RAW_API_SIZE[1]):
        raise CategoryPromptError(f"不支持的本地成品尺寸：{requested_size[0]}x{requested_size[1]}")
    anchor_y = 0.0 if role == "cover" else ((group_index + position) % 3) / 2
    anchor_y = crop_rules.get("cover_anchor_y" if role == "cover" else "detail_anchor_y", anchor_y)
    image = source_image.copy() if interior_profile else _fit_image(source_image, requested_size, anchor_y=anchor_y)
    if postprocess_rules and postprocess_rules.get('template'):
        from tools.graphic_templates import render_delivery
        return render_delivery(image,target,phone,service_items,postprocess_rules,role,category_id,[raw_path],{'group_index':group_index,'position':position,'service_role':service_role,'structure_version':structure_version,'generation_mode':generation_mode,'overlay_profile':overlay_profile,**({'signboard_phone_required':signboard_phone_required if signboard_phone_required is not None else False} if category_id=='diving_salvage' else {})})
    actual_services = []
    width, height = image.size
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    bottom_service_backing: str | None = None
    bottom_service_style: dict[str, Any] | None = None
    detail_palettes = [
        ((11, 55, 88, 222), (255, 224, 76, 255)),
        ((102, 33, 25, 222), (255, 239, 180, 255)),
        ((18, 78, 62, 222), (225, 255, 238, 255)),
    ]
    band, accent = detail_palettes[(group_index - 1) % len(detail_palettes)]
    expected = [f"电话：{phone}", *service_items]

    if role == "cover":
        cover_style = cover_overlay_style(group_index, None if interior_profile else category_id)
        truck_plan = (
            truck_cover_typography.cover_plan(group_index)
            if category_id == "truck_rescue" and not interior_profile
            and group_index >= truck_cover_typography.FIRST_GROUP else None
        )
        if truck_plan is not None:
            if len(service_items) != 10 or not all(isinstance(item, str) and item.strip() for item in service_items):
                raise CategoryPromptError("货车新版封面叠字必须提供恰好十个非空服务词")
            bottom_service_style = truck_plan["bottom_service_style"]
        if category_id in {"road_rescue", "home_appliance_repair"} and not interior_profile:
            bottom_service_style = road_rescue_bottom_service_style(group_index)
            cover_style = {
                **cover_style,
                "service_layout": bottom_service_style["layout"],
            }
        if category_id == "ktv" or interior_profile:
            # Interior photographs have no storefront signboard to detect or paint.
            cover_style = {**cover_style, "service_layout": "four_by_two"}
            signboard_quad = None
            signboard_detection = None
        elif category_id in MODEL_GENERATED_SIGNBOARD_CATEGORIES or preserve_signboard:
            sign_phone = f"联系电话：{phone}"
            signboard_quad = None
            signboard_detection = None
            expected.append(sign_phone)
        else:
            signboard_title = CATEGORY_SIGNBOARD_TITLES.get(category_id, category_id)
            signboard_services = _cover_signboard_service_items(category_id)
            sign_phone = f"联系电话：{phone}"
            signboard_layer, signboard_quad, signboard_detection = _direct_signboard_overlay(
                image, signboard_title, signboard_services, phone
            )
            overlay = Image.alpha_composite(overlay, signboard_layer)
            draw = ImageDraw.Draw(overlay)
            expected.extend([signboard_title, *signboard_services, sign_phone])

        phone_region = (
            [0.025, 0.43, 0.975, 0.535]
            if interior_profile else cover_center_phone_region(category_id, group_index)
        )
        phone_region = text_rules.get("phone_region", phone_region)
        cover_style = {**cover_style, "phone":tuple(text_rules.get("phone_color", cover_style["phone"])), "phone_fill":text_rules.get("phone_background", cover_style["phone_fill"])}
        phone_box = (
            int(width * phone_region[0]),
            int(height * phone_region[1]),
            int(width * phone_region[2]),
            int(height * phone_region[3]),
        )
        if cover_style["phone_fill"] is not None:
            draw.rectangle(phone_box, fill=tuple(cover_style["phone_fill"]))
        phone_text = f"电话：{phone}"
        phone_stroke = text_rules.get("phone_stroke", max(4, width // 165) if cover_style["phone_fill"] is None else 0)
        phone_font = _fit_font(
            draw, phone_text, int(width * 0.90), int(width * text_rules.get("phone_font_ratio", 0.082)), stroke=phone_stroke, family=text_rules.get("font_family"),
            max_height=int((phone_box[3] - phone_box[1]) * 0.90) if interior_profile or truck_plan is not None else None,
        )
        _centered_text(draw, phone_box, phone_text, phone_font, cover_style["phone"], phone_stroke, (0, 0, 0, 255))

        service_boxes = _cover_service_boxes(width, height, cover_style["service_layout"], len(service_items))
        multi_services = category_id in {"road_rescue", "home_appliance_repair"} and not interior_profile and cover_style["service_layout"] in ROAD_RESCUE_SERVICE_TEMPLATES
        compact_services = category_id in {"road_rescue", "home_appliance_repair"} and not interior_profile and (cover_style["service_layout"] == "compact_five_by_two" or multi_services)
        if truck_plan is not None:
            multi_services = not truck_plan["reference_supplement"]
            compact_services = multi_services
        # One flat backing for readability, never individual UI-like buttons.
        if truck_plan is not None:
            bottom_service_backing = "none" if truck_plan["reference_supplement"] else "opaque_mask"
            if not truck_plan["reference_supplement"]:
                draw.rectangle(
                    (0, int(height * truck_plan["bottom_service_region"][1]), width, height),
                    fill=bottom_service_style["background"],
                )
                _draw_road_service_template(draw, width, height, service_boxes, bottom_service_style)
        elif category_id in {"road_rescue", "home_appliance_repair"} and not interior_profile:
            bottom_service_backing = "opaque_mask"
            service_panel = (
                int(width * 0.025),
                min(box[1] for box in service_boxes),
                int(width * 0.975),
                height,
            )
            if compact_services:
                service_panel = (0, int(height * road_rescue_bottom_service_region(group_index)[1]), width, height)
            draw.rectangle(service_panel, fill=bottom_service_style["background"])
            accent_color = bottom_service_style["accent_color"]
            accent_width = max(4, width // 180)
            accent = bottom_service_style["accent"]
            if multi_services:
                _draw_road_service_template(draw, width, height, service_boxes, bottom_service_style)
            elif compact_services:
                left, right = int(width * 0.045), int(width * 0.955)
                middle_y = service_boxes[0][3]
                line_width = max(1, width // 700)
                separator = bottom_service_style["separator"]
                draw.line((left, middle_y, right, middle_y), fill=separator, width=line_width)
                for row in range(2):
                    for column in range(4):
                        box = service_boxes[row * 5 + column]
                        center_y = (box[1] + box[3]) // 2
                        half_line = max(5, width // 105)
                        draw.line((box[2], center_y - half_line, box[2], center_y + half_line), fill=separator, width=line_width)
                rule_y = service_panel[1] + max(4, width // 120)
                if accent == "short_rule":
                    draw.line((left, rule_y, left + int(width * 0.12), rule_y), fill=accent_color, width=max(3, width // 240))
                elif accent == "edge_rule":
                    draw.line((0, service_panel[1], width, service_panel[1]), fill=accent_color, width=max(3, width // 240))
                else:
                    draw.line((left, middle_y, left + int(width * 0.12), middle_y), fill=accent_color, width=max(2, width // 350))
            if accent in {"top_rule", "top_left", "double_top"}:
                draw.line(
                    (service_panel[0], service_panel[1], service_panel[2], service_panel[1]),
                    fill=accent_color,
                    width=accent_width,
                )
            if accent == "double_top":
                second_y = service_panel[1] + accent_width * 2
                draw.line(
                    (service_panel[0], second_y, service_panel[2], second_y),
                    fill=accent_color,
                    width=max(2, accent_width // 2),
                )
            if accent in {"left_rule", "top_left"}:
                draw.line(
                    (service_panel[0], service_panel[1], service_panel[0], service_panel[3]),
                    fill=accent_color,
                    width=accent_width,
                )
        elif cover_style["phone_fill"] is not None:
            bottom_service_backing = "translucent"
            draw.rectangle((int(width * 0.025), min(box[1] for box in service_boxes),
                            int(width * 0.975), int(height * 0.975)), fill=(12, 18, 24, 220))
        else:
            bottom_service_backing = "none"
        compact_font = None
        if compact_services:
            compact_font = min(
                (
                    _fit_font(draw, item, int((box[2] - box[0]) * 0.91), int(width * 0.034), min_size=15)
                    for item, box in zip(service_items, service_boxes)
                ),
                key=lambda font: font.size,
            )
        for index, (item, box) in enumerate(zip(service_items, service_boxes)):
            if multi_services and cover_style["service_layout"] == "service_title_rail" and index == 0:
                lines = [item[start:start + 2] for start in range(0, len(item), 2)]
                title_font = _fit_font(draw, max(lines, key=len), int((box[2] - box[0]) * .88), int(width * .046))
                line_height = int(width * .058)
                title_top = (box[1] + box[3] - len(lines) * line_height) // 2
                accent_color = bottom_service_style["accent_color"]
                title_ink = (30, 35, 39, 255) if sum(accent_color[:3]) > 540 else (255, 255, 255, 255)
                for line_index, line in enumerate(lines):
                    line_box = (box[0], title_top + line_index * line_height, box[2], title_top + (line_index + 1) * line_height)
                    _centered_text(draw, line_box, line, title_font, title_ink)
                actual_services.append({"text":item,"box":list(box),"font_size":title_font.size,"color":list(title_ink)})
                continue
            font_scale = (
                float(bottom_service_style["font_scale"])
                if bottom_service_style is not None
                else 1.0
            )
            stroke_width = 0 if compact_services else max(2, width // 360)
            item_font = compact_font or _fit_font(
                draw,
                item,
                int((box[2] - box[0]) * 0.90),
                min(
                    int(width * 0.043 * font_scale),
                    int((box[3] - box[1]) * 0.62 * font_scale),
                ),
                min_size=15,
                stroke=stroke_width,
            )
            if multi_services and cover_style["service_layout"] == "service_featured_top" and index < 2:
                item_font = _fit_font(draw, item, int((box[2] - box[0]) * .9), int(width * .04))
            text_colors = (
                bottom_service_style["text_colors"]
                if bottom_service_style is not None
                else ((255, 255, 255, 255), (255, 235, 60, 255))
            )
            stroke_fill = (
                bottom_service_style["stroke_fill"]
                if bottom_service_style is not None
                else (0, 0, 0, 235)
            )
            actual_services.append({"text":item,"box":list(box),"font_size":item_font.size,"color":list(text_colors[index % len(text_colors)])})
            _centered_text(
                draw,
                box,
                item,
                item_font,
                text_colors[index % len(text_colors)],
                stroke_width,
                stroke_fill,
            )
    else:
        if category_id != "business_ktv" and (service_role or role):
            label = str(service_role or role)
            label_box = (int(width * 0.12), int(height * 0.035), int(width * 0.88), int(height * 0.105))
            draw.rounded_rectangle(label_box, radius=max(10, width // 55), fill=(band[0], band[1], band[2], 200), outline=accent, width=max(2, width // 320))
            label_font = _fit_font(draw, label, int(width * 0.67), int(width * 0.054), stroke=max(1, width // 400))
            _centered_text(draw, label_box, label, label_font, (255, 255, 255, 255), max(1, width // 400), (0, 0, 0, 210))
            expected.append(label)
        phone_region = text_rules.get("phone_region", [0, .49, 1, .585])
        phone_box = tuple(int(v * (width if i % 2 == 0 else height)) for i,v in enumerate(phone_region))
        if text_rules.get("phone_background", [0,0,0,184]) is not None:
            draw.rectangle(phone_box, fill=tuple(text_rules.get("phone_background", [0,0,0,184])))
        phone_text = f"电话：{phone}"
        phone_stroke = text_rules.get("phone_stroke", max(3, width // 210))
        phone_font = _fit_font(draw, phone_text, int(width * 0.9), int(width * text_rules.get("phone_font_ratio", .078)), stroke=phone_stroke, family=text_rules.get("font_family"))
        _centered_text(draw, phone_box, phone_text, phone_font, tuple(text_rules.get("phone_color", accent)), phone_stroke, (0, 0, 0, 255))

        grid_box = (int(width * 0.025), int(height * 0.835), int(width * 0.975), int(height * 0.975))
        draw.rounded_rectangle(grid_box, radius=max(10, width // 45), fill=(band[0], band[1], band[2], 220), outline=accent, width=max(2, width // 300))
        columns = 5 if len(service_items) == 10 else 4
        rows = max(1, (len(service_items) + columns - 1) // columns)
        cell_w = (grid_box[2] - grid_box[0]) / columns
        cell_h = (grid_box[3] - grid_box[1]) / rows
        for col in range(1, columns):
            x = int(grid_box[0] + cell_w * col)
            draw.line((x, grid_box[1], x, grid_box[3]), fill=(accent[0], accent[1], accent[2], 145), width=max(1, width // 500))
        draw.line((grid_box[0], int(grid_box[1] + cell_h), grid_box[2], int(grid_box[1] + cell_h)), fill=(accent[0], accent[1], accent[2], 145), width=max(1, width // 500))
        for index, item in enumerate(service_items):
            row, col = divmod(index, columns)
            box = (
                int(grid_box[0] + cell_w * col), int(grid_box[1] + cell_h * row),
                int(grid_box[0] + cell_w * (col + 1)), int(grid_box[1] + cell_h * (row + 1)),
            )
            item_font = _fit_font(draw, item, int(cell_w * 0.86), int(width * 0.032), min_size=14, stroke=max(1, width // 600))
            actual_services.append({"text":item,"box":list(box),"font_size":item_font.size,"color":[255,255,255,255]})
            _centered_text(draw, box, item, item_font, (255, 255, 255, 255), max(1, width // 600), (0, 0, 0, 220))

    if any(key.startswith("service_") for key in text_rules) or "font_family" in text_rules:
        if role == "cover":
            original_box = (min(b[0] for b in service_boxes), min(b[1] for b in service_boxes), max(b[2] for b in service_boxes), max(b[3] for b in service_boxes))
        else: original_box = grid_box
        overlay.paste((0,0,0,0), original_box)
        region = text_rules.get("service_region", [original_box[0]/width, original_box[1]/height, original_box[2]/width, original_box[3]/height])
        custom_box = tuple(int(v * (width if i%2==0 else height)) for i,v in enumerate(region))
        draw = ImageDraw.Draw(overlay)
        draw.rectangle(custom_box, fill=tuple(text_rules.get("service_background", [12,18,24,230])))
        columns = text_rules.get("service_columns", 5 if len(service_items)==10 else 4)
        count_rows = max(1,(len(service_items)+columns-1)//columns)
        actual_services = []
        for i,item in enumerate(service_items):
            r,c=divmod(i,columns)
            box=(custom_box[0]+(custom_box[2]-custom_box[0])*c//columns, custom_box[1]+(custom_box[3]-custom_box[1])*r//count_rows, custom_box[0]+(custom_box[2]-custom_box[0])*(c+1)//columns, custom_box[1]+(custom_box[3]-custom_box[1])*(r+1)//count_rows)
            font=_fit_font(draw,item,int((box[2]-box[0])*.9),int(width*text_rules.get("service_font_ratio",.032)),min_size=14,family=text_rules.get("font_family"))
            color=tuple(text_rules.get("service_color",[255,255,255,255]))
            _centered_text(draw,box,item,font,color)
            actual_services.append({"text":item,"box":list(box),"font_size":font.size,"color":list(color)})
    actual_phone_color = cover_style["phone"] if role=="cover" else text_rules.get("phone_color", accent)
    postprocess_record = {"rules":postprocess_rules,"crop":{"mode":"unchanged" if interior_profile else "lanczos_cover_crop","anchor_y":anchor_y},"sources":[str(raw_path.resolve())],"phone":{"text":phone_text,"box":list(phone_box),"font_size":phone_font.size,"font_family":list(phone_font.getname()),"color":list(actual_phone_color),"stroke":phone_stroke,"background":text_rules.get("phone_background", cover_style["phone_fill"] if role=="cover" else [0,0,0,184])},"services":{"items":service_items,"boxes":[list(b) for b in service_boxes] if role=="cover" else [list(grid_box)],"rendered_items":actual_services,"font_sizes":[i["font_size"] for i in actual_services],"colors":[i["color"] for i in actual_services],"background":text_rules.get("service_background",list(bottom_service_style["background"]) if bottom_service_style else bottom_service_backing),"layout":cover_style["service_layout"] if role=="cover" else "detail_panel_grid","overrides":{k:v for k,v in text_rules.items() if k.startswith("service_")}}}
    if any(key.startswith("service_") for key in text_rules) or "font_family" in text_rules:
        postprocess_record["services"]["layout"] = str(text_rules.get("service_columns",5 if len(service_items)==10 else 4)) + " columns"
        postprocess_record["services"]["boxes"] = [i["box"] for i in actual_services]
    elif role == "detail":
        postprocess_record["services"]["background"] = [band[0],band[1],band[2],220]
    image = Image.alpha_composite(image, overlay).convert("RGB")
    _io_path(target.parent).mkdir(parents=True, exist_ok=True)
    temporary = _io_path(target.with_suffix(target.suffix + ".part"))
    image.save(temporary, format="PNG", optimize=True)
    temporary.replace(_io_path(target))
    validation = {
        "schema_version": PRODUCTION_SCHEMA_VERSION,
        "structure_version": structure_version or GROUP_STRUCTURE_VERSION,
        "status": "needs_user_review",
        "approved": False,
        "manual_visual_approval": False,
        "category_id": category_id,
        "group_index": group_index,
        "position": position,
        "delivery_position": position,
        "role": role,
        "generation_kind": role,
        "generation_mode": generation_mode or GENERATION_MODE,
        "service_role": service_role,
        "generation_target_id": generation_target_id,
        "delivery_target_id": delivery_target_id,
        "height_profile_id": height_profile_id,
        "final_size": f"{width}x{height}",
        "expected_size": f"{width}x{height}",
        "raw_api_size": (
            f"{source_image.width}x{source_image.height}"
            if interior_profile else f"{RAW_API_SIZE[0]}x{RAW_API_SIZE[1]}"
        ),
        "image_sha256": _file_sha256(target),
        "expected_text": expected,
        "postprocessed_locally": True,
        "postprocess_record": postprocess_record,
        "overlay_style": (
            {
                "version": 1 if interior_profile else cover_style_version(category_id, group_index),
                "name": cover_style["name"],
                "signboard_style": (
                    "not_applicable_interior"
                    if category_id == "ktv" or interior_profile else
                    "source_generated_physical_signboard_phone_no_local_overlay"
                    if category_id in MODEL_GENERATED_SIGNBOARD_CATEGORIES
                    else "direct_text_on_detected_physical_signboard"
                ),
                "signboard_detection": signboard_detection,
                "signboard_quad": signboard_quad,
                "typography_version": truck_plan["typography_version"] if truck_plan is not None else COVER_TYPOGRAPHY_VERSION,
                "phone_style": cover_style["typography"],
                "service_layout": cover_style["service_layout"],
                "bottom_service_backing": bottom_service_backing,
                "bottom_service_style": (
                    None
                    if bottom_service_style is None
                    else {
                        "style_id": bottom_service_style["style_id"],
                        "palette": bottom_service_style["name"],
                        "layout": bottom_service_style["layout"],
                        "accent": bottom_service_style["accent"],
                        "font_scale": bottom_service_style["font_scale"],
                        "version": bottom_service_style.get("version", 1),
                    }
                ),
            }
            if role == "cover"
            else {"version": 1, "name": "detail_panel_grid"}
        ),
        "note": (
            "文字由共享本地程序叠加；需实际视觉检查电话、八个服务词及遮挡，原图审核结果独立保留。"
            if interior_profile else "文字由本地程序叠加；仍需用户视觉确认真实门头、电话条、服务词、角色和构图。"
        ),
    }
    if interior_profile:
        validation["overlay_profile"] = overlay_profile
        validation["overlay_style"]["center_phone_region"] = phone_region
        validation["overlay_style"]["bottom_service_region"] = [0.045, 0.80, 0.955, 0.965]
    if role == "cover" and category_id in {"road_rescue", "home_appliance_repair"} and not interior_profile and group_index >= ROAD_RESCUE_COVER_V3_FIRST_GROUP:
        validation["overlay_style"]["center_phone_region"] = cover_center_phone_region(category_id, group_index)
        validation["overlay_style"]["bottom_service_region"] = road_rescue_bottom_service_region(group_index)
    if role == "cover" and truck_plan is not None:
        validation["overlay_style"].update(
            style_id=truck_plan["style_id"], family=truck_plan["family"],
            reference_supplement=truck_plan["reference_supplement"],
            center_phone_region=truck_plan["center_phone_region"],
            bottom_service_region=truck_plan["bottom_service_region"],
        )
    if role == "cover":
        validation["overlay_style"]["center_phone_region"] = list(phone_region)
        if preserve_signboard and not interior_profile and category_id != "ktv":validation["overlay_style"]["signboard_style"] = "preserved_source_signboard"
    atomic_json(target.with_suffix(".validation.json"), validation)
    return validation


def _triptych_lock(target: Path) -> threading.Lock:
    key = str(target.resolve()).lower()
    with _TRIPTYCH_LOCK_GUARD:
        lock = _TRIPTYCH_TARGET_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _TRIPTYCH_TARGET_LOCKS[key] = lock
        return lock


def _triptych_boxes(
    layout_id: str,
    width: int,
    content_height: int,
    gutter: int,
    category_id: str = DEFAULT_CATEGORY_ID,
    panels: list | None = None,
) -> list[tuple[int, int, int, int]]:
    layout = _layout_config_map(category_id=category_id).get(layout_id)
    if layout is None:
        raise CategoryPromptError(f"不支持的三拼布局：{layout_id}")
    boxes: list[tuple[int, int, int, int]] = []
    inset = max(1, gutter // 2)
    for panel in panels if panels is not None else layout["panels"]:
        left = round(float(panel["x"]) * width) + inset
        top = round(float(panel["y"]) * content_height) + inset
        right = round((float(panel["x"]) + float(panel["width"])) * width) - inset
        bottom = round((float(panel["y"]) + float(panel["height"])) * content_height) - inset
        left = max(0, min(width - 1, left))
        top = max(0, min(content_height - 1, top))
        right = max(left + 1, min(width, right))
        bottom = max(top + 1, min(content_height, bottom))
        boxes.append((left, top, right, bottom))
    return boxes


def compose_triptych(
    panel_records: list[dict[str, Any]],
    target: Path,
    phone: str,
    service_items: list[str],
    *, postprocess_rules: dict | None = None,
) -> dict[str, Any]:
    from PIL import Image, ImageDraw
    from tools.postprocess_rules import parameters
    pp = parameters(postprocess_rules)
    tr = pp.get("triptych", {})
    from tools import project_inventory

    records = sorted(panel_records, key=lambda item: int(item["panel_index"]))
    if len(records) != 3 or [int(item["panel_index"]) for item in records] != [1, 2, 3]:
        raise CategoryPromptError("三拼成品必须提供 panel_index 1、2、3 的三个面板")
    if any(_generation_kind(record) != "triptych_panel" for record in records):
        raise CategoryPromptError("三拼成品混入了非 triptych_panel 记录")
    raw_paths = [Path(record["raw_target"]) for record in records]
    if not all(valid_png(path, RAW_API_SIZE) for path in raw_paths):
        raise RuntimeError("三拼图的三个 1024x1536 原图尚未全部就绪")
    panel_fingerprints = [
        {
            "generation_target_id": str(record["generation_target_id"]),
            "panel_index": int(record["panel_index"]),
            "service_role": str(record["service_role"]),
            # Use the same scene bands as a normal work-detail image so a
            # panel can be compared with both other panels and standalone
            # details after local cropping/overlays.
            "fingerprint": project_inventory.image_fingerprint(
                raw_path, "detail"
            ),
        }
        for record, raw_path in zip(records, raw_paths)
    ]
    final_sizes = {_record_final_size(record) for record in records}
    layout_ids = {str(record.get("triptych_layout_id") or "") for record in records}
    if len(final_sizes) != 1 or len(layout_ids) != 1:
        raise CategoryPromptError("三拼面板的 final_size 或 triptych_layout_id 不一致")
    final_size = parse_size(next(iter(final_sizes)))
    layout_id = next(iter(layout_ids))
    category_ids = {str(record.get("category_id") or DEFAULT_CATEGORY_ID) for record in records}
    if len(category_ids) != 1:
        raise CategoryPromptError("triptych panels must belong to one category")
    category_id = next(iter(category_ids))
    delivery = {
        "category_id": category_id,
        "delivery_kind": "triptych",
        "final_size": next(iter(final_sizes)),
        "triptych_layout_id": layout_id,
        "records": records,
    }
    recipe = _triptych_recipe(delivery)
    for key in ("content_height_ratio", "gutter_px"):
        if key in tr: recipe[key] = tr[key]
    if "panels" in tr: recipe["layout_panels"] = tr["panels"]
    structural = bool(postprocess_rules and postprocess_rules.get('template'))
    if structural:
        # Structural templates place all text over the photograph. The old
        # 18% footer is only for the legacy labels/phone/services renderer.
        recipe['content_height_ratio'] = 1.0
        recipe['overlay'] = 'triptych_structural_full_canvas_v1'
    target_lock = _triptych_lock(target)
    with target_lock:
        width, height = final_size
        content_height = int(height * float(recipe["content_height_ratio"]))
        gutter = int(recipe["gutter_px"])
        boxes = _triptych_boxes(layout_id, width, content_height, gutter, category_id, tr.get("panels"))
        canvas = Image.new("RGB", final_size, (25, 25, 25))
        for record, raw_path, box in zip(records, raw_paths, boxes):
            with Image.open(_io_path(raw_path)) as source:
                source.load()
                panel = _fit_image(
                    source.convert("RGB"),
                    (box[2] - box[0], box[3] - box[1]),
                    anchor_y=pp.get("crop",{}).get("panel_anchor_y", TRIPTYCH_PANEL_ANCHOR_Y),
                )
            canvas.paste(panel, (box[0], box[1]))

        if structural:
            from tools.graphic_templates import render_delivery
            return render_delivery(canvas,target,phone,service_items,postprocess_rules,'triptych',category_id,raw_paths,{'group_index':int(records[0]['group_index']),'position':2,'triptych_recipe':recipe,'sources':[str(p) for p in raw_paths],'panels':[list(b) for b in boxes],'panel_service_roles':[r['service_role'] for r in records],'structure_version':records[0].get('structure_version'),'generation_mode':records[0].get('generation_mode')})
        overlay = Image.new("RGBA", final_size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        palettes = [
            ((10, 67, 92, 218), (52, 231, 240, 255)),
            ((118, 42, 27, 218), (255, 211, 67, 255)),
            ((25, 92, 58, 218), (148, 238, 119, 255)),
        ]
        expected = [f"{TRIPTYCH_PHONE_PREFIX}{phone}"]
        for index, (record, box) in enumerate(zip(records, boxes)):
            label = str(record["service_role"])
            expected.append(label)
            band, accent = palettes[index]
            label_box = (
                box[0] + gutter,
                box[1] + gutter,
                min(box[2] - gutter, box[0] + int((box[2] - box[0]) * 0.82)),
                box[1] + max(42, int(width * 0.063)),
            )
            draw.rectangle(label_box, fill=band, outline=accent, width=max(1, width // 420))
            label_font = _fit_font(
                draw,
                label,
                max(50, label_box[2] - label_box[0] - gutter * 2),
                int(width * 0.034),
                min_size=14,
                stroke=max(1, width // 600),
            )
            _centered_text(
                draw,
                label_box,
                label,
                label_font,
                (255, 255, 255, 255),
                max(1, width // 600),
                (0, 0, 0, 210),
            )

        footer_top = content_height
        if tr.get("phone_background", [8,25,35,238]) is not None:
            draw.rectangle((0, footer_top, width, height), fill=tuple(tr.get("phone_background", [8,25,35,238])))
        phone_box = (0, footer_top, width, footer_top + int((height - footer_top) * 0.46))
        phone_text = f"{TRIPTYCH_PHONE_PREFIX}{phone}"
        phone_font = _fit_font(
            draw,
            phone_text,
            int(width * 0.92),
            int(width * tr.get("phone_font_ratio", .068)),
            stroke=tr.get("phone_stroke",max(3, width // 230)), family=tr.get("font_family"),
        )
        _centered_text(
            draw,
            phone_box,
            phone_text,
            phone_font,
            tuple(tr.get("phone_color", [43,234,239,255])),
            tr.get("phone_stroke", max(3, width // 230)),
            (0, 0, 0, 255),
        )
        split_at = 5 if len(service_items) == 10 else 4
        services = (
            TRIPTYCH_SERVICE_SEPARATOR.join(service_items[:split_at])
            + "\n"
            + TRIPTYCH_SERVICE_SEPARATOR.join(service_items[split_at:])
        )
        service_box = (int(width * 0.035), phone_box[3], int(width * 0.965), height)
        service_font = _fit_font(
            draw,
            " · ".join(service_items[:4]),
            service_box[2] - service_box[0],
            int(width * tr.get("service_font_ratio", .027)),
            min_size=13,
            stroke=max(1, width // 650), family=tr.get("font_family"),
        )
        line_height = (service_box[3] - service_box[1]) // 2
        for row, line in enumerate(services.splitlines()):
            row_box = (
                service_box[0],
                service_box[1] + line_height * row,
                service_box[2],
                service_box[1] + line_height * (row + 1),
            )
            _centered_text(
                draw,
                row_box,
                line,
                service_font,
                tuple(tr.get("service_color", [245,245,245,255])),
                max(1, width // 650),
                (0, 0, 0, 220),
            )
        expected.extend(service_items)
        image = Image.alpha_composite(canvas.convert("RGBA"), overlay).convert("RGB")
        _io_path(target.parent).mkdir(parents=True, exist_ok=True)
        temporary = _io_path(target.with_suffix(target.suffix + ".part"))
        image.save(temporary, format="PNG", optimize=True)
        temporary.replace(_io_path(target))
        if not valid_png(target, final_size):
            raise RuntimeError("本地三拼成品未通过 PNG 完整性与尺寸检查")
        validation = {
            "schema_version": PRODUCTION_SCHEMA_VERSION,
            "structure_version": str(records[0].get("structure_version") or GROUP_STRUCTURE_VERSION),
            "status": "needs_user_review",
            "approved": False,
            "manual_visual_approval": False,
            "category_id": category_id,
            "group_index": int(records[0]["group_index"]),
            "position": 2,
            "delivery_position": 2,
            "role": "triptych",
            "generation_kind": "triptych",
            "generation_mode": str(records[0].get("generation_mode") or GENERATION_MODE),
            "delivery_target_id": str(records[0]["delivery_target_id"]),
            "panel_generation_target_ids": [
                str(record["generation_target_id"]) for record in records
            ],
            "panel_source_indices": [int(record["index"]) for record in records],
            "panel_service_roles": [str(record["service_role"]) for record in records],
            "panel_fingerprints": panel_fingerprints,
            "height_profile_id": records[0].get("height_profile_id"),
            "final_size": f"{width}x{height}",
            "expected_size": f"{width}x{height}",
            "raw_api_size": f"{RAW_API_SIZE[0]}x{RAW_API_SIZE[1]}",
            "image_sha256": _file_sha256(target),
            "triptych_recipe": recipe,
            "postprocess_record": {"rules":postprocess_rules,"sources":[str(p.resolve()) for p in raw_paths],"crop":{"mode":"center_fill_per_cell","anchor_y":pp.get("crop",{}).get("panel_anchor_y", TRIPTYCH_PANEL_ANCHOR_Y)},"panels":[list(b) for b in boxes],"phone":{"text":phone_text,"box":list(phone_box),"font_size":phone_font.size,"font_family":list(phone_font.getname()),"color":tr.get("phone_color",[43,234,239,255]),"stroke":tr.get("phone_stroke",max(3,width//230)),"background":tr.get("phone_background",[8,25,35,238])},"services":{"items":service_items,"font_size":service_font.size,"box":list(service_box),"color":tr.get("service_color",[245,245,245,255])}},
            "expected_text": expected,
            "postprocessed_locally": True,
            "overlay_style": {
                "version": 1,
                "name": "triptych_labels_phone_footer",
                "layout_id": layout_id,
            },
            "note": "三张独立实景原图由本地程序裁切合成并叠字；仍需用户视觉确认场景、电话、服务词和三拼构图。",
        }
        atomic_json(target.with_suffix(".validation.json"), validation)
        return validation


def _relay_normalization_rejection(
    source_size: tuple[int, int],
    expected_size: tuple[int, int],
) -> str | None:
    source_width, source_height = source_size
    expected_width, expected_height = expected_size
    if expected_size != RAW_API_SIZE:
        return "expected size is outside the relay normalization contract"
    if source_width >= source_height:
        return "relay response is not a portrait image"
    if source_width < round(expected_width * 0.75) or source_height < round(expected_height * 0.85):
        return "relay response is too small for controlled normalization"
    aspect_ratio = source_width / source_height
    if not 0.50 <= aspect_ratio <= 0.75:
        return f"relay response aspect ratio {aspect_ratio:.4f} is outside 0.50-0.75"
    pixel_ratio = (source_width * source_height) / (expected_width * expected_height)
    if not 0.85 <= pixel_ratio <= 1.25:
        return f"relay response pixel ratio {pixel_ratio:.4f} is outside 0.85-1.25"
    return None


def _archive_provider_payload(
    archive_root: Path,
    raw_target: Path,
    payload: bytes,
    source_format: str | None,
    source_size: tuple[int, int],
) -> Path:
    suffix = {
        "PNG": ".png",
        "JPEG": ".jpg",
        "WEBP": ".webp",
    }.get(str(source_format or "").upper(), ".bin")
    source_sha256 = hashlib.sha256(payload).hexdigest()
    group_dir = archive_root / raw_target.parent.name
    _io_path(group_dir).mkdir(parents=True, exist_ok=True)
    archive_path = group_dir / (
        f"{raw_target.stem}__source_{source_size[0]}x{source_size[1]}__{source_sha256[:12]}{suffix}"
    )
    if _io_path(archive_path).is_file():
        if _file_sha256(archive_path) != source_sha256:
            raise RuntimeError(f"provider response archive collision: {archive_path}")
        return archive_path
    temporary = _io_path(archive_path.with_suffix(archive_path.suffix + ".part"))
    temporary.write_bytes(payload)
    temporary.replace(_io_path(archive_path))
    return archive_path


def save_raw_png(
    path: Path,
    payload: bytes,
    expected_size: tuple[int, int],
    *,
    provider: str | None = None,
    archive_root: Path | None = None,
    anchor_y: float = 0.5,
) -> dict[str, Any]:
    from PIL import Image

    if not 0.0 <= anchor_y <= 1.0:
        raise ValueError("anchor_y must be between 0 and 1")
    source_sha256 = hashlib.sha256(payload).hexdigest()
    with Image.open(io.BytesIO(payload)) as source:
        source.load()
        source_size = source.size
        source_format = source.format
        image = source.convert("RGB")
    result: dict[str, Any] = {
        "source_returned_size": f"{source_size[0]}x{source_size[1]}",
        "source_format": source_format,
        "source_sha256": source_sha256,
        "normalized": False,
        "normalization_mode": "none",
        "normalized_to": f"{expected_size[0]}x{expected_size[1]}",
    }
    if source_size != expected_size:
        if provider != "relay":
            raise RawImageContractError(
                f"API 返回尺寸 {source_size[0]}x{source_size[1]}，预期 {expected_size[0]}x{expected_size[1]}"
            )
        if archive_root is None:
            raise RawImageContractError("中转返回非标准尺寸，但未配置原始响应归档目录")
        archive_path = _archive_provider_payload(
            archive_root,
            path,
            payload,
            source_format,
            source_size,
        )
        sidecar_path = archive_path.with_name(archive_path.name + ".json")
        result.update({
            "provider_original": str(archive_path),
            "provider_original_metadata": str(sidecar_path),
            "normalization_anchor_y": anchor_y,
        })
        rejection = _relay_normalization_rejection(source_size, expected_size)
        if rejection is not None:
            result.update({"archive_status": "rejected", "rejection_reason": rejection})
            atomic_json(sidecar_path, result)
            raise RawImageContractError(
                f"中转返回尺寸 {source_size[0]}x{source_size[1]} 无法安全归一化：{rejection}",
                evidence=result,
            )
        image = _fit_image(image, expected_size, anchor_y=anchor_y)
        result.update({
            "normalized": True,
            "normalization_mode": "lanczos_cover_crop",
            "archive_status": "normalized",
        })
    _io_path(path.parent).mkdir(parents=True, exist_ok=True)
    temporary = _io_path(path.with_suffix(path.suffix + ".part"))
    image.save(temporary, format="PNG", optimize=True)
    temporary.replace(_io_path(path))
    if not valid_png(path, expected_size):
        raise RuntimeError("API 返回图片无法通过 PNG 完整性检查")
    result["saved_raw_sha256"] = _file_sha256(path)
    if result.get("provider_original_metadata"):
        atomic_json(Path(str(result["provider_original_metadata"])), result)
    return result


def append_event(path: Path, payload: dict[str, Any], lock: threading.Lock) -> None:
    with lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps({"at": now_iso(), **payload}, ensure_ascii=False) + "\n")


def reserve_request(current: int, budget: int) -> int:
    if current >= budget:
        raise RuntimeError("已达到一次性许可证请求预算，禁止继续调用图片 API")
    return current + 1


def image_download_context(batch: Path, job_id: str, license_data: dict[str, Any],
                           target_id: str, request_number: int, attempt: int,
                           config: dict[str, Any], prompt: str) -> dict[str, Any]:
    """Bind a single paid response to its private, GET-only recovery receipt."""
    return {
        "root": str(ROOT / ".runtime" / "image_download_receipts"),
        "job_id": job_id, "license_id": str(license_data["license_id"]),
        "generation_target_id": target_id, "request_number": request_number,
        "attempt": attempt, "model": config["model"], "quality": config["quality"],
        "api_size": config["api_size"],
        "effective_prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "original_plan_sha256": license_data["plan_sha256"],
    }


def classify_request_error(error: Exception) -> str | None:
    """Classify only failures that are safe for one bounded paid retry."""

    metadata = image_generate.safe_stage_metadata(error)
    if isinstance(error, getattr(image_generate, "ReturnedImageDownloadError", ())):
        if getattr(error, "error_stage", None) == "preflight":
            return "transient"
        return "image_download_failed"
    if (metadata.get("response_kind") == "url" and metadata.get("error_stage")
            in {"image_download_open", "image_download_read"}):
        return "image_download_failed"
    message = str(error).lower()
    code = str(getattr(error, "code", "") or "").lower()
    status_code = getattr(error, "status_code", None)
    is_http_403 = str(status_code or "") == "403" or bool(
        re.search(r"\berror code:\s*403\b", message)
    )
    is_relay_billing_balance = (
        is_http_403
        and ("billing_error" in message or code == "billing_error")
        and "insufficient balance" in message
    )
    if (
        "insufficient_balance" in message
        or code == "insufficient_balance"
        or is_relay_billing_balance
    ):
        return "balance_exhausted"
    content_policy_markers = (
        "content_policy_violation",
        "content policy",
        "安全政策",
        "无法用于生成图像",
        "不适合进行图像生成",
    )
    if any(marker in message for marker in content_policy_markers):
        return "content_policy"
    if code in {"content_policy_violation", "safety_violation"}:
        return "content_policy"
    if status_code in {408, 409, 429, 500, 502, 503, 504}:
        return "transient"
    transient_markers = (
        "connection error",
        "connection reset",
        "connection aborted",
        "timed out",
        "timeout",
        "rate limit",
        "too many requests",
        "internal_server_error",
        "server error",
        "bad gateway",
        "service unavailable",
        "gateway timeout",
    )
    if any(marker in message for marker in transient_markers):
        return "transient"
    return None


def safe_request_error_summary(error: Exception, error_kind: str | None = None) -> str:
    """Keep diagnostic categories only, never provider bodies or exception text."""

    error_type = type(error).__name__
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,79}", error_type) is None:
        error_type = "Exception"
    safe_kind = error_kind if error_kind in {
        "transient", "content_policy", "balance_exhausted", "raw_contract_rejected", "image_download_failed",
    } else "non_retryable"
    parts = [f"error_type={error_type}", f"error_kind={safe_kind}"]
    status = getattr(error, "status_code", None)
    if type(status) is int and 100 <= status <= 599:
        parts.append(f"http_status={status}")
    elif isinstance(status, str) and re.fullmatch(r"[1-5][0-9]{2}", status):
        parts.append(f"http_status={status}")
    stage_metadata = image_generate.safe_stage_metadata(error)
    if stage_metadata.get("error_stage"):
        parts.append(f"error_stage={stage_metadata['error_stage']}")
    if stage_metadata.get("response_kind"):
        parts.append(f"response_kind={stage_metadata['response_kind']}")
    if "elapsed_seconds" in stage_metadata:
        parts.append(f"elapsed_seconds={stage_metadata['elapsed_seconds']}")
    return "; ".join(parts)


def content_policy_retry_prompt(prompt: str) -> str:
    """Use positive, operational wording without changing the service scene."""

    replacements = {
        "无抽象人物、塑料皮肤、蜡像感、畸形脸、畸形手指": "人物五官、皮肤和手部结构自然真实",
        "无血腥画面、危险站位和违规占道": "现场平稳有序，人员遵守道路和作业安全规范",
        "不要让人物像网红、明星脸、广告模特或假人；避免抽象人形、蜡像脸、畸形手和不自然站姿": (
            "人物保持普通从业者外观、自然工作姿态和真实手部结构"
        ),
    }
    prepared = prompt
    for source, replacement in replacements.items():
        prepared = prepared.replace(source, replacement)
    return (
        prepared.rstrip()
        + "\n\n内容安全重试说明：这是合法合规、平静有序的日常本地生活服务工作记录。"
        "保持原有服务项目、场景主体、工具设备、操作关系、环境和手机纪实风格不变；"
        "只表现规范服务过程，不表现人员冲突、伤害后果或不安全行为。"
    )


def truck_content_policy_retry_prompt(record: dict[str, Any]) -> str:
    """Build a short Chinese-only positive retry for one truck detail unit."""

    role = str(record.get("service_role") or "").strip()
    if role not in TRUCK_CONTENT_POLICY_SAFE_V2_ACTIONS:
        raise CategoryPromptError(f"货车详情安全重试缺少有效 service_role：{role or '<empty>'}")
    scene = record.get("scene")
    if not isinstance(scene, dict):
        raise CategoryPromptError(f"货车详情安全重试缺少场景数据：{role}")
    scene_values: dict[str, str] = {}
    for field in ("vehicle", "location", "action", "tools"):
        value = str(scene.get(field) or "").strip()
        if not value:
            raise CategoryPromptError(f"货车详情安全重试缺少 {field}：{role}")
        scene_values[field] = value
    action = scene_values["action"]
    if any(
        marker in action
        for marker in TRUCK_CONTENT_POLICY_SAFE_V2_NEGATIVE_MARKERS
    ):
        action = TRUCK_CONTENT_POLICY_SAFE_V2_ACTIONS[role]
    generation_kind = str(record.get("generation_kind") or "").strip()
    if generation_kind == "triptych_panel":
        layout = (
            "本图作为三拼图的一个独立面板，主体置于中央，四周保留可裁切背景，"
            "关键操作完整清楚。"
        )
    elif generation_kind == "detail":
        layout = (
            "顶部、画面中部横向区域和底部保留简洁背景，供本地添加服务标签、电话和服务词，"
            "关键操作完整清楚。"
        )
    else:
        raise CategoryPromptError(
            f"货车详情安全重试不支持 generation_kind：{generation_kind or '<empty>'}"
        )
    prepared = (
        "真实中国货车救援维修现场，普通手机纪实照片。"
        f"服务项目为{role}。车辆为{scene_values['vehicle']}，作业地点为{scene_values['location']}。"
        f"{action}现场使用{scene_values['tools']}。"
        "工作人员姿态自然，车辆、工具与操作关系清楚，画面保留真实工作痕迹。"
        f"{layout}"
    )
    if any(
        term in prepared for term in TRUCK_CONTENT_POLICY_SAFE_V2_FORBIDDEN_TERMS
    ):
        raise CategoryPromptError(f"货车详情安全重试包含禁用措辞：{role}")
    if any(
        marker in prepared
        for marker in TRUCK_CONTENT_POLICY_SAFE_V2_NEGATIVE_MARKERS
    ):
        raise CategoryPromptError(f"货车详情安全重试包含负向措辞：{role}")
    if re.search(r"[A-Za-z]{2,}", prepared):
        raise CategoryPromptError(f"货车详情安全重试包含长英文：{role}")
    return prepared


def content_policy_retry_for_record(
    record: dict[str, Any], prompt: str
) -> tuple[str, str]:
    """Select the scoped safe prompt version without mutating source manifests."""

    category_id = str(
        record.get("category_id") or record.get("project_id") or ""
    ).strip()
    generation_kind = str(record.get("generation_kind") or "").strip()
    if category_id == "truck_rescue" and generation_kind in {
        "triptych_panel",
        "detail",
    }:
        return (
            truck_content_policy_retry_prompt(record),
            "content_policy_safe_v2_truck",
        )
    return content_policy_retry_prompt(prompt), "content_policy_safe_v1"


def _materialize_delivery(
    delivery: dict[str, Any],
    phone: str,
    service_items: list[str],
    *,
    allow_rejected_replacement: bool = False,
) -> bool:
    target = Path(delivery["target"])
    final_size = parse_size(str(delivery["final_size"]))
    if reusable_target(target, final_size):
        return True
    if (
        not allow_rejected_replacement
        and target_review_status(target) in {"needs_fix", "rejected"}
    ):
        return False
    records = list(delivery["records"])
    if delivery["delivery_kind"] == "triptych":
        if not all(valid_png(Path(record["raw_target"]), RAW_API_SIZE) for record in records):
            return False
        compose_triptych(records, target, phone, service_items)
        return reusable_target(target, final_size)
    if len(records) != 1:
        raise RuntimeError("非三拼成品只能绑定一个生成单元")
    record = records[0]
    raw_target = Path(record["raw_target"])
    if not valid_png(raw_target, RAW_API_SIZE):
        return False
    apply_overlays(
        raw_target,
        target,
        phone,
        str(record["generation_kind"]),
        int(record["group_index"]),
        int(record["delivery_position"]),
        list(record.get("service_items") or service_items),
        str(record["final_size"]),
        service_role=record.get("service_role"),
        height_profile_id=record.get("height_profile_id"),
        generation_target_id=str(record["generation_target_id"]),
        delivery_target_id=str(record["delivery_target_id"]),
        category_id=str(record.get("category_id") or delivery.get("category_id") or DEFAULT_CATEGORY_ID),
        structure_version=str(record.get("structure_version") or delivery.get("structure_version") or GROUP_STRUCTURE_VERSION),
        generation_mode=str(record.get("generation_mode") or delivery.get("generation_mode") or GENERATION_MODE),
    )
    return reusable_target(target, final_size)


def recover_local_deliveries(
    run_plan: dict[str, Any],
    phone: str,
    *,
    allow_rejected_replacement: bool = False,
) -> int:
    completed = 0
    for delivery in run_plan["delivery_records"]:
        if _materialize_delivery(
            delivery,
            phone,
            run_plan["service_items"],
            allow_rejected_replacement=allow_rejected_replacement,
        ):
            completed += 1
    return completed


def prepare_cover_regeneration(
    category_id: str,
    batch_dir: Path,
    group_start: int,
    group_count: int,
    phone: str,
    config: dict[str, Any],
    output_root: Path,
    reason: str,
) -> dict[str, Any]:
    """Archive rejected cover evidence before a new paid generation attempt."""
    rejection_reason = reason.strip()
    if not rejection_reason:
        raise ValueError("重新生图前必须记录用户拒绝原因")
    run_plan = plan(
        category_id,
        batch_dir,
        group_start,
        group_count,
        phone,
        config,
        scope="covers",
        output_root=output_root,
    )
    deliveries = list(run_plan["delivery_records"])
    if len(deliveries) != group_count or any(
        delivery.get("delivery_kind") != "cover" for delivery in deliveries
    ):
        raise RuntimeError("重新生图准备范围必须只包含每组一张首图")

    prepared: list[dict[str, Any]] = []
    for delivery in deliveries:
        target = Path(delivery["target"])
        validation_path = target.with_suffix(".validation.json")
        if not target.is_file() or not validation_path.is_file():
            raise RuntimeError(f"缺少待归档首图或验收文件：{target}")
        old_validation = load_json(validation_path)
        if old_validation.get("approved") is True or old_validation.get("status") == "approved":
            raise RuntimeError(f"已人工批准的首图不能直接标记重做：{target}")
        if old_validation.get("status") in {"needs_fix", "rejected"}:
            raise RuntimeError(f"首图已经处于待修复或拒绝状态：{target}")
        records = list(delivery["records"])
        if len(records) != 1:
            raise RuntimeError(f"首图成品必须绑定一个原图：{target}")
        raw_target = Path(records[0]["raw_target"])
        if not valid_png(raw_target, RAW_API_SIZE):
            raise RuntimeError(f"旧付费原图缺失或损坏，不能安全准备重新生图：{raw_target}")
        prepared.append({
            "group_index": int(delivery["group_index"]),
            "target": target,
            "validation_path": validation_path,
            "raw_target": raw_target,
            "old_validation": old_validation,
        })

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    archive_root = production_dir(batch_dir) / "rejected_generations" / timestamp
    results: list[dict[str, Any]] = []
    for item in prepared:
        archive_group = archive_root / f"group_{item['group_index']:04d}"
        archive_group.mkdir(parents=True, exist_ok=True)
        archived_image = archive_group / item["target"].name
        archived_validation = archive_group / item["validation_path"].name
        archived_raw = archive_group / f"paid_raw_{item['raw_target'].name}"
        shutil.copy2(item["target"], archived_image)
        shutil.copy2(item["validation_path"], archived_validation)
        shutil.copy2(item["raw_target"], archived_raw)
        results.append({
            "group_index": item["group_index"],
            "current_image": str(item["target"]),
            "current_validation": str(item["validation_path"]),
            "current_raw": str(item["raw_target"]),
            "archived_image": str(archived_image),
            "archived_validation": str(archived_validation),
            "archived_raw": str(archived_raw),
            "image_sha256": _file_sha256(item["target"]),
            "validation_sha256": _file_sha256(item["validation_path"]),
            "raw_sha256": _file_sha256(item["raw_target"]),
        })

    created_at = now_iso()
    for item, result in zip(prepared, results):
        rejected_validation = dict(item["old_validation"])
        rejected_validation.update({
            "status": "rejected",
            "approved": False,
            "manual_visual_approval": False,
            "user_rejected": True,
            "replacement_required": True,
            "rejected_at": created_at,
            "rejection_reason": rejection_reason,
            "replacement_archive": {
                "image": result["archived_image"],
                "validation": result["archived_validation"],
                "raw": result["archived_raw"],
            },
        })
        atomic_json(item["validation_path"], rejected_validation)

    manifest = {
        "schema_version": 1,
        "category_id": category_id,
        "operation": "prepare_paid_cover_regeneration",
        "api_called": False,
        "paid_requests": 0,
        "reason": rejection_reason,
        "created_at": created_at,
        "archive_root": str(archive_root),
        "results": results,
    }
    atomic_json(archive_root / "regeneration_manifest.json", manifest)
    return manifest


def _require_detail_regeneration_idle(
    batch_dir: Path, group_index: int, owned_lock: dict[str, Any] | None = None,
) -> None:
    """Inspect only production metadata; never remove a stale lock or resume work."""
    root = production_dir(batch_dir)
    lock = root / "generation.lock"
    if lock.exists() and (owned_lock is None or load_json(lock) != owned_lock):
        raise RuntimeError("详情替换准备要求不存在 generation.lock；请先检查现有任务")
    terminal = {
        "completed", "completed_with_errors", "awaiting_review", "failed",
        "launch_failed", "failed_before_start_stale", "cancelled", "canceled",
        "paused_api_errors", "paused_probe_failed", "paused_balance_exhausted",
    }
    running = {
        "queued", "starting", "running", "waiting_for_api",
        "resume_running", "resume_waiting_for_api",
    }
    sources = [(root / "jobs", False), (root / "resume_sessions", False),
               (root / "licenses", True), (root / "resume_authorizations", True)]
    metadata = [(path, authorization) for directory, authorization in sources
                for path in directory.glob("*.json") if directory.is_dir()]
    metadata.extend((path, True) for path in root.glob("authorization_groups_*.json"))
    for path, authorization in metadata:
        if path.stat().st_size > 2_000_000:
            raise RuntimeError(f"生产元数据过大，不能安全判断空闲状态：{path}")
        payload = load_json(path)
        if not isinstance(payload, dict):
            raise RuntimeError(f"生产元数据无法识别：{path}")
        status = str(payload.get("status") or "")
        if authorization:
            if status not in {"consumed", "expired", "revoked", "cancelled", "canceled"}:
                raise RuntimeError(f"存在活动或未知状态的生产授权：{path}")
            continue
        if status in terminal:
            continue
        pids = [payload[key] for key in ("pid", "worker_pid", "launcher_pid")
                if payload.get(key) is not None]
        if any(type(pid) is int and pid > 0 and pid_is_running(pid) for pid in pids):
            raise RuntimeError(f"存在仍存活的生产任务进程：{path}")
        # Running workers share a batch-wide lock. Other unfinished historical
        # ranges do not own the image being replaced, but unknown ranges fail shut.
        first, count = payload.get("group_start"), payload.get("group_count")
        disjoint = (type(first) is int and first > 0 and type(count) is int and count > 0
                    and not first <= group_index < first + count)
        if (status in running and path.parent == root / "resume_sessions"
                and pids and all(type(pid) is int and pid > 0 for pid in pids)
                and (disjoint or (first is None and count is None))):
            # Older resume workers left "running" snapshots behind after the
            # original job finished. Ignore only a proven dead, unrelated run;
            # never rewrite its historical session or treat a dead PID alone as proof.
            job_id = str(payload.get("job_id") or "")
            if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", job_id):
                original_path = (root / "jobs" / f"{job_id}.json").resolve()
                if (original_path.parent == (root / "jobs").resolve()
                        and original_path.is_file() and original_path.stat().st_size <= 2_000_000):
                    original = load_json(original_path)
                    original_first = original.get("group_start")
                    original_count = original.get("group_count")
                    original_disjoint = (
                        type(original_first) is int and original_first > 0
                        and type(original_count) is int and original_count > 0
                        and not original_first <= group_index < original_first + original_count
                    )
                    if (original.get("job_id") == job_id and original.get("status") in terminal
                            and original_disjoint):
                        continue
        if status in running or not disjoint:
            raise RuntimeError(f"存在未结束或未知状态的生产任务：{path}")


def prepare_detail_regeneration(
    category_id: str,
    batch_dir: Path,
    group_start: int,
    group_count: int,
    phone: str,
    config: dict[str, Any],
    output_root: Path,
    reason: str,
    generation_target_id: str,
) -> dict[str, Any]:
    """Preserve one standalone detail and raw before marking it for paid replacement."""
    rejection_reason = str(reason).strip()
    target_id = str(generation_target_id or "").strip()
    if not rejection_reason or len(rejection_reason) > 2000:
        raise ValueError("详情重新生图前必须记录拒绝原因（最多2000字）")
    if (type(group_start) is not int or group_start < 1
            or type(group_count) is not int or group_count != 1 or not target_id):
        raise ValueError("详情替换必须指定一个组和一个独立详情 generation_target_id")
    phone = normalize_contact_number(phone)
    batch_dir = safe_batch_dir(category_id, batch_dir)
    output_root = safe_output_root(category_id, output_root)
    _require_detail_regeneration_idle(batch_dir, group_start)
    run_plan = plan(category_id, batch_dir, group_start, 1, phone, config,
                    scope="details", output_root=output_root,
                    generation_target_id=target_id)
    deliveries = list(run_plan["delivery_records"])
    if len(deliveries) != 1 or deliveries[0].get("delivery_kind") != "detail":
        raise RuntimeError("详情替换只允许一个独立详情，不允许首图或三拼组件")
    delivery = deliveries[0]
    records = list(delivery["records"])
    if len(records) != 1 or records[0].get("generation_kind") != "detail":
        raise RuntimeError("独立详情必须只绑定一个生成单元")
    record = records[0]
    delivery_id = str(delivery["delivery_target_id"])
    if (record.get("generation_target_id") != target_id
            or record.get("delivery_target_id") != delivery_id
            or record.get("group_index") != group_start
            or delivery.get("group_index") != group_start
            or not re.fullmatch(rf"{re.escape(category_id)}:v\d+:g{group_start:04d}:u\d{{2}}", target_id)):
        raise RuntimeError("详情生成目标、交付目标或组号绑定不一致")
    target = Path(delivery["target"]).resolve()
    expected_target = (output_root / f"group_{group_start:04d}" /
                       output_filename(int(delivery["delivery_position"]), "detail")).resolve()
    raw_target = Path(record["raw_target"]).resolve()
    if (target != expected_target or target.parent.parent != output_root
            or Path(record["target"]).resolve() != target
            or raw_target.parent != (batch_dir / "raw" / f"group_{group_start:04d}").resolve()
            or raw_target.parent.parent.parent != batch_dir
            or raw_target.suffix.lower() != ".png"):
        raise RuntimeError("详情成品或付费原图不在绑定的固定组目录")
    validation_path = target.with_suffix(".validation.json")
    if validation_path.resolve().parent != target.parent:
        raise RuntimeError("详情验收文件不能通过链接越出固定组目录")
    final_size = parse_size(str(delivery["final_size"]))
    if (not valid_png(target, final_size) or not valid_png(raw_target, RAW_API_SIZE)
            or not validation_path.is_file()):
        raise RuntimeError("详情成品、付费原图或验收文件缺失/损坏")
    previous = load_json(validation_path)
    if (previous.get("approved") is True or previous.get("manual_visual_approval") is True
            or previous.get("status") != "needs_user_review"):
        raise RuntimeError("详情已批准、已待修复/拒绝或状态未知，不能直接准备替换")
    expected_identity = {"category_id": category_id, "group_index": group_start,
                         "generation_target_id": target_id, "delivery_target_id": delivery_id,
                         "generation_kind": "detail", "role": "detail",
                         "delivery_position": delivery["delivery_position"],
                         "final_size": delivery["final_size"]}
    if any(previous.get(key) != value for key, value in expected_identity.items()):
        raise RuntimeError("详情验收记录的类别、组号、目标或尺寸不匹配")
    expected_text = previous.get("expected_text")
    if (not isinstance(expected_text, list) or f"电话：{phone}" not in expected_text
            or set(extract_contact_numbers(" ".join(map(str, expected_text)))) != {phone}
            or previous.get("postprocessed_locally") is not True):
        raise RuntimeError("详情验收记录的确认号码或本地叠字证据不匹配")
    sources = {"image": target, "validation": validation_path, "raw": raw_target}
    digests = {name: _file_sha256(path) for name, path in sources.items()}
    if previous.get("image_sha256") != digests["image"]:
        raise RuntimeError("详情图片 SHA-256 与验收记录不符")
    if load_json(validation_path) != previous:
        raise RuntimeError("详情验收文件在检查期间已变化")
    _require_detail_regeneration_idle(batch_dir, group_start)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    root = production_dir(batch_dir)
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / "generation.lock"
    lock_token = {"pid": os.getpid(), "job_id": f"detail-regeneration-{timestamp}"}
    try:
        handle = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as error:
        raise RuntimeError("准备详情替换时出现 generation.lock，未改动图片") from error
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as lock_file:
            json.dump(lock_token, lock_file)
        _require_detail_regeneration_idle(batch_dir, group_start, owned_lock=lock_token)
        archive_root = root / "rejected_generations" / timestamp
        archive_group = archive_root / f"group_{group_start:04d}"
        archive_group.mkdir(parents=True, exist_ok=False)
        archives = {"image": archive_group / target.name,
                    "validation": archive_group / validation_path.name,
                    "raw": archive_group / f"paid_raw_{raw_target.name}"}
        for name, source in sources.items():
            shutil.copy2(source, archives[name])
            if _file_sha256(archives[name]) != digests[name]:
                raise RuntimeError(f"详情归档副本 SHA-256 不符：{name}")
        if any(_file_sha256(source) != digests[name] for name, source in sources.items()):
            raise RuntimeError("详情归档期间源文件已变化，未更新验收状态")
        item = {"group_index": group_start, "generation_target_id": target_id,
                "delivery_target_id": delivery_id}
        for name in sources:
            item[f"current_{name}"] = str(sources[name])
            item[f"archived_{name}"] = str(archives[name])
            item[f"{name}_sha256"] = digests[name]
        manifest_path = archive_root / "regeneration_manifest.json"
        manifest = {"schema_version": 1, "category_id": category_id,
                    "operation": "prepare_paid_detail_regeneration", "scope": "details",
                    "api_called": False, "paid_requests": 0, "reason": rejection_reason,
                    "created_at": now_iso(), "phone": phone,
                    "generation_target_id": target_id, "delivery_target_id": delivery_id,
                    "archive_root": str(archive_root), "manifest_path": str(manifest_path),
                    "results": [item]}
        atomic_json(manifest_path, manifest)
        _require_detail_regeneration_idle(batch_dir, group_start, owned_lock=lock_token)
        if any(_file_sha256(source) != digests[name] for name, source in sources.items()):
            raise RuntimeError("详情归档后源文件已变化，未更新验收状态")
        updated = dict(previous)
        updated.update(status="rejected", approved=False, manual_visual_approval=False,
                       user_rejected=True, replacement_required=True,
                       rejected_at=manifest["created_at"], rejection_reason=rejection_reason,
                       replacement_archive={name: str(path) for name, path in archives.items()},
                       replacement_manifest=str(manifest_path))
        atomic_json(validation_path, updated)
        return manifest
    finally:
        if lock_path.is_file() and load_json(lock_path) == lock_token:
            lock_path.unlink()


def rebuild_cover_overlays(
    category_id: str,
    batch_dir: Path,
    group_start: int,
    group_count: int,
    phone: str,
    config: dict[str, Any],
    output_root: Path,
    reason: str,
) -> dict[str, Any]:
    """Archive rejected covers and rebuild them from preserved paid raw files.

    This function is intentionally local-only.  It neither constructs an API
    client nor consumes a production license, and it refuses to replace a cover
    that has already been manually approved.
    """
    if not reason.strip():
        raise ValueError("本地重做必须记录用户拒绝原因")
    run_plan = plan(
        category_id,
        batch_dir,
        group_start,
        group_count,
        phone,
        config,
        scope="covers",
        output_root=output_root,
    )
    deliveries = list(run_plan["delivery_records"])
    if len(deliveries) != group_count or any(
        delivery.get("delivery_kind") != "cover" for delivery in deliveries
    ):
        raise RuntimeError("本地重做范围必须只包含每组一张首图")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    archive_root = production_dir(batch_dir) / "rejected_overlays" / timestamp
    prepared: list[tuple[dict[str, Any], Path, Path, dict[str, Any]]] = []
    for delivery in deliveries:
        target = Path(delivery["target"])
        validation_path = target.with_suffix(".validation.json")
        if not target.is_file() or not validation_path.is_file():
            raise RuntimeError(f"缺少待重做首图或验收文件：{target}")
        old_validation = load_json(validation_path)
        if old_validation.get("approved") is True or old_validation.get("status") == "approved":
            raise RuntimeError(f"已人工批准的首图不能直接重做：{target}")
        records = list(delivery["records"])
        if len(records) != 1:
            raise RuntimeError(f"首图成品必须绑定一个原图：{target}")
        raw_target = Path(records[0]["raw_target"])
        if not valid_png(raw_target, RAW_API_SIZE):
            raise RuntimeError(f"已付费原图缺失或损坏，不能免费重排：{raw_target}")
        prepared.append((delivery, target, validation_path, old_validation))

    results: list[dict[str, Any]] = []
    for delivery, target, validation_path, old_validation in prepared:
        group_index = int(delivery["group_index"])
        archive_group = archive_root / f"group_{group_index:04d}"
        archive_group.mkdir(parents=True, exist_ok=True)
        archived_image = archive_group / target.name
        archived_validation = archive_group / validation_path.name
        shutil.copy2(target, archived_image)
        shutil.copy2(validation_path, archived_validation)
        archived_payload = dict(old_validation)
        archived_payload.update({
            "status": "rejected",
            "approved": False,
            "manual_visual_approval": False,
            "user_rejected": True,
            "rejected_at": now_iso(),
            "rejection_reason": reason.strip(),
            "superseded_output": str(target),
        })
        atomic_json(archived_validation, archived_payload)

        record = list(delivery["records"])[0]
        new_validation = apply_overlays(
            Path(record["raw_target"]),
            target,
            phone,
            str(record["generation_kind"]),
            group_index,
            int(record["delivery_position"]),
            run_plan["service_items"],
            str(record["final_size"]),
            service_role=record.get("service_role"),
            height_profile_id=record.get("height_profile_id"),
            generation_target_id=str(record["generation_target_id"]),
            delivery_target_id=str(record["delivery_target_id"]),
            category_id=category_id,
            structure_version=str(record.get("structure_version") or GROUP_STRUCTURE_VERSION),
            generation_mode=str(record.get("generation_mode") or GENERATION_MODE),
        )
        results.append({
            "group_index": group_index,
            "raw_target": str(record["raw_target"]),
            "archived_image": str(archived_image),
            "archived_validation": str(archived_validation),
            "rebuilt_image": str(target),
            "old_image_sha256": old_validation.get("image_sha256"),
            "new_image_sha256": new_validation.get("image_sha256"),
            "signboard_style": new_validation.get("overlay_style", {}).get("signboard_style"),
            "signboard_detection": new_validation.get("overlay_style", {}).get("signboard_detection"),
        })
    manifest = {
        "schema_version": 1,
        "category_id": category_id,
        "operation": "local_cover_overlay_rebuild",
        "api_called": False,
        "paid_requests": 0,
        "reason": reason.strip(),
        "created_at": now_iso(),
        "archive_root": str(archive_root),
        "results": results,
    }
    atomic_json(archive_root / "rebuild_manifest.json", manifest)
    return manifest


def write_production_summary(
    run_plan: dict[str, Any],
    job: dict[str, Any],
    config: dict[str, Any],
) -> None:
    batch_dir = Path(run_plan["batch_dir"])
    license_id = job.get("license_id") or run_plan.get("license_id")
    category_id = str(run_plan.get("category_id") or DEFAULT_CATEGORY_ID)
    summary = {
        "schema_version": PRODUCTION_SCHEMA_VERSION,
        "structure_version": str(run_plan.get("structure_version") or GROUP_STRUCTURE_VERSION),
        "generation_mode": str(run_plan.get("generation_mode") or GENERATION_MODE),
        "category_id": category_id,
        "batch_id": batch_dir.name,
        "license_id": license_id,
        "group_start": run_plan["group_start"],
        "group_count": run_plan["group_count"],
        "scope": run_plan.get("scope", "all"),
        "plan_sha256": run_plan.get("plan_sha256"),
        "generation_target_ids": run_plan.get("generation_target_ids", []),
        "delivery_target_ids": run_plan.get("delivery_target_ids", []),
        "pending_generation_target_ids": run_plan.get("pending_generation_target_ids", []),
        "pending_delivery_target_ids": run_plan.get("pending_delivery_target_ids", []),
        "pending_api_requests": run_plan.get("pending_api_requests", 0),
        "pending_delivery_count": run_plan.get("pending_delivery_count", 0),
        "generation_targets_sha256": run_plan.get("generation_targets_sha256"),
        "delivery_targets_sha256": run_plan.get("delivery_targets_sha256"),
        "group_recipes_sha256": run_plan.get("group_recipes_sha256"),
        "requested_count": job.get("requested_count", 0),
        "completed": job.get("completed", 0),
        "failed": job.get("failed", 0),
        "failed_request_attempts": job.get("failed_request_attempts", 0),
        "retry_count": job.get("retry_count", 0),
        "max_attempts": job.get("max_attempts", 1),
        "retry_policy": job.get("retry_policy", NO_RETRY_POLICY),
        "requests_used": job.get("requests_used", 0),
        "status": job.get("status"),
        "model": config["model"],
        "quality": config["quality"],
        "size": config["api_size"],
        "raw_api_size": run_plan.get("generation_profile", {}).get("working_raw_size", config["api_size"]),
        **category_generation_profile.bindings(config, category_id),
        "visual_approval": "needs_user_review",
        "updated_at": now_iso(),
    }
    target_summary = summary_path(
        batch_dir,
        run_plan["group_start"],
        run_plan["group_count"],
        str(license_id) if license_id else None,
    )
    summary_content = json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
    _write_text_artifact(target_summary, summary_content, immutable=bool(license_id))
    retry_note = (
        "受控自动重试已启用：可重试错误每个目标最多重试1次，且不超过许可证总预算。"
        if int(summary["max_attempts"] or 1) > 1
        else "本任务未启用自动重试。"
    )
    readable = (
        f"{category_id} 付费样片生产结果\n"
        f"状态：{summary['status']}\n"
        f"完成成品：{summary['completed']} / {run_plan['total_images']} 张\n"
        f"本次待付费 API 请求：{run_plan.get('pending_api_requests', 0)} 次\n"
        f"失败：{summary['failed']} 张\n"
        f"失败请求尝试：{summary['failed_request_attempts']} 次；自动重试：{summary['retry_count']} 次\n"
        f"实际 API 请求：{summary['requests_used']} 次\n"
        f"模型：{summary['model']}，质量：{summary['quality']}，尺寸：{summary['size']}（2:3 竖图）\n"
        "验收：尚未人工确认，当前所有图片均为 needs_user_review。\n"
        f"注意：{retry_note} 任务结束后仍缺图时，必须重新确认并创建新许可证。\n"
    )
    target_readable = summary_path(
        batch_dir,
        run_plan["group_start"],
        run_plan["group_count"],
        str(license_id) if license_id else None,
        readable=True,
    )
    _write_text_artifact(target_readable, readable, immutable=bool(license_id))


def run(args: argparse.Namespace) -> int:
    global ACTIVE_JOB_PATH, ACTIVE_LICENSE_PATH, ACTIVE_LOCK_PATH
    batch_dir = safe_batch_dir(args.category, args.batch_dir)
    license_id = getattr(args, "license_id", None)
    ACTIVE_LICENSE_PATH, ACTIVE_JOB_PATH = validate_worker_paths(
        batch_dir,
        args.group_start,
        args.group_count,
        args.license,
        args.job_file,
        license_id,
    )
    job = load_json(ACTIVE_JOB_PATH)
    job_id = str(job.get("job_id") or "")
    if not job_id:
        raise RuntimeError("任务文件缺少 job_id")
    ACTIVE_LOCK_PATH = acquire_lock(batch_dir, job_id)
    state_lock = threading.Lock()
    event_lock = threading.Lock()
    try:
        config = image_generate.apply_provider_config(image_generate.load_json(ROOT / "config.json"))
        license_preview = load_json(ACTIVE_LICENSE_PATH)
        config = category_generation_profile.from_license(config, args.category, license_preview)
        generation_profile = category_generation_profile.config_profile(config, args.category)
        if job.get("generation_profile") != generation_profile:
            raise RuntimeError("任务记录与许可证的generation-profile不一致")
        if generation_profile is not None and any(job.get(key) != value for key, value in {
            "license_id": license_preview.get("license_id"), "model": config["model"],
            "quality": config["quality"], "size": config["api_size"],
        }.items()):
            raise RuntimeError("新4K任务记录的模型、质量、尺寸或许可证身份不一致")
        request_metadata = category_generation_profile.event_metadata(config, args.category)
        if generation_profile is not None:
            request_metadata["license_id"] = str(license_preview.get("license_id") or "")
        raw_contract_stop = threading.Event()
        image_download_stop = threading.Event()
        image_download_target_ids: set[str] = set()
        phone = str(license_preview.get("phone", ""))
        scope = str(getattr(args, "scope", None) or license_preview.get("scope", "all"))
        output_root = getattr(args, "output_root", None)
        if output_root is None:
            output_root = license_preview.get("output_root")
        licensed_max_workers = int(
            getattr(args, "max_workers", None) or license_preview.get("max_workers", 0) or 0
        )
        run_plan = plan(
            args.category,
            batch_dir,
            args.group_start,
            args.group_count,
            phone,
            config,
            scope=scope,
            output_root=output_root,
            generation_target_id=license_preview.get("generation_target_id"),
        )
        run_plan["license_id"] = license_id or license_preview.get("license_id")
        key_slots = [int(slot) for slot in license_preview.get("api_key_slots") or []]
        validate_frozen_cover_typography(run_plan, license_preview)
        write_production_files(run_plan, phone, run_plan.get("license_id"))
        license_data = validate_license(
            ACTIVE_LICENSE_PATH,
            run_plan,
            config,
            key_slots,
            licensed_max_workers,
        )
        pending = list(run_plan["pending_records"])
        initial_pending_ids = {
            str(record["generation_target_id"]) for record in pending
        }
        generated_success_ids: set[str] = set()
        # Recovering already-paid raw files is entirely local. It deliberately
        # happens before client construction and before the one-time license is
        # consumed, so this path cannot make a network or paid request.
        _font(24)
        recover_local_deliveries(run_plan, phone)
        completed = sum(
            reusable_target(
                Path(delivery["target"]),
                parse_size(str(delivery["final_size"])),
            )
            for delivery in run_plan["delivery_records"]
        )
        failed = 0
        failed_request_attempts = 0
        retry_count = 0
        requests_used = 0
        normalized_responses = 0
        request_budget = int(license_data["approved_request_budget"])
        max_attempts = int(license_data.get("max_attempts", 1) or 1)
        retry_policy = str(license_data.get("retry_policy") or NO_RETRY_POLICY)
        last_error: str | None = None
        events = production_dir(batch_dir) / f"events_{job_id}.jsonl"
        update_job(
            ACTIVE_JOB_PATH,
            status="running",
            completed=completed,
            failed=0,
            total_images=run_plan["total_images"],
            total_delivery_images=run_plan["total_images"],
            total_api_requests=request_budget,
            generation_target_count=run_plan["pending_api_requests"],
            pending_delivery_count=run_plan["pending_delivery_count"],
            worker_count=0,
            current_worker_count=0,
            max_worker_count=licensed_max_workers,
            concurrency_policy=license_data.get(
                "concurrency_policy", ADAPTIVE_CONCURRENCY_POLICY
            ),
            concurrency_history=[],
            requests_used=0,
            max_attempts=max_attempts,
            retry_policy=retry_policy,
            retry_request_budget=request_budget - run_plan["pending_api_requests"],
            retry_count=0,
            failed_request_attempts=0,
            relay_normalized_responses=0,
            worker_pid=os.getpid(),
        )
        if not pending:
            status = (
                "awaiting_review"
                if completed == run_plan["total_images"]
                else "completed_with_errors"
            )
            update_job(ACTIVE_JOB_PATH, status=status, completed=completed, finished_at=now_iso())
            write_production_summary(run_plan, load_json(ACTIVE_JOB_PATH), config)
            return 0 if status == "awaiting_review" else 1

        image_download_receipts.preflight_receipt_support()
        image_download_receipts.assert_no_pending_for_job(ROOT / ".runtime" / "image_download_receipts", job_id)
        clients = openai_clients_by_slot(config, key_slots)
        expected_size = RAW_API_SIZE
        max_worker_count = min(licensed_max_workers, len(clients), len(pending))
        update_job(ACTIVE_JOB_PATH, max_worker_count=max_worker_count)
        # The license is consumed immediately before the first paid request.
        license_data = consume_license(ACTIVE_LICENSE_PATH, license_data)

        def generate_record(
            slot: int, client: Any, record: dict[str, Any]
        ) -> bool | RequestBatchResult:
            nonlocal completed, failed, failed_request_attempts, retry_count
            nonlocal requests_used, normalized_responses, last_error, license_data
            target = Path(record["target"])
            raw_target = Path(record["raw_target"])
            request_prompt = effective_prompt(record, phone)
            retry_prompt_variant = "original"
            content_policy_rejection_count = 0
            logical_attempts_used = int(record.get("_logical_attempts_used", 0))
            balance_failovers = int(record.get("_balance_failover_count", 0))
            for logical_attempt in range(logical_attempts_used + 1, max_attempts + 1):
                attempt = logical_attempt + balance_failovers
                with state_lock:
                    if image_download_stop.is_set():
                        return RequestBatchResult(False, final_error_kind="image_download_failed", attempt_count=0)
                    try:
                        image_download_receipts.assert_no_pending_for_target(
                            ROOT / ".runtime" / "image_download_receipts", job_id, str(record["generation_target_id"]),
                        )
                    except Exception:
                        image_download_stop.set()
                        image_download_target_ids.add(str(record["generation_target_id"]))
                        return RequestBatchResult(False, final_error_kind="image_download_failed", attempt_count=0)
                    if raw_contract_stop.is_set():
                        return RequestBatchResult(False, final_error_kind="raw_contract_rejected", attempt_count=0)
                    if generation_profile is not None and requests_used >= request_budget:
                        return RequestBatchResult(False, final_error_kind="request_budget_exhausted", attempt_count=0)
                    next_request_number = reserve_request(
                        requests_used, request_budget
                    )
                    download_context = image_download_context(
                        batch_dir, job_id, license_data, str(record["generation_target_id"]),
                        next_request_number, attempt, config, request_prompt,
                    )
                    try:
                        image_download_receipts.preflight_context(download_context)
                    except Exception:
                        image_download_stop.set()
                        image_download_target_ids.add(str(record["generation_target_id"]))
                        return RequestBatchResult(False, final_error_kind="image_download_failed", attempt_count=0)
                    append_event(
                        events,
                        {
                            "status": "request_reserved",
                            "raw_target": _artifact_reference(raw_target, batch_dir),
                            "delivery_target": _artifact_reference(target, batch_dir),
                            "generation_target_id": record["generation_target_id"],
                            "delivery_target_id": record["delivery_target_id"],
                            "group_index": record["group_index"],
                            "generation_position": record["generation_position"],
                            "delivery_position": record["delivery_position"],
                            "api_key_slot": slot,
                            "attempt": attempt,
                            "retry_prompt_variant": retry_prompt_variant,
                            "effective_prompt_sha256": hashlib.sha256(
                                request_prompt.encode("utf-8")
                            ).hexdigest(),
                            "request_number": next_request_number,
                            **request_metadata,
                        },
                        event_lock,
                    )
                    updated_license_data = dict(license_data)
                    updated_license_data["requests_used"] = next_request_number
                    atomic_json(ACTIVE_LICENSE_PATH, updated_license_data)
                    license_data = updated_license_data
                    requests_used = next_request_number
                    record["_api_requests_used"] = int(record.get("_api_requests_used", 0)) + 1
                    update_job(
                        ACTIVE_JOB_PATH,
                        status="waiting_for_api",
                        requests_used=requests_used,
                        current_group=record["group_index"],
                        current_position=record["position"],
                    )
                payload_received = False
                try:
                    request_config = {**config, "_image_download_context": download_context}
                    payload = image_generate.generate_one(client, request_config, request_prompt)
                    payload_received = True
                    normalization_anchor_y = (
                        0.0 if str(record["generation_kind"]) == "cover" else 0.5
                    )
                    if generation_profile is not None:
                        from tools.category_4k_raw import save_4k_raw_png

                        save_result = save_4k_raw_png(
                            raw_target, payload,
                            archive_root=production_dir(batch_dir) / "provider_originals" / job_id,
                            generation=config, credential_epoch=None,
                            anchor_y=normalization_anchor_y,
                            accepted_source_size=generation_profile["accepted_source_size"],
                            accepted_source_width_tolerance=generation_profile["accepted_source_width_tolerance"],
                        )
                    else:
                        save_result = save_raw_png(
                            raw_target, payload, expected_size,
                            provider=str(config.get("provider") or ""),
                            archive_root=production_dir(batch_dir) / "provider_originals" / job_id,
                            anchor_y=normalization_anchor_y,
                        )
                    if not isinstance(save_result, dict):
                        save_result = {}
                    if str(record["generation_kind"]) != "triptych_panel":
                        delivery = next(
                            item
                            for item in run_plan["delivery_records"]
                            if item["delivery_target_id"] == record["delivery_target_id"]
                        )
                        _materialize_delivery(
                            delivery,
                            phone,
                            run_plan["service_items"],
                            allow_rejected_replacement=True,
                        )
                    with state_lock:
                        record["_logical_attempts_used"] = logical_attempt
                        generated_success_ids.add(str(record["generation_target_id"]))
                        if save_result.get("normalized") is True:
                            normalized_responses += 1
                        completed = sum(
                            reusable_target(
                                Path(delivery["target"]),
                                parse_size(str(delivery["final_size"])),
                            )
                            for delivery in run_plan["delivery_records"]
                        )
                        update_job(
                            ACTIVE_JOB_PATH,
                            status="running",
                            completed=completed,
                            generated_api_units=len(generated_success_ids),
                            relay_normalized_responses=normalized_responses,
                            current_group=None,
                            current_position=None,
                            last_saved=(
                                str(target) if target.is_file() else str(raw_target)
                            ),
                        )
                    generated_event = {
                        "status": "generated",
                        "request_number": next_request_number,
                        "raw_target": _artifact_reference(raw_target, batch_dir),
                        "delivery_target": _artifact_reference(target, batch_dir),
                        "generation_target_id": record["generation_target_id"],
                        "delivery_target_id": record["delivery_target_id"],
                        "group_index": record["group_index"],
                        "generation_position": record["generation_position"],
                        "delivery_position": record["delivery_position"],
                        "api_key_slot": slot,
                        "attempt": attempt,
                        "retry_prompt_variant": retry_prompt_variant,
                        "source_returned_size": save_result.get("source_returned_size"),
                        "source_sha256": save_result.get("source_sha256"),
                        "saved_raw_sha256": save_result.get("saved_raw_sha256"),
                        "normalized": save_result.get("normalized", False),
                        "normalization_mode": save_result.get("normalization_mode", "none"),
                        "normalized_to": save_result.get("normalized_to"),
                        **request_metadata,
                    }
                    if save_result.get("provider_original"):
                        generated_event["provider_original"] = _artifact_reference(
                            save_result["provider_original"], batch_dir
                        )
                    if generation_profile is not None and save_result.get("provider_original_metadata"):
                        generated_event["provider_original_metadata"] = _artifact_reference(
                            save_result["provider_original_metadata"], batch_dir,
                        )
                    append_event(events, generated_event, event_lock)
                    try:
                        image_download_receipts.mark_materialized(download_context, save_result.get("saved_raw_sha256"))
                    except Exception:
                        # The generated event is already durable: never append a
                        # contradictory failed result or regenerate this target.
                        with state_lock:
                            image_download_stop.set()
                            image_download_target_ids.add(str(record["generation_target_id"]))
                        return RequestBatchResult(False, final_error_kind="image_download_failed", attempt_count=attempt)
                    return True
                except Exception as error:
                    error_kind = classify_request_error(error)
                    try:
                        image_download_receipts.assert_no_pending_for_target(
                            ROOT / ".runtime" / "image_download_receipts", job_id, str(record["generation_target_id"]),
                        )
                    except Exception:
                        error_kind = "image_download_failed"
                    if payload_received and not isinstance(error, RawImageContractError):
                        error_kind = "image_download_failed"
                    if generation_profile is not None and isinstance(error, RawImageContractError):
                        error_kind = "raw_contract_rejected"
                        raw_contract_stop.set()
                    if error_kind == "image_download_failed":
                        with state_lock:
                            image_download_stop.set()
                            image_download_target_ids.add(str(record["generation_target_id"]))
                    if error_kind == "content_policy":
                        content_policy_rejection_count += 1
                    if error_kind == "balance_exhausted":
                        record["_logical_attempts_used"] = logical_attempt - 1
                    else:
                        record["_logical_attempts_used"] = logical_attempt
                    will_retry = (
                        logical_attempt < max_attempts
                        and retry_policy == CLASSIFIED_RETRY_POLICY
                        and error_kind in {"transient", "content_policy"}
                    )
                    with state_lock:
                        failed_request_attempts += 1
                        last_error = safe_request_error_summary(error, error_kind)
                        if will_retry:
                            retry_count += 1
                        elif error_kind != "balance_exhausted":
                            failed += 1
                        update_job(
                            ACTIVE_JOB_PATH,
                            status="running",
                            failed=failed,
                            failed_request_attempts=failed_request_attempts,
                            retry_count=retry_count,
                            current_group=None,
                            current_position=None,
                            last_error=last_error,
                        )
                    failure_event = {
                        "status": "request_failed",
                        "request_number": next_request_number,
                        "generation_target_id": record["generation_target_id"],
                        "delivery_target_id": record["delivery_target_id"],
                        "group_index": record["group_index"],
                        "generation_position": record["generation_position"],
                        "delivery_position": record["delivery_position"],
                        "api_key_slot": slot,
                        "attempt": attempt,
                        "error_kind": error_kind or "non_retryable",
                        "will_retry": will_retry,
                        "api_key_failover_eligible": error_kind == "balance_exhausted",
                        "retry_prompt_variant": retry_prompt_variant,
                        "error": last_error,
                        **request_metadata,
                        **image_generate.safe_stage_metadata(error),
                    }
                    evidence = getattr(error, "evidence", None)
                    if isinstance(evidence, dict) and evidence:
                        failure_event["source_returned_size"] = evidence.get(
                            "source_returned_size"
                        )
                        failure_event["source_sha256"] = evidence.get("source_sha256")
                        failure_event["normalization_rejection_reason"] = evidence.get(
                            "rejection_reason"
                        )
                        if evidence.get("provider_original"):
                            failure_event["provider_original"] = _artifact_reference(
                                evidence["provider_original"], batch_dir
                            )
                        if generation_profile is not None and evidence.get("provider_original_metadata"):
                            failure_event["provider_original_metadata"] = _artifact_reference(
                                evidence["provider_original_metadata"], batch_dir,
                            )
                    append_event(events, failure_event, event_lock)
                    if not will_retry:
                        return RequestBatchResult(
                            success=False,
                            final_error_kind=error_kind,
                            attempt_count=attempt,
                            content_policy_rejection_count=(
                                content_policy_rejection_count
                            ),
                        )
                    if error_kind == "content_policy":
                        request_prompt, retry_prompt_variant = (
                            content_policy_retry_for_record(record, request_prompt)
                        )
                    else:
                        retry_prompt_variant = "original"
                    time.sleep(RETRY_BACKOFF_SECONDS)
            return False

        concurrency_history: list[dict[str, Any]] = []
        quarantined_api_key_slots: set[int] = set()

        def stop_checkpoint(reason: str) -> dict[str, Any]:
            """Persist exact remaining work without replacing the consumed license."""

            records = list(run_plan["pending_records"])
            return {
                "reason": reason,
                **({"generation_resubmit_allowed": False,
                    "image_download_target_ids": sorted(image_download_target_ids)}
                   if reason == "image_download_failed" else {}),
                "created_at": now_iso(),
                "license_id": run_plan.get("license_id"),
                "requests_used": requests_used,
                "remaining_request_budget": request_budget - requests_used,
                "unfinished_generation_target_ids": [
                    str(record["generation_target_id"])
                    for record in records
                    if str(record["generation_target_id"]) not in generated_success_ids
                ],
                "unattempted_generation_target_ids": [
                    str(record["generation_target_id"])
                    for record in records
                    if not record.get("_api_requests_used")
                ],
                "api_requests_by_generation_target": {
                    str(record["generation_target_id"]): int(record.get("_api_requests_used", 0))
                    for record in records
                },
                "logical_attempts_by_generation_target": {
                    str(record["generation_target_id"]): int(record.get("_logical_attempts_used", 0))
                    for record in records
                },
                "in_flight_drained": True,
            }

        def record_concurrency_stage(stage: dict[str, Any]) -> None:
            entry = {
                "stage": len(concurrency_history) + 1,
                **stage,
                "api_requests_used_total": requests_used,
                "retry_count_total": retry_count,
                "recorded_at": now_iso(),
            }
            concurrency_history.append(entry)
            job_changes: dict[str, Any] = {
                "worker_count": int(stage["worker_count"]),
                "current_worker_count": int(stage["worker_count"]),
                "concurrency_history": list(concurrency_history),
            }
            if stage.get("circuit_breaker_triggered") is True:
                job_changes.update(
                    content_policy_circuit_breaker_triggered=True,
                    content_policy_circuit_breaker_stage=entry["stage"],
                    content_policy_circuit_breaker_failure_count=stage.get(
                        "content_policy_double_failure_count", 0
                    ),
                    content_policy_circuit_breaker_failure_rate=stage.get(
                        "content_policy_double_failure_rate", 0.0
                    ),
                )
            if stage.get("balance_circuit_breaker_triggered") is True:
                job_changes.update(
                    balance_circuit_breaker_triggered=True,
                    balance_circuit_breaker_stage=entry["stage"],
                    balance_circuit_breaker_failure_count=stage.get(
                        "balance_exhausted_count", 0
                    ),
                )
            if "consecutive_api_failure_count" in stage:
                job_changes["consecutive_api_failure_count"] = stage[
                    "consecutive_api_failure_count"
                ]
            if stage.get("api_error_circuit_breaker_triggered") is True:
                job_changes.update(
                    api_error_circuit_breaker_triggered=True,
                    api_error_circuit_breaker_stage=entry["stage"],
                    api_error_circuit_breaker_failure_count=stage[
                        "consecutive_api_failure_peak"
                    ],
                    stop_reason=stage["api_error_circuit_breaker_reason"],
                )
            stage_quarantined = {
                int(slot) for slot in stage.get("quarantined_api_key_slots") or []
            }
            if stage_quarantined:
                quarantined_api_key_slots.update(stage_quarantined)
                job_changes.update(
                    quarantined_api_key_slots=sorted(quarantined_api_key_slots),
                    api_key_failover_count=sum(
                        int(item.get("balance_failover_target_count", 0))
                        for item in concurrency_history
                    ),
                )
            update_job(ACTIVE_JOB_PATH, **job_changes)
            append_event(
                events,
                {"status": "concurrency_stage", **entry},
                event_lock,
            )

        # Every paid run starts with one request. A balance-exhausted probe key
        # is isolated and the same target moves to the next licensed key.
        probe = pending.pop(0)
        active_clients = list(clients)
        probe_result: bool | RequestBatchResult = False
        while active_clients:
            probe_slot, probe_client = active_clients[0]
            probe_result = generate_record(probe_slot, probe_client, probe)
            probe_summary = _request_stage_result([probe_result], 1)
            probe_balance_failure = (
                isinstance(probe_result, RequestBatchResult)
                and not probe_result.success
                and probe_result.final_error_kind == "balance_exhausted"
            )
            if probe_balance_failure:
                probe["_balance_failover_count"] = int(
                    probe.get("_balance_failover_count", 0)
                ) + 1
                active_clients = active_clients[1:]
                probe_summary["balance_circuit_breaker_triggered"] = not active_clients
            record_concurrency_stage(
                {
                    "phase": "probe",
                    "worker_count": 1,
                    "request_count": 1,
                    **probe_summary,
                    "quarantined_api_key_slots": (
                        [int(probe_slot)] if probe_balance_failure else []
                    ),
                    "balance_failover_target_count": (
                        1 if probe_balance_failure else 0
                    ),
                    "remaining_api_key_slot_count": len(active_clients),
                }
            )
            if probe_balance_failure:
                continue
            break
        if not probe_result:
            probe_budget_exhausted = (
                isinstance(probe_result, RequestBatchResult)
                and probe_result.final_error_kind == "request_budget_exhausted"
            )
            status = (
                "paused_image_download" if image_download_stop.is_set() else
                "paused_api_errors" if probe_budget_exhausted else
                "paused_balance_exhausted"
                if probe_summary.get("balance_circuit_breaker_triggered")
                else "paused_probe_failed"
            )
            update_job(
                ACTIVE_JOB_PATH,
                status=status,
                completed=completed,
                failed=failed,
                requests_used=requests_used,
                worker_count=0,
                current_worker_count=0,
                current_group=None,
                current_position=None,
                stop_reason="image_download_failed" if image_download_stop.is_set() else "request_budget_exhausted" if probe_budget_exhausted else status,
                checkpoint=stop_checkpoint("image_download_failed" if image_download_stop.is_set() else "request_budget_exhausted" if probe_budget_exhausted else status),
                finished_at=now_iso(),
                output_dir=str(run_plan.get("output_root") or (batch_dir / "images")),
            )
            write_production_summary(run_plan, load_json(ACTIVE_JOB_PATH), config)
            return 1

        if pending:
            concurrency_policy = license_data.get(
                "concurrency_policy", ADAPTIVE_CONCURRENCY_POLICY
            )
            stage_phase = (
                "fixed_10"
                if concurrency_policy == FIXED_TEN_CONCURRENCY_POLICY
                else "adaptive"
            )

            def concurrency_stage_callback(stage: dict[str, Any]) -> None:
                record_concurrency_stage({"phase": stage_phase, **stage})

            scheduler = (
                run_fixed_request_batches
                if concurrency_policy == FIXED_TEN_CONCURRENCY_POLICY
                else run_adaptive_request_batches
            )
            scheduler(
                pending,
                active_clients,
                min(licensed_max_workers, len(active_clients)),
                generate_record,
                concurrency_stage_callback,
                balance_failover=True,
            )
        update_job(ACTIVE_JOB_PATH, worker_count=0, current_worker_count=0)

        # Compose triptychs only after all parallel panel requests have
        # finished. A per-target lock and atomic replace protect against
        # duplicate composition attempts inside this worker.
        for delivery in run_plan["delivery_records"]:
            bad_existing = target_review_status(Path(delivery["target"])) in {"needs_fix", "rejected"}
            delivery_pending_ids = {
                str(record["generation_target_id"])
                for record in delivery["records"]
                if str(record["generation_target_id"]) in initial_pending_ids
            }
            replacement_ready = (
                not bad_existing
                or delivery_pending_ids.issubset(generated_success_ids)
            )
            if replacement_ready:
                _materialize_delivery(
                    delivery,
                    phone,
                    run_plan["service_items"],
                    allow_rejected_replacement=bad_existing,
                )
        complete = sum(
            reusable_target(
                Path(delivery["target"]),
                parse_size(str(delivery["final_size"])),
            )
            for delivery in run_plan["delivery_records"]
        )
        api_error_stop = next((
            stage for stage in reversed(concurrency_history)
            if stage.get("api_error_circuit_breaker_triggered") is True
        ), None)
        status = (
            "paused_image_download" if image_download_stop.is_set()
            else "paused_api_errors" if api_error_stop is not None
            else "awaiting_review" if complete == run_plan["total_images"] and failed == 0
            else "completed_with_errors"
        )
        safety_changes = {}
        if image_download_stop.is_set():
            safety_changes = {"stop_reason": "image_download_failed", "checkpoint": stop_checkpoint("image_download_failed")}
        elif api_error_stop is not None:
            reason = str(api_error_stop["api_error_circuit_breaker_reason"])
            safety_changes = {
                "stop_reason": reason,
                "checkpoint": stop_checkpoint(reason),
            }
        update_job(
            ACTIVE_JOB_PATH,
            status=status,
            completed=complete,
            failed=failed,
            requests_used=requests_used,
            current_group=None,
            current_position=None,
            finished_at=now_iso(),
            last_error=None if failed == 0 else last_error,
            output_dir=str(run_plan.get("output_root") or (batch_dir / "images")),
            **safety_changes,
        )
        write_production_summary(run_plan, load_json(ACTIVE_JOB_PATH), config)
        return 0 if status == "awaiting_review" else 1
    finally:
        if ACTIVE_LOCK_PATH and ACTIVE_LOCK_PATH.exists():
            ACTIVE_LOCK_PATH.unlink()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Pipe-unclogging category image production worker")
    sub = parser.add_subparsers(dest="command", required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--category", required=True)
    run_parser.add_argument("--batch-dir", required=True)
    run_parser.add_argument("--group-start", type=int, required=True)
    run_parser.add_argument("--group-count", type=int, required=True)
    run_parser.add_argument("--license", required=True)
    run_parser.add_argument("--job-file", required=True)
    run_parser.add_argument("--scope", choices=sorted(SCOPES), default="all")
    run_parser.add_argument("--output-root")
    run_parser.add_argument("--license-id")
    run_parser.add_argument("--max-workers", type=int)
    run_parser.set_defaults(handler=run)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    raise SystemExit(args.handler(args))


def main_with_error_handling() -> None:
    try:
        main()
    except Exception as error:
        if ACTIVE_JOB_PATH is not None:
            try:
                update_job(
                    ACTIVE_JOB_PATH,
                    status="failed",
                    current_group=None,
                    current_position=None,
                    last_error=safe_request_error_summary(
                        error, classify_request_error(error),
                    ),
                    finished_at=now_iso(),
                )
            except Exception:
                pass
        if ACTIVE_LOCK_PATH and ACTIVE_LOCK_PATH.exists():
            ACTIVE_LOCK_PATH.unlink()
        # A raw traceback would copy provider response bodies into the worker log.
        raise SystemExit(1) from None


if __name__ == "__main__":
    main_with_error_handling()
