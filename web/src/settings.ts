import { useEffect, useState } from "react";

// Kept in this browser only (localStorage); hub-side settings come with "Send to tport.stream".
export type Settings = { cols: number; gridQuality: "sub" | "main"; labels: boolean };

const KEY = "camgrid-settings";
const DEFAULTS: Settings = { cols: 2, gridQuality: "sub", labels: true };

export function loadSettings(): Settings {
  try {
    return { ...DEFAULTS, ...JSON.parse(localStorage.getItem(KEY) || "{}") };
  } catch {
    return DEFAULTS;
  }
}

export function useSettings(): [Settings, (s: Partial<Settings>) => void] {
  const [s, set] = useState(loadSettings);
  useEffect(() => localStorage.setItem(KEY, JSON.stringify(s)), [s]);
  return [s, (patch) => set((old) => ({ ...old, ...patch }))];
}
