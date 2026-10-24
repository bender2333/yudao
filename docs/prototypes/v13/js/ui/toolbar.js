// 原型工具条：档位切换、标注、场景播放器、模拟（系统通知、断开连接、接口版本、离开的时长）、动作图鉴、主题。
// 原型专用，可以直接读写示例后端（BUILD.md 第 2 节的例外）
(function () {
  'use strict';
  const Y13 = window.Y13;

  const player = { id: null, step: 0, playing: false, last: null, timer: null };
  let open = window.innerWidth > 760;
  let simOpen = false;

  function scenarios() { return Y13.backend.scenarios(); }

  function current() {
    if (!player.id) return null;
    const found = scenarios().find((sc) => sc.id === player.id);
    if (!found) throw new Error('找不到场景：' + player.id);
    return found;
  }

  function stop() {
    if (player.timer) clearTimeout(player.timer);
    player.timer = null;
    player.playing = false;
  }

  Y13.scenario = {
    current,
    state: () => player,
    select(id) {
      stop();
      Y13.backend.reset();
      Object.assign(player, { id: id || null, step: 0, last: null });
      const sc = current();
      if (sc) {
        if (sc.level && !Y13.level.atLeast(sc.level)) Y13.level.set(sc.level);
        else Y13.backend.refold();
        Y13.backend.setup(sc.setup, '场景「' + sc.name + '」的准备');
        Y13.bus.emit('scenario-changed', player);
        if (sc.go) {
          if (location.hash === sc.go) Y13.app.renderAll(false);
          else Y13.go(sc.go);
        } else {
          Y13.app.renderAll(true);
        }
      } else {
        Y13.backend.refold();
        Y13.bus.emit('scenario-changed', player);
        Y13.app.renderAll(true);
      }
    },
    reset() { Y13.scenario.select(player.id); },
    step() {
      const sc = current();
      if (!sc) throw new Error('没有选择场景');
      if (player.step >= sc.steps.length) {
        stop();
        render();
        return false;
      }
      const st = sc.steps[player.step];
      player.step += 1;
      if (player.step >= sc.steps.length) stop();
      if (st.go && location.hash !== st.go) Y13.go(st.go);
      if (st.event) {
        const spec = Object.assign({ project_id: null, work_item_id: null, run_id: null, department: null, role: null, payload: {} }, Y13.clone(st.event));
        spec.patch = Y13.clone(st.patch || []);
        player.last = Y13.backend.emit(spec);
      } else if (st.act) {
        player.last = { type: st.act, label: st.label || st.act };
        // 界面动作的参数照页面元素的 data-* 给出
        Y13.actions.run(st.act, { dataset: Object.assign({}, st.data || {}) }, null);
      } else {
        player.last = { type: '跳转', label: st.label };
      }
      render();
      return true;
    },
    play() {
      const sc = current();
      if (!sc) throw new Error('没有选择场景');
      if (player.step >= sc.steps.length) Y13.scenario.select(sc.id);
      player.playing = true;
      render();
      const tick = () => {
        const s = current();
        if (!player.playing || !s) return;
        const next = s.steps[player.step];
        if (!next) {
          stop();
          render();
          return;
        }
        player.timer = setTimeout(() => {
          Y13.scenario.step();
          tick();
        }, next.delay || 1200);
      };
      tick();
    },
    pause() {
      stop();
      render();
    }
  };

  // 离开的时长：上次查看的时间设为现在往前若干小时
  const AWAY = [['3d', '三天', 72], ['1d', '一天', 24], ['8h', '八小时', 8], ['1h', '一小时', 1]];

  function render() {
    const host = Y13.app.dom.toolbar;
    if (!host) return;
    const sc = current();
    const total = sc ? sc.steps.length : 0;
    const level = Y13.level.current();
    const levelOptions = Y13.LEVELS.map((lv) => '<option value="' + lv + '"' + (lv === level ? ' selected' : '') + '>' + Y13.esc(Y13.LEVEL_LABELS[lv]) + '</option>').join('');
    const options = '<option value="">选择场景…</option>' + scenarios().map((item) =>
      '<option value="' + Y13.esc(item.id) + '"' + (item.id === player.id ? ' selected' : '') + '>' + item.no + '. ' + Y13.esc(item.name) + ' · ' + Y13.esc(Y13.LEVEL_LABELS[item.level || 'ui']) + '</option>'
    ).join('');
    const theme = Y13.app.theme();
    const themeOptions = [['system', '跟随系统'], ['light', '浅色'], ['dark', '深色']].map((pair) =>
      '<option value="' + pair[0] + '"' + (theme === pair[0] ? ' selected' : '') + '>' + pair[1] + '</option>').join('');
    const ev = player.last;
    const eventLine = sc
      ? (ev ? '<code>' + Y13.esc(ev.type) + '</code><span>' + Y13.esc(ev.label || '') + '</span>'
        : '<span class="y13-tb-hint">场景「' + Y13.esc(sc.name) + '」共 ' + total + ' 步，点击「单步」或「播放」开始</span>')
      : '<span class="y13-tb-hint">选择场景后逐步播放事件，每一步显示驱动画面的事件</span>';
    const connected = Y13.backend.sim.connected();
    const apiVersion = Y13.backend.sim.apiVersion();
    const sim = simOpen
      ? '<div class="y13-tb-sim">' +
          '<label><input type="checkbox" data-act="tb.connected"' + (connected ? ' checked' : '') + '><span>与控制主机连接</span></label>' +
          '<label><span>服务的接口版本</span><select class="y13-tb-select" data-act="tb.api">' +
            [1, 2, 3].map((n) => '<option value="' + n + '"' + (n === apiVersion ? ' selected' : '') + '>' + n + (n === Y13.CLIENT_API_VERSION ? '（与页面相同）' : n < Y13.CLIENT_API_VERSION ? '（服务较旧）' : '（服务较新）') + '</option>').join('') + '</select></label>' +
          '<label><span>离开的时长</span><select class="y13-tb-select" data-act="tb.away"><option value="">保持</option>' +
            AWAY.map((a) => '<option value="' + a[0] + '">' + a[1] + '</option>').join('') + '</select></label>' +
          '<button type="button" class="y13-tb-btn" data-act="tb.notify">' + Y13.ui.icon('bell') + '<span>模拟一条通知</span></button>' +
        '</div>'
      : '';
    host.className = 'y13-toolbar' + (open ? ' is-open' : '');
    host.innerHTML =
      '<div class="y13-tb-bar">' +
        '<span class="y13-tb-brand">原型工具</span>' +
        '<label class="y13-tb-level"><span>档位</span><select class="y13-tb-select" data-act="tb.level" aria-label="档位">' + levelOptions + '</select></label>' +
        '<label class="y13-tb-switch"><input type="checkbox" data-act="tb.annotate"' + (Y13.app.annotate() ? ' checked' : '') + '><span>标注</span></label>' +
        '<span class="y13-tb-sep"></span>' +
        '<select class="y13-tb-select is-scenario" data-act="tb.scenario" aria-label="场景">' + options + '</select>' +
        '<button type="button" class="y13-tb-btn" data-act="tb.reset" title="重置场景"' + (sc ? '' : ' disabled') + '>' + Y13.ui.icon('reset') + '<span>重置</span></button>' +
        '<button type="button" class="y13-tb-btn" data-act="tb.step" title="单步"' + (sc && player.step < total ? '' : ' disabled') + '>' + Y13.ui.icon('step') + '<span>单步</span></button>' +
        '<button type="button" class="y13-tb-btn" data-act="tb.play"' + (sc ? '' : ' disabled') + '>' + Y13.ui.icon(player.playing ? 'pause' : 'play') + '<span>' + (player.playing ? '暂停' : '播放') + '</span></button>' +
        '<span class="y13-tb-count">' + (sc ? player.step + ' / ' + total : '— / —') + '</span>' +
        '<span class="y13-tb-sep"></span>' +
        '<button type="button" class="y13-tb-btn' + (simOpen ? ' is-on' : '') + '" data-act="tb.sim" aria-expanded="' + simOpen + '">' + Y13.ui.icon('plug') + '<span>模拟</span></button>' +
        '<a class="y13-tb-link" href="#/gallery">动作图鉴</a>' +
        '<select class="y13-tb-select is-theme" data-act="tb.theme" aria-label="主题">' + themeOptions + '</select>' +
      '</div>' + sim +
      '<div class="y13-tb-event">' + eventLine + '</div>' +
      '<button type="button" class="y13-tb-toggle" data-act="tb.toggle" aria-expanded="' + open + '">' +
        '<span class="y13-tb-mini">原型工具 · ' + Y13.esc(Y13.LEVEL_LABELS[level]) + (sc ? ' · ' + player.step + '/' + total : '') + '</span>' +
        Y13.ui.icon('chevron', 'y13-icon y13-tb-chevron') + '</button>';
    updateSpace();
  }

  // 工具条占用的窗口底部高度：内容区底部与提示条按它留出空白
  function updateSpace() {
    const host = Y13.app.dom.toolbar;
    const tops = [host.getBoundingClientRect().top];
    const toggle = host.querySelector('.y13-tb-toggle');
    if (toggle) tops.push(toggle.getBoundingClientRect().top);
    const space = Math.max(0, Math.ceil(window.innerHeight - Math.min.apply(null, tops)));
    document.documentElement.style.setProperty('--tb-space', space + 'px');
  }

  Y13.actions.register('tb.level', (el) => Y13.level.set(el.value));
  Y13.actions.register('tb.annotate', (el) => Y13.app.setAnnotate(el.checked));
  Y13.actions.register('tb.theme', (el) => Y13.app.setTheme(el.value));
  Y13.actions.register('tb.scenario', (el) => Y13.scenario.select(el.value || null));
  Y13.actions.register('tb.reset', () => Y13.scenario.reset());
  Y13.actions.register('tb.step', () => Y13.scenario.step());
  Y13.actions.register('tb.play', () => (player.playing ? Y13.scenario.pause() : Y13.scenario.play()));
  Y13.actions.register('tb.toggle', () => { open = !open; render(); });
  Y13.actions.register('tb.sim', () => { simOpen = !simOpen; render(); });
  Y13.actions.register('tb.connected', (el) => Y13.backend.sim.setConnected(el.checked));
  Y13.actions.register('tb.api', (el) => Y13.backend.sim.setApiVersion(Number(el.value)));
  Y13.actions.register('tb.away', (el) => {
    const entry = AWAY.find((a) => a[0] === el.value);
    if (!entry) return;
    Y13.backend.sim.setLastSeen(Y13.time.add(Y13.app.now(), -entry[2] * 3600));
  });
  Y13.actions.register('tb.notify', () => Y13.shell.simulateNotification());

  Y13.toolbar = { render, updateSpace };
  window.addEventListener('resize', () => { if (Y13.app.dom.toolbar) updateSpace(); });
})();
