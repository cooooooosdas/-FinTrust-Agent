/* 金枢 FinTrust Agent V1.0.0 — 10 分钟答辩 PPT（严格 10 页） */
const fs = require('fs');
const path = require('path');
const pptxgen = require('pptxgenjs');

// 仓库根目录 = 本脚本（submission/tools/）的上两级，不依赖任何机器绝对路径
const ROOT = path.resolve(__dirname, '..', '..');
const SHOT = path.join(ROOT, 'docs', 'screenshots');
const OUT = process.env.FINTRUST_PPT_OUT || path.join(ROOT, 'submission', '02_金枢答辩PPT.pptx');

if (!fs.existsSync(SHOT)) {
  console.error('缺少真实系统截图目录：' + SHOT + '（请先运行系统并采集截图，禁止伪造）');
  process.exit(1);
}

const pptx = new pptxgen();
pptx.layout = 'LAYOUT_WIDE';
pptx.author = '金枢 FinTrust Agent';
pptx.company = '金枢 FinTrust Agent';
pptx.subject = '可信 AI 智能体系统答辩';
pptx.title = '金枢 FinTrust Agent V1.0.0';
pptx.lang = 'zh-CN';
pptx.theme = {
  headFontFace: 'Microsoft YaHei',
  bodyFontFace: 'Microsoft YaHei',
  lang: 'zh-CN'
};
pptx.defineLayout({ name: 'CUSTOM_WIDE', width: 13.333, height: 7.5 });
pptx.layout = 'CUSTOM_WIDE';
pptx.margin = 0;

const C = {
  navy: '0B1F3A', navy2: '153B66', navy3: '24466B',
  white: 'FFFFFF', off: 'F7F9FC', ink: '172238', muted: '5D6B7D',
  line: 'DDE5EE', gold: 'C9A96E', gold2: 'E9D8B8',
  green: '16815C', greenBg: 'EAF6EF',
  yellow: 'B7791F', yellowBg: 'FFF6DF',
  red: 'B4232A', redBg: 'FDECEC',
  blueBg: 'EAF1F8'
};
const FONT = 'Microsoft YaHei';
const W = 13.333, H = 7.5;

function addSlide(bg = C.off) {
  const s = pptx.addSlide();
  s.background = { color: bg };
  return s;
}
function addFooter(s, n, dark=false) {
  s.addText('金枢 FinTrust Agent V1.0.0', {
    x: 0.55, y: 7.16, w: 4.5, h: 0.18, margin: 0,
    fontFace: FONT, fontSize: 7.5, color: dark ? C.gold2 : C.muted, charSpacing: 1
  });
  s.addText(`${n} / 10`, {
    x: 12.25, y: 7.14, w: 0.52, h: 0.2, margin: 0,
    fontFace: FONT, fontSize: 8, bold: true, color: dark ? C.white : C.navy, align: 'right'
  });
}
function addTitle(s, title, sub, opts={}) {
  const color = opts.dark ? C.white : C.navy;
  s.addText(title, { x: 0.6, y: 0.42, w: 11.9, h: 0.48, margin: 0, fontFace: FONT, fontSize: 25, bold: true, color });
  if (sub) s.addText(sub, { x: 0.62, y: 0.94, w: 11.7, h: 0.28, margin: 0, fontFace: FONT, fontSize: 9.5, color: opts.dark ? C.gold2 : C.muted });
}
function addCircleIcon(s, x, y, txt, fill=C.navy, color=C.white, size=0.36) {
  s.addShape(pptx.ShapeType.ellipse, { x, y, w: size, h: size, fill: { color: fill }, line: { color: fill } });
  s.addText(txt, { x, y: y + 0.015, w: size, h: size - 0.02, margin: 0, align: 'center', valign: 'middle', fontFace: FONT, fontSize: 11, bold: true, color });
}
function addCard(s, x, y, w, h, opts={}) {
  s.addShape(pptx.ShapeType.roundRect, {
    x, y, w, h, rectRadius: 0.08, fill: { color: opts.fill || C.white, transparency: opts.transparency || 0 },
    line: { color: opts.line || C.line, width: opts.lineWidth || 0.8 },
    shadow: { type: 'outer', color: 'AAB4C0', opacity: 0.12, blur: 1, offset: 2, angle: 45 }
  });
}
function addLabel(s, x, y, text, opts={}) {
  s.addText(text, { x, y, w: opts.w || 2.2, h: opts.h || 0.26, margin: 0, fontFace: FONT, fontSize: opts.size || 8.5, bold: !!opts.bold, color: opts.color || C.ink, align: opts.align || 'left', valign: 'middle', breakLine: false, fit: 'shrink' });
}
function addBullet(s, items, x, y, w, opts={}) {
  const color = opts.color || C.ink;
  const runs = [];
  items.forEach((it, idx) => {
    runs.push({ text: it, options: { bullet: { code: '25AA', color: opts.bulletColor || C.gold, indent: 10 }, breakLine: idx < items.length - 1, paraSpaceAfter: opts.gap || 5 } });
  });
  s.addText(runs, { x, y, w, h: opts.h || 1.5, margin: 0, fontFace: FONT, fontSize: opts.size || 11.5, color, valign: 'top', lineSpacingMultiple: opts.lineSpacing || 1.12, fit: 'shrink' });
}
function addPicture(s, file, x, y, w, h, line=C.line) {
  if (!fs.existsSync(file)) throw new Error(`截图不存在: ${file}`);
  s.addImage({ path: file, x, y, w, h, sizing: { type: 'cover', w, h } });
  s.addShape(pptx.ShapeType.rect, { x, y, w, h, fill: { color: 'FFFFFF', transparency: 100 }, line: { color: line, width: 0.8 } });
}
function addNotes(s, text) { s.addNotes(text); }
function addChip(s, x, y, text, fill, color=C.white, w=1.0) {
  s.addShape(pptx.ShapeType.roundRect, { x, y, w, h: 0.28, rectRadius: 0.08, fill: { color: fill }, line: { color: fill } });
  s.addText(text, { x, y: y + 0.015, w, h: 0.23, margin: 0, align: 'center', valign: 'middle', fontFace: FONT, fontSize: 8.3, bold: true, color, fit: 'shrink' });
}

// P1 封面
{
  const s = addSlide(C.navy);
  addPicture(s, path.join(SHOT, '01_login.png'), 7.45, 0, 5.883, 7.5, C.navy);
  s.addShape(pptx.ShapeType.rect, { x: 7.45, y: 0, w: 5.883, h: 7.5, fill: { color: C.navy, transparency: 35 }, line: { color: C.navy, transparency: 100 } });
  addCircleIcon(s, 0.72, 0.72, '金', C.gold, C.navy, 0.62);
  addLabel(s, 1.48, 0.77, '金枢 FinTrust Agent', { w: 4.5, h: 0.32, size: 14, bold: true, color: C.white });
  addLabel(s, 1.49, 1.1, 'TRUSTED AI AGENT FOR BANKING', { w: 4.5, size: 7.5, color: C.gold2 });
  s.addText('金枢 FinTrust Agent', { x: 0.72, y: 2.1, w: 6.15, h: 0.78, margin: 0, fontFace: FONT, fontSize: 34, bold: true, color: C.white, fit: 'shrink' });
  s.addText('面向银行业的可信 AI 智能体', { x: 0.74, y: 2.94, w: 6.1, h: 0.42, margin: 0, fontFace: FONT, fontSize: 18, color: C.gold2 });
  s.addText('让自然语言驱动的资金操作始终安全可控', { x: 0.74, y: 3.45, w: 5.9, h: 0.32, margin: 0, fontFace: FONT, fontSize: 11.5, color: C.white });
  addCard(s, 0.74, 4.35, 5.75, 1.28, { fill: C.navy2, line: C.navy3 });
  s.addText('用自然语言办事，用独立权限引擎担保', { x: 1.0, y: 4.62, w: 5.2, h: 0.38, margin: 0, fontFace: FONT, fontSize: 17, bold: true, color: C.white, align: 'center' });
  s.addText('权限判定与模型彻底解耦', { x: 1.0, y: 5.04, w: 5.2, h: 0.24, margin: 0, fontFace: FONT, fontSize: 9.5, color: C.gold2, align: 'center' });
  s.addText('V1.0.0 ｜ 10 分钟答辩', { x: 0.74, y: 6.72, w: 3.5, h: 0.25, margin: 0, fontFace: FONT, fontSize: 9, color: C.gold2 });
  addFooter(s, 1, true);
  addNotes(s, '各位评委好，我们的作品是金枢 FinTrust Agent。它解决的是一个很具体的问题：银行要让 AI 帮客户办事，但 AI 会幻觉、会被提示词注入、会越权。我们的答案是把权限判定从模型手里拿走：自然语言负责理解，独立安全引擎负责裁决。');
}

// P2 问题与挑战
{
  const s = addSlide();
  addTitle(s, '银行 AI Agent 的三个死结', '不回避 AI 的固有缺陷，把它们变成可工程化解决的问题');
  const cards = [
    ['会幻觉', '编造交易结果、虚构流水号', '后端真实执行，成功必须有 transaction_id', C.red, C.redBg],
    ['会被注入', '恶意指令藏在输入、收款人名称、备注或工具返回里', '不可信内容只能提供数据，不能提供指令', C.yellow, C.yellowBg],
    ['会越权', '伪造身份、账户号或把高风险说成低风险', '策略引擎只接收业务事实，不接受模型建议', C.navy2, C.blueBg]
  ];
  cards.forEach((c, i) => {
    const x = 0.72 + i * 4.1;
    addCard(s, x, 1.72, 3.65, 3.75, { fill: c[5], line: c[3] });
    addCircleIcon(s, x + 0.3, 2.05, String(i + 1), c[3], C.white, 0.48);
    addLabel(s, x + 0.92, 2.08, c[0], { w: 2.3, size: 18, bold: true, color: c[3] });
    s.addText(c[1], { x: x + 0.3, y: 2.78, w: 3.05, h: 0.74, margin: 0, fontFace: FONT, fontSize: 12, bold: true, color: C.ink, lineSpacingMultiple: 1.12, fit: 'shrink' });
    s.addShape(pptx.ShapeType.line, { x: x + 0.3, y: 3.72, w: 3.02, h: 0, line: { color: c[3], width: 1, dashType: 'dash' } });
    s.addText(c[2], { x: x + 0.3, y: 3.93, w: 3.05, h: 0.92, margin: 0, fontFace: FONT, fontSize: 10.5, color: C.muted, lineSpacingMultiple: 1.1, fit: 'shrink' });
  });
  s.addText('设计原则：这三条都不能靠“提示词写得更好”解决，只能靠架构隔离。', { x: 1.1, y: 5.95, w: 11.1, h: 0.44, margin: 0, fontFace: FONT, fontSize: 14, bold: true, color: C.navy, align: 'center' });
  addFooter(s, 2);
  addNotes(s, '大模型做银行业务有三个绕不开的问题：幻觉、提示词注入和越权。我们的原则是，这三条都不能靠提示词工程解决，只能靠架构隔离。接下来所有设计都围绕这条原则展开。');
}

// P3 系统架构
{
  const s = addSlide(C.white);
  addTitle(s, '四层架构：安全引擎独立于模型', '模型只输出事实参数；权限结论由服务端安全层独立给出');
  const lanes = [
    ['接入层', ['React + TypeScript', '六大业务页面', 'FastAPI REST'], C.navy2, C.blueBg],
    ['智能层', ['意图识别 / 参数抽取', '固定 DAG 规划', '工具白名单 / 编排器'], C.navy, C.off],
    ['安全层', ['三级权限 PolicyEngine', '七状态机 + MFA', '幂等 / 限流 / 审计哈希链'], C.gold, C.gold2],
    ['数据层', ['SQLite + SQLAlchemy', '15 张核心表', '金额整数分 / WAL'], C.navy3, C.blueBg],
  ];
  lanes.forEach((l, i) => {
    const y = 1.48 + i * 1.18;
    addCard(s, 0.72, y, 11.9, 0.94, { fill: l[4], line: i === 2 ? C.gold : C.line });
    addCircleIcon(s, 0.98, y + 0.24, String(i + 1), i === 2 ? C.gold : C.navy, i === 2 ? C.navy : C.white, 0.46);
    addLabel(s, 1.62, y + 0.19, l[0], { w: 1.35, size: 14, bold: true, color: i === 2 ? C.navy : C.navy });
    l[1].forEach((t, j) => addChip(s, 3.25 + j * 2.72, y + 0.29, t, i === 2 ? C.white : C.white, i === 2 ? C.navy : C.ink, 2.45));
    if (i < lanes.length - 1) s.addShape(pptx.ShapeType.downArrow, { x: 6.48, y: y + 0.9, w: 0.22, h: 0.27, fill: { color: C.gold }, line: { color: C.gold } });
  });
  s.addText('权限判定只接收业务事实，不接收模型建议', { x: 2.6, y: 6.38, w: 8.1, h: 0.35, margin: 0, fontFace: FONT, fontSize: 15, bold: true, color: C.navy, align: 'center' });
  addFooter(s, 3);
  addNotes(s, '架构上只有一句话值得记住：安全层和智能层是分开的。模型在智能层工作，但输出永远只是意图和参数；安全层根据金额、当日累计、收款人属性等客观事实定级。模型说什么都不能改变权限结论。');
}

// P4 Agent 工作流
{
  const s = addSlide();
  addTitle(s, '从一句话到一次受控执行', 'DAG 轨迹来自后端真实执行事件，不是预先写死的动画');
  const steps = ['意图识别', '参数抽取', 'DAG 规划', '工具调用', '后端鉴权', '审计留痕'];
  steps.forEach((t, i) => {
    const x = 0.72 + i * 1.15;
    addChip(s, x, 1.53, t, i < 2 ? C.navy : (i < 4 ? C.navy2 : C.gold), i >= 4 ? C.navy : C.white, 0.98);
    if (i < steps.length - 1) s.addShape(pptx.ShapeType.chevron, { x: x + 1.0, y: 1.6, w: 0.13, h: 0.14, fill: { color: C.gold }, line: { color: C.gold } });
  });
  addPicture(s, path.join(SHOT, '03_agent_dag_expanded.png'), 0.72, 2.18, 7.65, 4.44);
  addCard(s, 8.66, 2.18, 3.95, 4.44, { fill: C.white });
  addLabel(s, 8.98, 2.48, '真实执行轨迹', { w: 2.6, size: 16, bold: true, color: C.navy });
  addBullet(s, [
    '规则引擎始终先执行，LLM 只做可选融合',
    'Planner 生成固定 DAG，节点含依赖关系',
    '工具仅能从服务端白名单注册表调用',
    'TraceBuilder 记录状态、详情与真实耗时',
    '轨迹 JSON 落库，前端可逐步展开回放'
  ], 8.98, 3.02, 3.15, { size: 10.5, gap: 6 });
  addLabel(s, 8.98, 6.05, '当前为本地规则演示模式', { w: 2.8, size: 8.5, bold: true, color: C.yellow });
  addFooter(s, 4);
  addNotes(s, '用户输入后，Agent 先识别意图和参数，再生成 DAG，并按依赖调用后端工具。右图的节点、状态和耗时来自后端 TraceBuilder 的真实事件。用户能看到每一步做了什么，这是可解释性的基础。需要说明，本次展示的是规则演示模式，真实大模型尚未联调。');
}

// P5 三级权限
{
  const s = addSlide(C.white);
  addTitle(s, '日累计单轴判定：写操作至少黄色', '阈值口径统一、可配置；执行阶段重新判权');
  const rows = [
    ['绿色', '只读查询', '直接执行 + 写审计', C.green, C.greenBg],
    ['黄色', '写操作且执行后当日累计 ≤ ¥1,000', '展示完整明细，要求用户确认', C.yellow, C.yellowBg],
    ['红色', '执行后当日累计 > ¥1,000；挂失 / 改密 / 敏感词', '强制模拟 MFA，验证通过才执行', C.red, C.redBg],
    ['阻断', '当日累计 > ¥100,000', '直接拦截，不执行资金操作', C.muted, C.off],
  ];
  rows.forEach((r, i) => {
    const y = 1.5 + i * 0.88;
    addCard(s, 0.72, y, 6.45, 0.72, { fill: r[4], line: r[3] });
    addChip(s, 0.95, y + 0.2, r[0], r[3], C.white, 0.78);
    s.addText(r[1], { x: 1.9, y: y + 0.12, w: 3.18, h: 0.46, margin: 0, fontFace: FONT, fontSize: 9.3, bold: true, color: C.ink, valign: 'middle', fit: 'shrink' });
    s.addText(r[2], { x: 5.12, y: y + 0.12, w: 1.85, h: 0.46, margin: 0, fontFace: FONT, fontSize: 8.7, color: C.ink, valign: 'middle', fit: 'shrink' });
  });
  addCard(s, 0.72, 5.18, 6.45, 1.18, { fill: C.off });
  addBullet(s, [
    '任何资金写操作绝不获得绿色权限',
    '执行时重算日累计并重新判权，不信任预览快照',
    '策略引擎返回 reason + rules，可解释、可审计'
  ], 1.02, 5.42, 5.7, { size: 10.5, gap: 4 });
  addPicture(s, path.join(SHOT, '04_transfer_yellow.png'), 7.55, 1.5, 5.05, 4.86);
  s.addText('真实页面：转账表单与三级策略展示。黄色确认面板本次未成功截取，以现场演示为准。', { x: 7.58, y: 6.43, w: 4.95, h: 0.32, margin: 0, fontFace: FONT, fontSize: 7.5, color: C.muted, align: 'center' });
  addFooter(s, 5);
  addNotes(s, '权限口径非常清晰：日累计是唯一主判定轴。不超过一千元是黄色，要用户确认；超过一千元是红色，必须过模拟 MFA；超过十万直接拦截。所有写操作最低黄色，而且执行那一刻会重新判权，解决预览和执行之间风险变化的经典漏洞。');
}

// P6 安全纵深
{
  const s = addSlide();
  addTitle(s, '五道防线，攻击必须逐层突破', '单点失效不足以造成未授权资金操作');
  const defs = [
    ['01', '身份认证', 'PBKDF2 哈希\nToken 仅存摘要'],
    ['02', '账户隔离', '逐接口校验归属\n越权即 403'],
    ['03', 'MFA 持久化', '验证码仅存 HMAC\n一次性消费'],
    ['04', '幂等 + 限流', '同键不重复扣款\n核心接口 429'],
    ['05', '注入防御', '工具白名单\n身份上下文 + 参数校验'],
  ];
  defs.forEach((d, i) => {
    const x = 0.72 + i * 2.43;
    addCard(s, x, 1.58, 2.15, 2.3, { fill: C.white, line: i === 2 ? C.gold : C.line });
    addCircleIcon(s, x + 0.25, 1.86, d[0], i === 2 ? C.gold : C.navy, i === 2 ? C.navy : C.white, 0.5);
    addLabel(s, x + 0.25, 2.52, d[1], { w: 1.65, size: 13, bold: true, color: C.navy });
    s.addText(d[2], { x: x + 0.25, y: 2.93, w: 1.65, h: 0.62, margin: 0, fontFace: FONT, fontSize: 8.8, color: C.muted, lineSpacingMultiple: 1.1, fit: 'shrink' });
  });
  addPicture(s, path.join(SHOT, '01_login.png'), 0.72, 4.25, 5.9, 2.35);
  addPicture(s, path.join(SHOT, '05_audit_pass.png'), 6.82, 4.25, 5.8, 2.35);
  addFooter(s, 6);
  addNotes(s, '攻击要得手必须突破五道防线。身份认证和账户隔离解决“你是谁、你能访问谁”；MFA 解决高风险操作的第二因子；幂等与限流解决重复扣款和暴力请求；注入防御由白名单、身份上下文和参数校验构成。');
}

// P7 信任边界
{
  const s = addSlide(C.white);
  addTitle(s, '不靠正则，靠边界', '真正的安全边界由五重后端强制机制构成');
  // 不可信区域
  s.addShape(pptx.ShapeType.roundRect, { x: 0.72, y: 1.48, w: 7.05, h: 4.82, rectRadius: 0.1, fill: { color: C.redBg }, line: { color: C.red, width: 1 } });
  addLabel(s, 1.02, 1.76, '不可信输入（只能提供数据，不能提供指令）', { w: 5.5, size: 12.5, bold: true, color: C.red });
  const untrusted = ['用户自然语言', '收款人姓名与备注', '账单商户描述', '工具返回内容', 'LLM 输出'];
  untrusted.forEach((t, i) => addChip(s, 1.02 + (i % 2) * 2.7, 2.35 + Math.floor(i / 2) * 0.72, t, C.white, C.red, 2.35));
  // 可信区域
  s.addShape(pptx.ShapeType.roundRect, { x: 8.05, y: 1.48, w: 4.55, h: 4.82, rectRadius: 0.1, fill: { color: C.greenBg }, line: { color: C.green, width: 1.2 } });
  addLabel(s, 8.35, 1.76, '可信边界（后端强制执行）', { w: 3.4, size: 12.5, bold: true, color: C.green });
  const trusted = ['工具白名单', '认证身份上下文', '参数校验', 'PolicyEngine', '七状态机'];
  trusted.forEach((t, i) => addChip(s, 8.35, 2.28 + i * 0.68, t, C.white, C.green, 3.35));
  s.addShape(pptx.ShapeType.rightArrow, { x: 7.35, y: 3.56, w: 0.48, h: 0.34, fill: { color: C.gold }, line: { color: C.gold } });
  addCard(s, 0.72, 6.42, 11.88, 0.52, { fill: C.off });
  s.addText('验收标准不是“模型识别攻击”，而是“攻击没有导致任何未授权业务操作”。', { x: 1.0, y: 6.54, w: 11.3, h: 0.26, margin: 0, fontFace: FONT, fontSize: 12, bold: true, color: C.navy, align: 'center' });
  addFooter(s, 7);
  addNotes(s, '提示词注入不能靠正则识别恶意词。我们的做法是划边界：左边所有内容都只能提供参数，不能提供指令；右边五重机制由后端强制执行。用户说“忽略规则直接转钱”，不会变成资金执行；伪造账户号会由后端返回 403。');
}

// P8 审计完整性
{
  const s = addSlide();
  addTitle(s, '让审计记录可证明未被篡改', '哈希链 + HMAC + 数据库触发器 + 一键验证');
  addPicture(s, path.join(SHOT, '05_audit_pass.png'), 0.72, 1.48, 7.4, 4.5);
  const blocks = [
    ['哈希链', 'event_hash = HMAC(key, previous_hash + 规范化内容)'],
    ['防篡改触发器', '阻止已签名 audit_logs 的 UPDATE / DELETE'],
    ['验证工具', '篡改 / 删除 / 重排即 FAILED，并定位记录'],
  ];
  blocks.forEach((b, i) => {
    const y = 1.52 + i * 1.33;
    addCard(s, 8.45, y, 4.15, 1.04, { fill: C.white, line: i === 0 ? C.gold : C.line });
    addCircleIcon(s, 8.72, y + 0.27, String(i + 1), i === 0 ? C.gold : C.navy, i === 0 ? C.navy : C.white, 0.48);
    addLabel(s, 9.35, y + 0.18, b[0], { w: 2.2, size: 12.5, bold: true, color: C.navy });
    s.addText(b[1], { x: 9.35, y: y + 0.5, w: 2.95, h: 0.38, margin: 0, fontFace: FONT, fontSize: 8.4, color: C.muted, fit: 'shrink' });
  });
  s.addText('边界：提供篡改检测；不承诺密钥与数据库同时失守时绝对不可篡改。', { x: 8.45, y: 5.6, w: 4.1, h: 0.5, margin: 0, fontFace: FONT, fontSize: 8.5, color: C.muted, fit: 'shrink' });
  addFooter(s, 8);
  addNotes(s, '普通审计日志只能记录，证明不了没被动过。金枢给每条审计事件建立哈希链，当前事件的摘要由前一条哈希和本条内容计算；迁移脚本还提供数据库触发器拦截修改和删除。页面一键验证可以看到 PASS。边界也很清楚：这是篡改检测，不声称密钥和数据库同时失守时仍绝对安全。');
}

// P9 演示回放
{
  const s = addSlide(C.navy);
  addTitle(s, '五分钟核心动线', '现场真实操作，不依赖 PPT 效果', { dark: true });
  const steps = ['登录与总览', 'DAG 账单查询', '黄色小额确认', '红色 MFA', '注入 / 403', '审计 PASS'];
  steps.forEach((t, i) => {
    const x = 0.75 + i * 1.9;
    addCircleIcon(s, x, 1.55, String(i + 1), C.gold, C.navy, 0.45);
    addLabel(s, x - 0.35, 2.1, t, { w: 1.15, size: 8.5, bold: true, color: C.white, align: 'center' });
    if (i < steps.length - 1) s.addShape(pptx.ShapeType.chevron, { x: x + 1.38, y: 1.7, w: 0.16, h: 0.18, fill: { color: C.gold2 }, line: { color: C.gold2 } });
  });
  addPicture(s, path.join(SHOT, '02_dashboard.png'), 0.72, 2.75, 3.85, 2.36);
  addPicture(s, path.join(SHOT, '03_agent_dag_expanded.png'), 4.75, 2.75, 3.85, 2.36);
  addPicture(s, path.join(SHOT, '05_audit_pass.png'), 8.78, 2.75, 3.85, 2.36);
  s.addShape(pptx.ShapeType.roundRect, { x: 3.92, y: 5.48, w: 5.5, h: 0.72, rectRadius: 0.08, fill: { color: C.navy2 }, line: { color: C.gold, width: 0.8 } });
  s.addText('60 秒录屏占位：待现场录制 800 元黄色、1500 元红色 MFA、注入与 403', { x: 4.1, y: 5.72, w: 5.15, h: 0.24, margin: 0, fontFace: FONT, fontSize: 9, bold: true, color: C.gold2, align: 'center', fit: 'shrink' });
  addFooter(s, 9, true);
  addNotes(s, '现场演示覆盖登录、DAG 查询、黄色确认、红色 MFA、注入与跨账户 403、审计 PASS。当前 PPT 只放入三张真实运行截图；完整 60 秒录屏留作现场录制，不使用虚构视频或伪造截图。所有资金操作都是本地模拟。');
}

// P10 创新与限制
{
  const s = addSlide(C.white);
  addTitle(s, '三点创新，一份诚实的清单', '把能力边界说清楚，是可信度的一部分');
  const innov = [
    ['权限与模型解耦', '模型只提供事实参数，安全引擎独立裁决'],
    ['可验证的审计', '哈希链让“做过什么”可证明，而非只可记录'],
    ['Agent 白名单边界', '模型无法调用未注册工具，也无法自选身份'],
  ];
  innov.forEach((it, i) => {
    const x = 0.72 + i * 4.1;
    addCard(s, x, 1.5, 3.65, 1.55, { fill: i === 1 ? C.gold2 : C.off, line: i === 1 ? C.gold : C.line });
    addCircleIcon(s, x + 0.25, 1.82, String(i + 1), i === 1 ? C.gold : C.navy, i === 1 ? C.navy : C.white, 0.5);
    addLabel(s, x + 0.9, 1.78, it[0], { w: 2.45, size: 13, bold: true, color: C.navy });
    s.addText(it[1], { x: x + 0.9, y: 2.15, w: 2.45, h: 0.54, margin: 0, fontFace: FONT, fontSize: 8.8, color: C.muted, fit: 'shrink' });
  });
  addCard(s, 0.72, 3.48, 7.5, 2.7, { fill: C.off });
  addLabel(s, 1.02, 3.75, '已知限制（如实声明）', { w: 3.2, size: 15, bold: true, color: C.red });
  addBullet(s, [
    '真实大模型尚未完成联调；当前为规则演示模式，界面已标注',
    '多轮上下文尚未实现，跨轮参数补全与指代消解待做',
    'SQLite 限流仅适合单机竞赛演示，不是分布式生产方案',
    '审计哈希链提供篡改检测，但不是绝对不可篡改',
    '所有资金交易均为本地模拟，不连接真实银行账户'
  ], 1.02, 4.22, 6.65, { size: 10.2, gap: 5 });
  addCard(s, 8.5, 3.48, 4.1, 2.7, { fill: C.navy, line: C.navy });
  addLabel(s, 8.85, 3.78, '本轮可复验', { w: 2.2, size: 13, bold: true, color: C.gold2 });
  s.addText('117', { x: 8.85, y: 4.22, w: 1.45, h: 0.68, margin: 0, fontFace: FONT, fontSize: 34, bold: true, color: C.white });
  addLabel(s, 10.18, 4.42, 'pytest 用例通过', { w: 1.9, size: 10, color: C.white });
  s.addText('前端生产构建成功', { x: 8.85, y: 5.08, w: 3.3, h: 0.28, margin: 0, fontFace: FONT, fontSize: 10, color: C.gold2 });
  s.addText('审计完整性 PASS', { x: 8.85, y: 5.44, w: 3.3, h: 0.28, margin: 0, fontFace: FONT, fontSize: 10, color: C.gold2 });
  s.addText('谢谢各位评委', { x: 0.72, y: 6.55, w: 11.9, h: 0.32, margin: 0, fontFace: FONT, fontSize: 13, bold: true, color: C.navy, align: 'center' });
  addFooter(s, 10);
  addNotes(s, '总结三点创新：权限判定从模型手里拿走；审计记录能被证明没被动过；Agent 被白名单和身份上下文约束。同时必须诚实说明：真实模型还没联调，多轮上下文还没实现，限流是单机方案，审计是检测而非绝对防篡改，资金全部是本地模拟。本轮可复验结果是 117 个测试通过、前端构建成功、审计完整性 PASS。谢谢大家。');
}

pptx.writeFile({ fileName: OUT }).then(() => {
  console.log(OUT);
});
