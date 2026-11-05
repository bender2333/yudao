// 命令标识（command_id）的生成：一条命令每次提交都要有一个唯一标识，控制核心按它把重复提交
// 识别为同一件事（接口合同第 6.3 节）。
// crypto.randomUUID 只在安全上下文（https 与本机地址）里存在；局域网访问方式下页面经
// http://<局域网地址> 提供，那不是安全上下文，页面里没有 randomUUID。因此按 RFC 4122 第 4 节
// 用 crypto.getRandomValues 取随机字节拼出第 4 版标识：getRandomValues 在任何上下文里都有，
// 命令标识在任何访问方式下都能生成。

export function newCommandId(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  // 第 4 版：把时间戳与机器位两处固定成规定的位
  bytes[6] = ((bytes[6] ?? 0) & 0x0f) | 0x40;
  bytes[8] = ((bytes[8] ?? 0) & 0x3f) | 0x80;
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0"));
  return [
    hex.slice(0, 4).join(""),
    hex.slice(4, 6).join(""),
    hex.slice(6, 8).join(""),
    hex.slice(8, 10).join(""),
    hex.slice(10, 16).join(""),
  ].join("-");
}