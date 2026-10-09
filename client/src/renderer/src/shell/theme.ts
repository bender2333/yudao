// 主题：浅色、深色、跟随系统三档（工单 #377）。选择记在 localStorage，
// 跟随系统时不写 data-theme，由样式里的 light-dark 按系统配色走；
// 手动选择时写 html[data-theme]，刷新以后保持。

import { useCallback, useEffect, useState } from "react";

export type ThemeChoice = "system" | "light" | "dark";

const KEY = "yudao.theme";

function readStored(): ThemeChoice {
  try {
    const raw = window.localStorage.getItem(KEY);
    if (raw === "light" || raw === "dark" || raw === "system") {
      return raw;
    }
  } catch {
    // 浏览器不让读写时回落到跟随系统
  }
  return "system";
}

function applyTheme(theme: ThemeChoice): void {
  const html = document.documentElement;
  if (theme === "system") {
    delete html.dataset.theme;
  } else {
    html.dataset.theme = theme;
  }
}

export function useTheme(): { theme: ThemeChoice; setTheme: (theme: ThemeChoice) => void } {
  const [theme, setThemeState] = useState<ThemeChoice>(() => {
    const stored = readStored();
    applyTheme(stored);
    return stored;
  });
  useEffect(() => {
    applyTheme(theme);
  }, [theme]);
  const setTheme = useCallback((next: ThemeChoice) => {
    setThemeState(next);
    try {
      window.localStorage.setItem(KEY, next);
    } catch {
      // 浏览器不让写时只在当前会话生效
    }
    applyTheme(next);
  }, []);
  return { theme, setTheme };
}
