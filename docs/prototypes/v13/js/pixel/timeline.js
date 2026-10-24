// 播放时间线（画面与播放设计说明第 5.2 节）：决定演什么、什么时候演、丢什么。楼、楼层、房间三个场景各有一条，规则只写在这里。
// 纯逻辑：不碰画布，不读页面的时钟，时钟由创建者传入（clock() 返回毫秒）。checks/timeline.js 在 Node 里直接检查它。
//
// 输入：动作（画面合同，带 position）、状态（画面合同，带 position）、跳到最新、渲染报告某个动作演完。
// 输出（回调）：开始演一个动作、立刻结束一个动作、把一份状态放上画面、显示一个进度动作。
//
// 规则：
// - 动作按位置进入时间线。一个动作占用它的参与方（lanes，通常是角色）；同一个参与方一次只演一件事，不同参与方可以同时演。
// - 动作分三级：关键一定演，堆积时可以缩短；普通排队演，排得太长或画面落后超过上限时丢掉；进度不排队，到了就交给渲染。
// - 动作至少演满声明的时长（ms），并且等渲染报告演完（done）才结束。
// - 状态只等位置不大于它、还在队里或正在演的动作；这些动作结束以后它上画面，没有这样的动作时下一帧就上画面。
// - 画面落后上限：一份状态到达以后最多等 lagMs。来不及时快进：普通动作丢掉，同一个参与方连续的同类关键动作合并成一次，
//   关键动作按比例缩短（最短 minMs）；到了上限仍没有演完的，正在演的立刻结束，状态照样上画面，排着的关键动作接着演。
// - 跳到最新：清空时间线，正在演的立刻结束，直接显示给出的状态，不补播。
(function () {
  'use strict';
  const P = window.Y13.pixel;

  // 三个场景共用的播放参数：落后上限、缩短时的最短时长、声明时长的倍率。原型的调节面板改这里（暂定值，等用户看过效果再定）
  const settings = { lagMs: 5000, minMs: 300, speed: 1 };

  // 一个参与方排着的普通动作最多几条，再多就丢掉最早的一条
  const MAX_NORMAL = 3;

  const LEVELS = ['key', 'normal', 'progress'];

  // o：{ clock(), classify(动作) → { level, ms, lanes }, begin(条目), cut(条目), apply(状态), progress(动作) }
  // 条目：{ id, action, pos, level, ms, lanes, arrivedAt, startAt, doneAt, cutAt, short, merged }
  function create(o) {
    ['clock', 'classify', 'begin', 'cut', 'apply', 'progress'].forEach((k) => {
      if (typeof o[k] !== 'function') throw new Error('播放时间线缺少回调：' + k);
    });
    let seq = 0;
    let entries = [];
    let pending = [];
    let shown = null;
    const stats = { pushed: 0, pushedKey: 0, started: 0, startedKey: 0, dropped: 0, droppedKey: 0, merged: 0, shortened: 0, cut: 0, forced: 0, maxLag: 0 };

    const playing = (e) => e.startAt !== null;
    const queued = (e) => e.startAt === null;
    const shares = (a, b) => a.lanes.some((l) => b.lanes.includes(l));
    const sameLanes = (a, b) => a.lanes.length === b.lanes.length && a.lanes.every((l, i) => l === b.lanes[i]);

    function remove(e) { entries = entries.filter((x) => x !== e); }

    function drop(e) {
      remove(e);
      stats.dropped += 1;
      if (e.level === 'key') throw new Error('关键动作不能丢掉：' + e.action.kind);
    }

    function end(e, byCut) {
      remove(e);
      if (byCut) { stats.cut += 1; o.cut(e); }
    }

    function push(action) {
      if (!action || !action.kind) throw new Error('时间线需要画面合同的动作');
      if (!Number.isFinite(action.position)) throw new Error('动作没有位置：' + action.kind);
      const c = o.classify(action);
      if (!c || !LEVELS.includes(c.level)) throw new Error('动作的级别无效：' + action.kind);
      stats.pushed += 1;
      if (c.level === 'progress') { o.progress(action); return null; }
      if (!(c.ms >= 0)) throw new Error('动作没有声明时长：' + action.kind);
      if (c.level === 'key') stats.pushedKey += 1;
      const e = {
        id: ++seq, action, pos: action.position, level: c.level, ms: c.ms * settings.speed, lanes: c.lanes || [],
        arrivedAt: o.clock(), startAt: null, doneAt: null, cutAt: null, short: false, merged: 0
      };
      // 按位置插入：位置更大的、还没有开始的动作排在它后面
      let i = entries.length;
      while (i > 0 && queued(entries[i - 1]) && entries[i - 1].pos > e.pos) i -= 1;
      entries.splice(i, 0, e);
      // 队伍过长：这个动作经过的每个参与方，排着的普通动作超过上限时丢掉最早的一条
      e.lanes.forEach((lane) => {
        let list = entries.filter((x) => queued(x) && x.level === 'normal' && x.lanes.includes(lane));
        while (list.length > MAX_NORMAL) { drop(list[0]); list = list.slice(1); }
      });
      return e;
    }

    function state(s) {
      if (!s || !Number.isFinite(s.position)) throw new Error('状态没有位置');
      // 比画面上的状态还旧的结果（跳到最新以后才回来的查询）不再上画面
      if (shown !== null && s.position < shown) return;
      pending.push({ state: s, pos: s.position, arrivedAt: o.clock() });
    }

    function jump(s) {
      if (!s || !Number.isFinite(s.position)) throw new Error('状态没有位置');
      entries.filter(playing).forEach((e) => { stats.cut += 1; o.cut(e); });
      entries = [];
      pending = [];
      shown = s.position;
      o.apply(s);
    }

    function done(id) {
      const e = entries.find((x) => x.id === id);
      if (e && e.doneAt === null) e.doneAt = o.clock();
    }

    const blockersOf = (pos) => entries.filter((e) => e.pos <= pos);

    // 每个参与方还要多久：正在演的按声明时长算剩下的部分，已经演满声明时长、渲染还没演完的按一个最短时长算；
    // 排着的按声明时长；不占参与方的动作各算各的
    function need(list, now) {
      const per = {};
      let free = 0;
      list.forEach((e) => {
        const over = playing(e) && e.doneAt === null && now >= e.startAt + e.ms;
        const left = !playing(e) ? e.ms : over ? settings.minMs : Math.max(0, Math.min(e.cutAt === null ? Infinity : e.cutAt, e.startAt + e.ms) - now);
        if (!e.lanes.length) { free = Math.max(free, left); return; }
        e.lanes.forEach((l) => { per[l] = (per[l] || 0) + left; });
      });
      return Math.max(free, ...Object.values(per), 0);
    }

    // 最紧的一份状态：没上画面的状态里，剩下的时间与它前面的动作还要多久之比最小的一份
    function tightest(now) {
      let worst = null;
      pending.forEach((p) => {
        const n = need(blockersOf(p.pos), now);
        if (n <= 0) return;
        const ratio = (p.arrivedAt + settings.lagMs - now) / n;
        if (!worst || ratio < worst.ratio) worst = { p, ratio };
      });
      return worst;
    }

    // 快进：有状态来不及在上限之内上画面时，按规则丢、合并、缩短它前面的动作
    function fastForward(now) {
      let w = tightest(now);
      if (!w || w.ratio >= 1) return;
      blockersOf(w.p.pos).filter((e) => e.level === 'normal').forEach((e) => {
        if (playing(e)) end(e, true);
        else drop(e);
      });
      w = tightest(now);
      if (!w || w.ratio >= 1) return;
      // 同一个参与方连续排着的同类关键动作并进第一条：内容取最新的一条，位置取最大的
      let list = blockersOf(w.p.pos).filter(queued);
      for (let i = 0; i < list.length; i++) {
        const a = list[i];
        if (!entries.includes(a)) continue;
        for (let j = i + 1; j < list.length; j++) {
          const b = list[j];
          if (!entries.includes(b)) continue;
          if (!shares(a, b)) continue;
          if (b.action.kind !== a.action.kind || !sameLanes(a, b)) break;
          a.action = b.action;
          a.pos = Math.max(a.pos, b.pos);
          a.merged += 1 + b.merged;
          remove(b);
          stats.merged += 1;
        }
      }
      w = tightest(now);
      // 已经过了上限的由第 4 步强制上画面
      if (!w || w.ratio >= 1 || w.ratio <= 0) return;
      const k = w.ratio;
      blockersOf(w.p.pos).forEach((e) => {
        if (playing(e)) {
          const left = Math.max(0, e.startAt + e.ms - now);
          const at = Math.max(e.startAt + settings.minMs, now + left * k);
          if (e.cutAt === null || at < e.cutAt) e.cutAt = at;
        } else {
          const ms = Math.max(settings.minMs, e.ms * k);
          if (ms < e.ms) { e.ms = ms; if (!e.short) stats.shortened += 1; e.short = true; }
        }
      });
    }

    function tick() {
      const now = o.clock();
      // 1. 结束：至少演满声明的时长并且渲染报告演完；缩短过的到了时间直接结束
      entries.filter(playing).forEach((e) => {
        if (e.cutAt !== null && now >= e.cutAt) end(e, e.doneAt === null || now < e.startAt + e.ms);
        else if (e.doneAt !== null && now >= e.startAt + e.ms) end(e, false);
      });
      // 2. 快进
      if (pending.length) fastForward(now);
      // 3. 开始：参与方都空着，并且这些参与方上没有位置更早、还排着的动作
      entries.slice().forEach((e) => {
        if (!queued(e) || !entries.includes(e)) return;
        const busy = entries.some((x) => x !== e && shares(x, e) && (playing(x) || entries.indexOf(x) < entries.indexOf(e)));
        if (busy) return;
        e.startAt = now;
        if (e.short) e.cutAt = now + e.ms;
        stats.started += 1;
        if (e.level === 'key') stats.startedKey += 1 + e.merged;
        o.begin(e);
      });
      // 4. 状态上画面：前面的动作都结束了的最新一份；或者到了落后上限的最新一份（它前面正在演的动作立刻结束，排着的普通动作丢掉）。
      // 落后多少按最早一份没上画面的状态等了多久算，在上画面之前量（逐帧推进，最多比上限多一帧）
      const lag = pending.length ? now - pending[0].arrivedAt : 0;
      if (lag > stats.maxLag) stats.maxLag = lag;
      let k = -1;
      pending.forEach((p, i) => {
        if (!blockersOf(p.pos).length || now >= p.arrivedAt + settings.lagMs) k = i;
      });
      if (k >= 0) {
        const p = pending[k];
        const left = blockersOf(p.pos);
        if (left.length) {
          stats.forced += 1;
          left.forEach((e) => {
            if (playing(e)) end(e, true);
            else if (e.level === 'normal') drop(e);
          });
        }
        pending = pending.slice(k + 1);
        shown = p.pos;
        o.apply(p.state);
      }
    }

    function inspect() {
      const now = o.clock();
      return {
        shown, pending: pending.length, lag: pending.length ? now - pending[0].arrivedAt : 0,
        queued: entries.filter(queued).length, playing: entries.filter(playing).map((e) => ({ id: e.id, kind: e.action.kind, lanes: e.lanes.slice(), level: e.level, ms: e.ms })),
        stats: Object.assign({}, stats)
      };
    }

    return { push, state, jump, done, tick, inspect };
  }

  P.timeline = { settings, create, MAX_NORMAL };
})();
