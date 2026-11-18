"""Local, category-scoped prompt generation for the first pipe-unclogging phase."""

from __future__ import annotations
from tools import runtime_paths

from tools import variable_catalog

import json
import random
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import visual_style_profiles


ROOT = Path(__file__).resolve().parent.parent
CATEGORY_CONFIG_DIR = ROOT / "configs" / "categories"
CATEGORY_BATCH_ROOT = ROOT / "prompts" / "category_batches"


class CategoryPromptError(ValueError):
    """Expected, user-facing validation error for category prompt work."""


def load_category_config(category_id: str) -> dict[str, Any]:
    supported_category_ids = {
        "ktv",
        "pipe_unclogging",
        "road_rescue",
        "home_appliance_repair",
        "pet_transport",
        "truck_rescue",
    }
    if category_id not in supported_category_ids:
        raise CategoryPromptError(
            f"当前类目提示词配置只支持 {sorted(supported_category_ids)}，收到的是：{category_id}"
        )
    path = CATEGORY_CONFIG_DIR / f"{category_id}.json"
    if not path.is_file():
        raise CategoryPromptError(f"没有找到类目配置文件：{path}")
    config = runtime_paths.read_json(path)
    required = {"category_id", "scene_types", "image_group_structure", "negative_prompt"}
    missing = sorted(required - set(config))
    if missing:
        raise CategoryPromptError(f"类目配置缺少必要字段：{', '.join(missing)}")
    if config["category_id"] != category_id:
        raise CategoryPromptError("类目配置中的 category_id 与文件名不一致")
    return config


def _choice(source: list[str], rng: random.Random) -> str:
    if not source:
        raise CategoryPromptError("类目配置存在空的合法组合列表，无法安全生成提示词")
    return rng.choice(source)


PIPE_CAMERAS = ['平视近景', '侧前方中近景', '轻微俯拍的施工细节镜头', '站在门口的自然抓拍角度']
PIPE_INDOOR_LIGHT = ['普通室内自然光', '厨房或卫生间的日间混合光', '顶灯与窗光的自然混合光']
PIPE_OUTDOOR_LIGHT = ['普通日间自然光', '阴天的柔和漫射光', '晴天的自然环境光']
PIPE_WEATHER = ['', '', '', '', '', '', '', '', '普通阴天', '晴天后的地面微湿']


def _weather(scene: dict[str, Any], rng: random.Random) -> str | None:
    if not scene.get("weather_allowed"):
        return None
    # Weather is deliberately a rare secondary detail for outdoor drain/septic scenes.
    return rng.choice(PIPE_WEATHER) or None


def scene_matches_legal_combination(config: dict[str, Any], role: str, selected: dict[str, Any]) -> bool:
    scene = config.get("scene_types", {}).get(role, {})
    for combination in scene.get("legal_combinations", []):
        if (
            selected.get("location") in combination.get("locations", [])
            and selected.get("customer_problem") in combination.get("problems", [])
            and selected.get("pipe_type") in combination.get("pipe_types", [])
            and selected.get("worker_action") == combination.get("action")
            and selected.get("tool") in combination.get("tools", [])
        ):
            return True
    return False


@variable_catalog.managed('$config','$role',documents=(('config',None),))
def build_prompt_record(
    config: dict[str, Any], role: str, index: int, rng: random.Random, group_index: int | None = None,
) -> dict[str, Any]:
    scene = config["scene_types"].get(role)
    if not isinstance(scene, dict):
        raise CategoryPromptError(f"没有找到角色“{role}”的合法场景配置")
    legal_combinations = scene.get("legal_combinations")
    if not isinstance(legal_combinations, list) or not legal_combinations:
        raise CategoryPromptError(f"角色“{role}”缺少 legal_combinations，已停止随机硬拼")
    combination = rng.choice(legal_combinations)
    location = _choice(combination["locations"], rng)
    problem = _choice(combination["problems"], rng)
    pipe_type = _choice(combination["pipe_types"], rng)
    tool = _choice(combination["tools"], rng)
    action = combination["action"]
    setting = "outdoor" if scene.get("weather_allowed") else "indoor"
    environment_options = config.get("environment_details_by_setting", {}).get(setting, config["environment_details"])
    environment = _choice(environment_options, rng)
    realism = _choice(config["realism_factors"], rng)
    camera = _choice(PIPE_CAMERAS, rng)
    lighting_options = (
        PIPE_OUTDOOR_LIGHT
        if setting == "outdoor"
        else PIPE_INDOOR_LIGHT
    )
    lighting = _choice(lighting_options, rng)
    weather = _weather(scene, rng)
    role_label = "管道疏通服务封面" if role == "cover" else role
    positive_parts = [
        f"中国本地管道疏通真实施工现场，主题：{role_label}",
        f"地点：{location}",
        f"客户问题：{problem}，管道类型：{pipe_type}",
        f"施工动作：{action}，使用真实工具：{tool}",
        f"环境细节：{environment}",
        f"{camera}，{lighting}，{realism}",
        "普通中国居民楼、老小区或商铺环境，画面实用、克制、可信，轻微脏乱但不展示令人不适的污物",
    ]
    if weather:
        positive_parts.append(f"室外条件仅作次要环境信息：{weather}，不渲染灾害天气")
    if role == "cover":
        positive_parts.append("为后期中心电话条与底部服务词预留干净区域；不生成电话、品牌、价格或可读招牌文字")
    positive_prompt = visual_style_profiles.ensure_target_mode(
        "；".join(positive_parts) + "。", config["category_id"]
    )
    negative_prompt = "、".join(config["negative_prompt"])
    return {
        "schema_version": 1,
        "category_id": config["category_id"],
        "category_name": config["category_name"],
        "index": index,
        "group_index": group_index,
        "role": role,
        "prompt_kind": "cover" if role == "cover" else "detail",
        "scene": {
            "location": location,
            "customer_problem": problem,
            "pipe_type": pipe_type,
            "tool": tool,
            "worker_action": action,
            "environment_detail": environment,
            "camera_angle": camera,
            "lighting": lighting,
            "weather": weather,
        },
        "positive_prompt": positive_prompt,
        "negative_prompt": negative_prompt,
        "api_called": False,
    }


def _next_batch_dir(category_id: str) -> Path:
    root = CATEGORY_BATCH_ROOT / category_id
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    candidate = root / f"batch_{stamp}"
    suffix = 1
    while candidate.exists():
        candidate = root / f"batch_{stamp}_{suffix:02d}"
        suffix += 1
    return candidate


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8", newline="\n")


def generate_batch(category_id: str, count: int | None, group_count: int | None, dry_run: bool) -> dict[str, Any]:
    if not dry_run:
        raise CategoryPromptError("第一阶段仅支持 --dry-run；该命令不会调用生图 API")
    if (count is None) == (group_count is None):
        raise CategoryPromptError("请二选一提供 --count 或 --group-count")
    if count is not None and not 1 <= count <= 500:
        raise CategoryPromptError("--count 必须是 1 到 500 的整数")
    if group_count is not None and not 1 <= group_count <= 100:
        raise CategoryPromptError("--group-count 必须是 1 到 100 的整数")
    config = load_category_config(category_id)
    rng = random.SystemRandom()
    records: list[dict[str, Any]] = []
    if count is not None:
        roles = ["cover", *config["image_group_structure"]["detail_roles"]]
        for index in range(1, count + 1):
            records.append(build_prompt_record(config, roles[(index - 1) % len(roles)], index, rng))
        mode = "independent_test_prompts"
    else:
        roles = ["cover", *config["image_group_structure"]["detail_roles"]]
        index = 1
        for group_index in range(1, group_count + 1):
            for role in roles:
                records.append(build_prompt_record(config, role, index, rng, group_index))
                index += 1
        mode = "complete_groups"
    batch_dir = _next_batch_dir(category_id)
    batch_dir.mkdir(parents=True, exist_ok=False)
    manifest = [
        {
            "schema_version": 1,
            "category_id": category_id,
            "index": record["index"],
            "group_index": record["group_index"],
            "role": record["role"],
            "status": "prompt_ready",
            "image_path": None,
            "api_called": False,
        }
        for record in records
    ]
    summary = {
        "schema_version": 1,
        "category_id": category_id,
        "category_name": config["category_name"],
        "mode": mode,
        "dry_run": True,
        "api_called": False,
        "prompt_count": len(records),
        "group_count": group_count or 0,
        "cover_count": sum(record["role"] == "cover" for record in records),
        "detail_count": sum(record["role"] != "cover" for record in records),
        "group_structure": config["image_group_structure"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "output_dir": str(batch_dir.resolve()),
    }
    _write_jsonl(batch_dir / "prompts.jsonl", records)
    _write_jsonl(batch_dir / "manifest.jsonl", manifest)
    (batch_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    readme = (
        "管道疏通提示词测试批次（第一阶段）\n\n"
        "本批次只生成本地提示词和清单，没有调用生图 API，也没有生成或伪造图片文件。\n"
        f"模式：{'完整组图' if group_count else '独立测试提示词'}\n"
        f"提示词数量：{len(records)}\n"
        f"完整组数：{group_count or 0}\n\n"
        "文件说明：\n"
        "- prompts.jsonl：每条提示词的正向、负向提示词与合法场景组合。\n"
        "- manifest.jsonl：后续审核/生图阶段使用的清单；image_path 为空是正常的。\n"
        "- summary.json：机器可读汇总。\n"
        "- summary_readable.txt：新手可读汇总。\n\n"
        f"下一步可运行：python factory.py audit-category-batch --category {category_id} --batch-dir \"{batch_dir.resolve()}\" --mode mock\n"
    )
    readable = (
        "生成成功\n"
        f"类目：{config['category_name']}\n"
        f"本次生成：{len(records)} 条提示词\n"
        f"输出目录：{batch_dir.resolve()}\n"
        "未调用生图 API，未生成图片。\n"
        "建议下一步：先运行 mock 审核，确认提示词业务组合和禁止元素检查结果。\n"
    )
    (batch_dir / "README_THIS_BATCH.txt").write_text(readme, encoding="utf-8", newline="\n")
    (batch_dir / "summary_readable.txt").write_text(readable, encoding="utf-8", newline="\n")
    return {"batch_dir": batch_dir.resolve(), "summary": summary}


def open_batch_directory(batch_dir: Path) -> tuple[bool, str | None]:
    try:
        if hasattr(__import__("os"), "startfile"):
            __import__("os").startfile(str(batch_dir))  # type: ignore[attr-defined]
        else:
            shutil.which("xdg-open") and __import__("subprocess").Popen(["xdg-open", str(batch_dir)])
        return True, None
    except OSError as error:
        return False, str(error)
