// 小人头顶的说话气泡（设计说明第 6 节）：小人做每一件事的时候，头顶冒出一句话说明自己现在在做什么。
// 说什么由翻译层写在动作里（动作的 say 与 sayTo，js/translate/say.js），这里只管怎么画：停留多久、怎么折行、几个气泡怎么错开。
(function () {
  'use strict';
  const Y13 = window.Y13;
  const P = Y13.pixel;
  if (!P || !P.bubble) throw new Error('say.js 需要先加载 js/pixel/engine.js');
  const PAL = P.PAL;

  // 一句话在头顶停留的毫秒数：读得完一句话，最长 4.6 秒
  P.sayMs = (text) => Math.min(4600, 1800 + String(text).length * 170);

  // ---------------------------------------------------------------------------
  // 画气泡：list 是 [{ a（小人的 actor）, text, kind: 'say'｜'think', until（消失的时间，最后 0.35 秒淡出）, tail（文字太长时留结尾） }]。
  // 文字按宽度折成最多两行；头顶有图标或举牌时画在它们上方；几个气泡水平重叠时依次往上抬，不互相盖住。
  // opt：{ W（画布宽度）, size（字号）, maxW（一行文字的最大宽度） }
  const layoutCache = {};
  function layout(c, text, size, maxW) {
    const key = text + '|' + size + '|' + maxW;
    if (layoutCache[key]) return layoutCache[key];
    const lines = [];
    let cur = '';
    Array.from(String(text)).forEach((ch) => {
      if (cur && P.measure(c, cur + ch, size, 500) > maxW) { lines.push(cur); cur = ch; } else cur += ch;
    });
    if (cur) lines.push(cur);
    if (lines.length > 2) {
      lines.length = 2;
      let last = lines[1];
      while (last.length > 1 && P.measure(c, last + '…', size, 500) > maxW) last = last.slice(0, -1);
      lines[1] = last + '…';
    }
    const w = Math.round(Math.max(...lines.map((l) => P.measure(c, l, size, 500))) + 8);
    if (Object.keys(layoutCache).length > 300) Object.keys(layoutCache).forEach((k) => { delete layoutCache[k]; });
    layoutCache[key] = { lines, w };
    return layoutCache[key];
  }

  P.drawSpeeches = function drawSpeeches(c, scene, list, opt) {
    const o = opt || {};
    const W = o.W || 640, size = o.size || 6, maxW = o.maxW || 84;
    const lh = size + 2;
    const rects = [];
    list.filter((it) => it.a && it.a.visible && it.text).sort((p, q) => p.a.x - q.a.x).forEach((it) => {
      const a = it.a;
      const [hx, hy] = P.headTop(scene, a);
      const text = it.tail && it.text.length > 24 ? '…' + it.text.slice(-23) : it.text;
      const lay = layout(c, text, size, maxW);
      const w = lay.w, h = lay.lines.length * lh + 3;
      const x = Math.max(2, Math.min(W - w - 2, Math.round(hx - w / 2 + 3)));
      // 头顶有状态图标或者举着的牌子时，气泡画在它们上方
      let y = hy - 9 - h - (a.icon || a.sign || (a.data && a.data.formSign) ? 14 : 0);
      while (rects.some((r) => x < r.x + r.w + 1 && x + w + 1 > r.x && y < r.y + r.h + 1 && y + h + 1 > r.y) && y > 2) y -= h + 2;
      y = Math.max(2, y);
      rects.push({ x, y, w, h });
      const fade = it.until && !scene.reduced ? Math.max(0, Math.min(1, (it.until - scene.realT) / 350)) : 1;
      c.globalAlpha = fade * (a.dim === undefined ? 1 : a.dim);
      P.bubble(c, x, y, w, h, { kind: it.kind === 'think' ? 'think' : 'say', tx: hx + 3 });
      lay.lines.forEach((line, i) => P.text(c, line, x + 4, y + 2 + i * lh + size / 2 + 0.5, { size, color: PAL.ink2 }));
      c.globalAlpha = 1;
    });
  };
})();
