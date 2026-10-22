// 页面文件与服务不匹配时的处理（工单 #704）：
// 页面跑的就是服务提供的那一份页面文件，所以「页面文件的接口版本」就是页面里写着的
// CLIENT_API_VERSION（由接口快照生成 ✓）；服务要的是几版，从能力清单的 deployment 读出 ✓。
// 这一份给出两件事：重新加载有没有用、用户该做什么。

/** 服务端的接口版本与页面的不一致时的说明。 */
export type VersionMismatch = {
  /** 页面这一份的接口版本 */
  pageVersion: number;
  /** 服务要的接口版本 */
  serverVersion: number;
  /** 页面构建时的发布版本与服务的是否相同：相同说明服务那边的页面文件也是这一份 */
  sameRelease: boolean;
};

export type MismatchAdvice = {
  /** 重新加载有没有用：服务那边的页面文件换了才有用 */
  reloadHelps: boolean;
  /** 提示的正文 */
  text: string;
};

/**
 * 重新加载有没有用：服务那边的页面文件是另一个发布时有用；只有接口版本不同时，
 * 服务那边的页面文件还是这一份，重载取回来的还是它，没有用。
 */
export function reloadHelps(mismatch: VersionMismatch): boolean {
  return !mismatch.sameRelease;
}

/** 这个状态下的提示：两个版本各是什么、该做什么。 */
export function mismatchAdvice(mismatch: VersionMismatch): MismatchAdvice {
  const { pageVersion, serverVersion } = mismatch;
  const text = mismatch.sameRelease
    ? `这一份页面文件的接口版本是 ${pageVersion}，服务要的是 ${serverVersion}。`
      + "服务那边的页面文件还是这一份，重新加载取回来的还是它；需要重新构建页面文件"
      + "（cd client && npm run build:pages），再把 client/out/renderer 复制到 harness/release_assets/，"
      + "然后重新加载本页。"
    : `这一份页面文件的接口版本是 ${pageVersion}，服务要的是 ${serverVersion}；`
      + "服务那边的页面文件是另一个发布，重新加载可以取到与服务匹配的那一份。";
  return { reloadHelps: reloadHelps(mismatch), text };
}
