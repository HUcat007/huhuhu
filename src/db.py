"""安心药箱 · 数据库操作层

使用 SQLite 存储药品主库和家庭药箱数据。
单文件部署，评审可现场查看。
"""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import date
from typing import Optional

from .models import CabinetEntry, Drug
from .seed_data import DRUGS

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "drugbox.sqlite3")


def _connect(db_path: str = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str = DB_PATH) -> None:
    """初始化数据库，建表并灌入种子药品数据"""
    conn = _connect(db_path)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS drugs (
            drug_id          TEXT PRIMARY KEY,
            generic_name     TEXT NOT NULL,
            brand_names      TEXT,        -- JSON list
            dosage_form      TEXT,
            specification    TEXT,
            active_ingredients TEXT,     -- JSON list
            indications      TEXT,      -- JSON list
            contraindications TEXT,     -- JSON list
            chronic_tags     TEXT,       -- JSON list
            otc_rx           TEXT,
            frequency        TEXT,
            precautions     TEXT,
            interactions     TEXT        -- JSON list (supplementary)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS cabinet_entries (
            entry_id          TEXT PRIMARY KEY,
            drug_id           TEXT NOT NULL,
            drug_name         TEXT NOT NULL,
            expiry_date       TEXT NOT NULL,   -- YYYY-MM-DD
            quantity          INTEGER DEFAULT 1,
            added_date        TEXT NOT NULL,
            active_ingredients TEXT,           -- JSON list (冗余缓存)
            contraindications  TEXT,            -- JSON list
            chronic_tags       TEXT,            -- JSON list
            FOREIGN KEY (drug_id) REFERENCES drugs(drug_id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS risk_records (
            record_id   TEXT PRIMARY KEY,
            rule_id     TEXT,
            rule_type   TEXT,
            level       TEXT,
            drugs       TEXT,        -- JSON list
            description TEXT,
            basis       TEXT,
            advice      TEXT,
            created_at  TEXT NOT NULL,
            rule_version TEXT
        )
    """)

    # 检查是否已有数据
    cur.execute("SELECT COUNT(*) FROM drugs")
    if cur.fetchone()[0] == 0:
        for d in DRUGS:
            cur.execute("""
                INSERT INTO drugs (drug_id, generic_name, brand_names, dosage_form,
                    specification, active_ingredients, indications, contraindications,
                    chronic_tags, otc_rx, frequency, precautions, interactions)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                d.drug_id, d.generic_name, json.dumps(d.brand_names, ensure_ascii=False),
                d.dosage_form, d.specification,
                json.dumps(d.active_ingredients, ensure_ascii=False),
                json.dumps(d.indications, ensure_ascii=False),
                json.dumps(d.contraindications, ensure_ascii=False),
                json.dumps(d.chronic_tags, ensure_ascii=False),
                d.otc_rx, d.frequency, d.precautions,
                json.dumps(d.interactions, ensure_ascii=False),
            ))
    conn.commit()
    conn.close()


# ============================================================
# 药品库查询
# ============================================================

def search_drugs(keyword: str, db_path: str = DB_PATH) -> list[Drug]:
    """按通用名或商品名模糊搜索药品"""
    conn = _connect(db_path)
    cur = conn.cursor()
    kw = f"%{keyword}%"
    cur.execute("""
        SELECT * FROM drugs
        WHERE generic_name LIKE ? OR brand_names LIKE ?
        ORDER BY generic_name
    """, (kw, kw))
    rows = cur.fetchall()
    conn.close()
    return [_row_to_drug(r) for r in rows]


def get_drug_by_id(drug_id: str, db_path: str = DB_PATH) -> Optional[Drug]:
    conn = _connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT * FROM drugs WHERE drug_id = ?", (drug_id,))
    row = cur.fetchone()
    conn.close()
    return _row_to_drug(row) if row else None


def get_drug_by_name(name: str, db_path: str = DB_PATH) -> Optional[Drug]:
    """按通用名或商品名精确查找"""
    conn = _connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        SELECT * FROM drugs
        WHERE generic_name = ? OR brand_names LIKE ?
        LIMIT 1
    """, (name, f'%"{name}"%'))
    row = cur.fetchone()
    conn.close()
    return _row_to_drug(row) if row else None


def all_drugs(db_path: str = DB_PATH) -> list[Drug]:
    conn = _connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT * FROM drugs ORDER BY generic_name")
    rows = cur.fetchall()
    conn.close()
    return [_row_to_drug(r) for r in rows]


def drug_count(db_path: str = DB_PATH) -> int:
    conn = _connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM drugs")
    n = cur.fetchone()[0]
    conn.close()
    return n


# ============================================================
# 家庭药箱操作
# ============================================================

def add_to_cabinet(drug_id: str, expiry_date: str, quantity: int = 1,
                   db_path: str = DB_PATH) -> CabinetEntry:
    """将药品加入家庭药箱，自动补充引擎所需字段"""
    drug = get_drug_by_id(drug_id, db_path)
    if not drug:
        raise ValueError(f"药品ID不存在: {drug_id}")

    entry_id = f"C{uuid.uuid4().hex[:8]}"
    today = date.today().isoformat()
    conn = _connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO cabinet_entries (entry_id, drug_id, drug_name, expiry_date,
            quantity, added_date, active_ingredients, contraindications, chronic_tags)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        entry_id, drug_id, drug.generic_name, expiry_date, quantity, today,
        json.dumps(drug.active_ingredients, ensure_ascii=False),
        json.dumps(drug.contraindications, ensure_ascii=False),
        json.dumps(drug.chronic_tags, ensure_ascii=False),
    ))
    conn.commit()
    conn.close()

    return CabinetEntry(
        entry_id=entry_id, drug_id=drug_id, drug_name=drug.generic_name,
        expiry_date=expiry_date, quantity=quantity, added_date=today,
        active_ingredients=drug.active_ingredients,
        contraindications=drug.contraindications,
        chronic_tags=drug.chronic_tags,
    )


def get_cabinet(db_path: str = DB_PATH) -> list[CabinetEntry]:
    """获取家庭药箱所有条目"""
    conn = _connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT * FROM cabinet_entries ORDER BY added_date DESC")
    rows = cur.fetchall()
    conn.close()
    return [_row_to_entry(r) for r in rows]


def remove_from_cabinet(entry_id: str, db_path: str = DB_PATH) -> bool:
    conn = _connect(db_path)
    cur = conn.cursor()
    cur.execute("DELETE FROM cabinet_entries WHERE entry_id = ?", (entry_id,))
    deleted = cur.rowcount
    conn.commit()
    conn.close()
    return deleted > 0


def clear_cabinet(db_path: str = DB_PATH) -> None:
    conn = _connect(db_path)
    cur = conn.cursor()
    cur.execute("DELETE FROM cabinet_entries")
    conn.commit()
    conn.close()


# ============================================================
# 风险记录持久化
# ============================================================

def save_risk_records(findings: list, rule_version: str,
                      db_path: str = DB_PATH) -> None:
    """将规则引擎输出持久化到 risk_records 表"""
    conn = _connect(db_path)
    cur = conn.cursor()
    now = date.today().isoformat()
    for f in findings:
        cur.execute("""
            INSERT INTO risk_records (record_id, rule_id, rule_type, level,
                drugs, description, basis, advice, created_at, rule_version)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            f"R{uuid.uuid4().hex[:8]}", f.rule_id, f.rule_type, f.level,
            json.dumps(f.drugs, ensure_ascii=False),
            f.description, f.basis, f.advice, now, rule_version,
        ))
    conn.commit()
    conn.close()


# ============================================================
# 内部转换
# ============================================================

def _row_to_drug(row: sqlite3.Row) -> Drug:
    return Drug(
        drug_id=row["drug_id"],
        generic_name=row["generic_name"],
        brand_names=json.loads(row["brand_names"]),
        dosage_form=row["dosage_form"],
        specification=row["specification"],
        active_ingredients=json.loads(row["active_ingredients"]),
        indications=json.loads(row["indications"]),
        contraindications=json.loads(row["contraindications"]),
        chronic_tags=json.loads(row["chronic_tags"]),
        otc_rx=row["otc_rx"],
        frequency=row["frequency"],
        precautions=row["precautions"],
        interactions=json.loads(row["interactions"]),
    )


def _row_to_entry(row: sqlite3.Row) -> CabinetEntry:
    return CabinetEntry(
        entry_id=row["entry_id"],
        drug_id=row["drug_id"],
        drug_name=row["drug_name"],
        expiry_date=row["expiry_date"],
        quantity=row["quantity"],
        added_date=row["added_date"],
        active_ingredients=json.loads(row["active_ingredients"]),
        contraindications=json.loads(row["contraindications"]),
        chronic_tags=json.loads(row["chronic_tags"]),
    )