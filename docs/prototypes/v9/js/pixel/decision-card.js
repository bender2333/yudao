// 世界里的决定卡片（设计说明第 7 节）：决定请求发出以后，一张决定单贴在大厅的板上；点板子，卡片在画面里摊开，
// 材料按种类写在纸上，选项是盖在纸上的章，说明写在纸下方的横线上。回答走命令接口，回答以后纸上盖「已回答」的章。
// 整个回答过程在世界里完成，不跳到画面以外的页面（材料里指向别的页面的链接是例外：那些页面自己还没有搬进世界）。
(function () {
  'use strict';
  const Y8 = window.Y8;
  const P = Y8.pixel;
  if (!P || !P.createScene) throw new Error('decision-card.js 需要先加载 js/pixel/engine.js');
  const PAL = P.PAL;
  const R = P.R, RB = P.RB;

  const W = 640, H = 320, BAR = 18;
  const PAPER = { x: 92, y: 26, w: 456, h: 270 };
  const LABEL_W = 78;
  // 卡片左边的色条：需要马上处理的种类偏橙，会造成损失的偏红，通知类偏蓝，其余是琥珀色
  const KIND_COLOR = { waiting_resume: PAL.orange2, unknown_action: PAL.orange2, rollback_restore: PAL.red2, repair_stopped: PAL.red2, provider_wait: PAL.blue2, rework_reminder: PAL.blue2 };

  // face：Y8.cards.face(决定请求) 给出的卡片内容
  // opts：{ onDecide({ decision_id, option, note, base_version }) → 命令的结果, onGo(链接), onChange() }
  P.createDecisionCard = function createDecisionCard(scene, canvas, opts) {
    const o = opts || {};
    let faces = [];
    let openId = null;
    let hits = [];
    let msg = null;
    let stamp = null;
    // 回答以后事件流带来的新列表里已经没有这个决定：纸留着这份内容，盖章结束再收起
    let ghost = null;
    const submitted = {};
    const notes = {};
    let wrapCache = {};
    let noteEl = null;

    // ---------------------------------------------------------------------------
    // 文字：按宽度折行（中文没有空格，逐字量）

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

    const rowLines = (c, face, i, valueW) => {
      const v = face.rows[i][1];
      const text = typeof v === 'object' && v ? v.text : v;
      const key = face.id + '|' + i + '|' + valueW + '|' + text;
      if (!wrapCache[key]) {
        if (Object.keys(wrapCache).length > 400) wrapCache = {};
        wrapCache[key] = wrap(c, text, valueW, 6.5, 500);
      }
      return wrapCache[key];
    };

    const faceOf = (id) => faces.find((f) => f.id === id) || null;
    // 打开着的那张卡片的内容：列表里已经没有它时用留下的那一份
    const shown = () => (openId ? faceOf(openId) || (ghost && ghost.id === openId ? ghost : null) : null);

    // ---------------------------------------------------------------------------
    // 说明的输入框：画面里的横线纸上叠一个透明的输入框，中文输入法需要它

    function ensureNote() {
      if (noteEl) return noteEl;
      const parent = canvas.parentElement;
      if (getComputedStyle(parent).position === 'static') parent.style.position = 'relative';
      noteEl = document.createElement('textarea');
      noteEl.setAttribute('aria-label', '决定的说明');
      noteEl.style.cssText = 'position:absolute;display:none;box-sizing:border-box;resize:none;border:1px solid #6a4a2e;background:#fff7dc;color:#1c1a26;padding:2px 4px;margin:0;outline:none;font-family:' + P.FONT + ';line-height:1.35;z-index:3';
      noteEl.addEventListener('input', () => { if (openId) notes[openId] = noteEl.value; });
      noteEl.addEventListener('keydown', (e) => { e.stopPropagation(); if (e.key === 'Escape') close(); });
      parent.appendChild(noteEl);
      return noteEl;
    }

    function placeNote(x, y, w, h, disabled) {
      const el = ensureNote();
      const r = canvas.getBoundingClientRect();
      const pr = canvas.parentElement.getBoundingClientRect();
      const sx = r.width / W, sy = r.height / H;
      el.style.left = (r.left - pr.left - canvas.parentElement.clientLeft + x * sx) + 'px';
      el.style.top = (r.top - pr.top - canvas.parentElement.clientTop + y * sy) + 'px';
      el.style.width = (w * sx) + 'px';
      el.style.height = (h * sy) + 'px';
      el.style.fontSize = (6.5 * sy) + 'px';
      el.style.display = 'block';
      el.disabled = Boolean(disabled);
      const want = notes[openId] || '';
      if (el.value !== want) el.value = want;
    }

    function hideNote() { if (noteEl) noteEl.style.display = 'none'; }

    // ---------------------------------------------------------------------------
    // 打开、关闭、翻页

    function onKey(e) {
      if (!openId) return;
      // 别处的文本框里打字（方向键移动光标）不算对卡片的操作
      const t = e.target;
      if (t && t !== noteEl && (/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName) || t.isContentEditable)) return;
      if (e.key === 'Escape') close();
      else if (e.key === 'ArrowLeft') flip(-1);
      else if (e.key === 'ArrowRight') flip(1);
    }

    function open(id) {
      const face = (id && faceOf(id)) || faces[0];
      if (!face) return;
      if (!openId) document.addEventListener('keydown', onKey);
      openId = face.id;
      msg = null;
    }

    function close() {
      if (openId) {
        document.removeEventListener('keydown', onKey);
        // 提交过的说明随卡片收起；列表里已经没有的决定，提交记录也一起清掉
        if (submitted[openId]) delete notes[openId];
        if (!faceOf(openId)) { delete submitted[openId]; delete notes[openId]; }
      }
      openId = null;
      ghost = null;
      msg = null;
      hideNote();
    }

    function flip(d) {
      const i = faces.findIndex((f) => f.id === openId);
      if (i < 0 || faces.length < 2) return;
      openId = faces[(i + d + faces.length) % faces.length].id;
      msg = null;
    }

    // ---------------------------------------------------------------------------
    // 回答

    function answer(face, op) {
      if (submitted[face.id]) return;
      const note = (notes[face.id] || '').trim();
      if (op.note_required && !note) { msg = { text: '「' + op.label + '」需要在说明里写明修改意见', until: scene.realT + 2600 }; return; }
      const result = o.onDecide ? o.onDecide({ decision_id: face.id, option: op.id, note, base_version: face.version }) : null;
      if (!result || !result.accepted) {
        msg = { text: (result && result.message) || '控制主机没有接受这个回答', until: scene.realT + 3200 };
        return;
      }
      submitted[face.id] = true;
      stamp = { id: face.id, text: '已回答：' + op.label, t0: scene.realT };
      scene.after(1200, () => { stamp = null; if (openId === face.id) close(); });
    }

    // ---------------------------------------------------------------------------
    // 绘制

    function button(c, x, y, w, h, text, style, act, arg, disabled) {
      const bg = disabled ? PAL.grey1 : style === 'primary' ? PAL.green2 : style === 'danger' ? PAL.red2 : PAL.white;
      const fg = disabled ? PAL.grey3 : style === 'primary' || style === 'danger' ? PAL.white : PAL.ink;
      RB(c, x, y, w, h, bg);
      R(c, x + 1, y + 1, w - 2, 1, disabled ? PAL.grey1 : P.mix(bg, PAL.white, 0.35));
      P.text(c, text, x + w / 2, y + h / 2 + 0.5, { size: 6.5, weight: 700, align: 'center', color: fg, max: w - 6 });
      if (!disabled && act) hits.push({ x, y, w, h, act, arg });
    }

    function draw(c) {
      hits = [];
      const face = shown();
      if (!face) { hideNote(); return; }
      const px = PAPER.x, py = PAPER.y, pw = PAPER.w, ph = PAPER.h;
      c.fillStyle = 'rgba(12,14,30,0.58)';
      c.fillRect(0, BAR, W, H - BAR);
      // 纸：木框、纸面、左边的色条、上面的图钉
      RB(c, px - 3, py - 3, pw + 6, ph + 6, PAL.wood3);
      RB(c, px, py, pw, ph, PAL.paper);
      R(c, px, py, 4, ph, KIND_COLOR[face.kind] || PAL.yellow2);
      RB(c, px + pw / 2 - 4, py - 6, 8, 8, PAL.red2);
      // 抬头：图标、种类、翻页与关闭
      P.drawBitmap(c, 'decision', px + 12, py + 8);
      P.text(c, face.title, px + 28, py + 14, { size: 8.5, weight: 800, color: PAL.ink, max: pw - 132 });
      const idx = faces.findIndex((f) => f.id === face.id);
      // 翻页在左，关闭在右，两组按钮之间留出间隔
      const bx = px + pw - 88;
      if (faces.length > 1 && idx >= 0) {
        button(c, bx, py + 6, 12, 12, '‹', null, 'prev');
        P.text(c, (idx + 1) + '/' + faces.length, bx + 26, py + 12.5, { size: 6.5, weight: 700, align: 'center', color: PAL.ink2 });
        button(c, bx + 40, py + 6, 12, 12, '›', null, 'next');
      }
      button(c, px + pw - 18, py + 6, 12, 12, '×', null, 'close');
      P.text(c, face.where, px + 14, py + 30, { size: 6.5, weight: 600, color: PAL.ink2, max: pw - 28 });
      P.text(c, face.waited + ' · ' + face.blocks, px + 14, py + 40, { size: 6, color: PAL.grey3, max: pw - 28 });
      R(c, px + 10, py + 46, pw - 20, 1, PAL.wood2);
      // 材料：标题在左，内容在右，按宽度折行；放不下的行截断，链接固定在说明栏上方的一行
      const valueX = px + 14 + LABEL_W, valueW = pw - 28 - LABEL_W;
      const noteY = py + ph - 74;
      const linksY = noteY - 34;
      const limit = (face.links.length ? linksY : noteY - 22) - 6;
      let y = py + 54;
      let cut = false;
      face.rows.forEach((row, i) => {
        if (cut) return;
        const lines = rowLines(c, face, i, valueW);
        const v = row[1];
        const isLink = Boolean(v && typeof v === 'object');
        // 这一行放不下：能放下几行画几行，最后一行以省略号结尾，后面的行不画
        const fit = Math.min(lines.length, Math.floor((limit - y) / 8));
        if (fit < lines.length) cut = true;
        if (fit < 1) return;
        P.text(c, row[0], px + 14, y + 4, { size: 6, weight: 600, color: PAL.grey3, max: LABEL_W - 4 });
        lines.slice(0, fit).forEach((line, k) => P.text(c, cut && k === fit - 1 ? line + '…' : line, valueX, y + 4 + k * 8, { size: 6.5, weight: isLink ? 700 : 500, color: isLink ? PAL.blue3 : PAL.ink, max: valueW }));
        if (isLink) hits.push({ x: valueX, y: y - 1, w: valueW, h: fit * 8 + 2, act: 'go', arg: v.go });
        y += fit * 8 + 3;
      });
      if (cut) P.text(c, '材料较长，其余内容在页面下方的文字列表里', px + pw - 14, noteY - 5, { size: 6, align: 'right', color: PAL.grey3 });
      // 材料里的链接（去别的页面）
      let lx = px + 14;
      face.links.forEach((l) => {
        const w = Math.min(150, Math.ceil(P.measure(c, l.text, 6.5, 700)) + 14);
        button(c, lx, linksY, w, 12, l.text, null, 'go', l.go);
        lx += w + 6;
      });
      // 说明
      const done = Boolean(submitted[face.id]);
      P.text(c, '说明（可选）', px + 14, noteY - 5, { size: 6, weight: 600, color: PAL.grey3 });
      placeNote(px + 10, noteY, pw - 20, 30, done);
      // 选项：盖在纸上的章；选项太多放不下时按比例收窄
      const oy = py + ph - 34;
      let ox = px + 12;
      const natural = face.options.map((op) => Math.max(58, Math.ceil(P.measure(c, op.label, 6.5, 700)) + 18));
      const gap = 8;
      const room = pw - 24 - gap * Math.max(0, natural.length - 1);
      const sum = natural.reduce((s, w) => s + w, 0);
      const k = sum > room ? room / sum : 1;
      face.options.forEach((op, i) => {
        const w = Math.max(30, Math.floor(natural[i] * k));
        button(c, ox, oy, w, 18, op.label, op.kind, 'option', op.id, done);
        ox += w + gap;
      });
      if (done) P.text(c, '已提交，等待控制主机确认', ox + 4, oy + 9, { size: 6.5, weight: 600, color: PAL.green3 });
      if (msg && msg.until > scene.realT) P.text(c, msg.text, px + 14, oy - 8, { size: 6.5, weight: 700, color: PAL.red3, max: pw - 28 });
      // 回答以后盖上的章
      if (stamp && stamp.id === face.id) {
        const k = Math.min(1, (scene.realT - stamp.t0) / 220);
        c.save();
        c.translate(px + pw / 2, py + ph / 2 - 8);
        c.rotate(-0.16);
        c.globalAlpha = 0.9 * k;
        const s = 1.6 - 0.6 * k;
        c.scale(s, s);
        const w = Math.ceil(P.measure(c, stamp.text, 12, 900)) + 24;
        c.fillStyle = PAL.green3;
        c.fillRect(-w / 2, -14, w, 28);
        c.fillStyle = PAL.paper;
        c.fillRect(-w / 2 + 2, -12, w - 4, 24);
        P.text(c, stamp.text, 0, 0.5, { size: 12, weight: 900, align: 'center', color: PAL.green3 });
        c.restore();
      }
    }

    // ---------------------------------------------------------------------------
    // 点击与鼠标

    function hitAt(x, y) {
      for (let i = hits.length - 1; i >= 0; i--) {
        const h = hits[i];
        if (x >= h.x && x <= h.x + h.w && y >= h.y && y <= h.y + h.h) return h;
      }
      return null;
    }

    // 返回 true 表示卡片打开着，点击已经被它处理（点在纸外面是关上）
    function click(x, y) {
      if (!openId) return false;
      const face = shown();
      const h = hitAt(x, y);
      if (h && face) {
        if (h.act === 'close') close();
        else if (h.act === 'prev') flip(-1);
        else if (h.act === 'next') flip(1);
        else if (h.act === 'go') { if (o.onGo) o.onGo(h.arg); }
        else if (h.act === 'option') answer(face, face.options.find((op) => op.id === h.arg));
        return true;
      }
      const inside = x >= PAPER.x && x <= PAPER.x + PAPER.w && y >= PAPER.y && y <= PAPER.y + PAPER.h;
      if (!inside && y > BAR) close();
      return true;
    }

    function cursor(x, y) {
      return openId && hitAt(x, y) ? 'pointer' : null;
    }

    // ---------------------------------------------------------------------------
    // 数据

    function setDecisions(list) {
      const next = list || [];
      // 正在盖章的决定被回答事件带来的新列表拿掉了：留下这份内容，盖章结束（1.2 秒）再收起
      if (openId && stamp && stamp.id === openId && !next.some((f) => f.id === openId)) ghost = faceOf(openId) || ghost;
      faces = next;
      const alive = (id) => Boolean(faceOf(id)) || Boolean(ghost && ghost.id === id);
      Object.keys(submitted).forEach((id) => { if (!alive(id)) delete submitted[id]; });
      Object.keys(notes).forEach((id) => { if (!alive(id)) delete notes[id]; });
      if (openId && !alive(openId)) close();
    }

    function destroy() {
      close();
      if (noteEl) { noteEl.remove(); noteEl = null; }
    }

    return {
      setDecisions, open, close, draw, click, cursor, destroy,
      isOpen: () => Boolean(openId),
      openId: () => openId,
      // 回答事件到达时盖章；自己刚回答过的已经盖着章，不重盖
      stamp: (id, text) => { if (!stamp || stamp.id !== id) stamp = { id, text, t0: scene.realT }; }
    };
  };
})();
