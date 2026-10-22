// 模型服务不可用时顶栏的状态项（工单 #718）：
// system.status 的 provider.available 为 false 时给出一处能看见的提示，写明服务端的说明，
// 点一下进模型管理页；可用时不显示。
//
// 单独成模块：顶栏是带 JSX 的视图模块，单元测试（node 直接跑 TypeScript）不能直接引入它，
// 提示的判断放在这里就能单独核对。

export type ProviderReadiness = {
  available: boolean;
  reason: string | null;
  message: string | null;
};

export type ProviderNotice = {
  label: string;
  detail: string;
};

/** 模型服务不可用时的提示；可用或还没有读到状态时为空。 */
export function providerNotice(provider: ProviderReadiness | null | undefined): ProviderNotice | null {
  if (!provider || provider.available) {
    return null;
  }
  const detail = provider.message ?? provider.reason ?? "";
  return { label: "模型服务不可用", detail };
}
