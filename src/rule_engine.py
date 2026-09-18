"""安心药箱 · 用药安全规则引擎

设计原则：
    多模态模型负责「识别」→ 数据库负责「信息」→ 规则引擎负责「安全判断」→ 大模型负责「解释与交互」

本模块只做确定性安全判断，不做自然语言解释。
每条输出可追溯至规则 ID + 依据出处。
"""
from __future__ import annotations

import itertools
import os
from datetime import date, datetime
from typing import Optional

import yaml

from .models import CabinetEntry, PatientProfile, RiskFinding

RULES_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "rules.yaml")


class RuleEngine:
    """确定性规则引擎

    用法：
        engine = RuleEngine()
        findings = engine.check(cabinet, patient)
    """

    def __init__(self, rules_path: str = RULES_PATH):
        with open(rules_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        self.version = data.get("version", "unknown")
        self.rules = data.get("rules", [])

    def check(
        self,
        cabinet: list[CabinetEntry],
        patient: Optional[PatientProfile] = None,
    ) -> list[RiskFinding]:
        """对家庭药箱执行全量规则检测，返回风险检出列表"""
        findings: list[RiskFinding] = []

        for rule in self.rules:
            ct = rule.get("check_type")
            if ct == "shared_ingredient":
                findings.extend(self._check_shared_ingredient(rule, cabinet))
            elif ct == "group_pair":
                findings.extend(self._check_group_pair(rule, cabinet))
            elif ct == "chronic_contraindication":
                findings.extend(self._check_chronic(rule, cabinet, patient))
            elif ct == "expired":
                findings.extend(self._check_expired(rule, cabinet))
            elif ct == "near_expiry":
                findings.extend(self._check_near_expiry(rule, cabinet))
            else:
                raise ValueError(f"未知 check_type: {ct} (规则 {rule.get('id')})")

        # 按风险等级排序：red > yellow > green
        order = {"red": 0, "yellow": 1, "green": 2}
        findings.sort(key=lambda f: (order.get(f.level, 9), f.rule_id))
        return findings

    # ============================================================
    # 重复有效成分检测
    # ============================================================
    def _check_shared_ingredient(
        self, rule: dict, cabinet: list[CabinetEntry]
    ) -> list[RiskFinding]:
        findings = []
        for a, b in itertools.combinations(cabinet, 2):
            shared = set(a.active_ingredients) & set(b.active_ingredients)
            if shared:
                for ingredient in shared:
                    findings.append(RiskFinding(
                        rule_id=rule["id"],
                        rule_type=rule["type"],
                        level=rule["level"],
                        drugs=[a.drug_name, b.drug_name],
                        description=rule["description"].format(
                            drug_a=a.drug_name,
                            drug_b=b.drug_name,
                            ingredient=ingredient,
                        ),
                        basis=rule["basis"],
                        advice=rule["advice"],
                    ))
        return findings

    # ============================================================
    # 药物相互作用检测（显式药物组对）
    # ============================================================
    def _check_group_pair(
        self, rule: dict, cabinet: list[CabinetEntry]
    ) -> list[RiskFinding]:
        findings = []
        group_a = set(rule.get("group_a", []))
        group_b = set(rule.get("group_b", []))

        for a, b in itertools.combinations(cabinet, 2):
            # 双向匹配：a 在 group_a 且 b 在 group_b，或反过来
            match_ab = (a.drug_name in group_a and b.drug_name in group_b)
            match_ba = (b.drug_name in group_a and a.drug_name in group_b)
            if match_ab or match_ba:
                drug_a = a.drug_name if match_ab else b.drug_name
                drug_b = b.drug_name if match_ab else a.drug_name
                findings.append(RiskFinding(
                    rule_id=rule["id"],
                    rule_type=rule["type"],
                    level=rule["level"],
                    drugs=[drug_a, drug_b],
                    description=rule["description"].format(
                        drug_a=drug_a, drug_b=drug_b,
                    ),
                    basis=rule["basis"],
                    advice=rule["advice"],
                ))
        return findings

    # ============================================================
    # 慢病禁忌检测
    # ============================================================
    def _check_chronic(
        self,
        rule: dict,
        cabinet: list[CabinetEntry],
        patient: Optional[PatientProfile],
    ) -> list[RiskFinding]:
        if not patient or not patient.chronic_conditions:
            return []

        findings = []
        patient_conditions = set(patient.chronic_conditions)
        for entry in cabinet:
            matched = patient_conditions & set(entry.contraindications)
            for cond in matched:
                findings.append(RiskFinding(
                    rule_id=rule["id"],
                    rule_type=rule["type"],
                    level=rule["level"],
                    drugs=[entry.drug_name],
                    description=rule["description"].format(
                        drug=entry.drug_name, condition=cond,
                    ),
                    basis=rule["basis"],
                    advice=rule["advice"].format(condition=cond),
                ))
        return findings

    # ============================================================
    # 效期检测
    # ============================================================
    def _check_expired(
        self, rule: dict, cabinet: list[CabinetEntry]
    ) -> list[RiskFinding]:
        findings = []
        today = date.today()
        for entry in cabinet:
            try:
                exp = datetime.strptime(entry.expiry_date, "%Y-%m-%d").date()
            except (ValueError, TypeError):
                continue
            if exp < today:
                findings.append(RiskFinding(
                    rule_id=rule["id"],
                    rule_type=rule["type"],
                    level=rule["level"],
                    drugs=[entry.drug_name],
                    description=rule["description"].format(
                        drug=entry.drug_name, expiry_date=entry.expiry_date,
                    ),
                    basis=rule["basis"],
                    advice=rule["advice"],
                ))
        return findings

    def _check_near_expiry(
        self, rule: dict, cabinet: list[CabinetEntry]
    ) -> list[RiskFinding]:
        findings = []
        today = date.today()
        threshold = rule.get("threshold_days", 30)
        for entry in cabinet:
            try:
                exp = datetime.strptime(entry.expiry_date, "%Y-%m-%d").date()
            except (ValueError, TypeError):
                continue
            if exp >= today and (exp - today).days <= threshold:
                findings.append(RiskFinding(
                    rule_id=rule["id"],
                    rule_type=rule["type"],
                    level=rule["level"],
                    drugs=[entry.drug_name],
                    description=rule["description"].format(
                        drug=entry.drug_name, expiry_date=entry.expiry_date,
                    ),
                    basis=rule["basis"],
                    advice=rule["advice"],
                ))
        return findings

    # ============================================================
    # 工具方法
    # ============================================================
    def summary(self, findings: list[RiskFinding]) -> dict:
        """生成风险摘要（供家庭联防报告使用）"""
        red = [f for f in findings if f.level == "red"]
        yellow = [f for f in findings if f.level == "yellow"]
        return {
            "total_risks": len(findings),
            "red_count": len(red),
            "yellow_count": len(yellow),
            "risk_types": list(set(f.rule_type for f in findings)),
            "rule_version": self.version,
        }
