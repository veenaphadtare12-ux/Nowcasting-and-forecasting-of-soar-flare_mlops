import "@fontsource/big-shoulders-display/400";
import "@fontsource/big-shoulders-display/800";
import "@fontsource-variable/newsreader/wght";
import "@fontsource-variable/newsreader/wght-italic";
import "@fontsource-variable/jetbrains-mono/wght";
import "lenis/dist/lenis.css";
import "./landing.css";

import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import Lenis from "lenis";
import { type ReactNode, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import type { Health, Nullable, PipelineStatus, ReplayDay, ResultRow, Results } from "../api";
import { useApi } from "../hooks";
import PhotonJar from "./PhotonJar";
import SolarScene, { type SceneState } from "./SolarScene";

gsap.registerPlugin(ScrollTrigger);

const clamp01 = (x: number) => Math.min(1, Math.max(0, x));
const reducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/** Calls cb(progress 0..1) while the element scrolls through [start, end]. The callback may change between renders. */
function useScrollProgress(ref: React.RefObject<HTMLElement | null>, cb: (p: number) => void, deps: unknown[] = [], start = "top top", end = "bottom bottom") {
  const fn = useRef(cb);
  useLayoutEffect(() => {
    fn.current = cb;
  });
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const st = ScrollTrigger.create({ trigger: el, start, end, onUpdate: (s) => fn.current(s.progress), onRefresh: (s) => fn.current(s.progress) });
    fn.current(st.progress);
    return () => st.kill();
  }, deps); // eslint-disable-line react-hooks/exhaustive-deps
}

// Which part of the camera path each section drives (see SolarScene KEYS).
const SCENE: Record<string, [number, number]> = {
  hero: [0, 0.12],
  stats: [0.12, 0.26],
  marquee: [0.26, 0.33],
  xday: [0.33, 0.52],
  pipeline: [0.52, 0.72],
  results: [0.72, 0.84],
  tiers: [0.84, 0.93],
  finale: [0.93, 1],
};
const CHAPTERS: { id: string; label: string }[] = [
  { id: "hero", label: "Mission" },
  { id: "stats", label: "Numbers" },
  { id: "xday", label: "X-class day" },
  { id: "pipeline", label: "Pipeline" },
  { id: "results", label: "Results" },
  { id: "finale", label: "Console" },
];

function SunMark() {
  return (
    <svg viewBox="0 0 32 32" aria-hidden="true">
      <circle cx="16" cy="16" r="7.5" fill="#ff7a1a" />
      <g stroke="#ffc874" strokeWidth="2" strokeLinecap="round">
        <path d="M16 2.5v4M16 25.5v4M2.5 16h4M25.5 16h4M6.4 6.4l2.9 2.9M22.7 22.7l2.9 2.9M25.6 6.4l-2.9 2.9M9.3 22.7l-2.9 2.9" />
      </g>
    </svg>
  );
}

/* ------------------------------------------------------------------ hero */
function Hero({ health }: { health: { data: Health | null; error: string | null } }) {
  const ref = useRef<HTMLElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ctx = gsap.context(() => {
      if (!reducedMotion()) {
        gsap.from(".line > span", { yPercent: 115, duration: 1.3, ease: "expo.out", stagger: 0.09, delay: 0.15 });
        gsap.from(".lx-hero-fade", { opacity: 0, y: 24, duration: 1.1, ease: "power3.out", stagger: 0.1, delay: 0.7 });
        gsap.fromTo(".lx-fillword", { "--fill": 0 }, { "--fill": 1, duration: 2.8, ease: "power2.inOut", delay: 0.9 });
      } else {
        gsap.set(".lx-fillword", { "--fill": 1 });
      }
      gsap.to(".lx-hero-body", { yPercent: -14, opacity: 0, ease: "none", scrollTrigger: { trigger: el, start: "top top", end: "bottom top", scrub: true } });
    }, el);
    return () => ctx.revert();
  }, []);
  const ok = !!health.data;
  return (
    <section ref={ref} id="hero" data-scene="hero" className="lx-section lx-hero">
      <div className="lx-hero-body">
        <div className="lx-eyebrow lx-hero-fade">Aditya-L1 · SoLEXS + HEL1OS · MLOps</div>
        <h1 className="lx-display">
          <span className="line"><span>Watch the</span></span>
          <span className="line">
            <span>
              <span className="lx-fillword" style={{ "--fill": 0 } as React.CSSProperties}>
                <span className="lx-outline">Sun</span>
                <span className="fill" aria-hidden="true">Sun</span>
              </span>{" "}
              flare
            </span>
          </span>
        </h1>
        <p className="lx-lede lx-hero-fade">
          A machine-learning system that reads the Sun's X-rays from India's first solar observatory, 1.5 million km away, and says
          whether a flare is <em>happening now</em>, or <em>coming within the hour</em>.
        </p>
        <div className="lx-hero-cta lx-hero-fade">
          <Link to="/latest" className="lx-btn lx-btn-solid">
            Open the live console <span className="arrow">→</span>
          </Link>
          <Link to="/replay" className="lx-btn">
            Replay an X-class day <span className="arrow">→</span>
          </Link>
        </div>
        <div className="lx-status lx-hero-fade" role="status">
          <i className={ok ? "ok" : health.error ? "bad" : ""} />
          {ok
            ? `API online · ${health.data!.models_loaded.length} champion models · bundle ${health.data!.bundle_version}`
            : health.error
              ? "API offline: the story still works, live panels will show placeholders"
              : "connecting to the API…"}
        </div>
      </div>
      <div className="lx-scrollcue" aria-hidden="true">
        Scroll to fly in
        <span />
      </div>
    </section>
  );
}

/* ----------------------------------------------------------- statistics */
type StatDef = { eyebrow: string; value: number; decimals: number; unit?: string; text: ReactNode; source: string };
const STATS: StatDef[] = [
  {
    eyebrow: "01 · Vantage point",
    value: 1.5,
    decimals: 1,
    unit: "M km",
    text: "Aditya-L1 watches the Sun from Lagrange point L1, sunward of Earth: no night, no eclipses, an unbroken view.",
    source: "ISRO Aditya-L1 mission",
  },
  {
    eyebrow: "02 · Soft X-rays",
    value: 424,
    decimals: 0,
    text: "usable days of SoLEXS light curves, one sample every second, April 2025 to September 2026.",
    source: "data/processed/solexs_qc.csv",
  },
  {
    eyebrow: "03 · Every 10 seconds",
    value: 44,
    decimals: 0,
    text: "causal features: 27 from SoLEXS soft X-rays and 17 from HEL1OS hard X-rays. None of them can see the future.",
    source: "reports/dataset_summary.json · leakage tests in tests/",
  },
  {
    eyebrow: "04 · Unseen data",
    value: 0.76,
    decimals: 2,
    text: "nowcast skill (TSS) on holdout2: 11 days no model had ever seen, scored once. Simple persistence scores 0.66.",
    source: "reports/holdout2/metrics.json",
  },
];

function Stat({ d }: { d: StatDef }) {
  const ref = useRef<HTMLElement>(null);
  const inner = useRef<HTMLDivElement>(null);
  const num = useRef<HTMLDivElement>(null);
  const a = useRef<HTMLSpanElement>(null);
  const b = useRef<HTMLSpanElement>(null);
  useScrollProgress(ref, (p) => {
    const k = clamp01((p - 0.2) / 0.45);
    const e = 1 - Math.pow(1 - k, 3);
    const txt = (d.value * e).toFixed(d.decimals);
    if (a.current) a.current.textContent = txt;
    if (b.current) b.current.textContent = txt;
    num.current?.style.setProperty("--fill", String(e));
    const op = p < 0.3 ? p / 0.3 : p > 0.88 ? (1 - p) / 0.12 : 1;
    if (inner.current) {
      inner.current.style.opacity = String(clamp01(op));
      inner.current.style.transform = `translateY(${(1 - clamp01(op)) * 40}px)`;
    }
  }, [], "top 55%", "bottom bottom");
  return (
    <article ref={ref} className="lx-stat">
      <div ref={inner} className="lx-stat-inner">
        <div className="lx-eyebrow">{d.eyebrow}</div>
        <div ref={num} className="num lx-display" aria-label={`${d.value}${d.unit ? " " + d.unit : ""}`}>
          <span className="lx-outline">
            <span ref={a}>0</span>
            {d.unit && <span className="unit">{d.unit}</span>}
          </span>
          <span className="fill" aria-hidden="true">
            <span ref={b}>0</span>
            {d.unit && <span className="unit">{d.unit}</span>}
          </span>
        </div>
        <p className="lx-lede">{d.text}</p>
        <div className="lx-source">source · {d.source}</div>
      </div>
    </article>
  );
}

/* --------------------------------------------------------------- marquee */
function Marquee() {
  const ref = useRef<HTMLElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ctx = gsap.context(() => {
      const st = { trigger: el, start: "top bottom", end: "bottom top", scrub: true };
      gsap.fromTo(".r1", { xPercent: 0 }, { xPercent: -38, ease: "none", scrollTrigger: st });
      gsap.fromTo(".r2", { xPercent: -38 }, { xPercent: 0, ease: "none", scrollTrigger: st });
    }, el);
    return () => ctx.revert();
  }, []);
  const words1 = ["Soft X-rays", "·", "Hard X-rays", "·", "Neupert", "·", "SoLEXS", "·", "HEL1OS", "·", "Soft X-rays"];
  const words2 = ["Nowcast", "·", "30 min", "·", "60 min", "·", "≥C", "·", "≥M", "·", "Forecast", "·", "Nowcast"];
  return (
    <section ref={ref} data-scene="marquee" className="lx-marquee" aria-label="What the system reads and predicts">
      <div className="row r1 lx-display">
        {words1.map((w, i) => (
          <span key={i} className={i % 4 === 0 ? "solid" : i % 4 === 2 ? "lx-outline" : "hot"}>
            {w}
          </span>
        ))}
      </div>
      <div className="row r2 lx-display">
        {words2.map((w, i) => (
          <span key={i} className={i % 4 === 0 ? "lx-outline" : i % 4 === 2 ? "blue" : "hot"}>
            {w}
          </span>
        ))}
      </div>
    </section>
  );
}

/* --------------------------------------------------------- X-class day */
const XDAY = "2026-04-24";
const STEP = 2; // every 2nd 10-s row is plenty for the drawing; keeps the payload under 1 MB
const W = 1000;
const H = 400;
const LOG_LO = 1;
const LOG_HI = 4.4;
const yOf = (rate: Nullable<number>) => H - ((Math.log10(Math.max(rate ?? 10, 10)) - LOG_LO) / (LOG_HI - LOG_LO)) * (H - 10);

function bisect(a: number[], x: number) {
  let lo = 0;
  let hi = a.length - 1;
  while (lo < hi) {
    const m = (lo + hi + 1) >> 1;
    if (a[m] <= x) lo = m;
    else hi = m - 1;
  }
  return lo;
}

const PROB_ROWS = [
  { key: "now", label: "Flare now" },
  { key: "c_60m", label: "≥C within 60 min" },
  { key: "m_60m", label: "≥M within 60 min" },
];

function XDay({ scene }: { scene: React.RefObject<SceneState> }) {
  const { data, error } = useApi<ReplayDay>(`/replay/${XDAY}?step=${STEP}&targets=now,c_60m,m_60m`);
  const ref = useRef<HTMLElement>(null);
  const clip = useRef<SVGRectElement>(null);
  const cursor = useRef<SVGLineElement>(null);
  const head = useRef<HTMLDivElement>(null);
  const clock = useRef<HTMLDivElement>(null);
  const rateEl = useRef<HTMLElement>(null);
  const device = useRef<HTMLDivElement>(null);
  const bars = useRef<(HTMLDivElement | null)[]>([]);
  const marks = useRef<(HTMLDivElement | null)[]>([]);
  const counter = useRef<HTMLElement>(null);
  const jar = useRef({ rate: 0, fill: 0 });

  const prep = useMemo(() => {
    if (!data) return null;
    const t0 = Date.parse(`${XDAY}T00:00:00Z`);
    const span = 86400e3;
    const T = data.lightcurve.time.map((t) => Date.parse(t));
    const R = data.lightcurve.solexs_rate;
    const xOf = (t: number) => ((t - t0) / span) * W;
    let d = "";
    let pen = false;
    for (let i = 0; i < T.length; i++) {
      const r = R[i];
      if (r == null) {
        pen = false;
        continue;
      }
      d += `${pen ? "L" : "M"}${xOf(T[i]).toFixed(1)},${yOf(r).toFixed(1)}`;
      pen = true;
    }
    const cum: number[] = new Array(T.length);
    let s = 0;
    for (let i = 0; i < T.length; i++) {
      s += (R[i] ?? 0) * 10 * STEP; // counts/s × seconds represented by each row
      cum[i] = s;
    }
    const flares = data.goes_flares
      .filter((g) => g.goes_class && /^[MX]/.test(g.goes_class))
      .map((g) => ({ t: Date.parse(g.begin), x: xOf(Date.parse(g.begin)), cls: g.goes_class! }));
    const m60 = data.predictions.m_60m;
    const alerts: [number, number][] = [];
    if (m60) {
      let startI = -1;
      m60.alert.forEach((on, i) => {
        if (on && startI < 0) startI = i;
        if ((!on || i === m60.alert.length - 1) && startI >= 0) {
          alerts.push([xOf(Date.parse(m60.time[startI])), xOf(Date.parse(m60.time[i]))]);
          startI = -1;
        }
      });
    }
    const preds = PROB_ROWS.map(({ key }) => {
      const p = data.predictions[key];
      return p ? { T: p.time.map((t) => Date.parse(t)), p: p.p_flare, alert: p.alert, thr: p.threshold } : null;
    });
    return { t0, span, T, R, d, cum, flares, alerts, preds, total: s };
  }, [data]);

  useScrollProgress(
    ref,
    (p) => {
      const st = scene.current;
      if (!prep) return;
      const f = clamp01((p - 0.03) / 0.92);
      const tc = prep.t0 + f * prep.span;
      const i = bisect(prep.T, tc);
      const r = prep.R[i];
      clip.current?.setAttribute("width", String(f * W));
      cursor.current?.setAttribute("x1", String(f * W));
      cursor.current?.setAttribute("x2", String(f * W));
      if (head.current) {
        head.current.style.left = `${f * 100}%`;
        head.current.style.top = `${(yOf(r) / (H + 26)) * 100}%`;
      }
      const hh = String(Math.floor(f * 24)).padStart(2, "0");
      const mm = String(Math.floor((f * 1440) % 60)).padStart(2, "0");
      if (clock.current) clock.current.textContent = `${hh}:${mm}`;
      if (rateEl.current) rateEl.current.textContent = r == null ? "no data" : `${Math.round(r).toLocaleString("en-US")} counts/s`;
      prep.preds.forEach((pr, k) => {
        const el = bars.current[k];
        if (!pr || !el) return;
        const j = bisect(pr.T, tc);
        const v = pr.p[j] ?? 0;
        const on = !!pr.alert[j] && f > 0;
        (el.querySelector(".bar span") as HTMLElement).style.width = `${(v * 100).toFixed(1)}%`;
        (el.querySelector(".val") as HTMLElement).textContent = `${(v * 100).toFixed(0)}%`;
        (el.querySelector(".lx-badge") as HTMLElement).textContent = on ? "alert" : "quiet";
        el.classList.toggle("alert", on);
      });
      prep.flares.forEach((fl, k) => marks.current[k]?.classList.toggle("on", tc >= fl.t));
      if (counter.current) counter.current.textContent = Math.round(prep.cum[i] * (f > 0 ? 1 : 0)).toLocaleString("en-US");
      jar.current.rate = f > 0 && f < 1 ? (r ?? 0) : 0;
      jar.current.fill = f > 0 ? prep.cum[i] / prep.total : 0;
      if (device.current && !reducedMotion()) {
        device.current.style.transform = `rotateY(${(0.5 - f) * 34}deg) rotateX(${8 - 10 * Math.sin(Math.PI * f)}deg) translateZ(0)`;
      }
      if (st) st.flare = p <= 0 || p >= 1 || r == null ? 0 : clamp01((Math.log10(Math.max(r, 1)) - 2.3) / 1.6);
    },
    [prep],
  );

  return (
    <section ref={ref} id="xday" data-scene="xday" className="lx-section lx-xday">
      <div className="lx-xday-inner">
        <div className="lx-xday-head">
          <div>
            <div className="lx-eyebrow">24 April 2026 · real SoLEXS data · scroll = time</div>
            <h2 className="lx-display">
              The day the Sun <span style={{ color: "var(--plasma)" }}>shouted</span> twice
            </h2>
          </div>
          <div className="lx-muted" style={{ maxWidth: "36ch", fontSize: 16 }}>
            Two X-class and three M-class flares. Watch the soft X-ray count rate climb a thousandfold, and the models' alarms switch
            on as the day unfolds.
          </div>
        </div>
        <div className="lx-chart">
          {error && <div className="lx-muted" style={{ padding: 30 }}>Start the API to see the real light curve ({error}).</div>}
          {prep && (
            <div className="plot">
              <svg viewBox={`0 0 ${W} ${H + 26}`} preserveAspectRatio="none" role="img" aria-label="SoLEXS soft X-ray count rate on 24 April 2026, log scale">
                <defs>
                  <linearGradient id="lx-curve-grad" x1="0" y1="1" x2="0" y2="0">
                    <stop offset="0" stopColor="#ffc874" />
                    <stop offset="0.6" stopColor="#ff7a1a" />
                    <stop offset="1" stopColor="#ff4d2e" />
                  </linearGradient>
                  <clipPath id="lx-reveal">
                    <rect ref={clip} x="0" y="-20" width="0" height={H + 60} />
                  </clipPath>
                </defs>
                <g className="grid">
                  {[1, 2, 3, 4].map((k) => (
                    <line key={k} x1="0" x2={W} y1={yOf(10 ** k)} y2={yOf(10 ** k)} vectorEffect="non-scaling-stroke" />
                  ))}
                </g>
                <g className="alerts" clipPath="url(#lx-reveal)">
                  {prep.alerts.map(([a, b], k) => (
                    <rect key={k} x={a} width={Math.max(1, b - a)} y={H + 8} height="10" rx="2" />
                  ))}
                </g>
                <path className="curve" d={prep.d} clipPath="url(#lx-reveal)" vectorEffect="non-scaling-stroke" />
                {prep.flares.map((fl, k) => (
                  <line key={k} x1={fl.x} x2={fl.x} y1="0" y2={H} stroke="rgba(255,200,116,0.25)" strokeDasharray="3 5" vectorEffect="non-scaling-stroke" />
                ))}
                <line ref={cursor} className="cursor" x1="0" x2="0" y1="0" y2={H + 20} vectorEffect="non-scaling-stroke" />
              </svg>
              <div ref={head} aria-hidden="true" style={{ position: "absolute", width: 12, height: 12, borderRadius: 99, background: "#fff4dc", boxShadow: "0 0 18px 6px rgba(255,122,26,.8)", transform: "translate(-50%,-50%)", pointerEvents: "none" }} />
              {prep.flares.map((fl, k) => (
                <div
                  key={k}
                  ref={(el) => {
                    marks.current[k] = el;
                  }}
                  className="flare-mark"
                  style={{ position: "absolute", left: `${(fl.x / W) * 100}%`, top: 2 + (k % 2) * 34, fontFamily: "var(--display)", fontWeight: 800, fontSize: 24, color: fl.cls.startsWith("X") ? "var(--flare)" : "var(--corona)", transform: "translateX(-50%)" }}
                >
                  {fl.cls}
                </div>
              ))}
              <div className="lx-source" style={{ position: "absolute", left: 0, bottom: -18, right: 0, display: "flex", justifyContent: "space-between" }}>
                {["00", "06", "12", "18", "24 UTC"].map((h) => (
                  <span key={h}>{h}</span>
                ))}
              </div>
              <div className="lx-source" style={{ position: "absolute", right: 6, top: -2 }}>counts/s · log scale</div>
            </div>
          )}
        </div>
        <div className="lx-device-wrap">
          <div ref={device} className="lx-device">
            <div className="lx-eyebrow" style={{ fontSize: 10 }}>Flare Watch · {XDAY}</div>
            <div ref={clock} className="clock">00:00</div>
            <div className="rate">
              SoLEXS <b ref={rateEl}>–</b>
            </div>
            {PROB_ROWS.map((row, k) => {
              const thr = prep?.preds[k]?.thr;
              return (
                <div
                  key={row.key}
                  className="lx-prob"
                  ref={(el) => {
                    bars.current[k] = el;
                  }}
                >
                  <div className="lbl">
                    <span>
                      {row.label} <span className="lx-badge">quiet</span>
                    </span>
                    <span className="val">0%</span>
                  </div>
                  <div className="bar">
                    <span style={{ width: 0 }} />
                    {thr != null && <i className="thr" style={{ left: `${thr * 100}%` }} title={`alert threshold ${thr.toFixed(2)}`} />}
                  </div>
                </div>
              );
            })}
            <div className="lx-source" style={{ marginTop: 10 }}>white tick = alert threshold, fixed before testing</div>
          </div>
          <div className="lx-jar" aria-label="X-ray counts recorded by SoLEXS so far today">
            <PhotonJar state={jar} />
            <div className="count">
              <b ref={counter}>0</b>X-ray counts recorded so far (≈)
            </div>
          </div>
        </div>
        <div className="lx-xday-foot lx-source">
          Red ticks under the curve: hours when the ≥M-in-60-min model was alerting. This day lies inside the models' fit period, so it
          illustrates behaviour; it is not a test score. Source: /replay/{XDAY} (model bundle).
        </div>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------ pipeline */
function Pipeline() {
  const { data, error } = useApi<PipelineStatus>("/pipeline/status", 30000);
  const ref = useRef<HTMLElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ctx = gsap.context(() => {
      gsap.to(".spine i", { scaleY: 1, ease: "none", scrollTrigger: { trigger: ".lx-steps", start: "top 70%", end: "bottom 70%", scrub: true } });
      gsap.utils.toArray<HTMLElement>(".lx-step").forEach((s) => {
        ScrollTrigger.create({ trigger: s, start: "top 72%", onEnter: () => s.classList.add("on"), onLeaveBack: () => s.classList.remove("on") });
      });
    }, el);
    return () => ctx.revert();
  }, []);

  const off = error ? "API offline" : "checking…";
  const champions = data ? Object.keys(data.registry).length : null;
  const prefectOk = data?.prefect?.reachable;
  const steps: { tag: string; title: string; text: string; live: string; tone?: "ok" | "warn" }[] = [
    {
      tag: "01",
      title: "Photons at L1",
      text: "SoLEXS (soft X-rays, every second) and HEL1OS (hard X-rays) files arrive from ISRO's archive into an inbox. The production window starts the day after the last locked test day.",
      live: data ? `production from ${data.production.production_start} · latest scored ${data.production.latest_scored_day ?? "none yet"}` : off,
      tone: data ? (data.production.latest_scored_day ? "ok" : "warn") : undefined,
    },
    {
      tag: "02",
      title: "Data contracts",
      text: "pandera checks every raw file and every feature table. A malformed file stops the run before it can reach a model.",
      live: data ? "pandera schemas enforced in daily_ingest" : off,
      tone: data ? "ok" : undefined,
    },
    {
      tag: "03",
      title: "44 causal features",
      text: "The same feature code runs in training and in serving, and a test proves the two produce identical numbers.",
      live: data ? `${data.dvc.total} DVC stages · ${data.dvc.frozen} frozen` : off,
      tone: data ? "ok" : undefined,
    },
    {
      tag: "04",
      title: "Champion models",
      text: "Five models in the MLflow registry under the alias 'champion': one nowcast and four forecasts (≥C and ≥M, 30 and 60 minutes).",
      live: data ? `${champions} champions · MLflow ${data.mlflow.reachable ? "reachable" : "not reachable"}` : off,
      tone: data ? (data.mlflow.reachable ? "ok" : "warn") : undefined,
    },
    {
      tag: "05",
      title: "Scheduled by Prefect",
      text: "daily_ingest runs at 02:15 UTC and scores new days; check_drift runs at 03:30 UTC. A worker container executes both.",
      live: data ? (prefectOk ? `Prefect online · ${data.prefect.deployments?.length ?? 0} deployments` : "Prefect not reachable") : off,
      tone: data ? (prefectOk ? "ok" : "warn") : undefined,
    },
    {
      tag: "06",
      title: "Store, API, metrics",
      text: "Predictions land in Parquet + SQLite. FastAPI serves them (with live SSE replay); Prometheus scrapes metrics and Grafana draws the dashboards.",
      live: data ? `${data.predictions_store.days.length} days in the store · bundle ${data.bundle.version}` : off,
      tone: data ? "ok" : undefined,
    },
    {
      tag: "07",
      title: "Drift watch",
      text: "Evidently compares recent features with the training reference. Drift is expected (the solar cycle moves) and shown, not hidden.",
      live: data ? `${Math.round(data.drift.drifted_share * 100)}% of ${data.drift.features_checked} features drifted` : off,
      tone: data ? (data.drift.drift_flag ? "warn" : "ok") : undefined,
    },
    {
      tag: "08",
      title: "This website",
      text: "React + ECharts behind nginx, in the same Docker Compose stack and Kubernetes manifests as everything above.",
      live: "you are here",
      tone: "ok",
    },
  ];
  return (
    <section ref={ref} id="pipeline" data-scene="pipeline" className="lx-section lx-pipeline">
      <div className="lx-eyebrow">From photon to prediction</div>
      <h2 className="lx-h2 lx-display">
        One pipeline,
        <br />
        <span className="lx-outline">every day</span>
      </h2>
      <p className="lx-lede lx-muted" style={{ maxWidth: "52ch" }}>
        Not a notebook: a running system. The badges below are live, read from the API's <span className="lx-mono">/pipeline/status</span>.
      </p>
      <div className="lx-steps">
        <div className="spine">
          <i />
        </div>
        {steps.map((s) => (
          <div key={s.tag} className="lx-step">
            <h3>
              <small>{s.tag}</small>
              {s.title}
            </h3>
            <p>{s.text}</p>
            <span className={`lx-live ${s.tone ?? ""}`}>{s.live}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

/* ------------------------------------------------------------- results */
const H2_ORDER: [string, string][] = [
  ["now", "Nowcast"],
  ["c_30m", "≥C · 30 min"],
  ["c_60m", "≥C · 60 min"],
  ["c_120m", "≥C · 2 h"],
  ["m_30m", "≥M · 30 min"],
  ["m_60m", "≥M · 60 min"],
  ["m_120m", "≥M · 2 h"],
];
const BASE_NAME: Record<string, string> = { flux: "current flux", persistence: "persistence", rule: "1-feature rule" };

function bestBase(r: ResultRow): [string, number] | null {
  const e = Object.entries(r.baselines).filter(([k]) => k in BASE_NAME);
  if (!e.length) return null;
  const [k, v] = e.reduce((a, c) => (c[1].tss > a[1].tss ? c : a));
  return [BASE_NAME[k], v.tss];
}

function ResultsSection() {
  const { data, error } = useApi<Results>("/results");
  const ref = useRef<HTMLElement>(null);
  const [on, setOn] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const st = ScrollTrigger.create({ trigger: el.querySelector(".lx-bars") ?? el, start: "top 78%", onEnter: () => setOn(true), onLeaveBack: () => setOn(false) });
    return () => st.kill();
  }, [data]);
  const t = data?.holdout2.targets;
  return (
    <section ref={ref} id="results" data-scene="results" className="lx-section lx-results">
      <div className="lx-eyebrow">Holdout2 · {data ? `${data.holdout2.days} days, scored once, locked before any feature existed` : "loading"}</div>
      <h2 className="lx-h2 lx-display">
        Honest <span style={{ color: "var(--plasma)" }}>numbers</span>
      </h2>
      <p className="lx-lede lx-muted" style={{ maxWidth: "60ch" }}>
        The nowcast clearly beats every simple rule. The forecasts mostly learn <em>how bright the Sun is right now</em>, so a one-number
        current-flux baseline does almost as well, and we show it right next to them.
      </p>
      {error && <p className="lx-muted">Results need the API ({error}).</p>}
      {t && (
        <div className={`lx-bars ${on ? "on" : ""}`}>
          {H2_ORDER.filter(([k]) => t[k]).map(([k, label], i) => {
            const r = t[k];
            const b = bestBase(r);
            const weak = !!r.underpowered;
            return (
              <div key={k} className="lx-barrow">
                <div className="name">
                  {label}
                  {weak && <small>underpowered · {data!.holdout2.m_flares} M flares</small>}
                </div>
                <div className="lx-barpair">
                  <div className={`lx-bar model ${weak ? "weak" : ""}`}>
                    <span style={{ "--v": clamp01(r.tss), transitionDelay: `${i * 70}ms` } as React.CSSProperties} />
                    <em>model {r.tss.toFixed(2)}</em>
                  </div>
                  {b && (
                    <div className="lx-bar base">
                      <span style={{ "--v": clamp01(b[1]), transitionDelay: `${i * 70 + 120}ms` } as React.CSSProperties} />
                      <em>
                        {b[0]} {b[1].toFixed(2)}
                      </em>
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
      <div className="lx-legend">
        <span>
          <i style={{ background: "linear-gradient(90deg,#ffb347,#ff7a1a)" }} />
          champion model (TSS)
        </span>
        <span>
          <i style={{ background: "#5b6475" }} />
          best simple baseline
        </span>
        <span>
          <i style={{ background: "repeating-linear-gradient(135deg,#000 0 3px,#ff7a1a 3px 6px)" }} />
          too few M flares to trust
        </span>
        <span>TSS: 0 = no skill, 1 = perfect</span>
      </div>
      <div className="lx-source" style={{ marginTop: 12 }}>
        source · /results → reports/holdout2/metrics.json
      </div>
    </section>
  );
}

/* --------------------------------------------------------------- tiers */
function Tiers() {
  const tiers: { eyebrow: string; title: string; color: string; items: ReactNode[] }[] = [
    {
      eyebrow: "What works",
      title: "Nowcast",
      color: "#34d399",
      items: [
        <>
          Flare-in-progress detection: <b>TSS 0.76</b> on unseen holdout2 days, against <b>0.66</b> for persistence.
        </>,
        <>
          The GOES-style detector finds flare starts within a <b>median 1 minute</b> of NOAA's times.
        </>,
        <>
          <b>One command</b> rebuilds everything: 37 DVC stages, leakage tests, a model bundle with SHA-256 checks.
        </>,
      ],
    },
    {
      eyebrow: "What is hard",
      title: "Forecasting",
      color: "#ff7a1a",
      items: [
        <>
          ≥M alerts mostly mean "<b>the Sun is active</b>": they warn early but raise many false alarms.
        </>,
        <>
          HEL1OS hard X-rays overlap only <b>4.7%</b> of the training rows, so its value is hard to measure.
        </>,
        <>
          Holdout2 had only <b>7 M flares</b>; those scores carry wide uncertainty and are marked underpowered.
        </>,
      ],
    },
    {
      eyebrow: "What is next",
      title: "Early rise",
      color: "#6f9cff",
      items: [
        <>
          Three minutes after a trigger, ≥M classification reaches <b>TSS 0.64</b> versus 0.58 for flux alone: the first minutes are where Aditya-L1 adds information.
        </>,
        <>
          <b>False-alarm-capped</b> thresholds for operational use.
        </>,
        <>
          Daily production scoring from <b>13 Nov 2026</b> onwards, with drift checks every night.
        </>,
      ],
    },
  ];
  useEffect(() => {
    if (reducedMotion()) return;
    const ctx = gsap.context(() => {
      gsap.from(".lx-tier", { y: 60, opacity: 0, duration: 1, ease: "power3.out", stagger: 0.12, scrollTrigger: { trigger: ".lx-tiergrid", start: "top 80%" } });
    });
    return () => ctx.revert();
  }, []);
  return (
    <section data-scene="tiers" className="lx-section lx-tiers">
      <div className="lx-eyebrow">Read this before quoting a number</div>
      <h2 className="lx-h2 lx-display">
        Works · hard · <span className="lx-outline">next</span>
      </h2>
      <div className="lx-tiergrid">
        {tiers.map((t) => (
          <div key={t.title} className="lx-tier" style={{ "--tier": t.color } as React.CSSProperties}>
            <div className="lx-eyebrow" style={{ color: t.color }}>
              {t.eyebrow}
            </div>
            <h3>{t.title}</h3>
            <ul>
              {t.items.map((it, i) => (
                <li key={i}>{it}</li>
              ))}
            </ul>
          </div>
        ))}
      </div>
      <div className="lx-source" style={{ marginTop: 18 }}>
        sources · docs/PRESENTATION_FACTS.md sections A, B, G, H, M
      </div>
    </section>
  );
}

/* -------------------------------------------------------------- finale */
function Finale() {
  const big = useRef<HTMLDivElement>(null);
  const foot = useRef<HTMLElement>(null);
  useScrollProgress(foot, (p) => big.current?.style.setProperty("--fill", String(clamp01(p * 1.15))), [], "top bottom", "bottom bottom");
  const links: [string, string][] = [
    ["/latest", "Latest"],
    ["/replay", "Replay"],
    ["/performance", "Forecast performance"],
    ["/models", "Models & pipeline"],
    ["/data", "Data & drift"],
    ["/about", "About"],
  ];
  return (
    <section id="finale" data-scene="finale" className="lx-section lx-finale">
      <div className="lx-eyebrow">The console</div>
      <h2 className="lx-display">
        Step inside
        <br />
        the <span style={{ color: "var(--plasma)" }}>control room</span>
      </h2>
      <div className="lx-console-links">
        {links.map(([to, label], i) => (
          <Link key={to} to={to} className={`lx-btn ${i === 0 ? "lx-btn-solid" : ""}`}>
            {label} <span className="arrow">→</span>
          </Link>
        ))}
      </div>
      <footer ref={foot} className="lx-footer">
        <div className="meta">
          <span>Research and teaching system, not an operational alert service.</span>
          <span>Data · ISRO Aditya-L1 (SoLEXS, HEL1OS) · NOAA SWPC GOES flare list</span>
          <a href="https://github.com/veenaphadtare12-ux/aditya-l1-solar-flare-nowcasting-forecasting" target="_blank" rel="noreferrer">
            Source on GitHub ↗
          </a>
        </div>
        <div ref={big} className="big lx-display lx-fillword" style={{ "--fill": 0 } as React.CSSProperties}>
          <span className="lx-outline">Aditya-L1</span>
          <span className="fill" aria-hidden="true">
            Aditya-L1
          </span>
        </div>
      </footer>
    </section>
  );
}

/* ---------------------------------------------------------------- page */
export default function Landing() {
  const scene = useRef<SceneState>({ progress: 0, flare: 0, px: 0, py: 0 });
  const root = useRef<HTMLDivElement>(null);
  const railFill = useRef<HTMLDivElement>(null);
  const lenisRef = useRef<Lenis | null>(null);
  const [active, setActive] = useState("hero");
  const health = useApi<Health>("/health", 30000);

  useEffect(() => {
    document.title = "Aditya-L1 Flare Watch: watch the Sun flare";
    window.scrollTo(0, 0);
    const reduced = reducedMotion();
    let lenis: Lenis | null = null;
    const tick = (t: number) => lenis?.raf(t * 1000);
    if (!reduced) {
      lenis = new Lenis({ lerp: 0.085, wheelMultiplier: 0.9 });
      lenis.on("scroll", ScrollTrigger.update);
      gsap.ticker.add(tick);
      gsap.ticker.lagSmoothing(0);
      lenisRef.current = lenis;
    }

    let lastActive = "hero";
    const update = () => {
      const vh = window.innerHeight;
      const y = window.scrollY + vh * 0.5;
      const docH = document.documentElement.scrollHeight;
      const els = root.current ? Array.from(root.current.querySelectorAll<HTMLElement>("[data-scene]")) : [];
      for (const el of els) {
        const r = el.getBoundingClientRect();
        const top = Math.max(r.top + window.scrollY, vh * 0.5);
        const bottom = Math.min(r.bottom + window.scrollY, docH - vh * 0.5);
        if (y <= bottom || el === els[els.length - 1]) {
          const [a, b] = SCENE[el.dataset.scene!] ?? [0, 1];
          scene.current.progress = a + (b - a) * clamp01((y - top) / Math.max(1, bottom - top));
          const chapter = CHAPTERS.find((c) => c.id === el.dataset.scene) ? el.dataset.scene! : el.dataset.scene === "marquee" ? "stats" : el.dataset.scene === "tiers" ? "results" : lastActive;
          if (chapter !== lastActive) {
            lastActive = chapter;
            setActive(chapter);
          }
          break;
        }
      }
      const max = Math.max(1, docH - vh);
      if (railFill.current) railFill.current.style.transform = `scaleY(${clamp01(window.scrollY / max)})`;
    };
    const onPointer = (e: PointerEvent) => {
      scene.current.px = (e.clientX / window.innerWidth - 0.5) * 2;
      scene.current.py = (e.clientY / window.innerHeight - 0.5) * 2;
    };
    window.addEventListener("scroll", update, { passive: true });
    window.addEventListener("resize", update);
    window.addEventListener("pointermove", onPointer, { passive: true });
    update();
    const refresh = window.setTimeout(() => ScrollTrigger.refresh(), 400);
    return () => {
      window.clearTimeout(refresh);
      window.removeEventListener("scroll", update);
      window.removeEventListener("resize", update);
      window.removeEventListener("pointermove", onPointer);
      gsap.ticker.remove(tick);
      gsap.ticker.lagSmoothing(500, 33);
      lenis?.destroy();
      lenisRef.current = null;
      document.title = "Aditya-L1 Flare Watch";
    };
  }, []);

  const go = (id: string) => (e?: React.MouseEvent) => {
    e?.preventDefault();
    const el = document.getElementById(id);
    if (!el) return;
    if (lenisRef.current) lenisRef.current.scrollTo(el, { duration: 1.8 });
    else el.scrollIntoView();
  };

  return (
    <div ref={root} className="lx">
      <SolarScene state={scene} />
      <div className="lx-grain" aria-hidden="true" />
      <div className="lx-vignette" aria-hidden="true" />
      <header className="lx-nav">
        <a href="#hero" className="lx-brand" onClick={go("hero")}>
          <SunMark />
          Flare Watch
        </a>
        <nav className="lx-links" aria-label="Sections">
          <a href="#xday" onClick={go("xday")}>X-class day</a>
          <a href="#pipeline" onClick={go("pipeline")}>Pipeline</a>
          <a href="#results" onClick={go("results")}>Results</a>
        </nav>
        <Link to="/latest" className="lx-btn" style={{ padding: "9px 16px" }}>
          Console <span className="arrow">→</span>
        </Link>
      </header>
      <aside className="lx-rail" aria-label="Chapters">
        <div className="lx-rail-track">
          <div ref={railFill} className="lx-rail-fill" />
        </div>
        <ol>
          {CHAPTERS.map((c, i) => (
            <li key={c.id}>
              <button type="button" aria-current={active === c.id} onClick={() => go(c.id)()}>
                <b>{String(i + 1).padStart(2, "0")}</b>
                {c.label}
              </button>
            </li>
          ))}
        </ol>
      </aside>
      <main className="lx-content">
        <Hero health={health} />
        <section id="stats" data-scene="stats" className="lx-section" aria-label="The mission in numbers">
          {STATS.map((d) => (
            <Stat key={d.eyebrow} d={d} />
          ))}
        </section>
        <Marquee />
        <XDay scene={scene} />
        <Pipeline />
        <ResultsSection />
        <Tiers />
        <Finale />
      </main>
    </div>
  );
}
