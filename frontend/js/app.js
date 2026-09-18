// ===== 安心药箱 · 前端交互逻辑 =====
const API = "";  // 前后端同源，使用相对路径

// ---- 通用请求 ----
async function apiGet(path) {
  const r = await fetch(API + path);
  return r.json();
}
async function apiPost(path, data = {}) {
  const r = await fetch(API + path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  return r.json();
}
async function apiDel(path) {
  const r = await fetch(API + path, { method: "DELETE" });
  return r.json();
}

// ---- Tab 切换 ----
document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
    document.querySelectorAll(".panel").forEach((p) => p.classList.remove("active"));
    tab.classList.add("active");
    document.getElementById("panel-" + tab.dataset.tab).classList.add("active");
  });
});

// ---- 老人/子女端切换 ----
document.querySelectorAll(".mode-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".mode-btn").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    if (btn.dataset.mode === "elderly") {
      document.body.classList.add("elderly-mode");
      showToast("已切换为老人端：大字体、大按钮");
    } else {
      document.body.classList.remove("elderly-mode");
      showToast("已切换为子女端：查看家庭报告");
    }
  });
});

// ---- Toast 提示 ----
function showToast(msg, duration = 2500) {
  const t = document.getElementById("elderlyToast");
  t.textContent = msg;
  t.style.display = "block";
  clearTimeout(t._timer);
  t._timer = setTimeout(() => (t.style.display = "none"), duration);
}

// ===== 模块1：一拍识药 =====
const btnScan = document.getElementById("btnScan");
const identifyResult = document.getElementById("identifyResult");
const resultList = document.getElementById("resultList");
const resultCount = document.getElementById("resultCount");
let identifiedResults = [];

btnScan.addEventListener("click", async () => {
  btnScan.textContent = "识别中...";
  btnScan.disabled = true;
  try {
    const res = await apiPost("/api/identify", {});
    identifiedResults = res.results;
    renderIdentifyResults(res.results);
  } catch (e) {
    showToast("识别失败，请检查后端服务");
  } finally {
    btnScan.textContent = "开 始 识 别";
    btnScan.disabled = false;
  }
});

function renderIdentifyResults(results) {
  identifyResult.style.display = "block";
  resultCount.textContent = `识别到 ${results.length} 种药品`;
  resultList.innerHTML = results
    .map((r) => {
      const confClass = r.confidence >= 0.95 ? "conf-high" : "conf-mid";
      return `
        <div class="result-item">
          <div>
            <div class="rname">${r.name}</div>
            <div class="rcat">${r.category}</div>
            <div class="rmeta">有效期至 ${r.expiry_date}</div>
          </div>
          <div class="confidence ${confClass}">${(r.confidence * 100).toFixed(1)}%</div>
        </div>`;
    })
    .join("");
}

document.getElementById("btnRescan").addEventListener("click", () => {
  identifyResult.style.display = "none";
  identifiedResults = [];
});

document.getElementById("btnAddAll").addEventListener("click", async () => {
  let added = 0;
  for (const r of identifiedResults) {
    const res = await apiPost("/api/cabinet", {
      medicine_id: r.medicine_id,
      expiry_date: r.expiry_date,
    });
    if (res.success) added++;
  }
  showToast(`已添加 ${added} 种药品到家庭药箱`);
  loadCabinet();
  // 切换到药箱tab
  document.querySelector('.tab[data-tab="cabinet"]').click();
});

// ===== 模块2：家庭药箱 =====
const cabinetGrid = document.getElementById("cabinetGrid");
const chronicTags = document.getElementById("chronicTags");
const CHRONIC_LIST = ["高血压", "糖尿病", "肝病", "消化道溃疡", "哮喘", "高血脂", "冠心病"];
let chronicActive = [];

function renderChronicTags() {
  chronicTags.innerHTML = CHRONIC_LIST.map(
    (c) => `<span class="chronic-tag ${chronicActive.includes(c) ? "active" : ""}" data-name="${c}">${c}</span>`
  ).join("");
  chronicTags.querySelectorAll(".chronic-tag").forEach((tag) => {
    tag.addEventListener("click", async () => {
      const name = tag.dataset.name;
      if (chronicActive.includes(name)) {
        chronicActive = chronicActive.filter((c) => c !== name);
      } else {
        chronicActive.push(name);
      }
      renderChronicTags();
      await apiPost("/api/chronic", { chronic_diseases: chronicActive });
    });
  });
}

async function loadCabinet() {
  const res = await apiGet("/api/cabinet");
  if (res.count === 0) {
    cabinetGrid.innerHTML = `<div class="empty-state">药箱为空，请先「一拍识药」添加药品</div>`;
    return;
  }
  const today = new Date();
  cabinetGrid.innerHTML = res.cabinet
    .map((item) => {
      const exp = new Date(item.expiry_date);
      const daysLeft = Math.ceil((exp - today) / (1000 * 60 * 60 * 24));
      let expClass = "ok",
        expText = `有效期至 ${item.expiry_date}`;
      if (daysLeft < 0) {
        expClass = "danger";
        expText = `已过期 ${-daysLeft} 天`;
      } else if (daysLeft <= 30) {
        expClass = "warn";
        expText = `近效期：剩余 ${daysLeft} 天`;
      }
      const ings = item.active_ingredients.map((i) => `${i.name} ${i.dose}`).join("、");
      return `
        <div class="med-card">
          <button class="btn-danger mc-remove" data-id="${item.id}">移除</button>
          <div class="mc-name">${item.name}</div>
          <div class="mc-cat">${item.category}</div>
          <div class="mc-ing">💊 有效成分：${ings}</div>
          <div class="mc-expiry ${expClass}">📅 ${expText}</div>
        </div>`;
    })
    .join("");

  cabinetGrid.querySelectorAll(".mc-remove").forEach((btn) => {
    btn.addEventListener("click", async () => {
      await apiDel("/api/cabinet/" + btn.dataset.id);
      loadCabinet();
      showToast("已从药箱移除");
    });
  });
}

// ===== 模块3：风险检测 =====
const btnRiskCheck = document.getElementById("btnRiskCheck");
const riskList = document.getElementById("riskList");
const riskScore = document.getElementById("riskScore");
const riskSummary = document.getElementById("riskSummary");

btnRiskCheck.addEventListener("click", async () => {
  btnRiskCheck.textContent = "检测中...";
  btnRiskCheck.disabled = true;
  try {
    const res = await apiPost("/api/risk-check", {});
    renderRiskResult(res);
  } catch (e) {
    showToast("检测失败，请检查后端服务");
  } finally {
    btnRiskCheck.textContent = "🔍 开始风险检测";
    btnRiskCheck.disabled = false;
  }
});

function renderRiskResult(res) {
  const colorMap = { red: "红", yellow: "黄", green: "绿" };
  riskScore.className = "risk-score " + res.overall_level;
  riskScore.textContent = colorMap[res.overall_level] || "—";
  riskSummary.innerHTML = `
    <div class="rs-title">${res.overall_text}</div>
    <div class="rs-stats">
      共检测到 ${res.summary.total} 项风险：
      🔴 ${res.summary.red} 项高风险 · 🟡 ${res.summary.yellow} 项需关注 · 🟢 ${res.summary.green} 项提示
    </div>
    <div class="rs-stats" style="margin-top:4px;">规则版本：${res.rule_version} · 检测时间：${res.check_time}</div>
  `;

  if (res.risks.length === 0) {
    riskList.innerHTML = `<div class="risk-card green">
      <div class="rc-title">✅ 未检出明显风险</div>
      <div class="rc-what">当前家庭药箱未发现重复成分、联合禁忌、慢病禁忌或效期问题。</div>
      <div class="rc-suggest">请继续遵医嘱用药，定期检查药品有效期。</div>
    </div>`;
    return;
  }

  riskList.innerHTML = res.risks
    .map((r) => {
      const badge = r.color === "red" ? "高风险" : r.color === "yellow" ? "需关注" : "提示";
      return `
        <div class="risk-card ${r.color}">
          <div class="rc-title">
            <span class="risk-level-badge ${r.color}">${badge}</span>
            ${r.title}
          </div>
          <div class="rc-what"><b>是什么：</b>${r.what}</div>
          <div class="rc-why"><b>为什么：</b>${r.why}</div>
          <div class="rc-suggest"><b>建议：</b>${r.suggestion}</div>
        </div>`;
    })
    .join("");
}

// ===== 模块4：服药计划 =====
const btnLoadPlan = document.getElementById("btnLoadPlan");
const planGrid = document.getElementById("planGrid");

btnLoadPlan.addEventListener("click", async () => {
  const res = await apiGet("/api/medication-plan");
  const periods = [
    { key: "morning", name: "早晨", emoji: "🌅" },
    { key: "noon", name: "中午", emoji: "☀️" },
    { key: "evening", name: "晚上", emoji: "🌙" },
    { key: "bedtime", name: "睡前", emoji: "😴" },
  ];
  planGrid.innerHTML = periods
    .map((p) => {
      const meds = res.plan[p.key] || [];
      if (meds.length === 0) return "";
      return `
        <div class="plan-card">
          <div class="pc-period"><span class="emoji">${p.emoji}</span> ${p.name}</div>
          ${meds
            .map(
              (m) => `
            <div class="plan-item">
              <div>
                <div class="pi-name">${m.name}</div>
                <div class="pi-usage">${m.usage}</div>
              </div>
              <button class="take-btn" data-id="${m.medicine_id}" data-period="${p.key}">已服用</button>
            </div>`
            )
            .join("")}
        </div>`;
    })
    .join("");

  if (!planGrid.innerHTML.trim()) {
    planGrid.innerHTML = `<div class="empty-state">药箱为空，暂无服药计划</div>`;
    return;
  }

  planGrid.querySelectorAll(".take-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      await apiPost("/api/medication/take", {
        medicine_id: btn.dataset.id,
        period: btn.dataset.period,
      });
      btn.classList.add("done");
      btn.textContent = "✓ 已记录";
      btn.disabled = true;
      showToast("服药记录已保存 ✅");
    });
  });
});

// ===== 模块5：家庭联防报告 =====
const btnFamilyReport = document.getElementById("btnFamilyReport");
const familyReport = document.getElementById("familyReport");

btnFamilyReport.addEventListener("click", async () => {
  const res = await apiGet("/api/family-report");
  const colorMap = { red: "#e11d48", yellow: "#d97706", green: "#059669" };
  const colorText = { red: "高风险", yellow: "需关注", green: "安全" };

  familyReport.innerHTML = `
    <div class="report-header">
      <h3>🏠 家庭用药安全报告</h3>
      <p>生成时间：${res.generated_at} · 规则版本：${res.rule_version}</p>
    </div>
    <div class="report-stats">
      <div class="stat-box"><div class="num" style="color:var(--cyan)">${res.cabinet_count}</div><div class="label">药品种数</div></div>
      <div class="stat-box"><div class="num" style="color:${res.overall_risk === "red" ? "var(--red)" : res.overall_risk === "yellow" ? "var(--amber)" : "var(--emerald)"}">${colorText[res.overall_risk]}</div><div class="label">总体风险</div></div>
      <div class="stat-box"><div class="num" style="color:var(--amber)">${res.near_expiry_count}</div><div class="label">近效期药品</div></div>
      <div class="stat-box"><div class="num" style="color:var(--emerald)">${res.adherence_7d}%</div><div class="label">近7天依从率</div></div>
    </div>
    <div class="report-section">
      <h4>⚠️ 风险提示（共 ${res.risk_summary.total} 项）</h4>
      ${
        res.risks.length === 0
          ? `<p style="color:var(--emerald);font-weight:600;">✅ 当前未检出明显用药风险</p>`
          : res.risks
              .map(
                (r) => `<div style="padding:10px 0;border-bottom:1px solid var(--line);">
                  <b style="color:${colorMap[r.color]}">● ${r.title}</b><br>
                  <span style="color:var(--sub);font-size:13px;">${r.what}</span>
                </div>`
              )
              .join("")
      }
    </div>
    <div class="report-section">
      <h4>👴 老人慢病情况</h4>
      <p>${res.chronic_diseases.length ? res.chronic_diseases.join("、") : "暂无登记慢病"}</p>
    </div>
    <div class="report-section" style="background:#fff1f2;border-color:#fecdd3;">
      <h4 style="color:var(--red);">🚨 重要提醒</h4>
      <p style="color:var(--red);font-weight:600;">${res.overall_text}</p>
      <p style="color:var(--sub);font-size:13px;margin-top:6px;">本系统仅提供药品信息整理与风险提示，不替代医生诊断。高风险情况请尽快咨询医生或药师。</p>
    </div>
  `;
});

// ===== 初始化 =====
async function init() {
  const chronic = await apiGet("/api/chronic");
  chronicActive = chronic.chronic_diseases || [];
  renderChronicTags();
  loadCabinet();
}

init();