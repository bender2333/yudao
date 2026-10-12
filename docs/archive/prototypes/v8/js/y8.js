// Yudao 界面原型 v8：命名空间、档位、事件总线、数据路径与补丁、克隆、时间与数字格式
(function () {
  'use strict';

  const Y8 = {};
  window.Y8 = Y8;

  // ---------------------------------------------------------------------------
  // 档位：表示控制主机上已经部署了哪些工作包（BUILD.md 第 4 节）

  Y8.LEVELS = ['ui', '3.1', '3.2C', '3.4A', '3.8', '3.2B', '3.2D', 'S4', 'S5'];
  Y8.LEVEL_LABELS = {
    ui: '界面工作线', '3.1': '3.1 可靠恢复', '3.2C': '3.2C 执行环境服务', '3.4A': '3.4A 不同项目并行',
    '3.8': '3.8 接入已有项目', '3.2B': '3.2B 网络与 MCP', '3.2D': '3.2D 浏览器与 computer use',
    S4: 'Stage 4', S5: 'Stage 5'
  };
  // 界面上的档位标签：界面工作线不显示标签
  Y8.LEVEL_TAGS = { ui: null, '3.1': '3.1', '3.2C': '3.2C', '3.4A': '3.4A', '3.8': '3.8', '3.2B': '3.2B', '3.2D': '3.2D', S4: 'Stage 4', S5: 'Stage 5' };

  const session = window.sessionStorage;
  const local = window.localStorage;

  Y8.store = {
    get(key, fallback, persistent) {
      const text = (persistent ? local : session).getItem('y8.' + key);
      return text === null ? fallback : JSON.parse(text);
    },
    set(key, value, persistent) {
      (persistent ? local : session).setItem('y8.' + key, JSON.stringify(value));
    }
  };

  function isLevel(value) {
    return typeof value === 'string' && Y8.LEVELS.includes(value);
  }
  Y8.isLevel = isLevel;

  function levelIndex(level) {
    if (!isLevel(level)) throw new Error('未知档位：' + level);
    return Y8.LEVELS.indexOf(level);
  }

  let currentLevel = Y8.store.get('level', 'ui');
  if (!isLevel(currentLevel)) currentLevel = 'ui';

  Y8.level = {
    current: () => currentLevel,
    atLeast(level) {
      if (level === undefined || level === null || level === '') return true;
      return levelIndex(currentLevel) >= levelIndex(level);
    },
    // 对象的档位范围：level 已到且 until 未到
    reached(obj) {
      if (!obj || typeof obj !== 'object') return true;
      if (obj.level !== undefined && isLevel(obj.level) && !Y8.level.atLeast(obj.level)) return false;
      if (obj.until !== undefined && isLevel(obj.until) && Y8.level.atLeast(obj.until)) return false;
      return true;
    },
    compare(a, b) {
      return levelIndex(a) - levelIndex(b);
    },
    set(level) {
      levelIndex(level);
      if (level === currentLevel) return;
      currentLevel = level;
      Y8.store.set('level', level);
      Y8.bus.emit('level-changed', level);
    }
  };

  // ---------------------------------------------------------------------------
  // 事件总线：界面层内部的通知（档位、标注、主题、场景）；领域事件走 Y8.api.subscribe

  const handlers = {};
  Y8.bus = {
    on(type, fn) { (handlers[type] = handlers[type] || []).push(fn); },
    off(type, fn) { handlers[type] = (handlers[type] || []).filter((item) => item !== fn); },
    emit(type, payload) { (handlers[type] || []).slice().forEach((fn) => fn(payload)); }
  };

  // ---------------------------------------------------------------------------
  // 克隆与标识

  Y8.clone = (value) => (value === undefined ? undefined : structuredClone(value));

  let idCounter = 0;
  Y8.uid = function uid(prefix) {
    idCounter += 1;
    return prefix + '-' + Date.now().toString(36).slice(-4) + idCounter;
  };

  Y8.isPlainObject = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);

  // ---------------------------------------------------------------------------
  // 数据路径：点号分隔；数组中的对象用 key[id=值] 找；数组下标用数字

  function parseSegment(segment, path) {
    const match = /^([^[\]]+)(?:\[(\w+)=([^\]]+)\])?$/.exec(segment);
    if (!match) throw new Error('路径格式无效：' + path);
    return { key: match[1], matchKey: match[2] || null, matchValue: match[3] || null };
  }

  function stepInto(container, segment, path) {
    const { key, matchKey, matchValue } = parseSegment(segment, path);
    if (container === null || typeof container !== 'object' || !(key in container)) {
      throw new Error('路径中找不到「' + key + '」：' + path);
    }
    let next = container[key];
    if (matchKey) {
      if (!Array.isArray(next)) throw new Error('「' + key + '」不是数组，不能按 ' + matchKey + ' 查找：' + path);
      next = next.find((item) => item && String(item[matchKey]) === matchValue);
      if (next === undefined) throw new Error('数组「' + key + '」中找不到 ' + matchKey + '=' + matchValue + '：' + path);
    }
    return next;
  }

  function splitPath(path) {
    if (typeof path !== 'string' || !path) throw new Error('路径必须是非空字符串');
    return path.split('.');
  }

  Y8.path = {
    get(root, path) {
      return splitPath(path).reduce((container, segment) => stepInto(container, segment, path), root);
    },
    // 返回路径上最后一个对象（被修改的对象）与最后一段
    parent(root, path) {
      const segments = splitPath(path);
      const last = segments.pop();
      const parent = segments.reduce((container, segment) => stepInto(container, segment, path), root);
      return { parent, last: parseSegment(last, path) };
    },
    set(root, path, value) {
      const { parent, last } = Y8.path.parent(root, path);
      if (parent === null || typeof parent !== 'object' || !(last.key in parent)) {
        throw new Error('路径中找不到「' + last.key + '」：' + path);
      }
      if (last.matchKey) {
        const list = parent[last.key];
        if (!Array.isArray(list)) throw new Error('「' + last.key + '」不是数组：' + path);
        const index = list.findIndex((item) => item && String(item[last.matchKey]) === last.matchValue);
        if (index < 0) throw new Error('数组「' + last.key + '」中找不到 ' + last.matchKey + '=' + last.matchValue + '：' + path);
        list[index] = value;
        return list[index];
      }
      if (Array.isArray(parent) && Number(last.key) >= parent.length) throw new Error('数组下标越界：' + path);
      parent[last.key] = value;
      return parent;
    },
    push(root, path, item) {
      const list = Y8.path.get(root, path);
      if (!Array.isArray(list)) throw new Error('「' + path + '」不是数组，不能追加');
      list.push(item);
      return list;
    },
    remove(root, path, matchKey, matchValue) {
      const list = Y8.path.get(root, path);
      if (!Array.isArray(list)) throw new Error('「' + path + '」不是数组，不能删除');
      const index = list.findIndex((item) => item && String(item[matchKey]) === String(matchValue));
      if (index < 0) throw new Error('数组「' + path + '」中找不到 ' + matchKey + '=' + matchValue);
      list.splice(index, 1);
      return list;
    }
  };

  // 补丁：{ path, value } 修改字段；{ path, push } 追加；{ path, remove: { key, value } } 删除。
  // 返回被修改的对象（用于版本号加一）
  Y8.applyPatch = function applyPatch(root, patch) {
    if (!patch || typeof patch.path !== 'string') throw new Error('补丁缺少 path');
    if ('push' in patch) return Y8.path.push(root, patch.path, Y8.clone(patch.push));
    if ('put' in patch) {
      // 向对象增加一个键：{ path, put: { key, value } }；键已存在时抛出错误
      const target = Y8.path.get(root, patch.path);
      if (!Y8.isPlainObject(target)) throw new Error('「' + patch.path + '」不是对象，不能增加键');
      if (patch.put.key in target) throw new Error('「' + patch.path + '」中已有键：' + patch.put.key);
      target[patch.put.key] = Y8.clone(patch.put.value);
      return target;
    }
    if ('remove' in patch) return Y8.path.remove(root, patch.path, patch.remove.key, patch.remove.value);
    if (!('value' in patch)) throw new Error('补丁缺少 value、push 或 remove：' + patch.path);
    return Y8.path.set(root, patch.path, Y8.clone(patch.value));
  };

  // snake_case 与 camelCase：data-* 属性读回的键名转为命令参数的键名
  Y8.snake = (key) => key.replace(/[A-Z]/g, (ch) => '_' + ch.toLowerCase());
  Y8.kebab = (key) => key.replace(/_/g, '-').replace(/[A-Z]/g, (ch) => '-' + ch.toLowerCase());

  // ---------------------------------------------------------------------------
  // 时间与数字

  const timeFormat = new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
  const dateFormat = new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', month: 'numeric', day: 'numeric' });
  const dayKey = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' });
  const numberFormat = new Intl.NumberFormat('zh-CN');

  Y8.time = {
    ms(iso) {
      const t = new Date(iso).getTime();
      if (Number.isNaN(t)) throw new Error('时间格式无效：' + iso);
      return t;
    },
    // now 为参照的当前时间；同一天只显示时分
    format(iso, now) {
      if (!iso) return '—';
      const date = new Date(Y8.time.ms(iso));
      const today = now && dayKey.format(new Date(Y8.time.ms(now))) === dayKey.format(date);
      return today ? timeFormat.format(date) : dateFormat.format(date) + ' ' + timeFormat.format(date);
    },
    clock(iso) {
      return timeFormat.format(new Date(Y8.time.ms(iso)));
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
      return Math.round((Y8.time.ms(b) - Y8.time.ms(a)) / 1000);
    },
    add(iso, sec) {
      const d = new Date(Y8.time.ms(iso) + sec * 1000);
      // 输出带 +08:00 的 ISO 字符串
      const shifted = new Date(d.getTime() + 8 * 3600 * 1000).toISOString().slice(0, 19);
      return shifted + '+08:00';
    }
  };

  Y8.num = (value) => (value === null || value === undefined ? '未上报' : numberFormat.format(value));
})();
