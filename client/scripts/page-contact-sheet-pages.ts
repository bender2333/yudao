// 联系表的页面清单与截图矩阵（工单 #376）：每一项写明页面名称、原型 v10 中的路由与档位、
// 真实系统中的路由模板，以及真实系统一侧用哪个预置项目准备数据。
// 脚本与单元测试都从这里取数据，页面清单只有一份。

// 原型 v10 的档位：低于页面所读查询的档位时页面打不开（docs/prototypes/v10/js/contract/registry.js）
export const LEVELS = ["ui", "3.1", "3.2C", "3.4A", "3.8", "3.2B", "3.2D", "pilot", "S4", "S5"];

export type PageEntry = {
  slug: string;
  name: string;
  /** 原型 v10 的路由，用原型自带的示例数据 */
  prototypeHash: string;
  /** 原型 v10 的档位：页面所读查询的最低档位 */
  prototypeLevel: string;
  /** 真实系统的路由模板，{project} 与 {workItem} 由脚本按项目名替换 */
  systemHash: string;
  /** 真实系统一侧的预置项目名（client/tests/e2e/backend.py 的 default 脚本），null 为系统页 */
  systemProject: string | null;
  /** 真实系统一侧是否需要事项标识（恢复页的路径里有事项） */
  systemWorkItem: boolean;
  /** 真实系统一侧打开页面的覆盖层（点覆盖层工具条上的这一格），null 为不开覆盖层 */
  systemOverlay: string | null;
  /** 首屏稳定后额外等待的毫秒数：像素画面（楼、房间）里的走位动画需要时间 */
  settle: number;
};

// 真实系统的机器、运行、工具页面按原型 v10 排布（工单 #378），明细等待所属工作包登记查询；
// 恢复页还没有内容（工单 #380），联系表照拍占位画面。
export const PAGES: PageEntry[] = [
  {
    slug: "home",
    name: "首页（含决定卡片）",
    prototypeHash: "#/home",
    prototypeLevel: "ui",
    systemHash: "#/home",
    systemProject: null,
    systemWorkItem: false,
    systemOverlay: null,
    settle: 1600,
  },
  {
    slug: "machines",
    name: "机器",
    prototypeHash: "#/sys/machines",
    prototypeLevel: "3.2C",
    systemHash: "#/sys/machines",
    systemProject: null,
    systemWorkItem: false,
    systemOverlay: null,
    settle: 0,
  },
  {
    slug: "runtime",
    name: "运行",
    prototypeHash: "#/sys/runtime",
    prototypeLevel: "3.4A",
    systemHash: "#/sys/runtime",
    systemProject: null,
    systemWorkItem: false,
    systemOverlay: null,
    settle: 0,
  },
  {
    slug: "tools",
    name: "工具",
    prototypeHash: "#/sys/tools",
    prototypeLevel: "3.2B",
    systemHash: "#/sys/tools",
    systemProject: null,
    systemWorkItem: false,
    systemOverlay: null,
    settle: 0,
  },
  {
    slug: "overview",
    name: "项目概览与楼层",
    prototypeHash: "#/p/p-metro/overview?w=w-metro-transfer",
    prototypeLevel: "ui",
    systemHash: "#/p/{project}/overview",
    systemProject: "交付历史",
    systemWorkItem: false,
    systemOverlay: "流转",
    settle: 1600,
  },
  {
    slug: "dept",
    name: "部门工作间",
    prototypeHash: "#/p/p-metro/dept/engineering?w=w-metro-transfer",
    prototypeLevel: "ui",
    systemHash: "#/p/{project}/dept/engineering",
    systemProject: "文本工具",
    systemWorkItem: false,
    systemOverlay: null,
    settle: 1600,
  },
  {
    slug: "materials",
    name: "资料",
    prototypeHash: "#/p/p-todo/materials?w=w-todo-due",
    prototypeLevel: "ui",
    systemHash: "#/p/{project}/materials",
    systemProject: "示例项目",
    systemWorkItem: false,
    systemOverlay: null,
    settle: 0,
  },
  {
    slug: "observe",
    name: "观测",
    prototypeHash: "#/p/p-metro/observe?w=w-metro-transfer",
    prototypeLevel: "ui",
    systemHash: "#/p/{project}/observe",
    systemProject: "交付历史",
    systemWorkItem: false,
    systemOverlay: null,
    settle: 0,
  },
  {
    slug: "settings",
    name: "项目设置",
    prototypeHash: "#/p/p-sensor/settings",
    prototypeLevel: "ui",
    systemHash: "#/p/{project}/settings",
    systemProject: "示例项目",
    systemWorkItem: false,
    systemOverlay: null,
    settle: 0,
  },
  {
    slug: "recovery",
    name: "恢复",
    prototypeHash: "#/p/p-sensor/w/w-sensor-chart/recovery",
    prototypeLevel: "3.1",
    systemHash: "#/p/{project}/w/{workItem}/recovery",
    systemProject: "文本工具",
    systemWorkItem: true,
    systemOverlay: null,
    settle: 0,
  },
  {
    slug: "models",
    name: "模型管理",
    prototypeHash: "#/sys/models",
    prototypeLevel: "ui",
    systemHash: "#/sys/models",
    systemProject: null,
    systemWorkItem: false,
    systemOverlay: null,
    settle: 0,
  },
];

export const THEMES = ["light", "dark"] as const;
export type Theme = (typeof THEMES)[number];

export const WINDOWS = [
  { width: 1440, height: 900 },
  { width: 1920, height: 1080 },
] as const;

export const SCALE_FACTORS = [1, 1.25, 1.5] as const;

export type ShotConfig = {
  width: number;
  height: number;
  scaleFactor: number;
  label: string;
};

// 一张联系表的行：两种窗口乘三种设备像素比
export function shotConfigs(): ShotConfig[] {
  return WINDOWS.flatMap((size) =>
    SCALE_FACTORS.map((scaleFactor) => ({
      ...size,
      scaleFactor,
      label: `${size.width}×${size.height} · DPR ${scaleFactor}`,
    })),
  );
}

export function sheetFileName(slug: string, theme: string): string {
  return `${slug}-${theme}.png`;
}