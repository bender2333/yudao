// 交付文件的下载入口（工单 #748）：文本文件的内容已经在页面上，同样给下载链接；
// 下载的文件名取交付里的路径名——同一交付里两个同名文件（a/x.py 与 b/x.py）按最后一段会互相覆盖。

export type DeliveryFileLike = {
  path: string;
  content: string | null | undefined;
  base64: string | null | undefined;
};

export type FileDownload = {
  href: string;
  name: string;
};

/** 交付文件���下载入口：文本按内容打包，二进制按 base64 打包；没有内容时没有下载入口。 */
export function fileDownload(file: DeliveryFileLike): FileDownload | null {
  if (file.content !== null && file.content !== undefined) {
    return {
      href: `data:text/plain;charset=utf-8,${encodeURIComponent(file.content)}`,
      name: file.path,
    };
  }
  if (file.base64 !== null && file.base64 !== undefined) {
    return {
      href: `data:application/octet-stream;base64,${file.base64}`,
      name: file.path,
    };
  }
  return null;
}
