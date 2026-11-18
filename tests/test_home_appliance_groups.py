from __future__ import annotations

import json
import unittest

import generate_home_appliance_groups as home_groups
from tools import rule_updates


class HomeApplianceGroupTests(unittest.TestCase):
    def test_rule_stage_exports_home_category_config(self) -> None:
        documents = rule_updates.export_documents()
        path = "configs/categories/home_appliance_repair.json"
        self.assertIn(path, documents)
        exported = json.loads(documents[path])
        self.assertEqual(exported["category_id"], "home_appliance_repair")
        self.assertEqual(len(exported["service_items"]), 10)
        self.assertEqual(exported["image_group_structure"]["generation_unit_count"], 7)

    def test_latest_cover_rules_include_physical_phone_and_real_shop(self) -> None:
        prompt, scene = home_groups.cover_prompt(26, "13317195304")
        self.assertIn("真实中国街边家电维修小门店", prompt)
        self.assertIn("realistic_mobile_documentary_v2", prompt)
        self.assertIn("家电维修", prompt)
        self.assertIn("13317195304", prompt)
        self.assertIn("真实物理招牌", prompt)
        self.assertIn("绝不能像后期平面贴字", prompt)
        self.assertIn("中间约一条横向区域", prompt)
        self.assertIn("画面底部约四分之一", prompt)
        self.assertTrue(scene["logo"])
        self.assertEqual(scene["visual_style_version"], "realistic_mobile_documentary_v2")
        self.assertEqual(scene["category_config_version"], "home_appliance_repair_category_content_v1")

    def test_fifty_groups_have_unique_cover_and_detail_compositions(self) -> None:
        covers, details, groups, production = home_groups.build_records(
            26,
            50,
            "13317195304",
        )
        self.assertEqual(len(covers), 50)
        self.assertEqual(len(details), 400)
        self.assertEqual(len(groups), 50)
        self.assertEqual(len(production), 450)
        self.assertEqual(len({item["prompt_sha256"] for item in [*covers, *details]}), 450)
        self.assertEqual(len({item["scene"]["composition_signature"] for item in covers}), 50)
        self.assertEqual(len({item["scene"]["logo"] for item in covers}), 50)
        for category in home_groups.DETAILS:
            category_records = [item for item in details if item["slug"] == category["slug"]]
            self.assertEqual(len(category_records), 50)
            self.assertEqual(
                len({item["scene"]["composition_signature"] for item in category_records}),
                50,
            )

    def test_production_records_keep_local_text_overlays(self) -> None:
        _, _, _, production = home_groups.build_records(26, 1, "13317195304")
        cover = production[0]
        self.assertEqual(cover["phone_bar_text"], "13317195304")
        self.assertEqual(cover["expected_text"], ["家电维修", "13317195304"])
        self.assertEqual(cover["visual_style_version"], "realistic_mobile_documentary_v2")
        self.assertEqual(
            [item["local_label"] for item in production[1:]],
            [item["title"] for item in home_groups.DETAILS],
        )
        self.assertTrue(all(item["visual_style_version"] == "realistic_mobile_documentary_v2" for item in production))

    def test_v3_group_matches_road_and_truck_delivery_shape(self) -> None:
        rows = home_groups.build_v3_rows(1401, "13317195304")
        self.assertEqual(len(rows), 7)
        self.assertEqual(
            [row["generation_kind"] for row in rows],
            ["cover", "triptych_panel", "triptych_panel", "triptych_panel", "detail", "detail", "detail"],
        )
        self.assertEqual([row["delivery_position"] for row in rows], [1, 2, 2, 2, 3, 4, 5])
        self.assertEqual([row["panel_index"] for row in rows[1:4]], [1, 2, 3])
        self.assertEqual(len({row["service_role"] for row in rows[1:]}), 6)
        self.assertTrue(all(row["final_size"] == "1024x1536" for row in rows))
        self.assertTrue(all(row["structure_version"] == home_groups.V3_STRUCTURE_VERSION for row in rows))
        self.assertIn("13317195304", rows[0]["prompt"])
        self.assertIn("家电维修", rows[0]["scene"]["store_name"])
        self.assertIn("救援车", rows[0]["prompt"])
        self.assertTrue(all("汽车救援" in row["prompt"] for row in rows[1:]))
        self.assertTrue(all("13317195304" not in row["prompt"] for row in rows[1:]))

    def test_v3_hundred_groups_have_unique_storefronts_and_six_distinct_roles(self) -> None:
        covers = []
        names = []
        for group_index in range(1401, 1501):
            rows = home_groups.build_v3_rows(group_index, "13317195304")
            covers.append(rows[0]["scene"]["composition_signature"])
            names.append(rows[0]["scene"]["store_name"])
            self.assertEqual(len({row["service_role"] for row in rows[1:]}), 6)
        self.assertEqual(len(set(covers)), 100)
        self.assertEqual(len(set(names)), 100)


if __name__ == "__main__":
    unittest.main()
