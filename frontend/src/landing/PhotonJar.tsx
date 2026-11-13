import { useEffect, useRef } from "react";

/** X-ray "photons" rain into a jar whose level is the share of the day's counts collected so far.
 *  The rain rate follows the real SoLEXS count rate (log-scaled). Reads a ref, so it never re-renders. */
export default function PhotonJar({ state }: { state: React.RefObject<{ rate: number; fill: number }> }) {
  const canvas = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const cv = canvas.current;
    const ctx = cv?.getContext("2d");
    if (!cv || !ctx) return;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    type P = { x: number; y: number; vy: number; r: number };
    let parts: P[] = [];
    let level = 0;
    let carry = 0;
    let raf = 0;
    let last = performance.now();
    let w = 0;
    let h = 0;
    const size = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      w = cv.clientWidth;
      h = cv.clientHeight;
      cv.width = Math.round(w * dpr);
      cv.height = Math.round(h * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    size();
    const ro = new ResizeObserver(size);
    ro.observe(cv);

    const frame = (now: number) => {
      raf = requestAnimationFrame(frame);
      const dt = Math.min((now - last) / 1000, 0.05);
      last = now;
      if (document.hidden || w === 0) return;
      const st = state.current ?? { rate: 0, fill: 0 };
      const intensity = st.rate > 0 ? Math.min(1, Math.max(0, (Math.log10(st.rate) - 1) / 3.2)) : 0;
      carry += dt * (st.rate > 0 ? 6 + 140 * intensity * intensity : 0) * (reduced ? 0.2 : 1);
      while (carry >= 1) {
        carry -= 1;
        parts.push({ x: 10 + Math.random() * (w - 20), y: -6, vy: 60 + Math.random() * 90, r: 0.8 + Math.random() * 1.8 * (0.4 + intensity) });
      }
      level += (st.fill - level) * Math.min(1, dt * 4);
      const surface = h - 6 - level * (h - 26);

      ctx.clearRect(0, 0, w, h);
      // liquid light
      const g = ctx.createLinearGradient(0, surface, 0, h);
      g.addColorStop(0, "rgba(255,200,116,0.85)");
      g.addColorStop(0.25, "rgba(255,122,26,0.55)");
      g.addColorStop(1, "rgba(255,77,46,0.35)");
      ctx.fillStyle = g;
      ctx.beginPath();
      ctx.moveTo(0, h);
      for (let x = 0; x <= w; x += 6) ctx.lineTo(x, surface + Math.sin(x * 0.05 + now * 0.003) * 2.2 * (0.4 + intensity));
      ctx.lineTo(w, h);
      ctx.closePath();
      ctx.fill();

      // falling photons
      ctx.globalCompositeOperation = "lighter";
      parts = parts.filter((p) => {
        p.vy += 240 * dt;
        p.y += p.vy * dt;
        if (p.y >= surface) return false;
        const grd = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, p.r * 4);
        grd.addColorStop(0, "rgba(255,244,220,0.95)");
        grd.addColorStop(1, "rgba(255,122,26,0)");
        ctx.fillStyle = grd;
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.r * 4, 0, Math.PI * 2);
        ctx.fill();
        return true;
      });
      ctx.globalCompositeOperation = "source-over";
    };
    raf = requestAnimationFrame(frame);
    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
    };
  }, [state]);

  return <canvas ref={canvas} aria-hidden="true" />;
}
