import * as echarts from "echarts";
import { useEffect, useRef } from "react";

type Props = {
  option: echarts.EChartsOption;
  height?: number | string;
  /** replace the whole option (true) or merge into the existing one (false: cheaper for live updates) */
  notMerge?: boolean;
  onReady?: (chart: echarts.ECharts) => void;
  className?: string;
};

const MUTED = "#8b98ab";
const GRID = "rgba(255,255,255,0.05)";

// One chart theme for the whole console (matches index.css).
echarts.registerTheme("console", {
  color: ["#5eead4", "#f5b544", "#8ea2ff", "#ff8a7a", "#f0627e", "#c4b5fd"],
  backgroundColor: "transparent",
  textStyle: { fontFamily: "IBM Plex Sans, system-ui, sans-serif", color: MUTED },
  legend: { textStyle: { color: "#aeb9c8", fontSize: 11 }, icon: "roundRect", itemWidth: 10, itemHeight: 4, itemGap: 16 },
  tooltip: {
    backgroundColor: "rgba(11,18,32,0.96)",
    borderColor: "rgba(255,255,255,0.08)",
    borderWidth: 1,
    padding: [8, 12],
    textStyle: { color: "#e6edf5", fontSize: 12, fontFamily: "IBM Plex Sans, sans-serif" },
    extraCssText: "border-radius:10px;box-shadow:0 12px 30px rgba(0,0,0,.45);",
  },
  axisPointer: { lineStyle: { color: "rgba(94,234,212,0.5)" }, crossStyle: { color: "rgba(94,234,212,0.5)" } },
});

/** Thin ECharts wrapper: one instance per mount, resized with its container, disposed on unmount. */
export default function Chart({ option, height = 320, notMerge = true, onReady, className }: Props) {
  const el = useRef<HTMLDivElement | null>(null);
  const chart = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    if (!el.current) return;
    const c = echarts.init(el.current, "console", { renderer: "canvas" });
    chart.current = c;
    onReady?.(c);
    const ro = new ResizeObserver(() => c.resize());
    ro.observe(el.current);
    return () => {
      ro.disconnect();
      c.dispose();
      chart.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    chart.current?.setOption({ backgroundColor: "transparent", ...option }, { notMerge, lazyUpdate: true });
  }, [option, notMerge]);

  return <div ref={el} className={className} style={{ height, width: "100%" }} />;
}

export const axisStyle = {
  axisLine: { lineStyle: { color: "rgba(255,255,255,0.1)" } },
  axisTick: { show: false },
  splitLine: { lineStyle: { color: GRID } },
  axisLabel: { color: MUTED, fontSize: 11, fontFamily: "IBM Plex Mono, monospace" },
  nameTextStyle: { color: "#5b6779", fontSize: 11, fontFamily: "IBM Plex Mono, monospace" },
};
