// 更新页（设计说明第 5.2 节，工单 #208）：连接时读取能力清单，接口版本与客户端构建时的接口版本
// 不同才显示。写明客户端与 Yudao 服务两边的发布版本号与接口版本，按钮「更新客户端」。
// 更新页不打开其他页面，不执行命令（外壳与左侧栏都不出现）。
//
// 更新过程在客户端的主进程里运行（src/main/update.ts 使用 electron-updater），本页只显示进度、
// 失败原因与「重试」；Yudao 服务没有提供安装包（/client-update/ 返回 404）时显示
// 「控制主机没有提供客户端安装包」（第 5.2 节）。

import { useEffect, useRef, useState } from "react";

export type UpdatePageProps = {
  address: string;
  clientVersion: number;
  serverVersion: number;
  serverRelease: string;
};

type Progress = {
  phase: "checking" | "downloading" | "downloaded" | "installing" | "none" | "failed";
  percent?: number;
  version?: string;
  message?: string;
};

// 各阶段给用户看的一句话；failed 用主进程给出的原因
function phaseText(progress: Progress): string {
  switch (progress.phase) {
    case "checking":
      return "正在检查更新…";
    case "downloading":
      return `正在下载更新${progress.percent === undefined ? "…" : `（${progress.percent}%）`}`;
    case "downloaded":
      return "下载完成，正在退出并安装新版本…";
    case "installing":
      return "正在安装新版本，安装完成以后客户端自动启动并重新连接…";
    case "none":
      return "控制主机提供的版本与当前客户端相同。";
    case "failed":
      return progress.message ?? "更新失败";
  }
}

export function UpdatePage(props: UpdatePageProps) {
  const [clientRelease, setClientRelease] = useState("");
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState<Progress | null>(null);
  const unsubscribe = useRef<(() => void) | null>(null);

  useEffect(() => {
    void (async () => {
      setClientRelease((await window.yudao?.getClientVersion()) ?? "");
    })();
    return () => unsubscribe.current?.();
  }, []);

  const start = async (): Promise<void> => {
    unsubscribe.current?.();
    unsubscribe.current = window.yudao?.onUpdateProgress((next) => setProgress(next)) ?? null;
    setProgress({ phase: "checking" });
    setRunning(true);
    try {
      const run = await window.yudao?.startUpdate(props.address);
      if (run !== undefined && run.phase === "failed") {
        setProgress({ phase: "failed", message: run.message });
      }
    } catch (error) {
      setProgress({ phase: "failed", message: error instanceof Error ? error.message : String(error) });
    } finally {
      setRunning(false);
    }
  };

  const failed = progress?.phase === "failed";
  return (
    <div className="gate">
      <div className="card">
        <h1>请更新客户端</h1>
        <p>客户端与控制主机的接口版本不同，不能打开页面，也不执行命令。</p>
        <ul>
          <li>控制主机地址：{props.address}</li>
          <li>客户端发布版本：{clientRelease}</li>
          <li>Yudao 服务发布版本：{props.serverRelease}</li>
          <li>客户端接口版本：{props.clientVersion}</li>
          <li>Yudao 服务接口版本：{props.serverVersion}</li>
        </ul>
        {progress !== null && (
          <p className={failed ? "error" : "note"}>{phaseText(progress)}</p>
        )}
        <button className="primary" type="button" disabled={running} onClick={() => void start()}>
          {failed ? "重试" : "更新客户端"}
        </button>
      </div>
    </div>
  );
}
