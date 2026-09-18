"""安心药箱 · 规则引擎单元测试

覆盖场景：
  1. 重复有效成分检测（含复方制剂交叉重复）
  2. 药物相互作用检测（显式药物组对 + 组匹配）
  3. 慢病禁忌检测
  4. 效期检测（过期 + 近效期）
  5. 正常药箱零误报
  6. 数据库集成（种子数据加载、药箱增删）
  7. 端到端冒烟（模拟真实老人药箱）
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import date, timedelta

# 确保能 import src 包
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.models import CabinetEntry, PatientProfile
from src.rule_engine import RuleEngine
from src import db as dbmod
from src.db import init_db, add_to_cabinet, get_cabinet, clear_cabinet, drug_count, search_drugs


# ============================================================
# 辅助函数
# ============================================================
def make_entry(drug_name: str, active_ingredients: list[str],
               contraindications: list[str] = None,
               chronic_tags: list[str] = None,
               expiry_date: str = None,
               entry_id: str = "") -> CabinetEntry:
    """快速构建 CabinetEntry，不依赖数据库"""
    return CabinetEntry(
        entry_id=entry_id or f"C_{drug_name}",
        drug_id="",
        drug_name=drug_name,
        expiry_date=expiry_date or "2027-06-30",
        quantity=1,
        added_date=date.today().isoformat(),
        active_ingredients=active_ingredients,
        contraindications=contraindications or [],
        chronic_tags=chronic_tags or [],
    )


class TestSharedIngredient(unittest.TestCase):
    """重复有效成分检测"""

    def setUp(self):
        self.engine = RuleEngine()

    def test_duplicate_acetaminophen(self):
        """复方氨酚烷胺 + 对乙酰氨基酚 → 都含对乙酰氨基酚 → 红色风险"""
        cabinet = [
            make_entry("复方氨酚烷胺胶囊", ["对乙酰氨基酚", "金刚烷胺", "氯苯那敏"]),
            make_entry("对乙酰氨基酚", ["对乙酰氨基酚"]),
        ]
        findings = self.engine.check(cabinet)
        dup = [f for f in findings if f.rule_type == "重复有效成分"]
        self.assertEqual(len(dup), 1)
        self.assertEqual(dup[0].level, "red")
        self.assertEqual(dup[0].rule_id, "R-DUP-001")
        self.assertIn("对乙酰氨基酚", dup[0].description)

    def test_duplicate_two_compound_drugs(self):
        """复方氨酚烷胺 + 感冒灵 → 含对乙酰氨基酚 + 氯苯那敏 → 2 条检出"""
        cabinet = [
            make_entry("复方氨酚烷胺胶囊", ["对乙酰氨基酚", "金刚烷胺", "氯苯那敏"]),
            make_entry("感冒灵颗粒", ["对乙酰氨基酚", "氯苯那敏", "咖啡因"]),
        ]
        findings = self.engine.check(cabinet)
        dup = [f for f in findings if f.rule_type == "重复有效成分"]
        self.assertEqual(len(dup), 2)

    def test_no_duplicate_different_ingredients(self):
        """不同成分的药品不报重复"""
        cabinet = [
            make_entry("氨氯地平", ["氨氯地平"]),
            make_entry("二甲双胍", ["二甲双胍"]),
        ]
        findings = self.engine.check(cabinet)
        dup = [f for f in findings if f.rule_type == "重复有效成分"]
        self.assertEqual(len(dup), 0)


class TestInteractionGroupPair(unittest.TestCase):
    """药物相互作用检测"""

    def setUp(self):
        self.engine = RuleEngine()

    def test_warfarin_aspirin(self):
        """华法林 + 阿司匹林 → 出血风险"""
        cabinet = [
            make_entry("华法林", ["华法林"]),
            make_entry("阿司匹林", ["阿司匹林"]),
        ]
        findings = self.engine.check(cabinet)
        inter = [f for f in findings if f.rule_type == "药物相互作用"
                 and f.rule_id == "R-INT-001"]
        self.assertEqual(len(inter), 1)
        self.assertEqual(inter[0].level, "red")

    def test_warfarin_ibuprofen(self):
        """华法林 + 布洛芬 → 消化道出血"""
        cabinet = [
            make_entry("华法林", ["华法林"]),
            make_entry("布洛芬", ["布洛芬"]),
        ]
        findings = self.engine.check(cabinet)
        inter = [f for f in findings if f.rule_id == "R-INT-002"]
        self.assertEqual(len(inter), 1)

    def test_acei_spironolactone(self):
        """ACEI 组 + 螺内酯 → 高钾血症（组匹配）"""
        cabinet = [
            make_entry("卡托普利", ["卡托普利"]),
            make_entry("螺内酯", ["螺内酯"]),
        ]
        findings = self.engine.check(cabinet)
        hyperk = [f for f in findings if f.rule_id == "R-INT-004"]
        self.assertEqual(len(hyperk), 1)

    def test_arb_spironolactone(self):
        """ARB 组 + 螺内酯 → 高钾血症"""
        cabinet = [
            make_entry("缬沙坦", ["缬沙坦"]),
            make_entry("螺内酯", ["螺内酯"]),
        ]
        findings = self.engine.check(cabinet)
        hyperk = [f for f in findings if f.rule_id == "R-INT-004"]
        self.assertEqual(len(hyperk), 1)

    def test_no_interaction_unrelated_drugs(self):
        """无相互作用的药品不报"""
        cabinet = [
            make_entry("氨氯地平", ["氨氯地平"]),
            make_entry("二甲双胍", ["二甲双胍"]),
        ]
        findings = self.engine.check(cabinet)
        inter = [f for f in findings if f.rule_type == "药物相互作用"]
        self.assertEqual(len(inter), 0)


class TestChronicContraindication(unittest.TestCase):
    """慢病禁忌检测"""

    def setUp(self):
        self.engine = RuleEngine()

    def test_metoprolol_asthma(self):
        """美托洛尔 + 哮喘患者 → 禁忌"""
        cabinet = [
            make_entry("美托洛尔", ["美托洛尔"],
                       contraindications=["哮喘", "严重心动过缓"]),
        ]
        patient = PatientProfile(chronic_conditions=["高血压", "哮喘"], age=70)
        findings = self.engine.check(cabinet, patient)
        chr_risk = [f for f in findings if f.rule_type == "慢病禁忌"]
        self.assertEqual(len(chr_risk), 1)
        self.assertEqual(chr_risk[0].level, "red")
        self.assertIn("美托洛尔", chr_risk[0].description)

    def test_no_contraindication_for_safe_drug(self):
        """安全药品不报禁忌"""
        cabinet = [
            make_entry("氨氯地平", ["氨氯地平"],
                       contraindications=["严重低血压"]),
        ]
        patient = PatientProfile(chronic_conditions=["高血压"], age=65)
        findings = self.engine.check(cabinet, patient)
        chr_risk = [f for f in findings if f.rule_type == "慢病禁忌"]
        self.assertEqual(len(chr_risk), 0)

    def test_no_patient_no_contraindication_check(self):
        """未提供患者画像时不做禁忌检测"""
        cabinet = [
            make_entry("美托洛尔", ["美托洛尔"],
                       contraindications=["哮喘"]),
        ]
        findings = self.engine.check(cabinet, patient=None)
        chr_risk = [f for f in findings if f.rule_type == "慢病禁忌"]
        self.assertEqual(len(chr_risk), 0)


class TestExpiry(unittest.TestCase):
    """效期检测"""

    def setUp(self):
        self.engine = RuleEngine()

    def test_expired(self):
        """过期药品 → 红色"""
        past = (date.today() - timedelta(days=30)).isoformat()
        cabinet = [make_entry("阿司匹林", ["阿司匹林"], expiry_date=past)]
        findings = self.engine.check(cabinet)
        exp = [f for f in findings if f.rule_id == "R-EXP-001"]
        self.assertEqual(len(exp), 1)
        self.assertEqual(exp[0].level, "red")

    def test_near_expiry(self):
        """近效期药品（15天后） → 黄色"""
        near = (date.today() + timedelta(days=15)).isoformat()
        cabinet = [make_entry("阿司匹林", ["阿司匹林"], expiry_date=near)]
        findings = self.engine.check(cabinet)
        near_f = [f for f in findings if f.rule_id == "R-EXP-002"]
        self.assertEqual(len(near_f), 1)
        self.assertEqual(near_f[0].level, "yellow")

    def test_not_expired(self):
        """远未过期药品不报"""
        far = (date.today() + timedelta(days=180)).isoformat()
        cabinet = [make_entry("阿司匹林", ["阿司匹林"], expiry_date=far)]
        findings = self.engine.check(cabinet)
        exp = [f for f in findings if f.rule_type == "效期"]
        self.assertEqual(len(exp), 0)


class TestNormalCabinet(unittest.TestCase):
    """正常药箱零误报"""

    def setUp(self):
        self.engine = RuleEngine()

    def test_safe_combination(self):
        """常见安全降压+降糖组合，无风险"""
        cabinet = [
            make_entry("氨氯地平", ["氨氯地平"],
                       contraindications=["严重低血压"]),
            make_entry("二甲双胍", ["二甲双胍"],
                       contraindications=["严重肾功能不全"]),
        ]
        patient = PatientProfile(chronic_conditions=["高血压", "糖尿病"], age=65)
        findings = self.engine.check(cabinet, patient)
        self.assertEqual(len(findings), 0)


class TestDatabaseIntegration(unittest.TestCase):
    """数据库集成测试"""

    def setUp(self):
        # 使用临时数据库
        self.tmp = tempfile.NamedTemporaryFile(
            suffix=".sqlite3", delete=False)
        self.tmp.close()
        self.db_path = self.tmp.name
        init_db(self.db_path)

    def tearDown(self):
        os.unlink(self.db_path)

    def test_seed_data_loaded(self):
        """种子药品数据已灌入"""
        n = drug_count(self.db_path)
        self.assertGreaterEqual(n, 80, f"种子药品数量应≥80，实际{n}")

    def test_search_drug(self):
        """按名称搜索药品"""
        results = search_drugs("阿司匹林", self.db_path)
        self.assertGreaterEqual(len(results), 1)
        self.assertEqual(results[0].generic_name, "阿司匹林")

    def test_add_to_cabinet_and_check(self):
        """添加药箱条目并执行规则检测"""
        # 添加华法林 + 阿司匹林（已知相互作用）
        add_to_cabinet("D0052", "2027-06-30", db_path=self.db_path)  # 华法林
        add_to_cabinet("D0050", "2027-06-30", db_path=self.db_path)  # 阿司匹林

        cabinet = get_cabinet(self.db_path)
        self.assertEqual(len(cabinet), 2)

        engine = RuleEngine()
        findings = engine.check(cabinet)
        inter = [f for f in findings if f.rule_id == "R-INT-001"]
        self.assertEqual(len(inter), 1)

    def test_compound_drug_duplicate(self):
        """复方氨酚烷胺 + 对乙酰氨基酚 → 重复成分（通过DB加载真实数据）"""
        add_to_cabinet("D0073", "2027-06-30", db_path=self.db_path)  # 复方氨酚烷胺
        add_to_cabinet("D0070", "2027-06-30", db_path=self.db_path)  # 对乙酰氨基酚

        cabinet = get_cabinet(self.db_path)
        engine = RuleEngine()
        findings = engine.check(cabinet)
        dup = [f for f in findings if f.rule_id == "R-DUP-001"]
        self.assertEqual(len(dup), 1)
        self.assertIn("对乙酰氨基酚", dup[0].description)

    def test_chronic_from_db(self):
        """通过DB加载药品+患者画像→检测慢病禁忌"""
        add_to_cabinet("D0010", "2027-06-30", db_path=self.db_path)  # 美托洛尔
        cabinet = get_cabinet(self.db_path)
        patient = PatientProfile(chronic_conditions=["哮喘"], age=70)
        engine = RuleEngine()
        findings = engine.check(cabinet, patient)
        chr_risk = [f for f in findings if f.rule_type == "慢病禁忌"]
        self.assertEqual(len(chr_risk), 1)


class TestEndToEndSmoke(unittest.TestCase):
    """端到端冒烟测试：模拟真实老人药箱"""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(
            suffix=".sqlite3", delete=False)
        self.tmp.close()
        self.db_path = self.tmp.name
        init_db(self.db_path)
        self.engine = RuleEngine()

    def tearDown(self):
        os.unlink(self.db_path)

    def test_realistic_elderly_cabinet(self):
        """模拟 70 岁老人药箱：高血压+糖尿病+冠心病+感冒"""
        # 降压：氨氯地平 + 美托洛尔
        add_to_cabinet("D0001", "2027-06-30", db_path=self.db_path)
        add_to_cabinet("D0010", "2028-01-15", db_path=self.db_path)
        # 降糖：二甲双胍
        add_to_cabinet("D0020", "2027-03-01", db_path=self.db_path)
        # 冠心病：阿司匹林
        add_to_cabinet("D0050", "2026-09-01", db_path=self.db_path)  # 近效期
        # 感冒：复方氨酚烷胺 + 对乙酰氨基酚（重复成分）
        add_to_cabinet("D0073", "2027-12-01", db_path=self.db_path)
        add_to_cabinet("D0070", "2027-12-01", db_path=self.db_path)
        # 阿托伐他汀 + 非诺贝特（相互作用）
        add_to_cabinet("D0040", "2027-06-30", db_path=self.db_path)
        add_to_cabinet("D0044", "2026-10-10", db_path=self.db_path)  # 近效期

        cabinet = get_cabinet(self.db_path)
        self.assertEqual(len(cabinet), 8)

        patient = PatientProfile(
            chronic_conditions=["高血压", "糖尿病", "冠心病"],
            age=70,
        )
        findings = self.engine.check(cabinet, patient)

        # 期望检出
        red_count = sum(1 for f in findings if f.level == "red")
        yellow_count = sum(1 for f in findings if f.level == "yellow")
        summary = self.engine.summary(findings)

        print(f"\n{'='*60}")
        print("端到端冒烟测试结果：")
        print(f"  药箱药品数: {len(cabinet)}")
        print(f"  风险检出数: {len(findings)}")
        print(f"  红色: {red_count}，黄色: {yellow_count}")
        print(f"  规则版本: {summary['rule_version']}")
        print(f"  风险类型: {summary['risk_types']}")
        print(f"{'='*60}")
        for f in findings:
            print(f"  [{f.level}] {f.rule_id} {f.rule_type}: {f.description}")
        print(f"{'='*60}")

        # 断言关键检出（此药箱无华法林，不触发 R-INT-001）
        rule_ids = {f.rule_id for f in findings}
        self.assertIn("R-DUP-001", rule_ids, "应检出重复成分(对乙酰氨基酚)")
        self.assertIn("R-INT-006", rule_ids, "应检出他汀+贝特相互作用")
        self.assertIn("R-EXP-001", rule_ids, "应检出过期药品")
        self.assertIn("R-EXP-002", rule_ids, "应检出近效期药品")

        # 阿司匹林2026-09-01已过期(今天是9/18)
        exp_red = [f for f in findings if f.rule_id == "R-EXP-001"]
        self.assertEqual(len(exp_red), 1)

        # 非诺贝特2026-10-10 → 23天后到期 → 近效期
        exp_yellow = [f for f in findings if f.rule_id == "R-EXP-002"]
        self.assertEqual(len(exp_yellow), 1)

    def test_empty_cabinet(self):
        """空药箱不报风险"""
        cabinet = get_cabinet(self.db_path)
        self.assertEqual(len(cabinet), 0)
        findings = self.engine.check(cabinet)
        self.assertEqual(len(findings), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)