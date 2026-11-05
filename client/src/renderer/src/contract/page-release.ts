// 页面构建时的发布版本（网页界面的提供与发布设计说明第 5.1 节）：
// 页面由 Vite 构建时把 client/package.json 的版本写进 import.meta.env.VITE_YUDAO_RELEASE。
// 页面每次连接读取能力清单里的 deployment.version（服务的发布版本），与它不同时重新加载页面，
// 取到与服务同一个版本的页面文件（升级以后服务重启，页面可能还是上一次发布留下的文件）。
// 服务与页面同出一个发布，两个版本相同。

export const PAGE_RELEASE: string = import.meta.env.VITE_YUDAO_RELEASE;