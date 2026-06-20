let ACCOUNTS = [], SEL = null, MODE = null, LEVEL = "instrument", POLL = null;

async function loadAccounts() {
  const r = await fetch("/api/accounts").then(r => r.json()).catch(() => ({ accounts: [] }));
  ACCOUNTS = r.accounts || [];
  const list = document.getElementById("accountList");
  list.innerHTML = "";
  document.getElementById("noAccounts").hidden = ACCOUNTS.length > 0;
  ACCOUNTS.forEach((a, i) => {
    const d = document.createElement("div");
    d.className = "card pick acct";
    d.onclick = () => selectAccount(i);
    d.innerHTML = `<div class="nm">${esc(a.insured || a.name)}</div>
      <div class="meta">${esc(a.policy || "")}${a.county ? " · " + esc(a.county) : ""}</div>
      <div class="meta">CY ${esc(a.crop_year || "")}</div>`;
    list.appendChild(d);
  });
}

function selectAccount(i) {
  SEL = ACCOUNTS[i];
  MODE = (SEL.review_mode || "location").toLowerCase();
  LEVEL = (SEL.specificity_level || "instrument").toLowerCase();
  document.getElementById("acctBadge").innerHTML =
    `Account: <b>${esc(SEL.insured || SEL.name)}</b> &nbsp;·&nbsp; ${esc(SEL.policy || "")} ${SEL.county ? "· " + esc(SEL.county) : ""}`;
  syncPicks();
  goStep(2);
}

function pickMode(m) { MODE = m; syncPicks(); }
function pickLevel(l) { LEVEL = l; syncPicks(); }

function syncPicks() {
  document.querySelectorAll("[data-mode]").forEach(e => e.classList.toggle("sel", e.dataset.mode === MODE));
  document.querySelectorAll("[data-level]").forEach(e => e.classList.toggle("sel", e.dataset.level === LEVEL));
  document.getElementById("specBlock").style.display = MODE === "location" ? "" : "none";
  document.getElementById("toRun").disabled = !MODE;
}

function goStep(n) {
  [1, 2, 3].forEach(i => {
    document.getElementById("step" + i).hidden = i !== n;
    const s = document.getElementById("s" + i);
    s.classList.toggle("active", i === n);
    s.classList.toggle("done", i < n);
  });
  if (n === 3) {
    const lvlTxt = MODE === "location" ? ` &nbsp;·&nbsp; Specificity: <b>${LEVEL === "instrument" ? "Standard" : LEVEL === "section" ? "Section" : "Strict"}</b>` : "";
    document.getElementById("runSummary").innerHTML =
      `<b>${esc(SEL.insured || SEL.name)}</b> &nbsp;·&nbsp; ${MODE === "location" ? "Location" : "Acreage"} Review${lvlTxt}`;
    document.getElementById("result").hidden = true;
    document.getElementById("progress").hidden = true;
    document.getElementById("runBtn").disabled = false;
  }
}

async function runReview() {
  document.getElementById("runBtn").disabled = true;
  const prog = document.getElementById("progress"), log = document.getElementById("progressLog");
  prog.hidden = false; log.innerHTML = ""; document.getElementById("spinner").style.display = "";
  const r = await fetch("/api/run", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ config_path: SEL.config_path, mode: MODE, level: LEVEL }),
  }).then(r => r.json());
  if (r.error) { addLog("ERROR: " + r.error); return; }
  let seen = 0;
  POLL = setInterval(async () => {
    const s = await fetch("/api/status/" + r.job_id).then(r => r.json());
    (s.progress || []).slice(seen).forEach(addLog); seen = (s.progress || []).length;
    if (s.done) { clearInterval(POLL); document.getElementById("spinner").style.display = "none";
      if (s.error) addLog("Could not finish: " + s.error); else showResult(s.result); }
  }, 700);
}

function addLog(m) {
  const li = document.createElement("li"); li.textContent = m;
  document.getElementById("progressLog").appendChild(li);
}

function showResult(res) {
  const wrap = document.getElementById("result"); wrap.hidden = false;
  const stats = document.getElementById("resultStats"); stats.innerHTML = "";
  const sm = res.summary || {};
  if (sm.locations) {
    stats.innerHTML = `<div class="stat">${sm.matched} of ${sm.locations} matched</div>`;
    const by = sm.by_status || {};
    const open = Object.entries(by).filter(([k]) => k === "LIKELY" || k === "EXCEPTION").reduce((a, [, v]) => a + v, 0);
    if (open) stats.innerHTML += `<div class="stat warn">${open} on the follow-up list</div>`;
  } else if (sm.grids) {
    stats.innerHTML = `<div class="stat">${sm.grids} grids checked</div>`;
  }
  const fdiv = document.getElementById("resultFolders"); fdiv.innerHTML = "";
  (res.folders || []).filter(Boolean).forEach(f => {
    const flat = /_FLAT$/.test(f);
    const row = document.createElement("div"); row.className = "folder";
    row.innerHTML = `<div><div class="fn">${esc(baseName(f))}</div>
      <div class="tag2">${flat ? "Flat — best for emailing / uploading" : "With subfolder — best kept on this PC"}</div></div>`;
    const b = document.createElement("button"); b.className = "primary"; b.textContent = "Open folder";
    b.onclick = () => fetch("/api/open-folder", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ path: f }) });
    row.appendChild(b); fdiv.appendChild(row);
  });
}

function baseName(p) { return p.replace(/\/+$/, "").split(/[\\/]/).pop(); }
function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }

loadAccounts();

fetch("/api/version").then(r => r.json()).then(d => {
  document.getElementById("ver").textContent = "Build " + (d.version || "dev");
}).catch(() => {});
