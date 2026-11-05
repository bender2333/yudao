// 访问令牌在这个浏览器中的保存与读取（应用层与接口层设计说明第 6.3 节）：
// 令牌由用户在页面中填写一次，保存在这个浏览器里；页面的查询、命令与事件流在请求头中带上它，
// 令牌不出现在地址里。服务端只保存摘要，页面保存明文只是为了让下一次请求能用同一个令牌。
// 本机访问方式不需要令牌，因此这里读到的通常是空串。

const TOKEN_KEY = "yudao.access-token";

// 读取这个浏览器里保存的令牌；没有保存过时令牌就是空串
export function storedToken(): string {
  return window.localStorage.getItem(TOKEN_KEY) ?? "";
}

// 保存用户填写的令牌：此后刷新页面不需要再次填写
export function rememberToken(token: string): void {
  window.localStorage.setItem(TOKEN_KEY, token);
}

// 清掉保存的令牌：服务端撤销以后，令牌撤销前保存的这一份同样不再被使用
export function forgetToken(): void {
  window.localStorage.removeItem(TOKEN_KEY);
}