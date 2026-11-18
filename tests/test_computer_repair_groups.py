from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import generate_computer_repair_groups as computer_groups
from tools import category_image_production, rule_updates, variable_catalog


class ComputerRepairGroupTests(unittest.TestCase):
    def test_rule_stage_exports_brand_and_service_dimensions(self) -> None:
        documents = rule_updates.export_documents()
        config = json.loads(documents["configs/categories/computer_repair.json"])
        self.assertEqual(config["category_name"], "电脑维修")
        self.assertEqual(
            config["brand_service_items"],
            ["联想维修", "戴尔维修", "惠普维修", "华硕维修", "苹果维修"],
        )
        self.assertEqual(
            config["repair_service_items"],
            ["电脑清灰", "电脑组装", "数据恢复", "电脑卡顿", "系统重装"],
        )
        self.assertEqual(config["service_items"], config["brand_service_items"] + config["repair_service_items"])
        category_image_production._validate_independent_delivery_structure_config(
            config["image_group_structure"],
            "computer_repair",
        )

    def test_random_group_has_five_distinct_computer_scenes(self) -> None:
        rows = computer_groups.build_random_pool_rows(1401, "13800138000")
        self.assertEqual(len(rows), 5)
        self.assertEqual([row["generation_kind"] for row in rows], ["detail"] * 5)
        self.assertEqual([row["delivery_position"] for row in rows], [1, 2, 3, 4, 5])
        self.assertEqual(len({row["service_role"] for row in rows}), 5)
        self.assertTrue(all(row["final_size"] == "1024x1536" for row in rows))
        self.assertTrue(all(row["structure_version"] == computer_groups.STRUCTURE_VERSION for row in rows))
        self.assertTrue(all("本地添加醒目手机号" in row["prompt"] for row in rows))
        self.assertTrue(all("汽车救援" in row["prompt"] for row in rows))
        self.assertTrue(all("品牌Logo" in row["prompt"] for row in rows))

    def test_hundred_groups_remain_diverse_and_group_unique(self) -> None:
        prompts = []
        for group_index in range(1401, 1501):
            rows = computer_groups.build_random_pool_rows(group_index, "13800138000")
            self.assertEqual(len({row["service_role"] for row in rows}), 5)
            prompts.extend(row["prompt"] for row in rows)
        self.assertGreaterEqual(len(set(prompts)), 490)

    def test_high_spec_and_fault_diagnosis_scenes_are_in_random_pool(self) -> None:
        titles = {detail["title"] for detail in computer_groups.DETAILS}
        self.assertEqual(len(titles), 15)
        self.assertTrue(
            {"高配主机组装", "水冷主机调试", "蓝屏死机诊断", "黑屏无信号诊断", "过热降频诊断"}
            <= titles
        )
        prompts = [
            row["prompt"]
            for group_index in range(1, 101)
            for row in computer_groups.build_random_pool_rows(group_index, "13800138000")
        ]
        self.assertTrue(any("适度RGB灯效" in prompt and "高配主机组装" in prompt for prompt in prompts))
        self.assertTrue(any("故障对象、检测工具和排查动作" in prompt and "蓝屏死机诊断" in prompt for prompt in prompts))

    def test_high_spec_candidate_reaches_local_variable_preview(self) -> None:
        catalog = variable_catalog.load("computer_repair")
        self.assertEqual(catalog["supported_roles"], ["detail"])
        dimension = next(
            item for item in catalog["dimensions"]
            if item["source"] == "DETAILS.high_end_gaming_build.actions"
        )
        option = dimension["options"][0]
        previews = variable_catalog.preview(
            "computer_repair",
            {"catalog": catalog, "role": "detail", "force": {dimension["id"]: option["id"]}},
        )
        self.assertEqual(len(previews), 3)
        self.assertTrue(all("高配主机组装" in row["prompt"] for row in previews))
        self.assertTrue(all(option["value"] in row["prompt"] for row in previews))
        self.assertTrue(all(row["api_called"] is False for row in previews))

    def test_rows_pass_formal_category_selection(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            rows = computer_groups.build_random_pool_rows(1, "13800138000")
            frozen = [
                {**row, "index": index, "group_index": 1, "category_id": "computer_repair"}
                for index, row in enumerate(rows, start=1)
            ]
            Path(folder, "prompts.jsonl").write_text(
                "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in frozen),
                encoding="utf-8",
            )
            selected = category_image_production.selected_records(
                Path(folder), 1, 1, "computer_repair"
            )
        self.assertEqual(len(selected), 5)
        self.assertEqual([row["generation_kind"] for row in selected], ["detail"] * 5)
        self.assertEqual([row["delivery_position"] for row in selected], [1, 2, 3, 4, 5])


if __name__ == "__main__":
    unittest.main()
