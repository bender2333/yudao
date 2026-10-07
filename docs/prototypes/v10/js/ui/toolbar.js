// 原型工具条：档位切换、标注、场景播放器、模拟（托盘与通知、断开连接、接口版本、离开的时长）、动作图鉴、主题。
// 原型专用，可以直接读写示例后端（BUILD.md 第 2 节的例外）
(function () {
  'use strict';
  const Y10 = window.Y10;

  const player = { id: null, step: 0, playing: false, last: null, timer: null };
  let open = window.innerWidth > 760;
  let simOpen = false;

  function scenarios() { return Y10.backend.scenarios(); }

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

  Y10.scenario = {
    current,
    state: () => player,
    select(id) {
      stop();
      Y10.backend.reset();
      Object.assign(player, { id: id || null, step: 0, last: null });
      const sc = current();
      if (sc) {
        if (sc.level && !Y10.level.atLeast(sc.level)) Y10.level.set(sc.level);
        else Y10.backend.refold();
        Y10.backend.setup(sc.setup, '场景「' + sc.name + '」的准备');
        Y10.bus.emit('scenario-changed', player);
        if (sc.go) {
          if (location.hash === sc.go) Y10.app.renderAll(false);
          else Y10.go(sc.go);
        } else {
          Y10.app.renderAll(true);
        }
      } else {
        Y10.backend.refold();
        Y10.bus.emit('scenario-changed', player);
        Y10.app.renderAll(true);
      }
    },
    reset() { Y10.scenario.select(player.id); },
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
      if (st.go && location.hash !== st.go) Y10.go(st.go);
      if (st.event) {
        const spec = Object.assign({ project_id: null, work_item_id: null, run_id: null, department: null, role: null, payload: {} }, Y10.clone(st.event));
        spec.patch = Y10.clone(st.patch || []);
        player.last = Y10.backend.emit(spec);
      } else if (st.act) {
        player.last = { type: st.act, label: st.label || st.act };
        Y10.actions.run(st.act, null, null);
      } else {
        player.last = { type: '跳转', label: st.label };
      }
      render();
      return true;
    },
    play() {
      const sc = current();
      if (!sc) throw new Error('没有选择场景');
      if (player.step >= sc.steps.length) Y10.scenario.select(sc.id);
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
          Y10.scenario.step();
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
    const host = Y10.app.dom.toolbar;
    if (!host) return;
    const sc = current();
    const total = sc ? sc.steps.length : 0;
    const level = Y10.level.current();
    const levelOptions = Y10.LEVELS.map((lv) => '<option value="' + lv + '"' + (lv === level ? ' selected' : '') + '>' + Y10.esc(Y10.LEVEL_LABELS[lv]) + '</option>').join('');
    const options = '<option value="">选择场景…</option>' + scenarios().map((item) =>
      '<option value="' + Y10.esc(item.id) + '"' + (item.id === player.id ? ' selected' : '') + '>' + item.no + '. ' + Y10.esc(item.name) + ' · ' + Y10.esc(Y10.LEVEL_LABELS[item.level || 'ui']) + '</option>'
    ).join('');
    const theme = Y10.app.theme();
    const themeOptions = [['system', '跟随系统'], ['light', '浅色'], ['dark', '深色']].map((pair) =>
      '<option value="' + pair[0] + '"' + (theme === pair[0] ? ' selected' : '') + '>' + pair[1] + '</option>').join('');
    const ev = player.last;
    const eventLine = sc
      ? (ev ? '<code>' + Y10.esc(ev.type) + '</code><span>' + Y10.esc(ev.label || '') + '</span>'
        : '<span class="y10-tb-hint">场景「' + Y10.esc(sc.name) + '」共 ' + total + ' 步，点击「单步」或「播放」开始</span>')
      : '<span class="y10-tb-hint">选择场景后逐步播放事件，每一步显示驱动画面的事件</span>';
    const connected = Y10.backend.sim.connected();
    const apiVersion = Y10.backend.sim.apiVersion();
    const sim = simOpen
      ? '<div class="y10-tb-sim">' +
          '<label><input type="checkbox" data-act="tb.connected"' + (connected ? ' checked' : '') + '><span>与控制主机连接</span></label>' +
          '<label><span>控制主机的接口版本</span><select class="y10-tb-select" data-act="tb.api">' +
            [1, 2].map((n) => '<option value="' + n + '"' + (n === apiVersion ? ' selected' : '') + '>' + n + (n === Y10.CLIENT_API_VERSION ? '（与客户端相同）' : '') + '</option>').join('') + '</select></label>' +
          '<label><span>离开的时长</span><select class="y10-tb-select" data-act="tb.away"><option value="">保持</option>' +
            AWAY.map((a) => '<option value="' + a[0] + '">' + a[1] + '</option>').join('') + '</select></label>' +
          '<button type="button" class="y10-tb-btn" data-act="tb.notify">' + Y10.ui.icon('bell') + '<span>模拟一条通知</span></button>' +
        '</div>'
      : '';
    host.className = 'y10-toolbar' + (open ? ' is-open' : '');
    host.innerHTML =
      '<div class="y10-tb-bar">' +
        '<span class="y10-tb-brand">原型工具</span>' +
        '<label class="y10-tb-level"><span>档位</span><select class="y10-tb-select" data-act="tb.level" aria-label="档位">' + levelOptions + '</select></label>' +
        '<label class="y10-tb-switch"><input type="checkbox" data-act="tb.annotate"' + (Y10.app.annotate() ? ' checked' : '') + '><span>标注</span></label>' +
        '<span class="y10-tb-sep"></span>' +
        '<select class="y10-tb-select is-scenario" data-act="tb.scenario" aria-label="场景">' + options + '</select>' +
        '<button type="button" class="y10-tb-btn" data-act="tb.reset" title="重置场景"' + (sc ? '' : ' disabled') + '>' + Y10.ui.icon('reset') + '<span>重置</span></button>' +
        '<button type="button" class="y10-tb-btn" data-act="tb.step" title="单步"' + (sc && player.step < total ? '' : ' disabled') + '>' + Y10.ui.icon('step') + '<span>单步</span></button>' +
        '<button type="button" class="y10-tb-btn" data-act="tb.play"' + (sc ? '' : ' disabled') + '>' + Y10.ui.icon(player.playing ? 'pause' : 'play') + '<span>' + (player.playing ? '暂停' : '播放') + '</span></button>' +
        '<span class="y10-tb-count">' + (sc ? player.step + ' / ' + total : '— / —') + '</span>' +
        '<span class="y10-tb-sep"></span>' +
        '<button type="button" class="y10-tb-btn' + (simOpen ? ' is-on' : '') + '" data-act="tb.sim" aria-expanded="' + simOpen + '">' + Y10.ui.icon('plug') + '<span>模拟</span></button>' +
        '<a class="y10-tb-link" href="#/gallery">动作图鉴</a>' +
        '<select class="y10-tb-select is-theme" data-act="tb.theme" aria-label="主题">' + themeOptions + '</select>' +
      '</div>' + sim +
      '<div class="y10-tb-event">' + eventLine + '</div>' +
      '<button type="button" class="y10-tb-toggle" data-act="tb.toggle" aria-expanded="' + open + '">' +
        '<span class="y10-tb-mini">原型工具 · ' + Y10.esc(Y10.LEVEL_LABELS[level]) + (sc ? ' · ' + player.step + '/' + total : '') + '</span>' +
        Y10.ui.icon('chevron', 'y10-icon y10-tb-chevron') + '</button>';
    updateSpace();
  }

  // 工具条占用的窗口底部高度：内容区底部与提示条按它留出空白
  function updateSpace() {
    const host = Y10.app.dom.toolbar;
    const tops = [host.getBoundingClientRect().top];
    const toggle = host.querySelector('.y10-tb-toggle');
    if (toggle) tops.push(toggle.getBoundingClientRect().top);
    const space = Math.max(0, Math.ceil(window.innerHeight - Math.min.apply(null, tops)));
    document.documentElement.style.setProperty('--tb-space', space + 'px');
  }

  Y10.actions.register('tb.level', (el) => Y10.level.set(el.value));
  Y10.actions.register('tb.annotate', (el) => Y10.app.setAnnotate(el.checked));
  Y10.actions.register('tb.theme', (el) => Y10.app.setTheme(el.value));
  Y10.actions.register('tb.scenario', (el) => Y10.scenario.select(el.value || null));
  Y10.actions.register('tb.reset', () => Y10.scenario.reset());
  Y10.actions.register('tb.step', () => Y10.scenario.step());
  Y10.actions.register('tb.play', () => (player.playing ? Y10.scenario.pause() : Y10.scenario.play()));
  Y10.actions.register('tb.toggle', () => { open = !open; render(); });
  Y10.actions.register('tb.sim', () => { simOpen = !simOpen; render(); });
  Y10.actions.register('tb.connected', (el) => Y10.backend.sim.setConnected(el.checked));
  Y10.actions.register('tb.api', (el) => Y10.backend.sim.setApiVersion(Number(el.value)));
  Y10.actions.register('tb.away', (el) => {
    const entry = AWAY.find((a) => a[0] === el.value);
    if (!entry) return;
    Y10.backend.sim.setLastSeen(Y10.time.add(Y10.app.now(), -entry[2] * 3600));
  });
  Y10.actions.register('tb.notify', () => Y10.shell.simulateNotification());

  Y10.toolbar = { render, updateSpace };
  window.addEventListener('resize', () => { if (Y10.app.dom.toolbar) updateSpace(); });
})();
