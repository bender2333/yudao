// 页面文件与服务不匹配时的处理（工单 #704、#909）：
// 页面跑的就是服务提供的那一份页面文件，所以「页面文件的接口版本」就是页面里写着的
// CLIENT_API_VERSION（由接口快照生成 ✓）；服务要的是几版，从能力清单的 deployment 读出 ✓。
// 这一份给出两件事：重新加载有没有用、用户该做什么。按两个接口版本哪一边新分两种（设计说明第 5.1 节）。

/** 服务端的接口版本与页面的不一致时的两份版本。 */
export type VersionMismatch = {
  /** 页面这一份的接口版本 */
  pageVersion: number;
  /** 服务要的接口版本 */
  serverVersion: number;
};

export type MismatchAdvice = {
  /** 重新加载有没有用：服务那边比页面新时，重新构建页面文件以后再重载本页才取到新的 */
  reloadHelps: boolean;
  /** 提示的正文 */
  text: string;
};

/**
 * 重新加载有没有用：服务比页面新时，服务提供的页面文件还没跟着更新，重新构建以后重载本页才取到新的；
 * 页面比服务新时，页面这一份就是新的那一份，重载取回来的还是它，没有用。
 */
export function reloadHelps(mismatch: VersionMismatch): boolean {
  return mismatch.serverVersion > mismatch.pageVersion;
}

/** 这个状态下的提示：两个版本各是什么、该做什么。 */
export function mismatchAdvice(mismatch: VersionMismatch): MismatchAdvice {
  const { pageVersion, serverVersion } = mismatch;
  const text = serverVersion > pageVersion
    ? `这一份页面文件的接口版本是 ${pageVersion}，服务要的是 ${serverVersion}，服务比页面新。`
      + "服务提供的页面文件没有跟着更新（从源码运行而没有重新构建时出现）；需要重新构建页面文件"
      + "（cd client && npm run build:pages），再把 client/out/renderer 复制到 harness/release_assets/，"
      + "然后重新加载本页。"
    : `这一份页面文件的接口版本是 ${pageVersion}，服务要的是 ${serverVersion}，页面比服务新。`
      + "服务在跑旧的代码，需要重启 Yudao 服务。";
  return { reloadHelps: reloadHelps(mismatch), text };
}
