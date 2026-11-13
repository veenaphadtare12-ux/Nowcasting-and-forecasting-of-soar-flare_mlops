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

/** Thin ECharts wrapper: one instance per mount, resized with its container, disposed on unmount. */
export default function Chart({ option, height = 320, notMerge = true, onReady, className }: Props) {
  const el = useRef<HTMLDivElement | null>(null);
  const chart = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    if (!el.current) return;
    const c = echarts.init(el.current, "dark", { renderer: "canvas" });
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
  axisLine: { lineStyle: { color: "#2c3b52" } },
  splitLine: { lineStyle: { color: "#1e2a3d" } },
  axisLabel: { color: "#94a3b8" },
  nameTextStyle: { color: "#94a3b8" },
};
