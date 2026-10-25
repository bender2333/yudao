// 回放（设计说明第 5.5 节）：时间轴只取关键事实（home.away_report 的 facts），没有关键事实的时间段跳过并用折断符号标出；
// 播放、暂停、单步、三档速度；点击刻度直接显示该时刻的状态。回放位置写在路径参数 at 中
(function () {
  'use strict';
  const Y9 = window.Y9;
  const esc = Y9.esc;

  const SPEEDS = [1, 2, 4];
  const BASE_MS = 1600;
  const GAP_SEC = 2 * 3600;   // 相邻关键事实相隔超过这个时长时画折断符号
  let active = null;

  // opts：{ el, project, range, onPosition(position|null), onFact(fact), onSelect(position) }
  function create(opts) {
    if (!opts || !opts.el) throw new Error('回放需要容器');
    const ctl = {
      facts: [], report: null, index: -1, position: null, playing: false, speed: 1, timer: null, highlight: new Set(), range: opts.range || 'since_seen'
    };

    function load() {
      const params = { range: ctl.range };
      if (opts.project) params.project = opts.project;
      ctl.report = Y9.api.query('home.away_report', params).data;
      ctl.facts = ctl.report.facts;
    }

    function stopTimer() {
      if (ctl.timer) clearTimeout(ctl.timer);
      ctl.timer = null;
      ctl.playing = false;
    }

    function setPosition(pos, fact) {
      ctl.position = pos;
      Y9.replaceQuery('at', pos);
      opts.onPosition(pos);
      if (fact) opts.onFact(fact);
      render();
    }

    const api = {
      get active() { return ctl.position !== null; },
      position: () => ctl.position,
      start() {
        stopTimer();
        ctl.index = -1;
        setPosition(ctl.report.range.from_position, null);
      },
      step() {
        if (ctl.position === null) api.start();
        if (ctl.index + 1 >= ctl.facts.length) { api.live(); return false; }
        ctl.index += 1;
        const fact = ctl.facts[ctl.index];
        setPosition(fact.position, fact);
        return true;
      },
      play() {
        if (ctl.position === null || ctl.index + 1 >= ctl.facts.length) api.start();
        ctl.playing = true;
        render();
        const tick = () => {
          if (!ctl.playing) return;
          ctl.timer = setTimeout(() => {
            if (api.step() && ctl.playing) tick();
          }, BASE_MS / ctl.speed);
        };
        tick();
      },
      pause() { stopTimer(); render(); },
      setSpeed(s) {
        if (!SPEEDS.includes(s)) throw new Error('回放速度无效：' + s);
        ctl.speed = s;
        render();
      },
      seek(index) {
        stopTimer();
        ctl.index = index;
        setPosition(ctl.facts[index].position, null);
        if (opts.onSelect) opts.onSelect(ctl.facts[index].position);
      },
      live() {
        stopTimer();
        ctl.index = -1;
        setPosition(null, null);
      },
      setRange(range) {
        ctl.range = range;
        load();
        if (ctl.position !== null) api.start();
        else render();
      },
      highlight(positions) {
        ctl.highlight = new Set(positions || []);
        render();
      },
      reload() {
        load();
        render();
      },
      destroy() {
        stopTimer();
        if (active === api) active = null;
      }
    };

    function tickHtml(f, i) {
      const kind = Y9.registry.KEY_KINDS[f.kind];
      const on = i === ctl.index;
      const hl = ctl.highlight.has(f.position);
      return '<button type="button" class="y9-tick' + (on ? ' is-current' : '') + (hl ? ' is-highlight' : '') + (i < ctl.index ? ' is-past' : '') + '" style="--tick:' + kind.color +
        '" data-act="replay.seek" data-index="' + i + '" title="' + esc(Y9.time.format(f.at, Y9.app.now()) + ' · ' + kind.label + ' · ' + f.label) + '"><span></span></button>';
    }

    function render() {
      const facts = ctl.facts;
      const parts = [];
      facts.forEach((f, i) => {
        if (i > 0) {
          const gap = Y9.time.between(facts[i - 1].at, f.at);
          if (gap > GAP_SEC) parts.push('<span class="y9-tick-break" title="跳过 ' + esc(Y9.time.duration(gap)) + '">⫽<small>' + esc(Y9.time.duration(gap)) + '</small></span>');
        }
        parts.push(tickHtml(f, i));
      });
      const current = ctl.index >= 0 ? facts[ctl.index] : null;
      const legend = Object.keys(Y9.registry.KEY_KINDS).filter((k) => facts.some((f) => f.kind === k))
        .map((k) => '<span class="y9-legend" style="--tick:' + Y9.registry.KEY_KINDS[k].color + '"><i></i>' + esc(Y9.registry.KEY_KINDS[k].label) + '</span>').join('');
      const status = ctl.position !== null
        ? '<span class="y9-replay-on">回放中 · ' + esc(current ? Y9.time.format(current.at, Y9.app.now()) : Y9.time.format(ctl.report.range.from_at, Y9.app.now())) + '</span>' +
          (current ? '<span class="y9-replay-fact">' + esc(current.label) + '</span>' : '<span class="y9-replay-fact">范围的起点</span>')
        : '<span class="y9-muted">实时画面 · ' + facts.length + ' 条关键事实</span>';
      opts.el.innerHTML = '<div class="y9-replay">' +
        '<div class="y9-replay-bar">' +
          '<button type="button" class="y9-btn small" data-act="replay.toggle"' + (facts.length ? '' : ' disabled') + '>' + Y9.ui.icon(ctl.playing ? 'pause' : 'play') + '<span>' + (ctl.playing ? '暂停' : '播放') + '</span></button>' +
          '<button type="button" class="y9-btn small" data-act="replay.step"' + (facts.length ? '' : ' disabled') + '>' + Y9.ui.icon('step') + '<span>单步</span></button>' +
          '<span class="y9-seg">' + SPEEDS.map((s) => '<button type="button" class="y9-seg-btn' + (s === ctl.speed ? ' is-on' : '') + '" data-act="replay.speed" data-speed="' + s + '">' + s + '×</button>').join('') + '</span>' +
          '<button type="button" class="y9-btn small" data-act="replay.live"' + (ctl.position === null ? ' disabled' : '') + '>回到现在</button>' +
          status +
        '</div>' +
        '<div class="y9-ticks" role="list" aria-label="关键事实的时间轴">' + (parts.length ? parts.join('') : '<span class="y9-muted">所选范围内没有关键事实</span>') + '</div>' +
        (legend ? '<div class="y9-legends">' + legend + '</div>' : '') +
      '</div>';
    }

    load();
    render();
    active = api;
    // 路径中带 at 时从该位置开始（刷新后保持）
    const at = Y9.route().query.at;
    if (at !== undefined) {
      const idx = ctl.facts.findIndex((f) => String(f.position) === String(at));
      ctl.index = idx;
      ctl.position = Number(at);
      opts.onPosition(ctl.position);
      render();
    }
    ctl.api = api;
    api._ctl = ctl;
    return api;
  }

  function need() {
    if (!active) throw new Error('当前页面没有回放时间轴');
    return active;
  }

  Y9.actions.register('replay.toggle', () => { const a = need(); if (a._ctl.playing) a.pause(); else a.play(); });
  Y9.actions.register('replay.step', () => need().step());
  Y9.actions.register('replay.start', () => need().start());
  Y9.actions.register('replay.live', () => need().live());
  Y9.actions.register('replay.seek', (el) => need().seek(Number(el.dataset.index)));
  Y9.actions.register('replay.speed', (el) => need().setSpeed(Number(el.dataset.speed)));

  Y9.replay = { create, active: () => active };
})();
