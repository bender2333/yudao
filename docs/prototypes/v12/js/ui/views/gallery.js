// 动作图鉴（原型专用，#/gallery）：按角色与动作列出全部小人动画，每一项写明驱动它的事实、来源事件与所属档位；
// 另有一节「管道与画面」，列出楼层画面的状态（由 floor.js 的 Y12.pixel.FLOOR_VIEWS 提供）。
(function () {
  const Y12 = window.Y12;
  const P = Y12.pixel;
  if (!P || !P.createVignette || !P.renderSprite) throw new Error('gallery.js 需要先加载 js/pixel/*.js');
  const esc = Y12.esc;

  // 部门的衣物颜色与角色的配件（设计说明第 8.2 节）
  const ROLE_ORDER = [
    'product.agent', 'engineering.agent', 'quality.agent', 'operations.ops',
    'product.manager', 'product.architect', 'product.explorer', 'product.reviewer',
    'engineering.manager', 'engineering.architect', 'engineering.lead', 'engineering.explorer', 'engineering.reviewer',
    'quality.manager', 'quality.tester', 'quality.explorer', 'quality.reviewer'
  ];
  const ROLE_LOOK = {
    agent: '部门颜色的制服、胸前工牌、头顶一撮翘发',
    manager: '部门颜色的西装、领带、手拿记录板',
    architect: '部门颜色的毛衣、圆眼镜、手拿图纸卷',
    lead: '部门颜色的连帽衫与帽子、耳机',
    explorer: '部门颜色的马甲、宽檐帽、背包',
    reviewer: '部门颜色的制服、袖标、手拿红笔',
    tester: '白大褂、部门颜色的衬衫、手拿放大镜',
    ops: '运维颜色的连体工作服、工具腰带、耳麦'
  };
  const STATUS_LABEL = {
    idle: '部门未工作', paused: '已暂停', failed: '失败', done: '已完成', cancelled: '已取消',
    interrupted: '中断', pending_verification: '待核实', waiting_resume: '待恢复'
  };
  const LEVEL_OPTIONS = Y12.LEVELS.map((lv) => [lv, Y12.LEVEL_LABELS[lv]]);

  // 页面选择，重新渲染后保留
  const sel = { role: '', stage: 'all' };
  let live = null;

  function levelTag(level) {
    return Y12.ui.tag(Y12.LEVEL_TAGS[level]) || Y12.ui.tag('界面工作线');
  }
  function reached(level) {
    return Y12.level.atLeast(level || 'ui');
  }
  function lockNote(level) {
    return reached(level) ? '' : '<span class="y12-g-lock">档位未到：' + esc(Y12.LEVEL_LABELS[level]) + '</span>';
  }
  function select(opts) {
    return '<label class="y12-g-ctl y12-field is-inline"><span>' + esc(opts.label) + '</span><select class="y12-select" data-act="' + esc(opts.act) + '">' +
      opts.options.map(([value, label]) => '<option value="' + esc(value) + '"' + (value === opts.value ? ' selected' : '') + '>' + esc(label) + '</option>').join('') +
      '</select></label>';
  }

  // ---------------------------------------------------------------------------
  // 角色

  function spriteForAction(name) {
    return sel.role || P.VIGNETTE_SPRITES[name];
  }

  function roleCards() {
    return '<div class="y12-g-grid is-roles">' + ROLE_ORDER.map((key) => {
      const kind = key.split('.')[1];
      const level = P.SPRITE_LEVELS[key];
      const look = ROLE_LOOK[kind] || '';
      const locked = reached(level) ? '' : ' is-locked';
      return '<figure class="y12-g-card' + locked + '">' +
        '<div class="y12-g-strip"><canvas data-role="' + esc(key) + '" width="64" height="80" aria-label="' + esc(P.ROLE_NAMES[key]) + '"></canvas></div>' +
        '<figcaption><div class="y12-g-name">' + esc(P.ROLE_NAMES[key]) + levelTag(level) + '</div>' +
        '<p class="y12-g-desc">' + esc(look) + '</p>' + lockNote(level) + '</figcaption></figure>';
    }).join('') + '</div>';
  }

  // ---------------------------------------------------------------------------
  // 动作

  function actionCard(name, def) {
    const level = def.level || 'ui';
    const locked = reached(level) ? '' : ' is-locked';
    const sprite = spriteForAction(name);
    const facts = def.source === undefined
      ? '<dl class="y12-g-facts"><dt>用途</dt><dd>' + esc(def.fact) + '</dd></dl>'
      : '<dl class="y12-g-facts"><dt>事实</dt><dd>' + esc(def.fact) + '</dd>' +
        '<dt>来源</dt><dd class="y12-g-mono">' + esc(def.source) + '</dd>' +
        '<dt>小人动作</dt><dd>' + esc(def.action) + '</dd>' +
        '<dt>房间变化</dt><dd>' + esc(def.room) + '</dd></dl>';
    return '<figure class="y12-g-card' + locked + '" data-act-card="' + esc(name) + '">' +
      '<div class="y12-g-stage"><canvas data-vig="' + esc(name) + '" data-sprite="' + esc(sprite) + '" aria-label="' + esc(def.label) + '"></canvas></div>' +
      '<figcaption><div class="y12-g-name">' + esc(def.label) + levelTag(level) + '</div>' + facts + lockNote(level) + '</figcaption></figure>';
  }

  function actionCards() {
    const base = Object.keys(P.BASE_MOTIONS).map((name) => actionCard(name, P.BASE_MOTIONS[name])).join('');
    const list = Object.keys(P.ACTIONS).map((name) => actionCard(name, P.ACTIONS[name])).join('');
    return '<h3 class="y12-g-sub">基础动作</h3><div class="y12-g-grid">' + base + '</div>' +
      '<h3 class="y12-g-sub">事实驱动的动作</h3><div class="y12-g-grid">' + list + '</div>';
  }

  function statusRows() {
    return Object.keys(P.STATUS_ACTIONS).map((status) => {
      const name = P.STATUS_ACTIONS[status];
      const def = P.ACTIONS[name];
      return { status: STATUS_LABEL[status], status_id: status, action: def.label, level: def.level };
    });
  }

  // ---------------------------------------------------------------------------
  // 管道与画面（floor.js 提供 FLOOR_VIEWS）

  function floorViewsBlock() {
    const views = P.FLOOR_VIEWS;
    if (!Array.isArray(views) || !views.length) {
      return Y12.ui.note(esc('楼层画面的说明由 floor.js 提供'));
    }
    return Y12.ui.table({
      columns: [
        { key: 'fact', label: '事实' },
        { key: 'source', label: '来源', className: 'y12-g-mono' },
        { key: 'picture', label: '画面' },
        { key: 'level', label: '档位', render: (r) => levelTag(r.level) },
        { key: 'events', label: '事件', className: 'y12-g-mono', render: (r) => esc((r.events || []).join('、')) }
      ],
      rows: views
    });
  }

  // ---------------------------------------------------------------------------
  // 渲染与挂载

  function render() {
    const filters = '<div class="y12-g-ctls">' + select({
      act: 'gallery.role',
      label: '角色',
      value: sel.role,
      options: [['', '各动作默认角色']].concat(ROLE_ORDER.map((key) => [key, P.ROLE_NAMES[key]]))
    }) + select({
      act: 'gallery.stage',
      label: '档位',
      value: sel.stage,
      options: [['all', '全部档位']].concat(LEVEL_OPTIONS)
    }) + '</div>';
    return '<header class="y12-page-head"><div class="y12-page-titles"><p class="y12-eyebrow">原型专用</p><h1>动作图鉴</h1>' +
      '<p class="y12-g-intro">部门房间与楼层画面里的全部小人和动画。每个动作写明驱动它的事实、来源事件、小人动作、房间变化与所属档位。' +
      '当前档位：' + esc(Y12.LEVEL_LABELS[Y12.level.current()]) + '；档位未到的项灰色显示并写明档位。系统设置为减少动画时，每个画面停在动作的关键姿势。</p></div></header>' +
      Y12.ui.block({ title: '角色', subtitle: '衣服颜色按部门区分，角色靠配件区分（设计说明第 8.2 节）。', body: roleCards(), className: 'y12-gallery' }) +
      Y12.ui.block({ title: '动作', subtitle: '每项循环播放一次该动作；可以统一换成某个角色查看。', body: filters + '<div data-g-action-list>' + actionCards() + '</div>', className: 'y12-gallery' }) +
      Y12.ui.block({
        title: '部门状态对应的姿势', subtitle: '由部门状态或恢复观察状态张贴（engine.js 的 P.STATUS_ACTIONS）。',
        body: Y12.ui.table({
          columns: [
            { key: 'status', label: '状态' },
            { key: 'status_id', label: '状态标识', className: 'y12-g-mono' },
            { key: 'action', label: '姿势' },
            { key: 'level', label: '档位', render: (r) => levelTag(r.level) }
          ],
          rows: statusRows()
        }),
        className: 'y12-gallery'
      }) +
      Y12.ui.block({ title: '管道与画面', subtitle: '楼层画面的状态与画面（设计说明第 5.3、5.4 节）。', body: floorViewsBlock(), className: 'y12-gallery' });
  }

  function applyStageFilter(root) {
    const list = root.querySelector('[data-g-action-list]');
    if (!list) return;
    list.querySelectorAll('[data-act-card]').forEach((card) => {
      const name = card.dataset.actCard;
      const level = (P.ACTIONS[name] || P.BASE_MOTIONS[name] || {}).level || 'ui';
      const show = sel.stage === 'all' || level === sel.stage;
      card.hidden = !show;
    });
  }

  function mountVignettes(root) {
    const io = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        const inst = live.vignettes.get(entry.target);
        if (inst) inst.pause(!entry.isIntersecting);
      });
    }, { rootMargin: '80px' });
    root.querySelectorAll('canvas[data-role]').forEach((canvas) => {
      P.renderSprite(canvas, canvas.dataset.role, 'idle', 0);
    });
    root.querySelectorAll('canvas[data-vig]').forEach((canvas) => {
      const inst = P.createVignette(canvas, { action: canvas.dataset.vig, sprite: canvas.dataset.sprite });
      live.vignettes.set(canvas, inst);
      io.observe(canvas);
    });
    live.io = io;
  }

  function destroyVignettes() {
    if (live.io) live.io.disconnect();
    live.vignettes.forEach((inst) => inst.destroy());
    live.vignettes = new Map();
    live.io = null;
  }

  function mount(ctx, root) {
    live = { vignettes: new Map(), io: null, root };
    mountVignettes(root);
  }

  function unmount() {
    if (live) destroyVignettes();
    live = null;
  }

  Y12.views.register('gallery', {
    title: () => '动作图鉴',
    render,
    mount,
    unmount
  });

  Y12.actions.register('gallery.role', (el) => {
    sel.role = el.value;
    if (!live) return;
    destroyVignettes();
    live.root.querySelector('[data-g-action-list]').innerHTML = actionCards();
    mountVignettes(live.root);
    applyStageFilter(live.root);
  });

  Y12.actions.register('gallery.stage', (el) => {
    sel.stage = el.value;
    applyStageFilter(Y12.app.dom.content);
  });
})();
