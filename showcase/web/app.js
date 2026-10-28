const app = document.getElementById("app");
const cache = new Map();

function api(path) {
  if (!cache.has(path)) {
    cache.set(path, fetch(`/api/${path}`).then((r) => {
      if (!r.ok) throw new Error(`${r.status} /api/${path}`);
      return r.json();
    }));
    cache.get(path).catch(() => cache.delete(path));
  }
  return cache.get(path);
}

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const fixed = (x, d = 1) => (x == null ? "—" : Number(x).toFixed(d));
const tokens = (x) => (x == null ? "—" : `${(x / 1e6).toFixed(2)}M`);
const repo = (iid) => iid.split("__")[0];
const short = (iid) => iid.split("__")[1];
const status = (ok) => (ok == null ? "" : ok ? "pass" : "fail");
const badge = (ok) => (ok == null ? `<span class="badge plain">无结果</span>` : `<span class="badge ${status(ok)}">${ok ? "通过" : "失败"}</span>`);

function diff(patch) {
  if (!patch.trim()) return `<p class="muted">空补丁：Agent 没有提交任何改动。</p>`;
  const cls = (l) => (l.startsWith("@@") ? "hunk" : /^\+(?!\+\+)/.test(l) ? "add" : /^-(?!--)/.test(l) ? "del" : "");
  return `<pre class="code diff">${patch.split("\n").map((l) => `<span class="${cls(l)}">${esc(l) || " "}</span>`).join("")}</pre>`;
}

function tabs(group, items, start = 0) {
  const head = items.map((t, i) => `<button role="tab" data-tab="${group}:${i}" aria-selected="${i === start}">${t.label}</button>`).join("");
  const panels = items.map((t, i) => `<div role="tabpanel" data-panel="${group}:${i}" ${i === start ? "" : "hidden"}>${t.body}</div>`).join("");
  return `<div class="tabs" role="tablist">${head}</div>${panels}`;
}

/* ---------- pages ---------- */

function barcode(runs, instances) {
  const rows = runs.map((run) => {
    const cells = instances.map((i) => {
      const ok = i.results[run.key];
      const label = `${i.id} · ${run.label}：${ok == null ? "无结果" : ok ? "通过" : "失败"}`;
      return `<a class="cell ${status(ok)}" href="#/instance/${i.id}" data-iid="${i.id}" data-tip="${esc(label)}" aria-label="${esc(label)}"></a>`;
    });
    return `<div class="barcode-row ${run.void ? "void" : ""}">
      <div class="barcode-label" title="${esc(run.note)}">${esc(run.label)}</div>
      <div class="cells">${cells.join("")}</div>
      <div class="barcode-score num">${run.resolved}<span class="muted" style="font-size:13px">/${run.n}</span></div>
    </div>`;
  });
  return `<div class="barcode">${rows.join("")}</div>
    <div class="tip" aria-live="polite"></div>
    <div class="legend"><span><i style="background:var(--pass)"></i>通过</span><span><i style="background:var(--fail)"></i>失败</span><span>同一列是同一道题，悬停可对比各配置</span></div>`;
}

async function overview() {
  const [o, r] = await Promise.all([api("overview"), api("runs")]);
  const runRows = o.runs.map((run) => `<tr class="${run.void ? "void" : ""}">
    <td>${esc(run.label)}</td>
    <td class="r num">${run.resolved}/${run.n}</td>
    <td class="r num">${fixed(run.steps)}${run.review_steps ? ` <span class="muted">+ 审查 ${fixed(run.review_steps)}</span>` : ""}</td>
    <td class="r num">${tokens(run.prompt_tokens)}</td>
    <td class="muted">${esc(run.note)}</td></tr>`);
  const selRows = o.selection.map((s) => `<tr class="${s.key === "listwise" ? "strong" : ""}">
    <td>${esc(s.label)}</td><td class="r num">${fixed(s.total)}/50</td><td></td><td></td>
    <td class="muted">8 道有对有错的题上：${fixed(s.mixed)}/8</td></tr>`);
  const findings = o.findings.map((f) => `<a class="finding" href="${f.link}"><h3>${esc(f.title)}</h3><p>${esc(f.body)}</p><span class="more">查看证据 →</span></a>`);
  return `
    <div class="page-head">
      <div class="eyebrow">${esc(o.subtitle)}</div>
      <h1>${esc(o.title)}</h1>
      <p class="lede">${esc(o.summary)}</p>
    </div>
    <section>
      <h2>50 道题，每次运行一行</h2>
      <p class="hint">每格是一道题。差距大多来自运行之间的随机波动，而不是检查机制本身。</p>
      ${barcode(r.runs, r.instances)}
    </section>
    <section>
      <h2>结果</h2>
      <p class="hint">${esc(o.noise)}</p>
      <div class="table-wrap"><table>
        <thead><tr><th>配置</th><th class="r">解出</th><th class="r">平均步数</th><th class="r">Prompt token/题</th><th>说明</th></tr></thead>
        <tbody>${runRows.join("")}
          <tr class="group"><td colspan="5">从 3 次断网运行中挑一个补丁</td></tr>
          ${selRows.join("")}</tbody>
      </table></div>
    </section>
    <section>
      <h2>发现</h2>
      <p class="hint">每条都能点进去看对应的题目和数据。</p>
      <div class="findings">${findings.join("")}</div>
    </section>`;
}

async function experiments() {
  const { runs, instances } = await api("runs");
  const rows = instances.map((i) => {
    const vals = runs.filter((r) => !r.void).map((r) => i.results[r.key]);
    const tags = [new Set(vals).size > 1 && "mixed", i.failure && "analyzed", vals.every((v) => !v) && "unsolved"].filter(Boolean);
    return `<tr class="link" data-href="#/instance/${i.id}" data-tags="${tags.join(" ")}">
      <td><span class="muted">${esc(repo(i.id))} /</span> <a href="#/instance/${i.id}">${esc(short(i.id))}</a></td>
      ${runs.map((r) => `<td class="r"><span class="dot ${status(i.results[r.key])}" title="${esc(r.label)}"></span></td>`).join("")}
      <td>${i.failure ? `<span class="badge plain">${esc(i.failure.cause)}</span>` : ""}</td></tr>`;
  });
  const filters = [["all", "全部"], ["mixed", "结果不一致"], ["analyzed", "有失败归因"], ["unsolved", "一直没解出"]];
  return `
    <div class="page-head">
      <div class="eyebrow">实验</div>
      <h1>同一组题，只改"提交前怎么检查"</h1>
      <p class="lede">模型、题目、断网环境都不变。每个配置各跑一次 50 题，用隐藏测试判断通过与否。</p>
    </div>
    <section>
      <div class="toolbar">${filters.map(([k, l], n) => `<button class="toggle" data-filter="${k}" aria-pressed="${!n}">${l}</button>`).join("")}
        <span class="muted num" data-count></span></div>
      <div class="table-wrap"><table class="dense" data-filterable>
        <thead><tr><th>题目</th>${runs.map((r) => `<th class="r">${esc(r.label)}</th>`).join("")}<th>失败归因</th></tr></thead>
        <tbody>${rows.join("")}</tbody>
      </table></div>
      <p class="hint" style="margin-top:12px">"失败归因"来自对首次（联网）基线 9 个失败题的逐题分析。"结果不一致"不计入作废的联网基线。</p>
    </section>`;
}

function runPanel(iid, run) {
  const t = run.tests;
  const testLine = t ? ["FAIL_TO_PASS", "PASS_TO_PASS"].map((k) => `${k} ${t[k].passed}/${t[k].passed + t[k].failed.length}`).join(" · ") : "无测试明细";
  const failed = t ? [...t.FAIL_TO_PASS.failed, ...t.PASS_TO_PASS.failed] : [];
  const reviews = (run.reviews || []).map((rv, n) => `<details ${rv.passed ? "" : "open"}>
    <summary>审查者意见 #${n + 1} · ${rv.exit_status !== "Submitted" ? "未给结论（自动放行）" : rv.passed ? "放行" : "驳回"} · ${rv.n_calls} 步</summary>
    <div class="body"><div class="prose">${esc(rv.verdict) || "（空）"}</div></div></details>`);
  return `
    <div class="stats">
      <div class="stat"><b>${run.resolved ? "通过" : "失败"}</b><span>隐藏测试</span></div>
      <div class="stat"><b class="num">${run.steps ?? "—"}</b><span>主 Agent 步数${run.review_steps ? ` · 审查 ${run.review_steps}` : ""}</span></div>
      <div class="stat"><b class="num">${tokens(run.prompt_tokens)}</b><span>Prompt token</span></div>
    </div>
    <p class="hint" style="margin:12px 0 0">${esc(run.note)} · ${testLine}</p>
    ${failed.length ? `<details><summary>未通过的测试（${failed.length}）</summary><div class="body"><pre class="code">${failed.map(esc).join("\n")}</pre></div></details>` : ""}
    ${reviews.join("")}
    <h3 style="margin:22px 0 10px">补丁</h3>
    ${diff(run.patch)}
    ${run.has_traj ? `<p><a class="more" href="#/traj/${run.key}/${iid}" style="color:var(--accent-ink)">查看完整轨迹 →</a></p>` : ""}`;
}

function candidates(sel) {
  const rows = sel.candidates.map((c) => `<div class="cand">
    ${badge(c.resolved)}<span class="num">#${c.id} <span class="muted">· 出现在 ${c.votes} 次运行</span></span>
    <span class="muted num">打分 ${c.score ?? "—"}</span>
    <span class="num">被选 ${c.picks}/${sel.calls.length}</span></div>`);
  const byId = Object.fromEntries(sel.candidates.map((c) => [c.id, c]));
  const calls = sel.calls.map((c, n) => `<details>
    <summary>第 ${n + 1} 次对比 · 选中 #${c.best} ${badge(byId[c.best]?.resolved)}</summary>
    <div class="body"><p class="hint">候选顺序：${c.order.map((id, k) => `候选 ${k + 1} = #${id}`).join("，")}</p><div class="prose">${esc(c.response)}</div></div></details>`);
  return `<div class="candidates">${rows.join("")}</div>${calls.join("")}`;
}

async function instance(iid) {
  const d = await api(`instances/${encodeURIComponent(iid)}`);
  return `
    <a class="back" href="#/experiments">← 全部题目</a>
    <div class="page-head">
      <div class="eyebrow">${esc(repo(iid))}</div>
      <h1>${esc(short(iid))}</h1>
      <div class="legend">${d.runs.map((r) => `<span>${esc(r.label)} ${badge(r.resolved)}</span>`).join("")}</div>
    </div>
    ${d.failure ? `<section style="margin-top:28px"><div class="callout"><b>失败归因 · ${esc(d.failure.cause)}</b><p>${esc(d.failure.text)}</p></div></section>` : ""}
    <section style="margin-top:28px">
      <details><summary>Issue 原文</summary><div class="body"><div class="prose">${esc(d.issue) || "（数据集中没有这道题的 issue）"}</div></div></details>
    </section>
    <section style="margin-top:36px">
      <h2>各配置的结果</h2>
      ${tabs("run", d.runs.map((r) => ({ label: esc(r.label), body: runPanel(iid, r) })), Math.max(0, d.runs.findIndex((r) => !r.void)))}
    </section>
    ${d.selection ? `<section><h2>候选选择</h2><p class="hint">3 次断网运行给出的候选补丁有对有错。Listwise 对比把候选放在一起，挑最可能对的那个。</p>${candidates(d.selection)}</section>` : ""}`;
}

function output(text) {
  return `<details class="quiet obs"><summary>输出 · ${text.split("\n").length} 行</summary><div class="body"><pre class="code">${esc(text)}</pre></div></details>`;
}

function steps(messages) {
  const groups = [];
  for (const m of messages) {
    if (m.role === "tool" && groups.at(-1)?.role === "assistant") groups.at(-1).outputs.push(m.content);
    else groups.push({ ...m, outputs: [] });
  }
  let n = 0;
  return groups.map((m, idx) => {
    if (m.role === "system" || m.role === "user") {
      const label = m.role === "system" ? "系统提示" : idx <= 1 ? "任务说明" : "用户消息";
      return `<div class="step"><div class="step-no"></div><div class="step-body"><details class="quiet" ${label === "用户消息" ? "open" : ""}>
        <summary>${label}</summary><div class="body"><div class="prose">${esc(m.content)}</div></div></details></div></div>`;
    }
    if (m.role !== "assistant") return `<div class="step"><div class="step-no"></div><div class="step-body"><div class="msg-role">结束</div><div class="msg-text">${esc(m.content)}</div></div></div>`;
    n += 1;
    const cmds = m.commands.map((c, k) => `<pre class="code cmd">${esc(c)}</pre>${m.outputs[k] != null ? output(m.outputs[k]) : ""}`);
    return `<div class="step"><div class="step-no">${n}</div><div class="step-body">
      ${m.content.trim() ? `<p class="msg-text">${esc(m.content.trim())}</p>` : ""}
      ${m.reasoning ? `<details class="quiet reasoning"><summary>思考过程</summary><div class="body"><div class="prose">${esc(m.reasoning)}</div></div></details>` : ""}
      ${cmds.join("")}${m.outputs.slice(m.commands.length).map(output).join("")}</div></div>`;
  }).join("");
}

async function traj(key, iid) {
  const [t, r] = await Promise.all([api(`trajectories/${key}/${encodeURIComponent(iid)}`), api("runs")]);
  const run = r.runs.find((x) => x.key === key);
  const views = [{ label: "主 Agent", body: `<div class="steps">${steps(t.messages)}</div>` }].concat(
    t.reviews.map((rv, n) => ({ label: `审查者 #${n + 1} · ${rv.passed ? "放行" : "驳回"}`, body: `<div class="steps">${steps(rv.messages)}</div>` })),
  );
  return `
    <a class="back" href="#/instance/${iid}">← ${esc(short(iid))}</a>
    <div class="page-head">
      <div class="eyebrow">${esc(run?.label ?? key)} · ${esc(iid)}</div>
      <h1>Agent 轨迹</h1>
      <p class="hint" style="margin-top:12px">每一步是一次模型调用：说明、执行的命令和命令输出。输出默认折叠。</p>
    </div>
    ${views.length > 1 ? tabs("traj", views) : views[0].body}`;
}

async function verifier() {
  const v = await api("verifier");
  const byInst = {};
  for (const s of v.scores) (byInst[s.instance] ??= []).push(s);
  const mixedScored = Object.entries(byInst).filter(([, ss]) => new Set(ss.map((s) => s.resolved)).size > 1);
  const strip = mixedScored.map(([iid, ss]) => `<div class="strip-row"><a href="#/instance/${iid}" class="muted">${esc(short(iid))}</a>
    <div class="strip-track">${ss.map((s) => `<i class="${status(s.resolved)}" style="left:${s.score}%" title="${s.score} 分 · ${s.resolved ? "正确" : "错误"}"></i>`).join("")}</div></div>`);
  const max = v.n_mixed;
  const bars = v.selection.map((s) => `<div class="bar-row ${s.key === "listwise" ? "key" : ""} ${["oracle", "pass1"].includes(s.key) ? "ref" : ""}">
    <span>${esc(s.label)}</span><div class="bar-track"><b style="width:${(s.mixed / max) * 100}%"></b></div><span class="num r">${fixed(s.mixed)}/${max}</span></div>`);
  const lw = v.listwise;
  const cards = v.instances.map((i) => `<div class="card"><h3><a href="#/instance/${i.id}">${esc(i.id)}</a></h3>${candidates(i)}</div>`);
  return `
    <div class="page-head">
      <div class="eyebrow">验证者</div>
      <h1>能不能从候选里挑出对的补丁？</h1>
      <p class="lede">驳回重做修不好难题。但 3 次断网运行合起来能解 ${fixed(v.selection.find((s) => s.key === "oracle").total, 0)} 题，单次只有 39–42：模型能写出正确补丁，只是不稳定。于是换个问法：不重做，只挑选。</p>
    </div>
    <section>
      <div class="stats">
        <div class="stat"><b class="num">${v.n_patches}</b><span>去重后的补丁</span></div>
        <div class="stat"><b class="num">${v.n_resolved} / ${v.n_patches - v.n_resolved}</b><span>正确 / 错误（隐藏测试）</span></div>
        <div class="stat"><b class="num">${v.n_mixed}</b><span>候选有对有错的题</span></div>
      </div>
    </section>
    <section>
      <h2>单独打分：只学会了判断"题难不难"</h2>
      <p class="hint">Pointwise：给每个补丁单独打 0–100 分。全局 AUROC 看着不错，但只用题目平均分（完全不看补丁）也一样高。</p>
      <div class="stats">
        <div class="stat"><b class="num">${fixed(v.auroc.global, 3)}</b><span>AUROC · 全部补丁</span></div>
        <div class="stat"><b class="num">${fixed(v.auroc.instance_mean, 3)}</b><span>AUROC · 只用题目平均分</span></div>
        <div class="stat key"><b class="num">${fixed(v.auroc.within, 3)}</b><span>同题内对 vs 错（${v.auroc.pairs} 对）· 低于随机</span></div>
      </div>
      <h3 style="margin:28px 0 4px">同一题的候选，分数分不开对错</h3>
      <p class="hint">每行一道题，点是它的补丁。绿点（正确）并不比橙点（错误）更靠右。</p>
      <div class="strip">${strip.join("")}</div>
      <div class="axis"><span>0 分</span><span>50</span><span>100</span></div>
    </section>
    <section>
      <h2>放在一起比：第一个正向信号</h2>
      <p class="hint">在 ${max} 道有对有错的题上，各方法平均选中几道正确补丁。Listwise 的 ${lw.calls} 次调用中 ${lw.correct} 次选对（随机期望 ${fixed(lw.random)}），单侧 p = ${fixed(lw.p, 2)}：方向正面，但样本太少，不显著。</p>
      <div class="bars">${bars.join("")}</div>
    </section>
    <section>
      <h2>${max} 道有对有错的题</h2>
      <p class="hint">"打分"是 pointwise 分数，"被选"是 listwise 在 3 次不同候选顺序下选中它的次数。</p>
      <div class="grid" style="grid-template-columns:1fr">${cards.join("")}</div>
    </section>`;
}

/* ---------- router & interactions ---------- */

const routes = [
  [/^$/, overview, "overview"],
  [/^experiments$/, experiments, "experiments"],
  [/^instance\/(.+)$/, instance, "experiments"],
  [/^traj\/([^/]+)\/(.+)$/, traj, "experiments"],
  [/^verifier$/, verifier, "verifier"],
];
let current = 0;

async function render() {
  const path = decodeURIComponent(location.hash.replace(/^#\/?/, ""));
  const [re, page, nav] = routes.find(([re]) => re.test(path)) ?? routes[0];
  const token = ++current;
  document.querySelectorAll("nav a").forEach((a) => a.classList.toggle("active", a.dataset.nav === nav));
  app.innerHTML = `<p class="loading">加载中…</p>`;
  let html;
  try {
    html = await page(...(path.match(re) ?? []).slice(1));
  } catch (e) {
    html = e.message.startsWith("404")
      ? `<p class="error">没有这道题或这条轨迹。<a href="#/experiments">查看全部题目</a></p>`
      : `<p class="error">没能加载数据（${esc(e.message)}）。请确认后端正在运行，且 <code>runs/</code> 目录存在。</p>`;
  }
  if (token !== current) return;
  app.innerHTML = html;
  window.scrollTo(0, 0);
  updateCount();
}

function updateCount() {
  const rows = [...app.querySelectorAll("[data-filterable] tbody tr")];
  const count = app.querySelector("[data-count]");
  if (count) count.textContent = `${rows.filter((r) => !r.hidden).length} 道题`;
}

app.addEventListener("click", (e) => {
  const tab = e.target.closest("[data-tab]");
  if (tab) {
    const group = tab.dataset.tab.split(":")[0];
    app.querySelectorAll(`[data-tab^="${group}:"]`).forEach((b) => b.setAttribute("aria-selected", b === tab));
    app.querySelectorAll(`[data-panel^="${group}:"]`).forEach((p) => (p.hidden = p.dataset.panel !== tab.dataset.tab));
    return;
  }
  const filter = e.target.closest("[data-filter]");
  if (filter) {
    app.querySelectorAll("[data-filter]").forEach((b) => b.setAttribute("aria-pressed", b === filter));
    app.querySelectorAll("[data-filterable] tbody tr").forEach((r) => {
      r.hidden = filter.dataset.filter !== "all" && !r.dataset.tags.split(" ").includes(filter.dataset.filter);
    });
    updateCount();
    return;
  }
  const row = e.target.closest("tr[data-href]");
  if (row && !e.target.closest("a")) location.hash = row.dataset.href;
});

app.addEventListener("mouseover", (e) => {
  const cell = e.target.closest(".cell");
  if (!cell) return;
  app.querySelectorAll(".cell.hl").forEach((c) => c.classList.remove("hl"));
  app.querySelectorAll(`.cell[data-iid="${cell.dataset.iid}"]`).forEach((c) => c.classList.add("hl"));
  const tip = app.querySelector(".tip");
  if (tip) tip.textContent = cell.dataset.tip;
});

window.addEventListener("hashchange", render);
render();
