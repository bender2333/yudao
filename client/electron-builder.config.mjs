// electron-builder 26 系列的打包配置（设计说明第 3.3、7 节，ADR-0023）：NSIS、x64、按用户安装
// （不需要管理员权限），安装到 %LOCALAPPDATA%\Programs\<产品名>，建立开始菜单快捷方式。
//
// 用 JS 配置按环境变量改写 appId、产品名与安装包文件名，测试构建因此与用户已经安装的那一份互不影响：
//   YUDAO_APP_ID         应用标识（默认 com.yudao.client）
//   YUDAO_PRODUCT_NAME   产品名、可执行文件名与安装目录名（默认 Yudao）
//   YUDAO_SETUP_BASENAME 安装包文件名前缀（默认 Yudao-Setup）
// script/build-installer.mjs 设置这些变量并调用 electron-builder。
//
// 不写 publisherName（不签名，TODO，设计说明第 7 节）：写了就要校验签名，未签名的安装包会更新失败。
// 更新用 generic 提供方，地址在连接时由主进程按已连接的地址加 /client-update/ 给出。

const appId = process.env.YUDAO_APP_ID ?? "com.yudao.client";
const productName = process.env.YUDAO_PRODUCT_NAME ?? "Yudao";
const setupBasename = process.env.YUDAO_SETUP_BASENAME ?? "Yudao-Setup";

/** @type {import('electron-builder').Configuration} */
const config = {
  appId,
  productName,
  directories: {
    output: process.env.YUDAO_OUTPUT_DIR ?? "dist",
    buildResources: "build",
  },
  files: ["out/**", "resources/**", "package.json", "!**/*.map"],
  win: {
    target: [{ target: "nsis", arch: ["x64"] }],
    // electron-builder 要求至少 256×256；resources/app-icon.png 由 scripts/make-tray-icons.mjs 生成
    icon: "resources/app-icon.png",
    // 可执行文件名跟随产品名（测试构建的可执行文件与用户那一份不同名）
    executableName: productName,
  },
  nsis: {
    oneClick: true,
    perMachine: false,
    allowToChangeInstallationDirectory: false,
    createStartMenuShortcut: true,
    shortcutName: productName,
    artifactName: `${setupBasename}-\${version}.\${ext}`,
    // 卸载不删除 Yudao 服务的数据：只删除客户端自己的文件（设计说明第 3.3 节）
    deleteAppDataOnUninstall: false,
  },
  // generic 提供方：electron-builder 据此生成更新清单 latest.yml 与差分下载用的 blockmap。
  // url 是占位值：更新地址在连接时由主进程按已连接的地址加 /client-update/ 给出（设计说明第 5.2 节），
  // 客户端不读打包时写死的地址。带有 publish 配置是 latest.yml 生成的条件。
  publish: [
    {
      provider: "generic",
      url: process.env.YUDAO_PUBLISH_URL ?? "http://127.0.0.1/",
      channel: "latest",
    },
  ],
};

export default config;
