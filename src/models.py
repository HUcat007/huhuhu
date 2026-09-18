"""安心药箱 · 数据模型定义"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional


@dataclass
class Drug:
    """药品主库记录"""
    drug_id: str
    generic_name: str               # 通用名
    brand_names: list[str]          # 商品名
    dosage_form: str                # 剂型
    specification: str             # 规格
    active_ingredients: list[str]  # 有效成分（重复检测核心字段）
    indications: list[str]         # 适应症
    contraindications: list[str]   # 禁忌症（慢病禁忌检测核心字段）
    chronic_tags: list[str]        # 慢病标签
    otc_rx: str                    # OTC / Rx
    frequency: str                 # 常用频次
    precautions: str = ""          # 注意事项
    interactions: list[str] = field(default_factory=list)  # 相互作用药物名


@dataclass
class CabinetEntry:
    """家庭药箱中的药品条目"""
    entry_id: str
    drug_id: str
    drug_name: str                  # 冗余缓存，避免每次查库
    expiry_date: str                # YYYY-MM-DD
    quantity: int
    added_date: str                 # YYYY-MM-DD
    # 以下字段从药品库补充，供规则引擎直接使用
    active_ingredients: list[str] = field(default_factory=list)
    contraindications: list[str] = field(default_factory=list)
    chronic_tags: list[str] = field(default_factory=list)


@dataclass
class PatientProfile:
    """患者画像"""
    chronic_conditions: list[str]  # 如 ["高血压", "糖尿病", "冠心病", "哮喘"]
    age: int = 65
    allergies: list[str] = field(default_factory=list)


@dataclass
class RiskFinding:
    """规则引擎输出：一条风险检出记录"""
    rule_id: str
    rule_type: str                  # 重复有效成分 / 药物相互作用 / 慢病禁忌 / 效期
    level: str                       # red / yellow / green
    drugs: list[str]                 # 涉及药品名
    description: str                # 大白话描述
    basis: str                      # 依据出处
    advice: str                      # 处理建议

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "rule_type": self.rule_type,
            "level": self.level,
            "drugs": self.drugs,
            "description": self.description,
            "basis": self.basis,
            "advice": self.advice,
        }
