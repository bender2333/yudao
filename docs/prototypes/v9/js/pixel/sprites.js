// 像素画面的点阵定义：色板、部门与角色外形、小人部件、手持物件、图标、物件与 3×5 数字字体。
// 点阵用字符串书写，每个字符对应色板中的一种颜色，「.」表示透明。
(function () {
  const Y9 = window.Y9;
  const P = (Y9.pixel = Y9.pixel || {});

  // ---------------------------------------------------------------------------
  // 画面色板（浅色与深色主题下相同）

  const PAL = {
    ink: '#1e1a2e', ink2: '#352e4d', inkSoft: '#4a4262',
    white: '#fbf8f1', white2: '#dedad0', white3: '#bdb8ad',
    grey1: '#cdd2da', grey2: '#9aa2b0', grey3: '#6b7382', grey4: '#474d5a', grey5: '#2f333d', grey6: '#22252d',
    paper: '#f6eed8', paper2: '#e3d5b3', paper3: '#bfac88', pline: '#8f9cc8',
    wood1: '#dca46a', wood2: '#b27a44', wood3: '#83552d', wood4: '#5a381b',
    metal1: '#dde4ec', metal2: '#aab6c4', metal3: '#7b8796', metal4: '#525a68',
    red1: '#ff9a90', red2: '#e5484d', red3: '#a82b3a', red4: '#6e1c2a',
    green1: '#a4f5b6', green2: '#3fbf66', green3: '#23804a', green4: '#15502f',
    yellow1: '#fff2b0', yellow2: '#f7cb46', yellow3: '#c99324', yellow4: '#8a5f14',
    blue1: '#b0d6ff', blue2: '#4f94e8', blue3: '#2e60ad', blue4: '#1d3d73',
    orange1: '#ffc990', orange2: '#f08a3c',
    pink1: '#ffc2dc', pink2: '#f27ec2',
    glass: '#d8edff', glass2: '#9fc9ef',
    screen0: '#0b1d14', screen1: '#18402a', screen2: '#35a05d', screen3: '#7ef5a0', screen4: '#d4ffe0',
    amber0: '#2a1a08', amber1: '#ffb347',
    card1: '#e8bd7f', card2: '#cc9657', card3: '#9c6a3a', card4: '#6f4724',
    tea: '#8c5a2c', leaf1: '#8fd46a', leaf2: '#4fa24a', leaf3: '#2f6d36',
    pot1: '#d9774a', pot2: '#a8522f',
    eye: '#2a2238', mouth: '#9a3f45', blush: '#f5a093',
    beige1: '#efe7d2', beige2: '#d4c8a8', beige3: '#a89a78', beige4: '#7a6d52',
    shadow: 'rgba(20, 16, 36, 0.28)'
  };
  P.PAL = PAL;

  // 部门的衣服与房间颜色
  P.DEPTS = {
    product: {
      name: '产品', main: '#2fa58c', shade: '#1e7563', light: '#78dcc3',
      wall: '#f0e2c4', wall2: '#e2cfa8', wall3: '#cdb68a', trim: '#8a6a44',
      floor: '#c8935c', floor2: '#b07d4a', floor3: '#8e6035', rug: '#d9786a', rug2: '#b85a4e'
    },
    engineering: {
      name: '工程', main: '#3c7bd0', shade: '#285597', light: '#82b1f2',
      wall: '#c9d6e6', wall2: '#b4c4d9', wall3: '#9aabc3', trim: '#56657d',
      floor: '#8f99a8', floor2: '#7d8797', floor3: '#646d7c', rug: '#5a82b8', rug2: '#436596'
    },
    quality: {
      name: '质检', main: '#8f5fcf', shade: '#6541a0', light: '#c3a0f2',
      wall: '#ebe8f3', wall2: '#dcd6ea', wall3: '#c4bcd9', trim: '#7a6c99',
      floor: '#e9e6ef', floor2: '#c9c2d9', floor3: '#aaa0c0', rug: '#a98bd8', rug2: '#8a6cbc'
    },
    operations: {
      name: '运维', main: '#e07b34', shade: '#a9561f', light: '#f7b27a',
      wall: '#3e4656', wall2: '#353c4a', wall3: '#2b313d', trim: '#1f232c',
      floor: '#343a47', floor2: '#2a2f3a', floor3: '#4a5162', rug: '#50596b', rug2: '#3f4757'
    },

  };

  // 事项颜色（color_index 0-5）：门口小旗、包裹与看板卡片使用同一种颜色
  P.ITEM_COLORS = ['#e8505b', '#f7c948', '#3fc1e8', '#f27ec2', '#8fd14f', '#b98558'];
  P.ITEM_SHADES = ['#a8303c', '#c29424', '#2585aa', '#b8508e', '#5f9a2d', '#85583a'];

  P.SKINS = [
    ['#f8d3ad', '#e1ab82'],
    ['#eab68c', '#ca8e64'],
    ['#b97c54', '#955b3c']
  ];
  P.HAIRS = {
    black: ['#2b2536', '#4d4565'],
    brown: ['#6e4631', '#94644a'],
    chestnut: ['#5a3a2a', '#80573f'],
    auburn: ['#a24a2c', '#cc6c45'],
    dbrown: ['#3d2a22', '#5e4336'],
    grey: ['#a8acb4', '#d5d8de']
  };

  // 角色外形：发型、发色、肤色、服装、配件、待机时手里的物件
  P.ROLE_KINDS = {
    agent: { label: '部门 Agent', hair: 'tuft', hairColor: 'brown', skin: 0, outfit: 'uniform', acc: [], idleItem: null },
    manager: { label: '经理', hair: 'sidepart', hairColor: 'black', skin: 1, outfit: 'suit', acc: [], idleItem: 'clipboard' },
    architect: { label: '架构师', hair: 'messy', hairColor: 'chestnut', skin: 0, outfit: 'sweater', acc: ['glasses'], idleItem: 'blueprint' },
    lead: { label: '主程', hair: 'spiky', hairColor: 'black', skin: 2, outfit: 'hoodie', acc: ['headphones'], hood: true, idleItem: null },
    explorer: { label: '探索者', hair: 'sidepart', hairColor: 'auburn', skin: 1, outfit: 'vest', acc: ['hat'], pack: true, idleItem: null },
    reviewer: { label: '审查者', hair: 'bob', hairColor: 'black', skin: 1, outfit: 'uniform', acc: [], armband: true, idleItem: 'pen_red' },
    tester: { label: '测试工程师', hair: 'bob', hairColor: 'black', skin: 0, outfit: 'labcoat', acc: [], idleItem: 'magnifier' },
    ops: { label: '运维', hair: 'buzz', hairColor: 'dbrown', skin: 2, outfit: 'jumpsuit', acc: ['headset'], idleItem: null }
  };


  // 角色的中文名称与档位（设计说明第 8.2 节）
  P.ROLE_NAMES = {
    'product.agent': '产品部门 Agent', 'engineering.agent': '工程部门 Agent', 'quality.agent': '质检部门 Agent',
    'product.manager': '产品部门经理', 'product.architect': '产品架构师', 'product.explorer': '产品探索者', 'product.reviewer': '产品审查者',
    'engineering.manager': '工程经理', 'engineering.architect': '工程架构师', 'engineering.lead': '主程', 'engineering.explorer': '工程探索者', 'engineering.reviewer': '工程审查者',
    'quality.manager': '质检经理', 'quality.tester': '测试工程师', 'quality.explorer': '质检探索者', 'quality.reviewer': '质检审查者',
    'operations.ops': '运维部门 Agent'
  };

  P.SPRITE_LEVELS = {
    'product.agent': 'ui', 'engineering.agent': 'ui', 'quality.agent': 'ui',
    'operations.ops': 'S4',
    'product.manager': 'S5', 'product.architect': 'S5', 'product.explorer': 'S5', 'product.reviewer': 'S5',
    'engineering.manager': 'S5', 'engineering.architect': 'S5', 'engineering.lead': 'S5', 'engineering.explorer': 'S5', 'engineering.reviewer': 'S5',
    'quality.manager': 'S5', 'quality.tester': 'S5', 'quality.explorer': 'S5', 'quality.reviewer': 'S5'
  };


  // 每个角色的配色：字符到颜色；d 为部门颜色，item 为事项颜色（背包）
  P.rolePalette = function rolePalette(dept, kind, itemIndex) {
    const d = P.DEPTS[dept];
    const r = P.ROLE_KINDS[kind];
    if (!d) throw new Error('未知部门：' + dept);
    if (!r) throw new Error('未知角色种类：' + kind);
    const skin = P.SKINS[r.skin];
    const hair = P.HAIRS[r.hairColor];
    const pack = itemIndex === null || itemIndex === undefined
      ? ['#9a6a3f', '#6f4a2a']
      : [P.ITEM_COLORS[itemIndex], P.ITEM_SHADES[itemIndex]];
    const map = {
      S: skin[0], s: skin[1], H: hair[0], h: hair[1],
      C: d.main, c: d.shade, L: d.light,
      T: PAL.white, t: PAL.white2, K: d.light, k: d.shade,
      P: '#3b4163', p: '#2b3050', F: '#3a2e2a', f: '#5a4a44',
      W: PAL.white, w: PAL.white2,
      X: pack[0], x: pack[1],
      A: PAL.grey4, a: PAL.grey5,
      G: PAL.glass, g: '#3a3350',
      E: PAL.eye, M: PAL.mouth, B: PAL.blush,
      m: PAL.metal3, o: PAL.ink
    };
    const sleeve = { color: 'C', shade: 'c' };
    switch (kind) {
      case 'manager':
        Object.assign(map, { K: '#c8384a', k: '#8e2233', P: '#2f3242', p: '#22242f' });
        break;
      case 'architect':
        Object.assign(map, { P: '#6b5040', p: '#4e3a2e' });
        break;
      case 'lead':
        Object.assign(map, { P: '#35558f', p: '#27406d', A: '#e5484d', a: '#2f333d', F: '#e8e4dc', f: '#b7b2a8' });
        break;
      case 'explorer':
        Object.assign(map, { T: '#e2cf9a', t: '#c1ab72', A: '#cdb27a', a: '#9e8452', K: d.main, P: '#6d6a3c', p: '#524f2b', F: '#6b4526' });
        sleeve.color = 'T'; sleeve.shade = 't';
        break;
      case 'reviewer':
        Object.assign(map, { K: PAL.red2, k: PAL.red3 });
        break;
      case 'tester':
        Object.assign(map, { W: '#f7f8fc', w: '#c6cadb', T: d.main, t: d.shade, K: d.main, P: '#555b6e', p: '#3f4453' });
        sleeve.color = 'W'; sleeve.shade = 'w';
        break;
      default:
        Object.assign(map, { K: PAL.white, k: d.main });
    }
    return { map, sleeve };
  };

  // ---------------------------------------------------------------------------
  // 小人部件
  // 帧缓冲 32×40，脚底在第 37 行；头部框 12×10 位于 (10,16)；发型与头部配件 14×12，相对头部框偏移 (-1,-2)

  const CHAR = {};
  P.CHAR = CHAR;

  CHAR.head = {
    f: [
      '..SSSSSSSS..',
      '.SSSSSSSSSS.',
      'SSSSSSSSSSSS',
      'SSSSSSSSSSSS',
      'SSSSSSSSSSSS',
      'SSSSSSSSSSSS',
      'SSSSSSSSSSSS',
      'SSSSSSSSSSSS',
      '.SSSSSSSSSS.',
      '..ssssssss..'
    ],
    s: [
      '..SSSSSSSS..',
      '.SSSSSSSSSS.',
      'SSSSSSSSSSS.',
      'SSSSSSSSSSSS',
      'SSSSSSSSSSSS',
      'SSSSsSSSSSSS',
      'SSSSsSSSSSSS',
      'SSSSSSSSSSS.',
      '.SSSSSSSSSS.',
      '..ssssssss..'
    ]
  };
  CHAR.head.b = CHAR.head.f;

  // 表情：头部框内的像素坐标；E 眼睛，M 嘴，B 腮红，s 眼皮
  CHAR.faces = {
    f: {
      normal: { E: [[3, 5], [3, 6], [8, 5], [8, 6]], M: [[5, 8], [6, 8]], B: [[2, 7], [9, 7]] },
      blink: { E: [[2, 6], [3, 6], [8, 6], [9, 6]], M: [[5, 8], [6, 8]], B: [[2, 7], [9, 7]] },
      happy: { E: [[2, 6], [3, 5], [4, 6], [7, 6], [8, 5], [9, 6]], M: [[4, 8], [5, 9], [6, 9], [7, 8]], B: [[1, 7], [10, 7]] },
      sad: { E: [[3, 6], [8, 6]], s: [[2, 5], [9, 5]], M: [[4, 9], [5, 8], [6, 8], [7, 9]] },
      surprised: { E: [[3, 5], [3, 6], [8, 5], [8, 6]], M: [[5, 8], [6, 8], [5, 9], [6, 9]], B: [[2, 7], [9, 7]] },
      down: { E: [[3, 6], [8, 6]], s: [[3, 5], [8, 5]], M: [[5, 8], [6, 8]], B: [[2, 7], [9, 7]] },
      closed: { E: [[2, 6], [3, 6], [8, 6], [9, 6]], M: [[5, 8], [6, 8], [5, 9], [6, 9]], B: [[1, 7], [10, 7]] },
      worried: { E: [[3, 5], [3, 6], [8, 5], [8, 6]], s: [[2, 4], [9, 4]], M: [[4, 9], [5, 8], [6, 9], [7, 8]] },
      bored: { E: [[3, 6], [8, 6]], s: [[3, 5], [8, 5]], M: [[5, 8]] },
      talk: { E: [[3, 5], [3, 6], [8, 5], [8, 6]], M: [[5, 8], [6, 8], [5, 9]], B: [[2, 7], [9, 7]] },
      left: { E: [[2, 5], [2, 6], [7, 5], [7, 6]], M: [[4, 8], [5, 8]], B: [[2, 7], [9, 7]] },
      right: { E: [[4, 5], [4, 6], [9, 5], [9, 6]], M: [[6, 8], [7, 8]], B: [[2, 7], [9, 7]] },
      up: { E: [[3, 4], [3, 5], [8, 4], [8, 5]], M: [[5, 8], [6, 8]], B: [[2, 7], [9, 7]] }
    },
    s: {
      normal: { E: [[8, 5], [8, 6]], M: [[10, 8]], B: [[9, 7]] },
      blink: { E: [[8, 6], [9, 6]], M: [[10, 8]], B: [[9, 7]] },
      happy: { E: [[7, 6], [8, 5], [9, 6]], M: [[9, 8], [10, 8], [10, 9]], B: [[8, 7]] },
      sad: { E: [[8, 6]], s: [[8, 5]], M: [[10, 9]] },
      surprised: { E: [[8, 5], [8, 6]], M: [[10, 8], [10, 9]], B: [[9, 7]] },
      down: { E: [[8, 6]], s: [[8, 5]], M: [[10, 8]] },
      closed: { E: [[8, 6], [9, 6]], M: [[10, 8], [10, 9]], B: [[8, 7]] },
      worried: { E: [[8, 5], [8, 6]], M: [[10, 9]] },
      bored: { E: [[8, 6]], s: [[8, 5]], M: [[10, 8]] },
      talk: { E: [[8, 5], [8, 6]], M: [[10, 8], [10, 9]], B: [[9, 7]] },
      left: { E: [[8, 5], [8, 6]], M: [[10, 8]] },
      right: { E: [[9, 5], [9, 6]], M: [[10, 8]] },
      up: { E: [[8, 4], [8, 5]], M: [[10, 8]] }
    }
  };

  // 发型：f 正面，s 侧面（朝右），b 背面
  CHAR.hair = {
    tuft: {
      f: [
        '......HH......',
        '.......H......',
        '...HHHHHHHH...',
        '..HHHHHhhHHH..',
        '.HHHHHHHHhHHH.',
        '.HHHHHHHHHHHH.',
        '.HHHH.HHHH.HH.',
        '.HH........HH.',
        '.H..........H.',
        '..............',
        '..............',
        '..............'
      ],
      s: [
        '.....HH.......',
        '......H.......',
        '..HHHHHHHH....',
        '.HHHHHHHhHHH..',
        'HHHHHHHHHHHHH.',
        'HHHHHHHHHHHHH.',
        'HHHHHHHHHH.HH.',
        'HHHHH.........',
        '.HHH..........',
        '..............',
        '..............',
        '..............'
      ],
      b: [
        '......HH......',
        '.......H......',
        '...HHHHHHHH...',
        '..HHHHHHHHHH..',
        '.HHHHHHhHHHHH.',
        '.HHHHHHHHHHHH.',
        '.HHHHHHHHHHHH.',
        '.HHHHHHHHHHHH.',
        '.HHHHHHHHHHHH.',
        '..HHHHHHHHHH..',
        '..............',
        '..............'
      ]
    },
    sidepart: {
      f: [
        '..............',
        '..............',
        '...HHHHHHHH...',
        '..HHhhHHHHHH..',
        '.HHhHHHHHHHHH.',
        '.HHHHHHHHHHHH.',
        '.HHHHHHHH..HH.',
        '.HH........HH.',
        '.HH.........H.',
        '..............',
        '..............',
        '..............'
      ],
      s: [
        '..............',
        '..............',
        '..HHHHHHHH....',
        '.HHHHHhhHHH...',
        'HHHHHHHHHHHH..',
        'HHHHHHHHHHHHH.',
        'HHHHHHHHH.....',
        'HHHHH.........',
        '.HHH..........',
        '..............',
        '..............',
        '..............'
      ],
      b: [
        '..............',
        '..............',
        '...HHHHHHHH...',
        '..HHHHHHHHHH..',
        '.HHHHHHhHHHHH.',
        '.HHHHHHHHHHHH.',
        '.HHHHHHHHHHHH.',
        '.HHHHHHHHHHHH.',
        '.HHHHHHHHHHHH.',
        '..HHHHHHHHHH..',
        '..............',
        '..............'
      ]
    },
    messy: {
      f: [
        '..............',
        '...H..H...H...',
        '..HHHHHHHHHH..',
        '.HHHHHHhHHHHH.',
        'HHHHHhHHHHHHHH',
        'HHHHHHHHHHHHHH',
        '.HHH.HHH.HHHH.',
        'HHH........HHH',
        '.H..........H.',
        '..............',
        '..............',
        '..............'
      ],
      s: [
        '..............',
        '..H..H..H.....',
        '.HHHHHHHHH....',
        'HHHHHHhHHHH...',
        'HHHHHHHHHHHH..',
        'HHHHHHHHHHHHH.',
        'HHHHHHHHH.HH..',
        'HHHHHH........',
        'HHHH..........',
        '.H............',
        '..............',
        '..............'
      ],
      b: [
        '..............',
        '...H..H...H...',
        '..HHHHHHHHHH..',
        '.HHHHHHHHHHHH.',
        'HHHHHHHHHHHHHH',
        'HHHHHhHHHHHHHH',
        'HHHHHHHHHHHHHH',
        'HHHHHHHHHHHHHH',
        '.HHHHHHHHHHHH.',
        '..HHHHHHHHHH..',
        '..............',
        '..............'
      ]
    },
    spiky: {
      f: [
        '..H....H...H..',
        '..HH..HHH.HH..',
        '.HHHHHHHHHHHH.',
        '.HHHHHHHHHHHH.',
        '.HHHHhHHHHHHH.',
        '.HHHHHHHHHHHH.',
        '.HH.HHH.HH.HH.',
        '.H..........H.',
        '..............',
        '..............',
        '..............',
        '..............'
      ],
      s: [
        '.H...H..H.....',
        '.HH.HHHHH.....',
        'HHHHHHHHHH....',
        'HHHHHHHHHHH...',
        'HHHHHhHHHHHH..',
        'HHHHHHHHHHHHH.',
        'HHHHHHHH.H.H..',
        'HHHH..........',
        '.HH...........',
        '..............',
        '..............',
        '..............'
      ],
      b: [
        '..H....H...H..',
        '..HH..HHH.HH..',
        '.HHHHHHHHHHHH.',
        '.HHHHHHHHHHHH.',
        '.HHHHHHHHHHHH.',
        '.HHHHhHHHHHHH.',
        '.HHHHHHHHHHHH.',
        '.HHHHHHHHHHHH.',
        '.HHHHHHHHHHHH.',
        '..HHHHHHHHHH..',
        '..............',
        '..............'
      ]
    },
    bob: {
      f: [
        '..............',
        '..............',
        '...HHHHHHHH...',
        '..HHHHHHhHHH..',
        '.HHHHHHHHHHHH.',
        '.HHHHHHHHHHHH.',
        '.HHHHHHHHHHHH.',
        'HHH........HHH',
        'HHH........HHH',
        'HH..........HH',
        'HH..........HH',
        '..............'
      ],
      s: [
        '..............',
        '..............',
        '..HHHHHHHH....',
        '.HHHHHHHHhH...',
        'HHHHHHHHHHHH..',
        'HHHHHHHHHHHHH.',
        'HHHHHHHHHHHH..',
        'HHHHHH........',
        'HHHHHH........',
        'HHHHH.........',
        '.HHHH.........',
        '..............'
      ],
      b: [
        '..............',
        '..............',
        '...HHHHHHHH...',
        '..HHHHHHHHHH..',
        '.HHHHHHHHHHHH.',
        '.HHHHHHhHHHHH.',
        '.HHHHHHHHHHHH.',
        'HHHHHHHHHHHHHH',
        'HHHHHHHHHHHHHH',
        'HHHHHHHHHHHHHH',
        '.HHHHHHHHHHHH.',
        '..............'
      ]
    },
    buzz: {
      f: [
        '..............',
        '..............',
        '...HHHHHHHH...',
        '..HHHHHhHHHH..',
        '.HHHHHHHHHHHH.',
        '.HHH......HHH.',
        '.H..........H.',
        '..............',
        '..............',
        '..............',
        '..............',
        '..............'
      ],
      s: [
        '..............',
        '..............',
        '..HHHHHHHH....',
        '.HHHHHhHHHH...',
        'HHHHHHHHHHHH..',
        'HHHHHHH.......',
        'HHHH..........',
        '.HH...........',
        '..............',
        '..............',
        '..............',
        '..............'
      ],
      b: [
        '..............',
        '..............',
        '...HHHHHHHH...',
        '..HHHHHHHHHH..',
        '.HHHHHHhHHHHH.',
        '.HHHHHHHHHHHH.',
        '.HHHHHHHHHHHH.',
        '.HHHHHHHHHHHH.',
        '..HHHHHHHHHH..',
        '..............',
        '..............',
        '..............'
      ]
    },
  };

  // 头部配件（与发型同一坐标框）
  CHAR.acc = {
    glasses: {
      f: [
        '..............',
        '..............',
        '..............',
        '..............',
        '..............',
        '..............',
        '..gggg..gggg..',
        '.gGGGGggGGGGg.',
        '.gGGGGggGGGGg.',
        '..gggg..gggg..',
        '..............',
        '..............'
      ],
      s: [
        '..............',
        '..............',
        '..............',
        '..............',
        '..............',
        '..............',
        '........ggg...',
        '.....gggGGGg..',
        '.......gGGGg..',
        '........ggg...',
        '..............',
        '..............'
      ],
      b: null
    },
    headphones: {
      f: [
        '..............',
        '....aaaaaa....',
        '..aa......aa..',
        '.a..........a.',
        '.a..........a.',
        '.a..........a.',
        'AA..........AA',
        'AA..........AA',
        'AA..........AA',
        '..............',
        '..............',
        '..............'
      ],
      s: [
        '..............',
        '....aaa.......',
        '.....a........',
        '.....a........',
        '.....a........',
        '.....a........',
        '....AAA.......',
        '....AAA.......',
        '....AAA.......',
        '..............',
        '..............',
        '..............'
      ],
      b: [
        '..............',
        '....aaaaaa....',
        '..aa......aa..',
        '.a..........a.',
        '.a..........a.',
        '.a..........a.',
        'AA..........AA',
        'AA..........AA',
        'AA..........AA',
        '..............',
        '..............',
        '..............'
      ]
    },
    headset: {
      f: [
        '..............',
        '....aaaaaa....',
        '..aa......aa..',
        '.a..........a.',
        '.a............',
        '.a............',
        'AA............',
        'AA............',
        'AA............',
        '.aa...........',
        '...aaaA.......',
        '..............'
      ],
      s: [
        '..............',
        '....aaa.......',
        '.....a........',
        '.....a........',
        '.....a........',
        '.....a........',
        '....AAA.......',
        '....AAA.......',
        '....AAA.......',
        '.....aaa......',
        '........aaA...',
        '..............'
      ],
      b: [
        '..............',
        '....aaaaaa....',
        '..aa......aa..',
        '.a..........a.',
        '............a.',
        '............a.',
        '............AA',
        '............AA',
        '............AA',
        '..............',
        '..............',
        '..............'
      ]
    },
    hat: {
      f: [
        '..............',
        '....AAAAAA....',
        '...AAAAAAAA...',
        '...AAAAAAAA...',
        '...KKKKKKKK...',
        'AAAAAAAAAAAAAA',
        '.aaaaaaaaaaaa.',
        '..............',
        '..............',
        '..............',
        '..............',
        '..............'
      ],
      s: [
        '..............',
        '...AAAAAA.....',
        '..AAAAAAAA....',
        '..AAAAAAAA....',
        '..KKKKKKKK....',
        'AAAAAAAAAAAAAA',
        '.aaaaaaaaaaaa.',
        '..............',
        '..............',
        '..............',
        '..............',
        '..............'
      ],
      b: [
        '..............',
        '....AAAAAA....',
        '...AAAAAAAA...',
        '...AAAAAAAA...',
        '...KKKKKKKK...',
        'AAAAAAAAAAAAAA',
        '.aaaaaaaaaaaa.',
        '..............',
        '..............',
        '..............',
        '..............',
        '..............'
      ]
    }
  };

  // 服装：f 正面 10 宽，s 侧面 8 宽，b 背面 10 宽；长外套高 8 行，盖住裤子上部
  CHAR.outfit = {
    uniform: {
      f: ['cCCTTTTCCc', 'cCCCTTCCCc', 'cKKCCCCCCc', 'cKkCCCCCCc', 'cCCCCCCCCc', 'cccccccccc'],
      s: ['cCCCCCCT', 'cCCCCCCC', 'cCCCCCKC', 'cCCCCCkC', 'cCCCCCCC', 'cccccccc'],
      b: ['cCCCCCCCCc', 'cCCCCCCCCc', 'cCCCCCCCCc', 'cCCCCCCCCc', 'cCCCCCCCCc', 'cccccccccc']
    },
    suit: {
      f: ['cCTTKKTTCc', 'cCCTKKTCCc', 'cCCTKKTCCc', 'cCCCKKCCCc', 'cCCCCCCCCc', 'cccccccccc'],
      s: ['cCCCCCTK', 'cCCCCCCK', 'cCCCCCCK', 'cCCCCCCC', 'cCCCCCCC', 'cccccccc'],
      b: ['cCCCCCCCCc', 'cCCCCCCCCc', 'cCCCCCCCCc', 'cCCCCCCCCc', 'cCCCCcCCCc', 'cccccccccc']
    },
    sweater: {
      f: ['cCCTTTTCCc', 'cCCCTTCCCc', 'cCCCCCCCCc', 'cCLCCCCLCc', 'cCCCLLCCCc', 'cccccccccc'],
      s: ['cCCCCCCT', 'cCCCCCCC', 'cCCCCCCC', 'cCCCCLCC', 'cCCCCCCC', 'cccccccc'],
      b: ['cCCCCCCCCc', 'cCCCCCCCCc', 'cCCCCCCCCc', 'cCLCCCCLCc', 'cCCCLLCCCc', 'cccccccccc']
    },
    hoodie: {
      f: ['cCCTCCTCCc', 'cCCTCCTCCc', 'cCCCCCCCCc', 'cCCccccCCc', 'cCcCCCCcCc', 'cccccccccc'],
      s: ['cCCCCCCT', 'cCCCCCCT', 'cCCCCCCC', 'cCCCCccC', 'cCCCCCcC', 'cccccccc'],
      b: ['cCCCCCCCCc', 'cCCCCCCCCc', 'cCCCCCCCCc', 'cCCCCCCCCc', 'cCCCCCCCCc', 'cccccccccc']
    },
    vest: {
      f: ['cXCTTTTCXc', 'cXCTTTTCXc', 'cXCCTTCCXc', 'cCcCTTCcCc', 'cCCCTTCCCc', 'cccccccccc'],
      s: ['XCCCCCTT', 'XCCCCCTT', 'XCCCCCCT', 'cCCCCcCT', 'cCCCCCCT', 'cccccccc'],
      b: ['cCCCCCCCCc', 'cCCCCCCCCc', 'cCCCCCCCCc', 'cCCCCCCCCc', 'cCCCCCCCCc', 'cccccccccc']
    },
    labcoat: {
      f: ['wWWTTTTWWw', 'wWWWTTWWWw', 'wWKWWWWWWw', 'wWKWWWWWWw', 'wWWWWWWWWw', 'wWWWWwWWWw', 'wWWWWwWWWw', 'wwwwwPwwww'],
      s: ['wWWWWWWT', 'wWWWWWWT', 'wWWWWKWW', 'wWWWWKWW', 'wWWWWWWW', 'wWWWWWWW', 'wWWWWWWw', 'wwwwwwww'],
      b: ['wWWWWWWWWw', 'wWWWWWWWWw', 'wWWWWWWWWw', 'wWWWWWWWWw', 'wWWWWWWWWw', 'wWWWWwWWWw', 'wWWWWwWWWw', 'wwwwwPwwww']
    },
    jumpsuit: {
      f: ['cCCTTTTCCc', 'cCCCLCCCCc', 'cCWWLCCCCc', 'cCCCLCCCCc', 'KKKKkkKKKK', 'cCCCLCCCCc'],
      s: ['cCCCCCCT', 'cCCCCCLC', 'cCCCCCLC', 'cCCCCCLC', 'KKKKKKKK', 'cCCCCCCC'],
      b: ['cCCCCCCCCc', 'cCCCCCCCCc', 'cCCCCCCCCc', 'cCCCCCCCCc', 'KKKKKKKKKK', 'cCCCCCCCCc']
    }
  };

  // 腿：正面站立、坐姿、蹲下（侧面走路由程序按关键点绘制）
  CHAR.legs = {
    stand: ['PPPPPPPPPP', '.PPP..PPP.', '.PPP..PPP.', '.pPP..PPp.', 'FFFF..FFFF', 'FFFf..fFFF'],
    sit: ['PPPPPPPPPP', 'FFFF..FFFF', 'FFFf..fFFF'],
    crouch: ['.PPPPPPPPPP.', 'PPPPp..pPPPP', 'FFFF....FFFF'],
    tap: ['PPPPPPPPPP', '.PPP..PPP.', '.PPP..PPP.', '.pPP..FFFF', 'FFFF..FFFf', 'FFFf......']
  };

  // 连帽衫的帽子（画在头部之前）与背包
  CHAR.hood = {
    f: { x: 10, y: 24, rows: ['.CCC....CCC.', 'CCCC....CCCC'] },
    s: { x: 8, y: 23, rows: ['.CC..', 'CCCC.', 'CCCCC', 'cCCCC', '.cc..'] },
    b: { x: 10, y: 24, rows: ['..CCCCCCCC..', '.CCCCCCCCCC.', '..cCCCCCCc..', '...cccccc...'] }
  };
  CHAR.pack = {
    s: { x: 7, y: 25, rows: ['.XXXX.', 'XXXXXX', 'XxXXXX', 'XxXooX', 'XxXXXX', 'XxXXXX', 'XXXXXX', 'xxxxxx'] },
    b: { x: 11, y: 25, rows: ['.XXXXXXXX.', 'XXXXXXXXXX', 'XxXXXXXXxX', 'XxXooooXxX', 'XxXXXXXXxX', 'XxXXXXXXxX', 'XXXXXXXXXX', 'xxxxxxxxxx'] }
  };

  // ---------------------------------------------------------------------------
  // 位图：手持物件、图标与小物件。map 为字符到颜色，outline 为是否自动描黑边

  const BMP = {};
  P.BITMAPS = BMP;
  function def(name, rows, map, extra) {
    BMP[name] = Object.assign({ name, rows, map, outline: true }, extra || {});
  }

  const paperMap = { W: PAL.white, w: PAL.white2, l: PAL.pline };

  def('clipboard', [
    '..mmm..',
    'bbmMmbb',
    'bWWWWWb',
    'bWlllWb',
    'bWWWWWb',
    'bWllWWb',
    'bWWWWWb',
    'bWlllWb',
    'bbbbbbb'
  ], { m: PAL.metal2, M: PAL.metal3, b: PAL.wood2, W: PAL.white, l: PAL.pline });

  def('blueprint', [
    '.UUUUUUUU.',
    'WUUuUUUUUW',
    '.uuuuuuuu.'
  ], { U: '#5b8fd8', u: '#39649f', W: PAL.white });

  def('blueprint_v', [
    '.W.',
    'UUU',
    'UuU',
    'UUU',
    'UUU',
    'UuU',
    'UUU',
    'UUU',
    '.W.'
  ], { U: '#5b8fd8', u: '#39649f', W: PAL.white });

  def('magnifier', [
    '.mmmm..',
    'mGGWGm.',
    'mGGGGm.',
    'mGGGGm.',
    '.mmmm..',
    '....bb.',
    '.....bb'
  ], { m: PAL.yellow3, G: PAL.glass, W: PAL.white, b: PAL.wood4 });

  def('doc', [
    'WWWWW.',
    'WllWWw',
    'WWWWWW',
    'WlllWW',
    'WWWWWW',
    'WllWWW',
    'WWWWWW',
    'wwwwww'
  ], paperMap);

  def('doc_write', [
    'WWWWWWW',
    'WllllWW',
    'WWWWWWW',
    'WlllWWW',
    'wwwwwww'
  ], paperMap);

  def('docs', [
    'WWWWWWW.',
    'wwwwwwww',
    'WWWWWWWW',
    'lwwwwwww',
    'WWWWWWWW',
    'wwwwwwww'
  ], paperMap);

  def('folder', [
    'YYY.....',
    'YYYYYYYY',
    'yyyyyyyy',
    'yyyWWyyy',
    'yyyyyyyy',
    'YYYYYYYY'
  ], { Y: '#d9a64e', y: '#f0c878', W: PAL.white });

  def('scroll', [
    'bppppprppb',
    'bppppprppb',
    'bpqqqqrqqb'
  ], { b: PAL.wood3, p: PAL.paper, q: PAL.paper2, r: PAL.red2 });

  def('cup', [
    'wkkkw.',
    'WWWWWW',
    'WWWWW.',
    '.www..'
  ], { W: PAL.white, w: PAL.white2, k: PAL.tea });

  def('stamp', [
    '.bbb.',
    '.bBb.',
    '..b..',
    '..b..',
    'BBBBB',
    'XXXXX'
  ], { b: PAL.wood3, B: PAL.wood2, X: PAL.red2 });

  def('card', [
    'XXXXXX',
    'WWWWWW',
    'WllllW',
    'WWWWWW',
    'WlllWW'
  ], { X: PAL.yellow2, W: PAL.white, l: PAL.pline });

  def('card_result', [
    'XXXXXX',
    'WWWWWW',
    'WlllgW',
    'WWWggW',
    'WlgWWW'
  ], { X: PAL.green2, W: PAL.white, l: PAL.pline, g: PAL.green3 });

  def('paperball', ['.W.', 'WwW', '.w.'], paperMap);

  def('box', [
    '.qqqqqqqqqq.',
    'qqqqqqqqqqqq',
    'NNNNNNNNNNNN',
    'NNNNNNNNNNNN',
    'NNNNNNNNNNNN',
    'NNNNNNNNNNNN',
    'NNNNNNNNNNNN',
    'nnnnnnnnnnnn'
  ], { q: PAL.card1, N: PAL.card2, n: PAL.card3 });

  def('box_open', [
    'qq........qq',
    '.qq......qq.',
    'nddddddddddn',
    'NNNNNNNNNNNN',
    'NNNNNNNNNNNN',
    'NNNNNNNNNNNN',
    'NNNNNNNNNNNN',
    'NNNNNNNNNNNN',
    'nnnnnnnnnnnn'
  ], { q: PAL.card1, N: PAL.card2, n: PAL.card3, d: PAL.card4 });

  def('box_sealed', [
    '.qqqqTTqqqq.',
    'qqqqqTTqqqqq',
    'NNNNNTTNNNNN',
    'NNNNNTTNRRNN',
    'NNNNNTTRrRRN',
    'NNNNNTTNRRNN',
    'NNNNNTTNNNNN',
    'nnnnnTTnnnnn'
  ], { q: PAL.card1, N: PAL.card2, n: PAL.card3, T: '#efe0b8', R: PAL.red2, r: PAL.red1 });

  // 贴着放行单的箱子：质检送到成果库时搬运
  def('box_release', [
    '.qqqqTTqqqq.',
    'qqqqqTTqqqqq',
    'NNWWWWWNNNNN',
    'NNWgggWNRRNN',
    'NNWgWgWRrRRN',
    'NNWgggWNRRNN',
    'NNWWWWWNNNNN',
    'nnnnnTTnnnnn'
  ], { q: PAL.card1, N: PAL.card2, n: PAL.card3, T: '#efe0b8', W: PAL.white, g: PAL.green2, R: PAL.red2, r: PAL.red1 });

  def('box_rework', [
    '.qqqqTTqqqq.',
    'qqqqqTTqqqqq',
    'NNWWWWWWWNNN',
    'NNWrrrrrWNNN',
    'NNWrWrWrWNNN',
    'NNWrrrrrWNNN',
    'NNWWWWWWWNNN',
    'nnnnnTTnnnnn'
  ], { q: PAL.card1, N: PAL.card2, n: PAL.card3, T: '#efe0b8', W: PAL.white, r: PAL.red2 });

  def('slip_release', [
    'WWWWWW',
    'WllllW',
    'WWWWWW',
    'WgggWW',
    'WgWgWW',
    'WgggWW',
    'wwwwww'
  ], { W: PAL.white, w: PAL.white2, l: PAL.pline, g: PAL.green2 });

  def('slip_defect', [
    'WWWWWW',
    'WllllW',
    'WWWWWW',
    'WrrrWW',
    'WrWrWW',
    'WrrrWW',
    'wwwwww'
  ], { W: PAL.white, w: PAL.white2, l: PAL.pline, r: PAL.red2 });

  def('ticket', [
    'WWWWWWWW',
    'WWWWWWWW',
    'WWWWWWWW',
    'WWWWWWWW',
    'WWWWWWWW',
    'wwwwwwww'
  ], paperMap);

  def('form', [
    'rrrrrrr',
    'WWWWWWW',
    'WlllllW',
    'WWWWWWW',
    'WllllWW',
    'WWWWWWW',
    'WlllWWW',
    'WWWWWbW',
    'wwwwwww'
  ], { r: PAL.orange2, W: PAL.white, w: PAL.white2, l: PAL.pline, b: PAL.blue3 });

  def('eraser', ['WWWWW', 'bbbbb', 'BBBBB'], { W: PAL.white2, b: PAL.grey4, B: PAL.grey3 });

  // 决定单：用户对结果未知的动作作出的决定，从门缝塞进来
  def('decision', [
    'bbbbbbb',
    'WWWWWWW',
    'WlllllW',
    'WWWWWWW',
    'WllWWgW',
    'WWWWgWW',
    'wwwwwww'
  ], { b: PAL.blue2, W: PAL.white, w: PAL.white2, l: PAL.pline, g: PAL.green3 });

  def('note', [
    'YYYYY',
    'YyyyY',
    'YYYYY',
    'YyyYY',
    'yyyyy'
  ], { Y: PAL.yellow1, y: PAL.yellow2 });

  def('note_done', [
    'YYYYY',
    'YyyyY',
    'YYYYg',
    'YgYgY',
    'yygyy'
  ], { Y: PAL.yellow1, y: PAL.yellow2, g: PAL.green3 });

  def('letter', [
    'WWWWWWWW',
    'wWWWWWWw',
    'WwWWWWwW',
    'WWwWWwWW',
    'WWWwwWrr',
    'wwwwwwrr'
  ], { W: PAL.white, w: PAL.white3, r: PAL.red2 });

  def('pen', ['K', 'K', 'K', 'm'], { K: PAL.blue3, m: PAL.metal2 });

  def('pen_red', ['K', 'K', 'K', 'm'], { K: PAL.red2, m: PAL.metal2 });

  def('tape', ['.TT.', 'TmmT', 'TmmT', '.TT.'], { T: '#efe0b8', m: PAL.card3 });

  // 图标
  def('bulb', [
    '...yyy...',
    '..yYYYy..',
    '.yYWYYYy.',
    '.yYWYYYy.',
    '.yYYYYYy.',
    '.yYYYYYy.',
    '..yYYYy..',
    '...yYy...',
    '...mmm...',
    '...MMM...',
    '...mmm...'
  ], { y: PAL.yellow2, Y: PAL.yellow1, W: PAL.white, m: PAL.metal2, M: PAL.metal3 });

  def('question', [
    '.YYY.',
    'YYyYY',
    'yy.YY',
    '..YYy',
    '..Yy.',
    '..y..',
    '.....',
    '..Y..',
    '..y..'
  ], { Y: PAL.yellow2, y: PAL.yellow3 });

  def('exclaim', [
    'RRR',
    'RRR',
    'RRR',
    'RrR',
    '.r.',
    '...',
    'RRR',
    'rrr'
  ], { R: PAL.red2, r: PAL.red3 });

  def('check', [
    '......G',
    '.....GG',
    'G...GG.',
    'GG.GG..',
    '.GGG...',
    '..G....'
  ], { G: PAL.green2 });

  def('cross', [
    'RR...RR',
    '.RR.RR.',
    '..RRR..',
    '.RR.RR.',
    'RR...RR'
  ], { R: PAL.red2 });

  def('heart', ['.RR.RR.', 'RRRRRRR', 'RRRRRRR', '.RRRRR.', '..RRR..', '...R...'], { R: PAL.pink2 });

  def('zzz', ['WWWW', '..W.', '.W..', 'WWWW'], { W: PAL.white }, { outline: true });

  def('flag', [
    'mXXXXX..',
    'mXXXXXXX',
    'mXXXXXXx',
    'mxXXXXx.',
    'm.xxx...',
    'm.......',
    'm.......',
    'm.......',
    'm.......',
    'm.......',
    'M.......'
  ], { m: PAL.metal2, M: PAL.metal3, X: '#ffffff', x: '#cccccc' });

  def('flag2', [
    'mXXXX...',
    'mXXXXXX.',
    'mXXXXXXX',
    'mXXXXXxx',
    'mxxxx...',
    'm.......',
    'm.......',
    'm.......',
    'm.......',
    'm.......',
    'M.......'
  ], { m: PAL.metal2, M: PAL.metal3, X: '#ffffff', x: '#cccccc' });

  def('smoke1', ['.ww.', 'wWWw', 'wWWw', '.ww.'], { W: '#b9bcc4', w: '#8e929c' }, { outline: false });
  def('smoke2', ['..ww..', '.wWWw.', 'wWWWWw', 'wWWWWw', '.wWWw.', '..ww..'], { W: '#c7c9d0', w: '#9da1ab' }, { outline: false });

  // 桌面物件
  def('deskMonitor', [
    '.EEEEEEEEEEEEEEEEEE.',
    'EEEEEEEEEEEEEEEEEEEe',
    'EEdSSSSSSSSSSSSSSdEe',
    'EEdSSSSSSSSSSSSSSdEe',
    'EEdSSSSSSSSSSSSSSdEe',
    'EEdSSSSSSSSSSSSSSdEe',
    'EEdSSSSSSSSSSSSSSdEe',
    'EEdSSSSSSSSSSSSSSdEe',
    'EEdSSSSSSSSSSSSSSdEe',
    'EEdSSSSSSSSSSSSSSdEe',
    'EEdSSSSSSSSSSSSSSdEe',
    'EEddddddddddddddddEe',
    'EEEEEEEEEEEEEEELEEEe',
    'eeeeeeeeeeeeeeeeeeee',
    '.....eeeeeeeeee.....',
    '....dddddddddddd....'
  ], { E: PAL.beige1, e: PAL.beige2, d: PAL.beige3, S: PAL.screen0, L: PAL.green2 });

  def('keyboard', [
    'wwwwwwwwwwwwww',
    'wgwgwgwgwgwgww',
    'gggggggggggggg'
  ], { w: PAL.grey1, g: PAL.grey3 });

  def('clock', [
    '....FFFFF....',
    '..FFWWWWWFF..',
    '.FWWWWoWWWWF.',
    '.FWWWWWWWWWF.',
    'FWWWWWWWWWWWF',
    'FWWWWWWWWWWWF',
    'FoWWWWWWWWWoF',
    'FWWWWWWWWWWWF',
    'FWWWWWWWWWWWF',
    '.FWWWWWWWWWF.',
    '.FWWWWoWWWWF.',
    '..FFWWWWWFF..',
    '....FFFFF....'
  ], { F: PAL.wood3, W: PAL.white, o: PAL.ink2 });

  def('lamp', [
    '......oo......',
    '......oo......',
    '....LLLLLL....',
    '..LLLLLLLLLL..',
    '.LLLLLLLLLLLL.',
    '..yyyyyyyyyy..'
  ], { o: PAL.grey4, L: PAL.grey2, y: PAL.yellow1 });

  def('plant', [
    '.....GG.......',
    '....GgG..GG...',
    '..GG.GgG.GgG..',
    '.GgG..GgGgG...',
    '..GgG..GgG..G.',
    '...GgGGgG..GgG',
    '.G..GgGgGGgG..',
    'GgGG..GgGgG...',
    '.GgGG.GgG.....',
    '..GGgGGgG.....',
    '....GgGG......',
    '.....GG.......',
    '...NNNNNNNN...',
    '...NnnnnnnN...',
    '....NNNNNN....',
    '....NnnnnN....',
    '....NNNNNN....',
    '.....nnnn.....'
  ], { G: PAL.leaf2, g: PAL.leaf1, N: PAL.pot1, n: PAL.pot2 });

  def('bin', [
    'mmmmmmmmmm',
    'MMMMMMMMMM',
    'MdMdMdMdMM',
    'MdMdMdMdMM',
    '.MdMdMdMd.',
    '.MdMdMdMd.',
    '.MMMMMMMM.',
    '..dddddd..'
  ], { m: PAL.metal1, M: PAL.metal3, d: PAL.metal4 });

  def('teapot', [
    '...bb....',
    '..WWWW...',
    'WWWWWWWW.',
    'W.WWWWWWW',
    'W.WWWWWW.',
    '.WWWWWW..',
    '..wwww...'
  ], { W: '#9fd3c7', w: '#6aa89a', b: PAL.wood3 });

  // 灯与指示灯
  def('beacon', [
    '..LL..',
    '.LLLL.',
    'LLWLLL',
    'LLLLLL',
    'mmmmmm',
    'MMMMMM'
  ], { L: PAL.yellow2, W: PAL.white, m: PAL.grey3, M: PAL.grey4 });

  def('beacon_red', [
    '..LL..',
    '.LLLL.',
    'LLWLLL',
    'LLLLLL',
    'mmmmmm',
    'MMMMMM'
  ], { L: PAL.red2, W: PAL.white, m: PAL.grey3, M: PAL.grey4 });

  def('cart', [
    'mm........................',
    '.m........................',
    '.m........................',
    '..m.......................',
    '..mmmmmmmmmmmmmmmmmmmmmmmm',
    '..MMMMMMMMMMMMMMMMMMMMMMMM',
    '...m..................m...',
    '...m..................m...',
    '..MMMMMMMMMMMMMMMMMMMMMMM.',
    '..oWo................oWo..',
    '...o..................o...'
  ], { m: PAL.metal2, M: PAL.metal3, o: PAL.grey5, W: PAL.grey2 });

  // ---------------------------------------------------------------------------
  // 3×5 像素数字字体：版本号、号码牌、档案盒编号等短标记

  P.FONT3 = {
    '0': ['111', '101', '101', '101', '111'],
    '1': ['010', '110', '010', '010', '111'],
    '2': ['111', '001', '111', '100', '111'],
    '3': ['111', '001', '011', '001', '111'],
    '4': ['101', '101', '111', '001', '001'],
    '5': ['111', '100', '111', '001', '111'],
    '6': ['111', '100', '111', '101', '111'],
    '7': ['111', '001', '010', '010', '010'],
    '8': ['111', '101', '111', '101', '111'],
    '9': ['111', '101', '111', '001', '111'],
    'r': ['000', '101', '110', '100', '100'],
    'v': ['000', '101', '101', '101', '010'],
    'x': ['000', '101', '010', '101', '000'],
    'n': ['000', '110', '101', '101', '101'],
    '#': ['101', '111', '101', '111', '101'],
    '/': ['001', '001', '010', '100', '100'],
    ':': ['000', '010', '000', '010', '000'],
    '-': ['000', '000', '111', '000', '000'],
    '+': ['000', '010', '111', '010', '000'],
    '.': ['000', '000', '000', '000', '010'],
    '%': ['101', '001', '010', '100', '101'],
    ' ': ['000', '000', '000', '000', '000']
  };

  // 点阵自检：行宽不一致或字符不在色板中时直接抛出错误
  function checkRows(label, rows, chars) {
    if (!rows) return;
    const w = rows[0].length;
    rows.forEach((row, i) => {
      if (row.length !== w) throw new Error('点阵行宽不一致：' + label + ' 第 ' + i + ' 行');
      if (chars) {
        for (const ch of row) if (ch !== '.' && !chars.includes(ch)) throw new Error('点阵字符未定义：' + label + ' 「' + ch + '」');
      }
    });
  }
  Object.values(BMP).forEach((b) => checkRows(b.name, b.rows, Object.keys(b.map)));
  const roleChars = Object.keys(P.rolePalette('product', 'agent', null).map);
  checkRows('head.f', CHAR.head.f, roleChars);
  checkRows('head.s', CHAR.head.s, roleChars);
  Object.entries(CHAR.hair).forEach(([k, v]) => ['f', 's', 'b'].forEach((view) => checkRows('hair.' + k + '.' + view, v[view], roleChars)));
  Object.entries(CHAR.acc).forEach(([k, v]) => ['f', 's', 'b'].forEach((view) => checkRows('acc.' + k + '.' + view, v[view], roleChars)));
  Object.entries(CHAR.outfit).forEach(([k, v]) => ['f', 's', 'b'].forEach((view) => checkRows('outfit.' + k + '.' + view, v[view], roleChars)));
  Object.entries(CHAR.legs).forEach(([k, v]) => checkRows('legs.' + k, v, roleChars));
  Object.entries(CHAR.hood).forEach(([k, v]) => checkRows('hood.' + k, v.rows, roleChars));
  Object.entries(CHAR.pack).forEach(([k, v]) => checkRows('pack.' + k, v.rows, roleChars));
})();
