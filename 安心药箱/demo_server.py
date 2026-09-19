"""安心药箱 · 演示后端（W2/W3 之前的联调桩）

用途：
    在 AI 识别（W2）与正式 API 层（W3）完成前，用「模拟识别数据 + 真实规则引擎」
    把 frontend/ 五个模块完整跑通，供答辩现场演示与前端联调。

启动：
    cd 安心药箱
    python demo_server.py
    浏览器打开 http://localhost:8000

设计约束：
    - 安全判断仍然只走 src.rule_engine（确定性规则），本文件不做任何风险判定
    - /api/identify 返回的是预置模拟识别结果（W2 接入 PaddleOCR 后替换）
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta

from flask import Flask, jsonify, request, send_from_directory

from src.db import (
    init_db,
    get_drug_by_id,
    add_to_cabinet,
    get_cabinet,
    remove_from_cabinet,
    save_risk_records,
)
from src.models import PatientProfile
from src.rule_engine import RuleEngine

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(BASE_DIR, "..", "frontend")
STATE_PATH = os.path.join(BASE_DIR, "data", "demo_state.json")

app = Flask(__name__, static_folder=FRONTEND_DIR, static_url_path="")
engine = RuleEngine()

# ============================================================
# 演示状态持久化（慢病画像 + 服药打卡记录）
# ============================================================
DEFAULT_STATE = {
    "chronic": ["高血压", "糖尿病", "冠心病"],   # 70 岁老人典型画像
    "takes": {},                                   # {"2026-09-19": {"D0050|morning": true}}
}


def load_state() -> dict:
    if os.path.exists(STATE_PATH):
        try:
            with open(STATE_PATH, "r", encoding="utf-8") as f:
                state = json.load(f)
            state.setdefault("chronic", DEFAULT_STATE["chronic"])
            state.setdefault("takes", {})
            return state
        except (json.JSONDecodeError, OSError):
            pass
    return json.loads(json.dumps(DEFAULT_STATE))


def save_state(state: dict) -> None:
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


# ============================================================
# 静态页面：/ 直接返回前端 H5
# ============================================================
@app.route("/")
def index():
    return send_from_directory(FRONTEND_DIR, "index.html")


# ============================================================
# 模块1：一拍识药（W2 之前为模拟识别结果）
# 预置组合刻意覆盖三类风险：
#   华法林 + 阿司匹林          → 药物相互作用（红）
#   复方氨酚烷胺 + 对乙酰氨基酚 → 重复有效成分（红）
#   布洛芬（10 天后到期）       → 近效期（黄）
# ============================================================
DEMO_IDENTIFY = [
    ("D0052", 400, 0.962),   # 华法林
    ("D0050", 365, 0.981),   # 阿司匹林
    ("D0073", 200, 0.974),   # 复方氨酚烷胺胶囊
    ("D0070", 300, 0.918),   # 对乙酰氨基酚（低置信度，对应人工确认场景）
    ("D0071", 10, 0.955),    # 布洛芬（近效期）
    ("D0001", 500, 0.993),   # 氨氯地平（安全对照）
]


@app.route("/api/identify", methods=["POST"])
def api_identify():
    today = date.today()
    results = []
    for drug_id, days_to_expiry, confidence in DEMO_IDENTIFY:
        drug = get_drug_by_id(drug_id)
        if not drug:
            continue
        results.append({
            "medicine_id": drug.drug_id,
            "name": drug.generic_name,
            "category": f"{drug.otc_rx} · {drug.dosage_form}",
            "expiry_date": (today + timedelta(days=days_to_expiry)).isoformat(),
            "confidence": confidence,
        })
    return jsonify({"results": results, "source": "demo_mock"})


# ============================================================
# 模块2：家庭药箱
# ============================================================
@app.route("/api/cabinet", methods=["GET"])
def api_cabinet_list():
    entries = get_cabinet()
    cabinet = []
    for e in entries:
        drug = get_drug_by_id(e.drug_id)
        cabinet.append({
            "id": e.entry_id,
            "name": e.drug_name,
            "category": f"{drug.otc_rx} · {drug.dosage_form}" if drug else "",
            "expiry_date": e.expiry_date,
            "active_ingredients": [
                {"name": ing, "dose": drug.specification if drug else ""}
                for ing in e.active_ingredients
            ],
        })
    return jsonify({"count": len(cabinet), "cabinet": cabinet})


@app.route("/api/cabinet", methods=["POST"])
def api_cabinet_add():
    data = request.get_json(force=True)
    drug_id = data.get("medicine_id")
    expiry_date = data.get("expiry_date", date.today().isoformat())
    try:
        add_to_cabinet(drug_id, expiry_date)
    except ValueError as ex:
        return jsonify({"success": False, "error": str(ex)}), 400
    return jsonify({"success": True})


@app.route("/api/cabinet/<entry_id>", methods=["DELETE"])
def api_cabinet_remove(entry_id):
    remove_from_cabinet(entry_id)
    return jsonify({"success": True})


@app.route("/api/chronic", methods=["GET", "POST"])
def api_chronic():
    state = load_state()
    if request.method == "POST":
        data = request.get_json(force=True)
        state["chronic"] = data.get("chronic_diseases", [])
        save_state(state)
    return jsonify({"chronic_diseases": state["chronic"]})


# ============================================================
# 模块3：风险检测 —— 真实规则引擎
# ============================================================
RULE_TITLES = {
    "重复有效成分": "重复用药风险",
    "药物相互作用": "药物相互作用风险",
    "慢病禁忌": "慢病用药禁忌",
    "效期": "药品效期风险",
}


def run_engine():
    """执行规则检测，返回 (findings, 前端风险卡片列表, 汇总)"""
    state = load_state()
    patient = PatientProfile(chronic_conditions=state["chronic"], age=70)
    findings = engine.check(get_cabinet(), patient)
    save_risk_records(findings, engine.version)

    risks = [{
        "color": f.level,
        "title": f"{RULE_TITLES.get(f.rule_type, f.rule_type)}：{'、'.join(f.drugs)}",
        "what": f.description,
        "why": f"依据：{f.basis}（规则 {f.rule_id}，规则版本 {engine.version}）",
        "suggestion": f.advice,
    } for f in findings]

    summary = {
        "total": len(findings),
        "red": sum(1 for f in findings if f.level == "red"),
        "yellow": sum(1 for f in findings if f.level == "yellow"),
        "green": sum(1 for f in findings if f.level == "green"),
    }
    return findings, risks, summary


def overall_level(summary: dict) -> str:
    if summary["red"] > 0:
        return "red"
    if summary["yellow"] > 0:
        return "yellow"
    return "green"


def overall_text(level: str, summary: dict) -> str:
    if level == "red":
        return f"检出 {summary['red']} 项高风险，建议尽快咨询医生或药师后再用药"
    if level == "yellow":
        return f"检出 {summary['yellow']} 项需关注事项，请按提示处理"
    return "当前药箱未检出明显风险，请继续遵医嘱用药"


@app.route("/api/risk-check", methods=["POST"])
def api_risk_check():
    _, risks, summary = run_engine()
    level = overall_level(summary)
    return jsonify({
        "overall_level": level,
        "overall_text": overall_text(level, summary),
        "summary": summary,
        "rule_version": engine.version,
        "check_time": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "risks": risks,
    })


# ============================================================
# 模块4：服药计划 + 打卡
# ============================================================
def frequency_to_periods(frequency: str) -> list[str]:
    """把药品库中文频次映射到 morning/noon/evening/bedtime"""
    if "必要时" in frequency:
        return []  # 「必要时每6-8小时1次」为按需用药，不排入定时计划
    if "3次" in frequency:
        return ["morning", "noon", "evening"]
    if "2次" in frequency:
        return ["morning", "evening"]
    if "1次" in frequency:
        return ["morning"]
    return []  # 「必要时」药品不排入定时计划


@app.route("/api/medication-plan", methods=["GET"])
def api_medication_plan():
    plan = {"morning": [], "noon": [], "evening": [], "bedtime": []}
    for e in get_cabinet():
        drug = get_drug_by_id(e.drug_id)
        if not drug:
            continue
        for period in frequency_to_periods(drug.frequency):
            plan[period].append({
                "medicine_id": e.drug_id,
                "name": e.drug_name,
                "usage": f"{drug.frequency}，每次 {drug.specification}",
            })
    return jsonify({"plan": plan})


@app.route("/api/medication/take", methods=["POST"])
def api_medication_take():
    data = request.get_json(force=True)
    drug_id = data.get("medicine_id", "")
    period = data.get("period", "")
    state = load_state()
    today = date.today().isoformat()
    state["takes"].setdefault(today, {})[f"{drug_id}|{period}"] = True
    save_state(state)
    return jsonify({"success": True})


# ============================================================
# 模块5：家庭联防报告
# ============================================================
def calc_adherence_7d() -> int:
    """近 7 天服药依从率（%）= 实际打卡次数 / 计划应服次数"""
    state = load_state()
    takes = state["takes"]
    if not takes:
        return 100  # 尚未开始打卡，演示默认满分

    # 每天计划剂量数
    per_day = sum(len(v) for v in _build_plan().values())
    if per_day == 0:
        return 100

    today = date.today()
    dates = [today - timedelta(days=i) for i in range(7)]
    first_take = min(date.fromisoformat(d) for d in takes.keys())
    taken = sum(
        len(takes.get(d.isoformat(), {}))
        for d in dates if d >= first_take
    )
    scheduled_days = len([d for d in dates if d >= first_take])
    scheduled = per_day * scheduled_days
    return min(100, round(taken / scheduled * 100)) if scheduled else 100


def _build_plan() -> dict:
    plan = {"morning": [], "noon": [], "evening": [], "bedtime": []}
    for e in get_cabinet():
        drug = get_drug_by_id(e.drug_id)
        if drug:
            for period in frequency_to_periods(drug.frequency):
                plan[period].append(e.drug_id)
    return plan


@app.route("/api/family-report", methods=["GET"])
def api_family_report():
    findings, risks, summary = run_engine()
    level = overall_level(summary)
    state = load_state()

    today = date.today()
    near_expiry = 0
    for e in get_cabinet():
        try:
            exp = datetime.strptime(e.expiry_date, "%Y-%m-%d").date()
        except ValueError:
            continue
        if today <= exp <= today + timedelta(days=30):
            near_expiry += 1

    return jsonify({
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "rule_version": engine.version,
        "cabinet_count": len(get_cabinet()),
        "overall_risk": level,
        "overall_text": overall_text(level, summary),
        "near_expiry_count": near_expiry,
        "adherence_7d": calc_adherence_7d(),
        "risk_summary": {"total": summary["total"]},
        "risks": [{"color": r["color"], "title": r["title"], "what": r["what"]}
                  for r in risks],
        "chronic_diseases": state["chronic"],
    })


if __name__ == "__main__":
    init_db()
    print("=" * 60)
    print("安心药箱 · 演示后端已启动")
    print("前端页面：http://localhost:8000")
    print("规则版本：", engine.version)
    print("=" * 60)
    app.run(host="127.0.0.1", port=8000, debug=False)