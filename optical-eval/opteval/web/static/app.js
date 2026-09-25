"use strict";

// ------------------------------------------------------------------
// 定数・状態
// ------------------------------------------------------------------
const FRAUNHOFER = { g: 0.435835, F: 0.4861327, e: 0.546074, d: 0.5875618, C: 0.6562725 };
const PARAMS = [
  ["curvature", "曲率"], ["thickness", "面間隔"], ["conic", "コーニック"],
  ["A4", "A4"], ["A6", "A6"], ["A8", "A8"], ["A10", "A10"],
];
const STORAGE_KEY = "opteval.lens.v1";

const state = {
  lens: null,
  summary: null,
  view: "layout",
  cache: {},          // view+options -> response
  version: 0,         // レンズ編集ごとに増加
  pending: 0,
  viewOpts: { mtf: { max_freq: "" }, spot: { rings: 10 }, layout: { rays: 7 } },
  optResult: null,
};

const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => Array.from(root.querySelectorAll(s));

function el(tag, attrs = {}, ...children) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") e.className = v;
    else if (k === "dataset") Object.assign(e.dataset, v);
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (k === "value") e.value = v;
    else if (v === true) e.setAttribute(k, "");
    else e.setAttribute(k, v);
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    e.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return e;
}

// ------------------------------------------------------------------
// 数値の表示と解釈
// ------------------------------------------------------------------
function isInf(v) {
  return v === "inf" || v === "Infinity" || v === Infinity || v === null;
}
function fmt(v, digits = 6) {
  if (v === undefined || v === "") return "";
  if (isInf(v)) return "inf";
  if (typeof v === "string") return v;
  if (v === 0) return "0";
  const a = Math.abs(v);
  if (a >= 1e6 || a < 1e-4) return v.toExponential(4);
  return String(Number(v.toPrecision(digits + 2)));
}
/** 入力文字列を数値へ。{inf:true} なら "inf" を許可、{empty:x} なら空欄で x。失敗時は undefined */
function parseNum(s, { inf = false, empty } = {}) {
  s = String(s).trim();
  if (s === "") return empty;
  if (inf && /^(inf|infinity|∞)$/i.test(s)) return "inf";
  const v = Number(s);
  return Number.isFinite(v) ? v : undefined;
}

// ------------------------------------------------------------------
// レンズデータ
// ------------------------------------------------------------------
function defaultLens() {
  return normalizeLens({
    title: "新しいレンズ",
    wavelengths: [FRAUNHOFER.F, FRAUNHOFER.d, FRAUNHOFER.C],
    wavelength_weights: [1, 1, 1],
    primary: 1,
    fields: { type: "angle", values: [0, 5, 10] },
    aperture: { type: "EPD", value: 10 },
    surfaces: [
      { radius: "inf", thickness: "inf", material: "AIR", comment: "OBJ" },
      { radius: 51.68, thickness: 4, material: "N-BK7", stop: true },
      { radius: -51.68, thickness: 48, material: "AIR" },
      { radius: "inf", thickness: 0, material: "AIR", comment: "IMG" },
    ],
  });
}

function normalizeLens(d) {
  const lens = JSON.parse(JSON.stringify(d));
  lens.title = lens.title || "";
  lens.wavelengths = (lens.wavelengths || ["F", "d", "C"]).map((w) =>
    typeof w === "string" && FRAUNHOFER[w] ? FRAUNHOFER[w] : Number(w));
  const nw = lens.wavelengths.length;
  if (!Array.isArray(lens.wavelength_weights) || lens.wavelength_weights.length !== nw) {
    lens.wavelength_weights = Array(nw).fill(1);
  }
  if (!(lens.primary >= 0 && lens.primary < nw)) lens.primary = Math.floor(nw / 2);
  lens.fields = lens.fields || { type: "angle", values: [0] };
  lens.fields.type = lens.fields.type || "angle";
  lens.aperture = lens.aperture || { type: "EPD", value: 10 };
  lens.aperture.type = String(lens.aperture.type || "EPD").toUpperCase();
  for (const s of lens.surfaces) {
    if (isInf(s.radius) || s.radius === 0) s.radius = "inf";
    if (isInf(s.thickness)) s.thickness = "inf";
    s.material = s.material || "AIR";
  }
  const opt = lens.optimization || {};
  lens.optimization = {
    variables: (opt.variables || []).map((v) => ({ ...v, param: v.param === "radius" ? "curvature" : v.param })),
    targets: opt.targets || {},
    iterations: opt.iterations ?? 50,
    rings: opt.rings ?? 4,
    ...(opt.focus ? { focus: opt.focus } : {}),
  };
  return lens;
}

/** API / ファイル用に整形（空の optimization は省く） */
function lensForExport() {
  const lens = JSON.parse(JSON.stringify(state.lens));
  const o = lens.optimization;
  if (!o.variables.length && !Object.keys(o.targets).length && !o.focus) delete lens.optimization;
  return lens;
}

function persist() {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(state.lens)); } catch (_) { /* 保存できなくても動作は継続 */ }
}

function setLens(lens, { keepOpt = false } = {}) {
  state.lens = normalizeLens(lens);
  if (!keepOpt) { state.optResult = null; }
  renderAll();
  lensChanged();
}

/** 編集後に呼ぶ: キャッシュを破棄し、自動更新なら再計算 */
function lensChanged({ rerender = false } = {}) {
  state.version++;
  state.cache = {};
  persist();
  if (rerender) renderEditors();
  if ($("#auto").checked) scheduleRefresh();
}

let refreshTimer = null;
function scheduleRefresh(delay = 350) {
  clearTimeout(refreshTimer);
  refreshTimer = setTimeout(refresh, delay);
}

// ------------------------------------------------------------------
// API
// ------------------------------------------------------------------
async function apiCall(path, body) {
  const res = await fetch(path, body === undefined ? {} : {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const ctype = res.headers.get("Content-Type") || "";
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    if (ctype.includes("json")) { try { msg = (await res.json()).error || msg; } catch (_) { /* ignore */ } }
    throw new Error(msg);
  }
  return ctype.includes("json") ? res.json() : res.text();
}

function setBusy(on) {
  state.pending += on ? 1 : -1;
  $("#busy").hidden = state.pending <= 0;
}
function showError(msg) {
  const e = $("#error");
  e.textContent = msg || "";
  e.hidden = !msg;
}

function viewKey(view) {
  return view + JSON.stringify(state.viewOpts[view] || {});
}

async function refresh() {
  const version = state.version;
  const lens = lensForExport();
  const jobs = [];
  if (!state.summary || state.summaryVersion !== version) {
    jobs.push(apiCall("/api/analyze", { lens, analysis: "summary" }).then((r) => {
      if (version !== state.version) return;
      state.summary = r;
      state.summaryVersion = version;
      renderSummaryBits();
    }));
  }
  const view = state.view;
  const key = viewKey(view);
  if (view !== "summary" && !state.cache[key]) {
    jobs.push(apiCall("/api/analyze", { lens, analysis: view, options: state.viewOpts[view] || {} }).then((r) => {
      if (version !== state.version) return;
      state.cache[key] = r;
    }));
  }
  if (!jobs.length) { renderView(); return; }
  setBusy(true);
  try {
    await Promise.all(jobs);
    if (version === state.version) showError("");
  } catch (err) {
    if (version === state.version) showError(err.message);
  } finally {
    setBusy(false);
    if (version === state.version) renderView();
  }
}

// ------------------------------------------------------------------
// 描画: レンズデータ表
// ------------------------------------------------------------------
function isVar(i, param) {
  return state.lens.optimization.variables.some((v) => v.surface === i && v.param === param);
}
function toggleVar(i, param) {
  const vars = state.lens.optimization.variables;
  const k = vars.findIndex((v) => v.surface === i && v.param === param);
  if (k >= 0) vars.splice(k, 1); else vars.push({ surface: i, param });
  persist();
  renderEditors();
}

function numInput({ value, onCommit, inf = false, empty, placeholder, disabled, cls = "num", title }) {
  const inp = el("input", { class: cls, value: fmt(value), placeholder, disabled, title, spellcheck: "false" });
  inp.addEventListener("change", () => {
    const v = parseNum(inp.value, { inf, empty });
    if (v === undefined) { inp.classList.add("bad"); return; }
    inp.classList.remove("bad");
    onCommit(v);
  });
  return inp;
}
function textInput({ value, onCommit, list, cls = "", placeholder, disabled }) {
  const inp = el("input", { type: "text", class: cls, value: value ?? "", list, placeholder, disabled, spellcheck: "false" });
  inp.addEventListener("change", () => onCommit(inp.value.trim()));
  return inp;
}
function withV(input, i, param) {
  const on = isVar(i, param);
  const b = el("button", {
    type: "button", class: "vbtn" + (on ? " on" : ""), title: on ? "変数を解除" : "最適化の変数にする",
    onclick: () => toggleVar(i, param),
  }, "V");
  return el("div", { class: "cell" }, input, b);
}

function renderLensTable() {
  const lens = state.lens;
  const tb = $("#lens-table tbody");
  tb.replaceChildren();
  const last = lens.surfaces.length - 1;
  const info = state.summary ? state.summary.surfaces : [];
  lens.surfaces.forEach((s, i) => {
    const isObj = i === 0, isImg = i === last, isSurf = !isObj && !isImg;
    const upd = (key) => (v) => { s[key] = v; lensChanged(); };
    const label = isObj ? "OBJ" : isImg ? "IMG" : s.stop ? el("span", { class: "sto" }, "STO") : String(i);
    const sdInfo = info.length === lens.surfaces.length ? info[i] : null;

    const radius = numInput({ value: s.radius, inf: true, empty: "inf", onCommit: upd("radius"), disabled: isObj });
    const thick = numInput({
      value: isImg ? "" : s.thickness, inf: isObj, onCommit: upd("thickness"), disabled: isImg,
      title: isObj ? "物体距離（inf = 無限遠）" : undefined,
    });
    const mat = textInput({ value: s.material, list: "glass-list", onCommit: (v) => { s.material = v || "AIR"; lensChanged(); }, disabled: isImg });
    const n = sdInfo && sdInfo.n !== null && !isImg ? Number(sdInfo.n).toFixed(5) : "";
    const sdPh = sdInfo && sdInfo.sd !== null && i > 0 ? `自動 ${Number(sdInfo.sd).toFixed(3)}` : "";
    const sd = numInput({
      value: s.semi_diameter ?? "", empty: null, placeholder: sdPh, disabled: isObj,
      onCommit: (v) => { if (v === null) delete s.semi_diameter; else s.semi_diameter = v; lensChanged(); },
    });
    const conic = numInput({ value: s.conic || "", empty: 0, placeholder: "0", disabled: !isSurf,
      onCommit: (v) => { if (v) s.conic = v; else delete s.conic; lensChanged(); } });
    const asph = textInput({
      value: (s.aspheric || []).map((a) => fmt(a)).join(", "), cls: "wide", placeholder: isSurf ? "例: 1e-6, -2e-9" : "",
      disabled: !isSurf,
      onCommit: (v) => {
        const parts = v ? v.split(/[,\s]+/).filter(Boolean).map(Number) : [];
        if (parts.some((x) => !Number.isFinite(x))) { asph.classList.add("bad"); return; }
        asph.classList.remove("bad");
        if (parts.length) s.aspheric = parts; else delete s.aspheric;
        lensChanged();
      },
    });
    const stop = isSurf ? el("input", {
      type: "radio", name: "stop", checked: !!s.stop, title: "開口絞り",
      onchange: () => { lens.surfaces.forEach((t) => delete t.stop); s.stop = true; lensChanged({ rerender: true }); },
    }) : "";
    const comment = textInput({ value: s.comment || "", onCommit: (v) => { if (v) s.comment = v; else delete s.comment; lensChanged(); } });
    const ins = !isImg ? el("button", { type: "button", class: "rowbtn", title: "この面の後ろに面を挿入", onclick: () => insertSurface(i + 1) }, "＋") : "";
    const del = isSurf && last > 2 ? el("button", { type: "button", class: "rowbtn del", title: "この面を削除", onclick: () => deleteSurface(i) }, "×") : "";

    tb.append(el("tr", {},
      el("td", { class: "label" }, label),
      el("td", {}, isSurf ? withV(radius, i, "curvature") : radius),
      el("td", {}, isSurf ? withV(thick, i, "thickness") : thick),
      el("td", {}, mat),
      el("td", { class: "ro" }, n),
      el("td", {}, sd),
      el("td", {}, isSurf ? withV(conic, i, "conic") : conic),
      el("td", {}, asph),
      el("td", { class: "center" }, stop),
      el("td", {}, comment),
      el("td", { class: "center" }, ins, del),
    ));
  });
}

function insertSurface(at) {
  const lens = state.lens;
  lens.surfaces.splice(at, 0, { radius: "inf", thickness: 5, material: "AIR" });
  for (const v of lens.optimization.variables) if (v.surface >= at) v.surface++;
  lensChanged({ rerender: true });
}
function deleteSurface(i) {
  const lens = state.lens;
  const wasStop = lens.surfaces[i].stop;
  lens.surfaces.splice(i, 1);
  const o = lens.optimization;
  o.variables = o.variables.filter((v) => v.surface !== i);
  for (const v of o.variables) if (v.surface > i) v.surface--;
  if (wasStop && lens.surfaces.length > 2) lens.surfaces[Math.min(i, lens.surfaces.length - 2)].stop = true;
  lensChanged({ rerender: true });
}

// ------------------------------------------------------------------
// 描画: システム
// ------------------------------------------------------------------
function renderSystem() {
  const lens = state.lens;
  // 波長
  const wtb = $("#wl-table tbody");
  wtb.replaceChildren();
  lens.wavelengths.forEach((w, i) => {
    wtb.append(el("tr", {},
      el("td", { class: "label" }, i + 1),
      el("td", {}, numInput({ value: w, onCommit: (v) => { if (v > 0) { lens.wavelengths[i] = v; lensChanged(); } } })),
      el("td", {}, numInput({ value: lens.wavelength_weights[i], onCommit: (v) => { lens.wavelength_weights[i] = v; lensChanged(); } })),
      el("td", { class: "center" }, el("input", {
        type: "radio", name: "primary", checked: lens.primary === i,
        onchange: () => { lens.primary = i; lensChanged(); },
      })),
      el("td", { class: "center" }, lens.wavelengths.length > 1 ? el("button", {
        type: "button", class: "rowbtn del", title: "削除",
        onclick: () => {
          lens.wavelengths.splice(i, 1); lens.wavelength_weights.splice(i, 1);
          if (lens.primary >= lens.wavelengths.length || lens.primary === i) lens.primary = Math.min(lens.primary, lens.wavelengths.length - 1);
          else if (lens.primary > i) lens.primary--;
          lensChanged({ rerender: true });
        },
      }, "×") : ""),
    ));
  });
  // 視野
  $("#field-type").value = lens.fields.type;
  const ftb = $("#field-table tbody");
  ftb.replaceChildren();
  lens.fields.values.forEach((f, i) => {
    ftb.append(el("tr", {},
      el("td", { class: "label" }, i + 1),
      el("td", {}, numInput({ value: f, onCommit: (v) => { lens.fields.values[i] = v; lensChanged(); } })),
      el("td", { class: "center" }, lens.fields.values.length > 1 ? el("button", {
        type: "button", class: "rowbtn del", title: "削除",
        onclick: () => { lens.fields.values.splice(i, 1); lensChanged({ rerender: true }); },
      }, "×") : ""),
    ));
  });
  // 開口
  $("#ap-type").value = lens.aperture.type;
  $("#ap-value").value = fmt(lens.aperture.value);
}

// ------------------------------------------------------------------
// 描画: 最適化
// ------------------------------------------------------------------
function currentParamValue(v) {
  const s = state.lens.surfaces[v.surface];
  if (!s) return "";
  if (v.param === "curvature") return isInf(s.radius) ? 0 : 1 / s.radius;
  if (v.param === "thickness") return s.thickness;
  if (v.param === "conic") return s.conic || 0;
  const k = (parseInt(v.param.slice(1), 10) - 4) / 2;
  return (s.aspheric || [])[k] || 0;
}

function renderOpt() {
  const lens = state.lens;
  const o = lens.optimization;
  const tb = $("#var-table tbody");
  tb.replaceChildren();
  const nsurf = lens.surfaces.length - 2;
  o.variables.forEach((v, i) => {
    const sel = el("select", { onchange: () => { v.param = sel.value; persist(); renderEditors(); } },
      PARAMS.map(([k, name]) => el("option", { value: k, selected: v.param === k }, name)));
    const surf = el("select", { onchange: () => { v.surface = Number(surf.value); persist(); renderEditors(); } },
      Array.from({ length: nsurf }, (_, k) => el("option", { value: k + 1, selected: v.surface === k + 1 }, k + 1)));
    const bound = (key) => numInput({
      value: v[key] ?? "", empty: null, placeholder: "—",
      onCommit: (x) => { if (x === null) delete v[key]; else v[key] = x; persist(); },
    });
    tb.append(el("tr", {},
      el("td", {}, surf), el("td", {}, sel), el("td", {}, bound("min")), el("td", {}, bound("max")),
      el("td", { class: "ro" }, fmt(currentParamValue(v), 6)),
      el("td", { class: "center" }, el("button", {
        type: "button", class: "rowbtn del", title: "削除",
        onclick: () => { o.variables.splice(i, 1); persist(); renderEditors(); },
      }, "×")),
    ));
  });
  if (!o.variables.length) {
    tb.append(el("tr", {}, el("td", { colspan: 6, class: "ro", style: "text-align:left" }, "（変数なし）")));
  }
  $("#opt-efl-on").checked = o.targets.efl !== undefined;
  $("#opt-efl").value = o.targets.efl !== undefined ? fmt(o.targets.efl) : "";
  $("#opt-efl-w").value = o.targets.efl_weight !== undefined ? fmt(o.targets.efl_weight) : "";
  $("#opt-focus").checked = o.focus === "paraxial";
  $("#opt-iter").value = o.iterations ?? "";
  $("#opt-rings").value = o.rings ?? "";
  renderOptResult();
}

function renderOptResult() {
  const box = $("#opt-result");
  box.replaceChildren();
  const r = state.optResult;
  if (!r) return;
  const h = r.merit_history;
  const first = h[0], last = h[h.length - 1];
  // 収束履歴（log スケール）
  const W = 400, H = 120, P = 26;
  const ys = h.map((m) => Math.log10(Math.max(m, 1e-300)));
  const ymin = Math.min(...ys), ymax = Math.max(...ys);
  const sx = (i) => P + (i / Math.max(h.length - 1, 1)) * (W - P - 6);
  const sy = (y) => 6 + (ymax === ymin ? 0.5 : (ymax - y) / (ymax - ymin)) * (H - P);
  const svg = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="評価関数の推移">
    <line class="axis" x1="${P}" y1="${H - P + 6}" x2="${W}" y2="${H - P + 6}"/>
    <line class="axis" x1="${P}" y1="0" x2="${P}" y2="${H - P + 6}"/>
    <polyline class="line" points="${ys.map((y, i) => `${sx(i).toFixed(1)},${sy(y).toFixed(1)}`).join(" ")}"/>
    <text x="2" y="12">1e${ymax.toFixed(0)}</text><text x="2" y="${H - P + 6}">1e${ymin.toFixed(0)}</text>
    <text x="${W - 60}" y="${H - 4}">反復 ${h.length - 1}</text></svg>`;
  const vars = r.variables.map((v) => el("tr", {},
    el("td", {}, `面 ${v.surface}`), el("td", {}, PARAMS.find((p) => p[0] === v.param)?.[1] || v.param),
    el("td", {}, fmt(v.before, 6)), el("td", {}, fmt(v.after, 6))));
  const fields = state.lens.fields.values;
  box.append(el("div", { class: "opt-result" },
    el("h4", {}, "最適化結果"),
    el("div", {}, "評価関数: ", el("b", {}, first.toExponential(3)), " → ", el("b", { class: "good" }, last.toExponential(3)),
      ` （${(100 * (1 - last / first)).toFixed(2)} % 減少）`),
    (() => { const d = el("div"); d.innerHTML = svg; return d; })(),
    el("div", { class: "table-wrap" }, el("table", { class: "grid" },
      el("thead", {}, el("tr", {}, el("th", {}, "面"), el("th", {}, "パラメータ"), el("th", {}, "変更前"), el("th", {}, "変更後"))),
      el("tbody", {}, vars))),
    el("p", {}, "RMS スポット: ", r.rms_spot_um.map((v, i) => `${fields[i] ?? i}: ${Number(v).toFixed(2)} µm`).join(" / ")),
    el("div", { class: "toolbar" },
      el("button", { type: "button", class: "primary", onclick: applyOpt }, "結果をレンズに適用"),
      el("button", { type: "button", onclick: () => { state.optResult = null; renderOptResult(); } }, "破棄")),
  ));
}

async function runOptimize() {
  const btn = $("#btn-optimize");
  const lens = lensForExport();
  const cfg = state.lens.optimization;
  if (!cfg.variables.length) { showError("変数がありません。レンズデータの V ボタンか「＋ 変数を追加」で指定してください。"); return; }
  btn.disabled = true;
  btn.textContent = "最適化中…";
  setBusy(true);
  try {
    const r = await apiCall("/api/optimize", { lens, config: cfg });
    const after = normalizeLens(r.lens);
    const saved = state.lens;
    r.variables = cfg.variables.map((v) => {
      const before = currentParamValue(v);
      state.lens = after;
      const a = currentParamValue(v);
      state.lens = saved;
      return { ...v, before, after: a };
    });
    state.optResult = r;
    showError("");
    renderOptResult();
  } catch (err) {
    showError(err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "最適化を実行";
    setBusy(false);
  }
}

function applyOpt() {
  const r = state.optResult;
  if (!r) return;
  const lens = normalizeLens(r.lens);
  lens.optimization = state.lens.optimization;
  state.optResult = null;
  state.lens = lens;
  renderAll();
  lensChanged();
}

// ------------------------------------------------------------------
// 描画: 評価ビュー
// ------------------------------------------------------------------
function table(header, rows, cls = "grid") {
  return el("div", { class: "table-wrap" }, el("table", { class: cls },
    header ? el("thead", {}, el("tr", {}, header.map((h) => el("th", {}, h)))) : null,
    el("tbody", {}, rows.map((r) => el("tr", {}, r.map((c) => el("td", {}, c)))))));
}

function renderSummaryBits() {
  const s = state.summary;
  const m = $("#metrics");
  m.replaceChildren();
  if (s) {
    const fo = Object.fromEntries(s.first_order);
    const chips = [
      ["EFL", fo["焦点距離 EFL"]], ["F/#", fo["F ナンバー"]], ["BFL", fo["バックフォーカス BFL"]],
      ["全長", fo["全長（S1→像面）"]], ["像高", fo["最大像高（近軸）"]],
    ];
    for (const [k, v] of chips) if (v) m.append(el("span", { class: "chip" }, `${k} `, el("b", {}, v)));
  }
  // n と自動有効半径を表に反映（入力中のフォーカスを奪わないよう、フォーカスがなければ再描画）
  if (!document.activeElement || !$("#lens-table").contains(document.activeElement)) renderLensTable();
  if (state.view === "summary" || state.view === "seidel") renderView();
}

const VIEW_OPTIONS = {
  mtf: [["max_freq", "最大周波数 [lp/mm]（空欄 = カットオフ）"]],
  spot: [["rings", "リング数"]],
  layout: [["rays", "光線数/視野"]],
};

function renderViewOptions() {
  const box = $("#view-options");
  box.replaceChildren();
  for (const [key, label] of VIEW_OPTIONS[state.view] || []) {
    const o = state.viewOpts[state.view];
    const inp = el("input", { value: o[key] ?? "" });
    inp.addEventListener("change", () => { o[key] = inp.value.trim(); refresh(); });
    box.append(el("label", {}, label, " ", inp));
  }
}

function renderView() {
  const v = $("#view");
  v.replaceChildren();
  const s = state.summary;
  if (state.view === "summary") {
    if (!s) { v.append(el("div", { class: "empty" }, "「評価 ▶」を押すと結果が表示されます")); return; }
    v.append(
      el("h3", {}, "一次量（近軸）"), table(null, s.first_order, "grid kv"),
      el("h3", {}, "結像性能"), table(s.performance.header, s.performance.rows),
      el("p", { class: "hint" }, "Strehl は Maréchal 近似。スポットは重心基準、波面は主光線基準の参照球で評価。"),
      el("h3", {}, "Seidel 波面収差係数（瞳端・最大画角）"),
      table(null, Object.entries(s.seidel.wave).map(([k, x]) => [k, x === null ? "-" : `${x.toFixed(3)} λ`]), "grid kv"),
    );
    return;
  }
  const r = state.cache[viewKey(state.view)];
  if (r && r.image) v.append(el("img", { class: "figure", src: "data:image/png;base64," + r.image, alt: state.view }));
  else if (!state.pending) v.append(el("div", { class: "empty" }, "「評価 ▶」を押すと結果が表示されます"));
  if (state.view === "seidel" && s) {
    v.append(el("h3", {}, "面ごとの Seidel 和 [mm]"), table(s.seidel.header, s.seidel.rows));
  }
}

// ------------------------------------------------------------------
// 全体
// ------------------------------------------------------------------
function renderEditors() {
  $("#title").value = state.lens.title || "";
  renderLensTable();
  renderSystem();
  renderOpt();
}
function renderAll() {
  renderEditors();
  renderViewOptions();
  renderView();
}

function download(name, data, type) {
  const url = URL.createObjectURL(new Blob([data], { type }));
  const a = el("a", { href: url, download: name });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function safeName(s) {
  return (s || "lens").replace(/[\\/:*?"<>|\s]+/g, "_").slice(0, 60) || "lens";
}

function bindUI() {
  // タブ
  for (const b of $$('.tabs[data-group="left"] button')) {
    b.addEventListener("click", () => {
      $$('.tabs[data-group="left"] button').forEach((x) => x.classList.toggle("active", x === b));
      $$(".editor .tabpanel").forEach((p) => { p.hidden = p.dataset.panel !== b.dataset.tab; });
      try { localStorage.setItem("opteval.tab", b.dataset.tab); } catch (_) { /* ignore */ }
    });
  }
  for (const b of $$('.tabs[data-group="right"] button')) {
    b.addEventListener("click", () => {
      state.view = b.dataset.view;
      $$('.tabs[data-group="right"] button').forEach((x) => x.classList.toggle("active", x === b));
      renderViewOptions();
      renderView();
      refresh();
      try { localStorage.setItem("opteval.view", state.view); } catch (_) { /* ignore */ }
    });
  }

  $("#title").addEventListener("change", (e) => { state.lens.title = e.target.value; persist(); });
  $("#btn-run").addEventListener("click", () => { state.cache = {}; state.summaryVersion = -1; refresh(); });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); document.activeElement?.blur(); setTimeout(refresh, 0); }
  });
  $("#auto").addEventListener("change", (e) => { if (e.target.checked) refresh(); });

  $("#btn-new").addEventListener("click", () => {
    if (confirm("新しいレンズを作成します。現在の内容は破棄されます（保存していない場合）。")) setLens(defaultLens());
  });
  $("#example-select").addEventListener("change", async (e) => {
    const id = e.target.value;
    e.target.value = "";
    if (!id) return;
    try { setLens(await apiCall(`/api/examples/${encodeURIComponent(id)}`)); } catch (err) { showError(err.message); }
  });
  $("#file-open").addEventListener("change", async (e) => {
    const f = e.target.files[0];
    e.target.value = "";
    if (!f) return;
    try {
      const d = JSON.parse(await f.text());
      if (!Array.isArray(d.surfaces)) throw new Error("surfaces がありません");
      setLens(d);
    } catch (err) { showError(`ファイルを読み込めません: ${err.message}`); }
  });
  $("#btn-save").addEventListener("click", () => {
    download(`${safeName(state.lens.title)}.json`, JSON.stringify(lensForExport(), null, 2) + "\n", "application/json");
  });
  $("#btn-report").addEventListener("click", async () => {
    setBusy(true);
    try {
      const html = await apiCall("/api/report", { lens: lensForExport() });
      download(`${safeName(state.lens.title)}_report.html`, html, "text/html");
    } catch (err) { showError(err.message); } finally { setBusy(false); }
  });

  // レンズデータ
  $("#btn-add-surface").addEventListener("click", () => insertSurface(state.lens.surfaces.length - 1));
  $("#btn-focus").addEventListener("click", async () => {
    const s = state.summary && state.summaryVersion === state.version ? state.summary : null;
    const fo = s ? Object.fromEntries(s.first_order) : null;
    const d = fo ? parseFloat(fo["近軸像距離"]) : NaN;
    if (!Number.isFinite(d)) { showError("先に評価を実行してください"); return; }
    const surfs = state.lens.surfaces;
    surfs[surfs.length - 2].thickness = d;
    lensChanged({ rerender: true });
  });

  // システム
  $("#btn-add-wl").addEventListener("click", () => {
    const L = state.lens;
    L.wavelengths.push(0.55); L.wavelength_weights.push(1);
    lensChanged({ rerender: true });
  });
  for (const b of $$("[data-wl-preset]")) {
    b.addEventListener("click", () => {
      const L = state.lens;
      const keys = b.dataset.wlPreset.split("");
      L.wavelengths = keys.map((k) => FRAUNHOFER[k]);
      L.wavelength_weights = keys.map(() => 1);
      L.primary = keys.indexOf("d");
      lensChanged({ rerender: true });
    });
  }
  $("#field-type").addEventListener("change", (e) => { state.lens.fields.type = e.target.value; lensChanged(); });
  $("#btn-add-field").addEventListener("click", () => {
    const v = state.lens.fields.values;
    v.push(v.length ? v[v.length - 1] : 0);
    lensChanged({ rerender: true });
  });
  $("#ap-type").addEventListener("change", (e) => { state.lens.aperture.type = e.target.value; lensChanged(); });
  $("#ap-value").addEventListener("change", (e) => {
    const v = parseNum(e.target.value);
    e.target.classList.toggle("bad", !(v > 0));
    if (v > 0) { state.lens.aperture.value = v; lensChanged(); }
  });

  // 最適化
  $("#btn-add-var").addEventListener("click", () => {
    state.lens.optimization.variables.push({ surface: 1, param: "curvature" });
    persist(); renderEditors();
  });
  const o = () => state.lens.optimization;
  $("#opt-efl-on").addEventListener("change", (e) => {
    if (e.target.checked) {
      const cur = state.summary ? Number(state.summary.efl) : 100;
      o().targets.efl = parseNum($("#opt-efl").value) ?? Number(cur.toFixed(3));
    } else { delete o().targets.efl; }
    persist(); renderOpt();
  });
  $("#opt-efl").addEventListener("change", (e) => {
    const v = parseNum(e.target.value);
    if (v !== undefined) { o().targets.efl = v; $("#opt-efl-on").checked = true; persist(); }
  });
  $("#opt-efl-w").addEventListener("change", (e) => {
    const v = parseNum(e.target.value);
    if (v === undefined) delete o().targets.efl_weight; else o().targets.efl_weight = v;
    persist();
  });
  $("#opt-focus").addEventListener("change", (e) => {
    if (e.target.checked) o().focus = "paraxial"; else delete o().focus;
    persist();
  });
  $("#opt-iter").addEventListener("change", (e) => { const v = parseNum(e.target.value); if (v > 0) o().iterations = Math.round(v); persist(); });
  $("#opt-rings").addEventListener("change", (e) => { const v = parseNum(e.target.value); if (v > 0) o().rings = Math.round(v); persist(); });
  $("#btn-optimize").addEventListener("click", runOptimize);
}

async function init() {
  bindUI();
  // 硝材リストとサンプル一覧
  try {
    const glasses = await apiCall("/api/glasses");
    $("#glass-list").replaceChildren(
      el("option", { value: "AIR" }),
      glasses.map((g) => el("option", { value: g.name }, `nd ${g.nd}  νd ${g.vd}`)));
  } catch (_) { /* 硝材候補がなくても入力は可能 */ }
  let exs = [];
  try {
    exs = await apiCall("/api/examples");
    $("#example-select").append(...exs.map((e) => el("option", { value: e.id }, e.title)));
  } catch (_) { /* ignore */ }

  // 前回の状態
  try {
    const tab = localStorage.getItem("opteval.tab");
    if (tab) $(`.tabs[data-group="left"] button[data-tab="${tab}"]`)?.click();
    const view = localStorage.getItem("opteval.view");
    if (view && $(`.tabs[data-group="right"] button[data-view="${view}"]`)) {
      state.view = view;
      $$('.tabs[data-group="right"] button').forEach((x) => x.classList.toggle("active", x.dataset.view === view));
    }
  } catch (_) { /* ignore */ }
  let lens = null;
  try { const raw = localStorage.getItem(STORAGE_KEY); if (raw) lens = JSON.parse(raw); } catch (_) { lens = null; }
  if (!lens && exs.some((e) => e.id === "cooke_triplet")) {
    try { lens = await apiCall("/api/examples/cooke_triplet"); } catch (_) { lens = null; }
  }
  setLens(lens || defaultLens());
  clearTimeout(refreshTimer);
  refresh();
}

init();
