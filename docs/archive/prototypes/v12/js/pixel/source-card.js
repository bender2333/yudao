// 来源卡片（design.md 第 5.1 节）：画面上的事实元素点开以后，一张小纸贴在被点的元素旁边，写这条事实的来源种类与给出它的事件；
// 点纸外面关闭。覆盖层「检验」的逐条清单用同一张纸（openList）。写法照决定卡片（decision-card.js）
(function () {
  'use strict';
  const Y12 = window.Y12;
  const P = Y12.pixel;
  if (!P || !P.createScene) throw new Error('source-card.js 需要先加载 js/pixel/engine.js');
  const PAL = P.PAL;
  const R = P.R, RB = P.RB;

  const W = 640, H = 320, BAR = 18;

  // 五种来源的图标（7×7）：确定规则是齿轮，主机测量是量尺，用户是人像，角色陈述是对话框，决策模型是天平
  const ICONS = {
    rule: ['..x.x..', '.xxxxx.', 'xxx.xxx', '.x...x.', 'xxx.xxx', '.xxxxx.', '..x.x..'],
    host_measurement: ['.......', 'xxxxxxx', 'x.x.x.x', 'x.x.x.x', 'x.....x', 'xxxxxxx', '.......'],
    user: ['..xxx..', '..xxx..', '..xxx..', '.......', '.xxxxx.', 'xxxxxxx', 'xxxxxxx'],
    role_statement: ['xxxxxxx', 'x.....x', 'x.x.x.x', 'x.....x', 'xxxxxxx', '.xx....', '.x.....'],
    decision_model: ['...x...', 'xxxxxxx', 'x..x..x', 'x..x..x', 'xx.x.xx', '...x...', '.xxxxx.']
  };
  // 覆盖层「来源」的描边：确定规则灰、主机测量蓝、用户绿；角色陈述与决策模型没有经过主机核实，用加粗的虚线
  P.SOURCE_STYLE = {
    rule: { line: PAL.grey1, dash: false },
    host_measurement: { line: PAL.blue2, dash: false },
    user: { line: PAL.green2, dash: false },
    role_statement: { line: PAL.yellow2, dash: true },
    decision_model: { line: PAL.orange2, dash: true }
  };
  const kindOf = (source) => Y12.registry.SOURCE_KINDS[source];

  // 角标：11×11；没有经过主机核实的来源为黄底并加粗边框，其余为浅色底
  P.drawSourceIcon = function drawSourceIcon(c, source, x, y) {
    const k = kindOf(source);
    if (!k || !ICONS[source]) throw new Error('未知的来源种类：' + source);
    x = Math.round(x); y = Math.round(y);
    if (k.unverified) {
      R(c, x - 1, y - 1, 13, 13, PAL.ink);
      R(c, x + 1, y + 1, 9, 9, PAL.yellow2);
    } else {
      R(c, x, y, 11, 11, PAL.ink);
      R(c, x + 1, y + 1, 9, 9, PAL.white);
    }
    c.fillStyle = PAL.ink;
    ICONS[source].forEach((row, j) => Array.from(row).forEach((ch, i) => { if (ch === 'x') c.fillRect(x + 2 + i, y + 2 + j, 1, 1); }));
  };

  function wrap(c, str, maxW, size, weight) {
    const lines = [];
    let cur = '';
    Array.from(String(str)).forEach((ch) => {
      if (ch === '\n') { lines.push(cur); cur = ''; return; }
      if (cur && P.measure(c, cur + ch, size, weight) > maxW) { lines.push(cur); cur = ch; } else cur += ch;
    });
    if (cur || !lines.length) lines.push(cur);
    return lines;
  }

  // opts：{ onSeek(position) 时间轴跳到这条事件, fetchEvent(position) → 事件对象 }
  // fact：{ kind, rect: { x, y, w, h }, position, source, title, notes: [文字], missing }
  P.createSourceCard = function createSourceCard(scene, canvas, opts) {
    const o = opts || {};
    let card = null;
    let hits = [];
    let paper = null;

    function onKey(e) {
      if (e.key === 'Escape') close();
    }

    function show(next) {
      if (!card) document.addEventListener('keydown', onKey);
      card = next;
    }

    function open(fact) {
      const ev = fact.position && o.fetchEvent ? o.fetchEvent(fact.position) : null;
      show({ mode: 'fact', fact, ev, anchor: fact.rect });
    }

    // 逐条清单：rows 为 [{ label, method, result, open, fact }]；点一行打开这一行的来源
    function openList(title, rows, anchor) {
      show({ mode: 'list', title, rows, anchor: anchor || { x: W / 2, y: BAR + 40, w: 0, h: 0 } });
    }

    function close() {
      if (card) document.removeEventListener('keydown', onKey);
      card = null;
      paper = null;
      hits = [];
    }

    function place(w, h) {
      const a = card.anchor;
      let x = a.x + a.w + 6;
      if (x + w > W - 4) x = a.x - w - 6;
      if (x < 4) x = Math.round((W - w) / 2);
      const y = Math.max(BAR + 4, Math.min(H - h - 4, a.y - 8));
      return { x: Math.round(x), y: Math.round(y), w, h };
    }

    function button(c, x, y, w, h, text, act, arg) {
      RB(c, x, y, w, h, PAL.white);
      P.text(c, text, x + w / 2, y + h / 2 + 0.5, { size: 6.5, weight: 700, align: 'center', color: PAL.ink, max: w - 6 });
      hits.push({ x, y, w, h, act, arg });
    }

    function drawFact(c) {
      const f = card.fact;
      const ev = card.ev;
      const w = 210;
      const inner = w - 20;
      const lines = [];
      const add = (text, style) => wrap(c, text, inner, 6.5, style.weight || 500).forEach((s) => lines.push({ text: s, style }));
      if (f.title) add(f.title, { weight: 700, color: PAL.ink });
      (f.notes || []).forEach((n) => add(n, { color: PAL.ink2 }));
      if (f.missing) add('缺少的事实：' + f.missing, { color: PAL.ink2 });
      // 事实的来源按「事件加字段」：事件里的测量值（例如已用时间）是主机测量，可以与事件本身的来源不同
      const source = f.source || (ev ? ev.source : null);
      if (ev) {
        add(ev.label, { weight: 600, color: PAL.ink });
        add(ev.type + ' · ' + Y12.time.format(ev.at), { color: PAL.grey3 });
        add('提出者 ' + ev.actor + ' · 全局位置 ' + ev.position, { color: PAL.grey3 });
        if (source !== ev.source) add('这条事实是事件里由主机测出的数值；事件本身的来源是' + kindOf(ev.source).label, { color: PAL.grey3 });
        if (source === 'decision_model' && ev.payload && ev.payload.probability !== undefined) add('概率 ' + ev.payload.probability, { weight: 700, color: PAL.orange2 });
      }
      const h = 26 + lines.length * 9 + (ev ? 20 : 4);
      const p = paper = place(w, h);
      RB(c, p.x - 2, p.y - 2, p.w + 4, p.h + 4, PAL.wood3);
      RB(c, p.x, p.y, p.w, p.h, PAL.paper);
      if (source) {
        R(c, p.x, p.y, 3, p.h, kindOf(source).unverified ? PAL.yellow2 : P.SOURCE_STYLE[source].line);
        P.drawSourceIcon(c, source, p.x + 8, p.y + 6);
        P.text(c, kindOf(source).label, p.x + 24, p.y + 12, { size: 7.5, weight: 800, color: PAL.ink });
      } else {
        R(c, p.x, p.y, 3, p.h, PAL.grey2);
        P.text(c, '不判定', p.x + 10, p.y + 12, { size: 7.5, weight: 800, color: PAL.grey3 });
      }
      button(c, p.x + p.w - 16, p.y + 5, 11, 11, '×', 'close');
      lines.forEach((l, i) => P.text(c, l.text, p.x + 10, p.y + 27 + i * 9, { size: 6.5, weight: l.style.weight || 500, color: l.style.color }));
      if (ev) button(c, p.x + 10, p.y + p.h - 17, 74, 12, '在时间轴上查看', 'seek', ev.position);
    }

    function drawList(c) {
      const rows = card.rows;
      const w = 430;
      const h = 30 + rows.length * 11 + 6;
      const p = paper = place(w, h);
      const MX = 238, RX = 320;   // 检验方式与结果两列的位置
      RB(c, p.x - 2, p.y - 2, p.w + 4, p.h + 4, PAL.wood3);
      RB(c, p.x, p.y, p.w, p.h, PAL.paper);
      R(c, p.x, p.y, 3, p.h, PAL.blue2);
      P.text(c, card.title, p.x + 10, p.y + 10, { size: 7.5, weight: 800, color: PAL.ink, max: p.w - 40 });
      button(c, p.x + p.w - 16, p.y + 4, 11, 11, '×', 'close');
      P.text(c, '验收条件', p.x + 10, p.y + 22, { size: 6, weight: 700, color: PAL.grey3 });
      P.text(c, '检验方式', p.x + MX, p.y + 22, { size: 6, weight: 700, color: PAL.grey3 });
      P.text(c, '最近一次结果', p.x + RX, p.y + 22, { size: 6, weight: 700, color: PAL.grey3 });
      rows.forEach((r, i) => {
        const y = p.y + 28 + i * 11;
        if (i % 2) R(c, p.x + 6, y, p.w - 12, 11, PAL.paper2);
        const tagW = r.open ? 24 : 0;
        P.text(c, r.label, p.x + 10, y + 5.5, { size: 6.5, weight: 600, color: PAL.ink, max: MX - 16 - tagW });
        if (r.open) {
          RB(c, p.x + MX - 6 - tagW, y + 1, 22, 9, PAL.yellow2);
          P.text(c, '开环', p.x + MX - 6 - tagW + 11, y + 5.5, { size: 6, weight: 800, align: 'center', color: PAL.ink });
        }
        P.text(c, r.method, p.x + MX, y + 5.5, { size: 6.5, color: PAL.ink2, max: RX - MX - 6 });
        const color = r.result === 'pass' ? PAL.green3 : r.result === 'fail' ? PAL.red3 : PAL.grey3;
        P.text(c, r.resultText, p.x + RX, y + 5.5, { size: 6.5, weight: 700, color, max: p.w - RX - 8 });
        if (r.fact) hits.push({ x: p.x + 6, y, w: p.w - 12, h: 11, act: 'row', arg: r.fact });
      });
    }

    function draw(c) {
      hits = [];
      if (!card) return;
      if (card.mode === 'list') drawList(c);
      else drawFact(c);
    }

    function hitAt(x, y) {
      for (let i = hits.length - 1; i >= 0; i--) {
        const h = hits[i];
        if (x >= h.x && x <= h.x + h.w && y >= h.y && y <= h.y + h.h) return h;
      }
      return null;
    }

    // 返回 true 表示卡片打开着，点击已经被它处理（点在纸的外面是关上）
    function click(x, y) {
      if (!card) return false;
      const h = hitAt(x, y);
      if (h) {
        if (h.act === 'close') close();
        else if (h.act === 'seek') { const pos = h.arg; close(); if (o.onSeek) o.onSeek(pos); }
        else if (h.act === 'row') open(h.arg);
        return true;
      }
      const inside = paper && x >= paper.x && x <= paper.x + paper.w && y >= paper.y && y <= paper.y + paper.h;
      if (!inside) close();
      return true;
    }

    return {
      open, openList, close, draw, click,
      cursor: (x, y) => (card && hitAt(x, y) ? 'pointer' : null),
      isOpen: () => Boolean(card),
      // 验收脚本读取：打开着的是哪一种、哪条事实、清单的各行
      state: () => (card ? { mode: card.mode, fact: card.fact || null, event: card.ev || null, title: card.title || null, rows: card.rows || null } : null),
      destroy: close
    };
  };
})();
