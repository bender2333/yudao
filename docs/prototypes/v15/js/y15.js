// Yudao 界面原型 v15：命名空间、档位、事件总线、数据路径与补丁、克隆、时间与数字格式
(function () {
  'use strict';

  const Y15 = {};
  window.Y15 = Y15;

  const session = window.sessionStorage;
  const local = window.localStorage;
  Y15.store = {
    get(key, fallback, persistent) {
      try { const text = (persistent ? local : session).getItem('y15.' + key); return text === null ? fallback : JSON.parse(text); } catch (e) { return fallback; }
    },
    set(key, value, persistent) {
      try { (persistent ? local : session).setItem('y15.' + key, JSON.stringify(value)); } catch (e) { /* 存储不可用时不记住 */ }
    }
  };

  // ---------------------------------------------------------------------------
  // 事件总线：界面层内部的通知（档位、标注、主题、场景）；领域事件走 Y15.api.subscribe

  const handlers = {};
  Y15.bus = {
    on(type, fn) { (handlers[type] = handlers[type] || []).push(fn); },
    off(type, fn) { handlers[type] = (handlers[type] || []).filter((item) => item !== fn); },
    emit(type, payload) { (handlers[type] || []).slice().forEach((fn) => fn(payload)); }
  };

  // ---------------------------------------------------------------------------
  // 克隆与标识

  Y15.clone = (value) => (value === undefined ? undefined : structuredClone(value));

  let idCounter = 0;
  Y15.uid = function uid(prefix) {
    idCounter += 1;
    return prefix + '-' + Date.now().toString(36).slice(-4) + idCounter;
  };

  Y15.isPlainObject = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);

  // snake_case 与 camelCase：data-* 属性读回的键名转为命令参数的键名
  Y15.snake = (key) => key.replace(/[A-Z]/g, (ch) => '_' + ch.toLowerCase());
  Y15.kebab = (key) => key.replace(/_/g, '-').replace(/[A-Z]/g, (ch) => '-' + ch.toLowerCase());

  // ---------------------------------------------------------------------------
  // 时间与数字

  const timeFormat = new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
  const dateFormat = new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', month: 'numeric', day: 'numeric' });
  const dayKey = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' });
  const numberFormat = new Intl.NumberFormat('zh-CN');

  Y15.time = {
    ms(iso) {
      const t = new Date(iso).getTime();
      if (Number.isNaN(t)) throw new Error('时间格式无效：' + iso);
      return t;
    },
    // now 为参照的当前时间；同一天只显示时分
    format(iso, now) {
      if (!iso) return '—';
      const date = new Date(Y15.time.ms(iso));
      const today = now && dayKey.format(new Date(Y15.time.ms(now))) === dayKey.format(date);
      return today ? timeFormat.format(date) : dateFormat.format(date) + ' ' + timeFormat.format(date);
    },
    clock(iso) {
      return timeFormat.format(new Date(Y15.time.ms(iso)));
    },
    duration(sec) {
      if (sec === null || sec === undefined) return '—';
      const total = Math.round(sec);
      if (total < 60) return total + ' 秒';
      const days = Math.floor(total / 86400);
      const hours = Math.floor((total % 86400) / 3600);
      const minutes = Math.floor((total % 3600) / 60);
      const seconds = total % 60;
      if (days) return days + ' 天' + (hours ? ' ' + hours + ' 小时' : '');
      if (hours) return hours + ' 小时' + (minutes ? ' ' + minutes + ' 分' : '');
      return minutes + ' 分' + (seconds ? ' ' + seconds + ' 秒' : '');
    },
    between(a, b) {
      return Math.round((Y15.time.ms(b) - Y15.time.ms(a)) / 1000);
    },
    add(iso, sec) {
      const d = new Date(Y15.time.ms(iso) + sec * 1000);
      // 输出带 +08:00 的 ISO 字符串
      const shifted = new Date(d.getTime() + 8 * 3600 * 1000).toISOString().slice(0, 19);
      return shifted + '+08:00';
    }
  };

  Y15.num = (value) => (value === null || value === undefined ? '未上报' : numberFormat.format(value));

  // 检验覆盖的写法（CONTEXT.md「开环」：靠模型阅读判断的条件包含在开环之内）：「覆盖 7/8 · 开环 1（其中模型阅读 1）」，开环为 0 时只写覆盖比例
  Y15.coverageText = (c) => '覆盖 ' + c.covered + '/' + c.total +
    (c.open_count ? ' · 开环 ' + c.open_count + (c.model_read ? '（其中模型阅读 ' + c.model_read + '）' : '') : '');
})();
