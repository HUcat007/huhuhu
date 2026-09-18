# 安心药箱 · 家庭用药安全辅助系统

> 第八届全球校园人工智能算法精英大赛 · 算法创新赛道 · AI+场景创新

## 项目简介

「安心药箱」是一款面向家庭的用药安全辅助系统，通过 **AI 拍照识药 + 规则引擎风险检测 + 老人友好交互 + 子女远程联防**，打造"识别—守护—反馈"的用药安全闭环。

**核心设计理念**：大模型不参与最终安全判断 —— 识别归模型、判断归规则、解释归 LLM。

## 快速启动

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 初始化数据库（生成 data/drugbox.sqlite3，灌入 100 种药品种子数据）
python -m src.seed_data

# 3. 运行测试（22 项单元测试 + 端到端冒烟）
python -m pytest tests/ -v
```

> 数据库文件 `data/drugbox.sqlite3` 不随仓库分发，需本地执行 `python -m src.seed_data` 生成。

## 项目结构

```
├── requirements.txt            # 依赖（pyyaml）
├── data/
│   └── rules.yaml              # 11 条用药安全规则（YAML 版本化）
├── src/
│   ├── __init__.py
│   ├── models.py               # 数据模型（Drug/CabinetEntry/PatientProfile/RiskFinding）
│   ├── db.py                   # SQLite 数据库操作层
│   ├── rule_engine.py          # 确定性规则引擎（5 种检查类型）
│   └── seed_data.py            # 100 种常见慢病药品种子数据
├── tests/
│   ├── __init__.py
│   └── test_rule_engine.py     # 22 项测试（含端到端冒烟）
├── frontend/
│   ├── index.html              # 五模块 H5 页面骨架
│   ├── css/style.css           # 医院白色风样式（含老人端大字体模式）
│   └── js/app.js               # 前端交互逻辑
└── mvp-architecture.html       # 自包含 MVP 架构图（可浏览器直接打开）
```

## 规则引擎

规则引擎采用 **纯确定性设计**，每条检出可追溯至规则 ID 和依据出处，YAML 配置实现版本化管理（无需改代码即可增改规则）。

### 5 种检查类型

| check_type | 说明 | 规则 ID |
|------------|------|---------|
| shared_ingredient | 重复有效成分检测（含复方交叉） | R-DUP-001 |
| group_pair | 药物相互作用检测（显式组对 + 组匹配） | R-INT-001~008 |
| chronic_contraindication | 慢病用药禁忌检测 | R-CHR-001 |
| expired | 过期药品检测 | R-EXP-001 |
| near_expiry | 近效期药品检测（≤30 天） | R-EXP-002 |

### 风险等级

- 🔴 **红色**：高风险（重复成分、联合禁忌、慢病禁忌、过期）
- 🟡 **黄色**：需关注（近效期）
- 🟢 **绿色**：提示

## 演示亮点

| 场景 | 操作 | 预期结果 |
|------|------|----------|
| 重复成分 | 同时含"复方氨酚烷胺"和"对乙酰氨基酚片" | 🔴 红色高风险 |
| 联合禁忌 | 同时含"阿司匹林"和"华法林" | 🔴 红色高风险 |
| 慢病禁忌 | 哮喘患者使用"美托洛尔" | 🔴 红色高风险 |
| 效期检测 | 添加近效期药品（≤30天） | 🟡 黄色提醒 |

## 端到端冒烟测试

模拟 70 岁老人药箱（高血压 + 糖尿病 + 冠心病 + 感冒），8 种药品检出 4 条风险。

```bash
python -m pytest tests/ -v
```

## 技术栈

- **后端**：Python 3 + SQLite
- **规则引擎**：YAML 配置 + 纯 Python 确定性判断
- **前端**：HTML5 + CSS3 + JavaScript（原生 H5）
- **测试**：unittest + pytest

## 合规声明

本系统仅提供药品信息整理、风险提示与用药提醒服务，**不替代医生诊断、处方及专业医疗判断**。高风险情况请咨询医生或药师。