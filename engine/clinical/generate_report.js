const fs = require("fs");
const pptxgen = require("pptxgenjs");

const THEME = {
  bg: "F4F7FF",
  panel: "FFFFFF",
  text: "0F172A",
  muted: "475569",
  border: "D7E0F0",
  header: "0B1E4B",
  accent: "1D4ED8",
  danger: "DC2626",
  warning: "D97706",
  success: "16A34A",
  info: "0284C7",
};

function clamp01(v) {
  const n = Number(v || 0);
  if (Number.isNaN(n)) return 0;
  return Math.max(0, Math.min(1, n));
}

function asPercent(v) {
  return `${Math.round(clamp01(v) * 100)}%`;
}

function riskBand(v) {
  const n = clamp01(v);
  if (n >= 0.67) return "high";
  if (n >= 0.34) return "medium";
  return "low";
}

function colorByBand(band) {
  const b = String(band || "").toLowerCase();
  if (b === "high") return THEME.danger;
  if (b === "medium") return THEME.warning;
  return THEME.success;
}

function statusColor(status) {
  const s = String(status || "").toLowerCase();
  if (s === "high") return THEME.danger;
  if (s === "low") return THEME.warning;
  if (s === "normal") return THEME.success;
  return "64748B";
}

function textList(values, emptyText = "- none captured") {
  if (!Array.isArray(values) || values.length === 0) return emptyText;
  return values.map((v) => `- ${String(v || "").trim()}`).join("\n");
}

function addPageChrome(slide, title, subtitle = "") {
  slide.background = { color: THEME.bg };
  slide.addShape("rect", {
    x: 0, y: 0, w: 13.333, h: 0.82,
    fill: { color: THEME.header }, line: { color: THEME.header },
  });
  slide.addText(title, {
    x: 0.35, y: 0.16, w: 8.7, h: 0.4,
    fontSize: 17, bold: true, color: "FFFFFF",
  });
  if (subtitle) {
    slide.addText(subtitle, {
      x: 8.8, y: 0.2, w: 4.2, h: 0.32,
      fontSize: 9, color: "BFD0FF", align: "right",
    });
  }
  slide.addShape("rect", {
    x: 0.35, y: 7.1, w: 12.65, h: 0.02,
    fill: { color: THEME.border }, line: { color: THEME.border },
  });
  slide.addText("Decision support only. Clinician verification required.", {
    x: 0.35, y: 7.14, w: 8.4, h: 0.2,
    fontSize: 8.5, color: THEME.muted, italic: true,
  });
}

function addPanel(slide, x, y, w, h, title = "") {
  slide.addShape("roundRect", {
    x, y, w, h, radius: 0.06,
    fill: { color: THEME.panel }, line: { color: THEME.border, pt: 1 },
    shadow: { type: "outer", color: "CAD5EA", blur: 2, angle: 45, distance: 1, opacity: 0.18 },
  });
  if (title) {
    slide.addText(title, {
      x: x + 0.2, y: y + 0.12, w: w - 0.4, h: 0.26,
      fontSize: 11, bold: true, color: THEME.text,
    });
  }
}

function normalRangeText(v) {
  const min = v && v.min !== undefined && v.min !== null ? v.min : "-";
  const max = v && v.max !== undefined && v.max !== null ? v.max : "-";
  return `${min} - ${max}`;
}

function addExecutiveSlide(pres, sd, ins) {
  const s = pres.addSlide();
  const patient = sd.patient || {};
  const chief = (sd.chief_complaint || {}).complaint || "not captured";
  const red = (((ins.analytics || {}).red_flag_summary || {}).count) || 0;
  const gaps = (((ins.actionable_insights || {}).documentation_gaps) || []).length;
  const tier = ((ins.diagnosis_support || {}).risk_tier) || "low";
  const conf = sd.confidence_score !== undefined ? sd.confidence_score : 0.5;

  addPageChrome(
    s,
    "Clinical Intelligence Report",
    `Session: ${sd.session_id || "N/A"} | Encounter: ${sd.encounter_date || "N/A"}`
  );

  addPanel(s, 0.35, 1.0, 12.65, 1.18, "Patient Snapshot");
  s.addText(`Chief Complaint: ${chief}`, {
    x: 0.6, y: 1.35, w: 8.2, h: 0.28, fontSize: 13, bold: true, color: THEME.text,
  });
  s.addText(`Demographics: ${patient.gender || "unknown"}, age ${patient.age ?? "N/A"}`, {
    x: 0.6, y: 1.67, w: 5.8, h: 0.24, fontSize: 10.5, color: THEME.muted,
  });

  const cards = [
    { label: "Risk Tier", value: String(tier), color: colorByBand(tier) },
    { label: "Red Flags", value: String(red), color: red > 0 ? THEME.danger : THEME.success },
    { label: "Documentation Gaps", value: String(gaps), color: gaps > 0 ? THEME.warning : THEME.success },
    { label: "Confidence", value: asPercent(conf), color: THEME.info },
  ];
  for (let i = 0; i < cards.length; i++) {
    const c = cards[i];
    const x = 0.35 + i * 3.18;
    addPanel(s, x, 2.36, 3.03, 1.45, "");
    s.addText(c.label, { x: x + 0.16, y: 2.56, w: 2.7, h: 0.2, fontSize: 9.5, color: THEME.muted, bold: true });
    s.addText(c.value, { x: x + 0.16, y: 2.82, w: 2.7, h: 0.56, fontSize: 25, color: c.color, bold: true });
  }

  addPanel(s, 0.35, 4.02, 6.2, 2.82, "Possible Differential Diagnoses");
  const diffs = ((ins.diagnosis_support || {}).differential_diagnoses) || [];
  s.addText(textList(diffs.slice(0, 8), "- none captured"), {
    x: 0.58, y: 4.42, w: 5.8, h: 2.25, fontSize: 10.5, color: THEME.text, valign: "top",
  });

  addPanel(s, 6.8, 4.02, 6.2, 2.82, "Priority Actions");
  const steps = ((ins.actionable_insights || {}).recommended_next_steps) || {};
  const immediate = steps.Immediate || [];
  const today = steps.Today || [];
  const follow = steps["Follow-up"] || [];
  s.addText(`Immediate\n${textList(immediate.slice(0, 3), "- none")}\n\nToday\n${textList(today.slice(0, 3), "- none")}\n\nFollow-up\n${textList(follow.slice(0, 3), "- none")}`, {
    x: 7.05, y: 4.42, w: 5.75, h: 2.32, fontSize: 9.4, color: THEME.text, valign: "top",
  });
}

function addVitalsSlide(pres, ins) {
  const s = pres.addSlide();
  addPageChrome(s, "Vitals and Physiologic Status");
  addPanel(s, 0.35, 1.0, 12.65, 5.95, "Vitals Table and Status");

  const vitals = ((ins.analytics || {}).vitals) || [];
  const rows = [["Vital", "Value", "Unit", "Normal Range", "Status"]];
  vitals.forEach((v) => {
    rows.push([
      String(v.name || ""),
      v.value === null || v.value === undefined ? "not captured" : String(v.value),
      String(v.unit || ""),
      normalRangeText(v),
      String(v.status || "not_captured"),
    ]);
  });

  s.addTable(rows, {
    x: 0.62, y: 1.45, w: 8.2,
    colW: [2.4, 1.25, 1.0, 1.8, 1.55],
    fontFace: "Calibri",
    fontSize: 10,
    color: THEME.text,
    border: { pt: 1, color: THEME.border },
    fill: THEME.panel,
    valign: "middle",
  });

  addPanel(s, 8.98, 1.45, 3.72, 5.24, "Status Distribution");
  const counts = { normal: 0, high: 0, low: 0, not_captured: 0 };
  vitals.forEach((v) => {
    const k = String(v.status || "not_captured").toLowerCase();
    if (counts[k] === undefined) counts.not_captured += 1;
    else counts[k] += 1;
  });
  const order = ["high", "low", "normal", "not_captured"];
  let y = 1.95;
  order.forEach((k) => {
    const c = counts[k] || 0;
    const pct = vitals.length ? Math.round((c / vitals.length) * 100) : 0;
    const color = statusColor(k);
    s.addText(`${k.replace("_", " ")}`, { x: 9.25, y, w: 2.0, h: 0.2, fontSize: 10, color: THEME.text, bold: true });
    s.addShape("rect", { x: 9.25, y: y + 0.23, w: 2.8, h: 0.16, fill: { color: "E2E8F0" }, line: { color: "E2E8F0" } });
    s.addShape("rect", { x: 9.25, y: y + 0.23, w: 2.8 * (pct / 100), h: 0.16, fill: { color }, line: { color } });
    s.addText(`${c} (${pct}%)`, { x: 12.1, y: y + 0.14, w: 0.5, h: 0.25, fontSize: 9, color: THEME.muted, align: "right" });
    y += 0.95;
  });
}

function addRiskSlide(pres, ins) {
  const s = pres.addSlide();
  addPageChrome(s, "Risk Model Signals");
  addPanel(s, 0.35, 1.0, 12.65, 5.95, "Risk Scores (Heuristic)");

  const risk = ((ins.analytics || {}).risk_scores) || [];
  let y = 1.52;
  risk.slice(0, 8).forEach((r) => {
    const v = clamp01(r.value);
    const band = String(r.band || riskBand(v));
    const color = colorByBand(band);
    s.addText(String(r.name || "risk_score"), {
      x: 0.62, y, w: 4.3, h: 0.24, fontSize: 10.5, color: THEME.text, bold: true,
    });
    s.addText(`${asPercent(v)} (${band})`, {
      x: 10.2, y, w: 2.45, h: 0.24, fontSize: 10, color, bold: true, align: "right",
    });
    s.addShape("roundRect", {
      x: 0.62, y: y + 0.28, w: 9.58, h: 0.2, radius: 0.06,
      fill: { color: "E2E8F0" }, line: { color: "E2E8F0" },
    });
    s.addShape("roundRect", {
      x: 0.62, y: y + 0.28, w: 9.58 * v, h: 0.2, radius: 0.06,
      fill: { color }, line: { color },
    });
    s.addText(String(r.explanation || "No explanation provided."), {
      x: 0.62, y: y + 0.55, w: 11.9, h: 0.3, fontSize: 8.8, color: THEME.muted, italic: true,
    });
    y += 0.95;
  });
}

function addClinicalReasoningSlide(pres, ins) {
  const s = pres.addSlide();
  addPageChrome(s, "Diagnosis Support and Evidence Mapping");

  const ds = ins.diagnosis_support || {};
  const evidence = Array.isArray(ds.evidence) ? ds.evidence : [];
  const missing = Array.isArray(ds.missing_questions) ? ds.missing_questions : [];
  const diffs = Array.isArray(ds.differential_diagnoses) ? ds.differential_diagnoses : [];

  addPanel(s, 0.35, 1.0, 6.2, 2.9, "Differentials (possible)");
  s.addText(textList(diffs.slice(0, 10), "- none captured"), {
    x: 0.6, y: 1.37, w: 5.8, h: 2.35, fontSize: 10, color: THEME.text, valign: "top",
  });

  addPanel(s, 6.8, 1.0, 6.2, 2.9, "Missing Questions");
  s.addText(textList(missing.slice(0, 10), "- none captured"), {
    x: 7.05, y: 1.37, w: 5.75, h: 2.35, fontSize: 10, color: THEME.text, valign: "top",
  });

  addPanel(s, 0.35, 4.1, 12.65, 2.85, "Evidence Table");
  const rows = [["Finding", "Source"]];
  evidence.slice(0, 12).forEach((e) => rows.push([String(e.finding || ""), String(e.source || "")]));
  s.addTable(rows, {
    x: 0.62, y: 4.48, w: 12.1,
    colW: [6.0, 6.1],
    fontFace: "Calibri",
    fontSize: 9.6,
    color: THEME.text,
    border: { pt: 1, color: THEME.border },
    fill: THEME.panel,
    valign: "middle",
  });
}

function addActionSlide(pres, ins) {
  const s = pres.addSlide();
  addPageChrome(s, "Actionable Plan and Safety Net");

  const ai = ins.actionable_insights || {};
  const steps = ai.recommended_next_steps || {};
  const gaps = Array.isArray(ai.documentation_gaps) ? ai.documentation_gaps : [];
  const safety = Array.isArray(ai.safety_net) ? ai.safety_net : [];

  addPanel(s, 0.35, 1.0, 4.1, 3.05, "Immediate");
  s.addText(textList(steps.Immediate || [], "- none"), { x: 0.6, y: 1.37, w: 3.8, h: 2.5, fontSize: 9.6, color: THEME.text });
  addPanel(s, 4.62, 1.0, 4.1, 3.05, "Today");
  s.addText(textList(steps.Today || [], "- none"), { x: 4.88, y: 1.37, w: 3.8, h: 2.5, fontSize: 9.6, color: THEME.text });
  addPanel(s, 8.9, 1.0, 4.1, 3.05, "Follow-up");
  s.addText(textList(steps["Follow-up"] || [], "- none"), { x: 9.16, y: 1.37, w: 3.78, h: 2.5, fontSize: 9.6, color: THEME.text });

  addPanel(s, 0.35, 4.25, 7.8, 2.7, "Documentation Gaps");
  const gapRows = [["Gap", "Severity", "Why it matters"]];
  gaps.slice(0, 10).forEach((g) => {
    gapRows.push([String(g.gap || ""), String(g.severity || "low"), String(g.why_it_matters || "")]);
  });
  s.addTable(gapRows, {
    x: 0.58, y: 4.58, w: 7.3,
    colW: [2.8, 1.2, 3.3],
    fontFace: "Calibri",
    fontSize: 8.8,
    color: THEME.text,
    border: { pt: 1, color: THEME.border },
    fill: THEME.panel,
    valign: "middle",
  });

  addPanel(s, 8.32, 4.25, 4.68, 2.7, "Safety Net");
  s.addText(textList(safety.slice(0, 12), "- none"), {
    x: 8.58, y: 4.58, w: 4.25, h: 2.25, fontSize: 9.2, color: THEME.text, valign: "top",
  });
}

function addAppendixSlide(pres, sd, ins) {
  const s = pres.addSlide();
  addPageChrome(s, "Structured Data Appendix");
  addPanel(s, 0.35, 1.0, 12.65, 5.95, "Raw Structured Snapshot");
  const minimal = {
    chief_complaint: sd.chief_complaint || null,
    symptoms: sd.symptoms || [],
    vitals: sd.vitals || null,
    assessment: sd.assessment || null,
    treatment_plan: sd.treatment_plan || null,
    red_flags: ((ins.analytics || {}).red_flag_summary || {}).items || [],
  };
  const raw = JSON.stringify(minimal, null, 2);
  s.addText(raw, {
    x: 0.58, y: 1.35, w: 12.1, h: 5.45,
    fontFace: "Consolas",
    fontSize: 8.2,
    color: "1E293B",
    breakLine: true,
    valign: "top",
  });
}

async function run(inputPath, outputPath) {
  const payload = JSON.parse(fs.readFileSync(inputPath, "utf8"));
  const sd = payload.structured_data || payload || {};
  const ins = payload.insights || {};

  const pres = new pptxgen();
  pres.layout = "LAYOUT_WIDE";
  pres.author = "Cavista Clinical Assistant";
  pres.company = "Cavista";
  pres.subject = "Clinical Structured Report";
  pres.title = "Clinical Intelligence Report";
  pres.lang = "en-US";

  addExecutiveSlide(pres, sd, ins);
  addVitalsSlide(pres, ins);
  addRiskSlide(pres, ins);
  addClinicalReasoningSlide(pres, ins);
  addActionSlide(pres, ins);
  addAppendixSlide(pres, sd, ins);

  await pres.writeFile({ fileName: outputPath });
}

const args = process.argv.slice(2);
if (args.length < 2) {
  console.error("Usage: node generate_report.js <input.json> <output.pptx>");
  process.exit(1);
}
run(args[0], args[1]).catch((e) => {
  console.error(e && e.stack ? e.stack : (e && e.message) || e);
  process.exit(1);
});
