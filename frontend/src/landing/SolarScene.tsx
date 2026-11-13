import { useEffect, useRef } from "react";
import * as THREE from "three";
import * as S from "./shaders";

/** Mutable state the page writes every scroll frame (a ref, so scrolling never re-renders React). */
export type SceneState = { progress: number; flare: number; px: number; py: number };

type V3 = [number, number, number];
type Key = { at: number; pos: V3; look: V3; shift: number };

// Stylised (not to scale) layout: Sun at the origin, Aditya-L1 sunward of Earth on the Sun–Earth line.
const CRAFT: V3 = [3.42, 0.09, 3.57]; // lower right of the Sun in the opening shot
const EARTH: V3 = [7.67, 0.4, 8.14]; // further out on the same Sun–L1 line

// Camera path through the page (progress 0 = top, 1 = bottom). shift moves the image sideways (fraction of width).
const KEYS: Key[] = [
  { at: 0.0, pos: [4.6, 0.9, 5.6], look: [0, 0, 0], shift: 0.24 },
  { at: 0.12, pos: [3.4, 0.5, 4.2], look: [0, 0, 0], shift: 0.27 },
  { at: 0.26, pos: [2.2, 1.1, 2.9], look: [0, 0.1, 0], shift: 0.24 },
  { at: 0.36, pos: [1.75, 0.45, 2.15], look: [0, 0.15, 0], shift: 0.0 },
  { at: 0.5, pos: [1.9, 0.2, 2.35], look: [0, 0.0, 0], shift: 0.0 },
  { at: 0.64, pos: [21.7, 8.0, -12.8], look: [3.8, 0.2, 4.1], shift: 0.25 },
  { at: 0.8, pos: [-4.0, 1.4, 4.4], look: [0, 0, 0], shift: -0.2 },
  { at: 1.0, pos: [0.6, -0.9, 6.2], look: [0, 0.6, 0], shift: 0.27 },
];

const smooth = (x: number) => x * x * (3 - 2 * x);

function cameraAt(p: number): { pos: THREE.Vector3; look: THREE.Vector3; shift: number } {
  let i = 0;
  while (i < KEYS.length - 2 && p > KEYS[i + 1].at) i++;
  const a = KEYS[i];
  const b = KEYS[i + 1];
  const t = smooth(Math.min(1, Math.max(0, (p - a.at) / (b.at - a.at))));
  const lerp3 = (u: V3, v: V3) => new THREE.Vector3(u[0] + (v[0] - u[0]) * t, u[1] + (v[1] - u[1]) * t, u[2] + (v[2] - u[2]) * t);
  return { pos: lerp3(a.pos, b.pos), look: lerp3(a.look, b.look), shift: a.shift + (b.shift - a.shift) * t };
}

function loopCurve(a: THREE.Vector3, b: THREE.Vector3, height: number): THREE.CatmullRomCurve3 {
  const pts: THREE.Vector3[] = [];
  for (let k = 0; k <= 40; k++) {
    const s = k / 40;
    const dir = a.clone().lerp(b, s).normalize();
    pts.push(dir.multiplyScalar(1 + height * Math.sin(Math.PI * s)));
  }
  return new THREE.CatmullRomCurve3(pts);
}

/** Aditya-L1, simplified: gold-foil bus, one solar wing, high-gain antenna, Sun-facing payload deck (+z). */
function buildCraft(): THREE.Group {
  const g = new THREE.Group();
  const gold = new THREE.MeshStandardMaterial({ color: 0xd4a437, metalness: 0.9, roughness: 0.32, emissive: 0x2a1600 });
  const panel = new THREE.MeshStandardMaterial({ color: 0x1b2f63, metalness: 0.6, roughness: 0.25, emissive: 0x050a1c });
  const white = new THREE.MeshStandardMaterial({ color: 0xdfe3ea, metalness: 0.2, roughness: 0.5 });
  const dark = new THREE.MeshStandardMaterial({ color: 0x20242c, metalness: 0.5, roughness: 0.6 });
  const bus = new THREE.Mesh(new THREE.BoxGeometry(0.16, 0.16, 0.2), gold);
  g.add(bus);
  const deck = new THREE.Mesh(new THREE.CylinderGeometry(0.035, 0.035, 0.09, 20), white); // VELC-like telescope
  deck.rotation.x = Math.PI / 2;
  deck.position.set(0.03, 0.03, 0.14);
  g.add(deck);
  const deck2 = new THREE.Mesh(new THREE.BoxGeometry(0.05, 0.04, 0.05), dark); // X-ray spectrometers
  deck2.position.set(-0.045, -0.04, 0.12);
  g.add(deck2);
  const arm = new THREE.Mesh(new THREE.CylinderGeometry(0.006, 0.006, 0.12, 8), white);
  arm.rotation.z = Math.PI / 2;
  arm.position.set(0.14, 0, 0);
  g.add(arm);
  const wing = new THREE.Group();
  for (let k = 0; k < 2; k++) {
    const pnl = new THREE.Mesh(new THREE.BoxGeometry(0.22, 0.004, 0.15), panel);
    pnl.position.set(0.32 + k * 0.235, 0, 0);
    wing.add(pnl);
    const frame = new THREE.LineSegments(new THREE.EdgesGeometry(pnl.geometry), new THREE.LineBasicMaterial({ color: 0x8aa0c8 }));
    frame.position.copy(pnl.position);
    wing.add(frame);
  }
  g.add(wing);
  const dish = new THREE.Mesh(new THREE.SphereGeometry(0.07, 24, 12, 0, Math.PI * 2, 0, Math.PI / 3.2), white);
  dish.material.side = THREE.DoubleSide;
  dish.rotation.x = Math.PI; // faces away from the Sun, towards Earth
  dish.position.set(-0.02, 0.02, -0.15);
  g.add(dish);
  g.userData.wing = wing;
  return g;
}

export default function SolarScene({ state }: { state: React.RefObject<SceneState> }) {
  const host = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = host.current;
    if (!el) return;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: "high-performance" });
    } catch {
      el.classList.add("scene-fallback");
      return;
    }
    const dpr = Math.min(window.devicePixelRatio || 1, 1.75);
    renderer.setPixelRatio(dpr);
    renderer.setClearColor(0x03050b, 1);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    el.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(40, 1, 0.05, 400);
    const disposables: { dispose: () => void }[] = [];
    const track = <T extends { dispose: () => void }>(x: T) => (disposables.push(x), x);

    // Stars
    {
      const n = 4000;
      const pos = new Float32Array(n * 3);
      const col = new Float32Array(n * 3);
      for (let k = 0; k < n; k++) {
        const v = new THREE.Vector3().randomDirection().multiplyScalar(80 + Math.random() * 60);
        pos.set([v.x, v.y, v.z], k * 3);
        const warm = Math.random();
        col.set([0.75 + 0.25 * warm, 0.8 + 0.1 * warm, 1.0 - 0.25 * warm], k * 3);
      }
      const geo = track(new THREE.BufferGeometry());
      geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
      geo.setAttribute("color", new THREE.BufferAttribute(col, 3));
      const mat = track(new THREE.PointsMaterial({ size: 0.35, vertexColors: true, transparent: true, opacity: 0.85, depthWrite: false }));
      const stars = new THREE.Points(geo, mat);
      stars.name = "stars";
      scene.add(stars);
    }

    // The Sun (rotating group: surface, loops, active region)
    const uniforms = { uTime: { value: 0 }, uFlare: { value: 0 } };
    const sun = new THREE.Group();
    scene.add(sun);
    sun.rotation.z = 0.12; // a little axial tilt makes the rotation readable
    const surfaceGeo = track(new THREE.SphereGeometry(1, 160, 160));
    const surfaceMat = track(new THREE.ShaderMaterial({ uniforms, vertexShader: S.SUN_VERT, fragmentShader: S.SUN_FRAG }));
    sun.add(new THREE.Mesh(surfaceGeo, surfaceMat));

    const region = new THREE.Vector3(0.35, 0.42, 0.84).normalize();
    const tangent = new THREE.Vector3().crossVectors(region, new THREE.Vector3(0, 1, 0)).normalize();
    const bitangent = new THREE.Vector3().crossVectors(region, tangent).normalize();
    const loops: THREE.ShaderMaterial[] = [];
    const loopSpec: [number, number, number, number][] = [
      // offset along tangent, offset along bitangent, height, tube radius
      [0.16, 0.02, 0.22, 0.012],
      [0.12, -0.05, 0.16, 0.009],
      [0.2, 0.06, 0.3, 0.014],
      [0.09, 0.08, 0.12, 0.008],
      [0.24, -0.02, 0.38, 0.016],
    ];
    loopSpec.forEach(([dt, db, h, w], k) => {
      const a = region.clone().addScaledVector(tangent, dt).addScaledVector(bitangent, db).normalize();
      const b = region.clone().addScaledVector(tangent, -dt).addScaledVector(bitangent, -db).normalize();
      const geo = track(new THREE.TubeGeometry(loopCurve(a, b, h), 96, w, 8, false));
      const mat = track(
        new THREE.ShaderMaterial({
          uniforms: { uTime: uniforms.uTime, uFlare: uniforms.uFlare, uSeed: { value: k * 0.37 } },
          vertexShader: S.LOOP_VERT,
          fragmentShader: S.LOOP_FRAG,
          blending: THREE.AdditiveBlending,
          transparent: true,
          depthWrite: false,
        }),
      );
      loops.push(mat);
      sun.add(new THREE.Mesh(geo, mat));
    });
    // A big quiescent prominence on the other hemisphere
    {
      const c = new THREE.Vector3(-0.7, -0.2, 0.55).normalize();
      const t2 = new THREE.Vector3().crossVectors(c, new THREE.Vector3(0, 1, 0)).normalize();
      const geo = track(new THREE.TubeGeometry(loopCurve(c.clone().addScaledVector(t2, 0.35).normalize(), c.clone().addScaledVector(t2, -0.35).normalize(), 0.55), 128, 0.03, 10, false));
      const mat = track(
        new THREE.ShaderMaterial({
          uniforms: { uTime: uniforms.uTime, uFlare: { value: 0.1 }, uSeed: { value: 2.3 } },
          vertexShader: S.LOOP_VERT,
          fragmentShader: S.LOOP_FRAG,
          blending: THREE.AdditiveBlending,
          transparent: true,
          depthWrite: false,
        }),
      );
      sun.add(new THREE.Mesh(geo, mat));
    }

    // Corona (camera-facing)
    const CORONA = 7;
    const coronaMat = track(
      new THREE.ShaderMaterial({
        uniforms: { ...uniforms, uSize: { value: CORONA } },
        vertexShader: S.BILLBOARD_VERT,
        fragmentShader: S.CORONA_FRAG,
        blending: THREE.AdditiveBlending,
        transparent: true,
        depthWrite: false,
      }),
    );
    const corona = new THREE.Mesh(track(new THREE.PlaneGeometry(CORONA, CORONA)), coronaMat);
    scene.add(corona);

    // Flare flash + shock ring at the active region
    const flashU = { uFlare: { value: 0 }, uRing: { value: 0 } };
    const flash = new THREE.Mesh(
      track(new THREE.PlaneGeometry(1.6, 1.6)),
      track(new THREE.ShaderMaterial({ uniforms: flashU, vertexShader: S.BILLBOARD_VERT, fragmentShader: S.FLASH_FRAG, blending: THREE.AdditiveBlending, transparent: true, depthWrite: false })),
    );
    scene.add(flash);

    // Solar wind
    {
      const n = 2200;
      const dir = new Float32Array(n * 3);
      const seed = new Float32Array(n);
      for (let k = 0; k < n; k++) {
        const v = new THREE.Vector3().randomDirection();
        dir.set([v.x, v.y, v.z], k * 3);
        seed[k] = Math.random();
      }
      const geo = track(new THREE.BufferGeometry());
      geo.setAttribute("position", new THREE.BufferAttribute(new Float32Array(n * 3), 3));
      geo.setAttribute("aDir", new THREE.BufferAttribute(dir, 3));
      geo.setAttribute("aSeed", new THREE.BufferAttribute(seed, 1));
      const mat = track(
        new THREE.ShaderMaterial({
          uniforms: { uTime: uniforms.uTime, uPixel: { value: dpr } },
          vertexShader: S.WIND_VERT,
          fragmentShader: S.WIND_FRAG,
          blending: THREE.AdditiveBlending,
          transparent: true,
          depthWrite: false,
        }),
      );
      const wind = new THREE.Points(geo, mat);
      wind.frustumCulled = false;
      scene.add(wind);
    }

    // Lights for the spacecraft (the shader objects are self-lit)
    scene.add(new THREE.PointLight(0xffd2a0, 3.2, 0, 0));
    scene.add(new THREE.AmbientLight(0x4a5a80, 0.45));
    const fill = new THREE.DirectionalLight(0x9fb4ff, 1.4); // "earthshine" so the night side of the craft reads
    scene.add(fill);

    // Aditya-L1 and Earth (+ Moon)
    const craft = buildCraft();
    craft.position.set(...CRAFT);
    craft.scale.setScalar(0.72);
    scene.add(craft);
    const earthU = { uSunDir: { value: new THREE.Vector3() }, uTime: uniforms.uTime };
    const earth = new THREE.Mesh(track(new THREE.SphereGeometry(0.32, 64, 64)), track(new THREE.ShaderMaterial({ uniforms: earthU, vertexShader: S.SUN_VERT, fragmentShader: S.EARTH_FRAG })));
    earth.position.set(...EARTH);
    scene.add(earth);
    const moon = new THREE.Mesh(track(new THREE.SphereGeometry(0.08, 32, 32)), track(new THREE.MeshStandardMaterial({ color: 0x9a9a9a, roughness: 1 })));
    scene.add(moon);

    // Labels for the wide "Sun – L1 – Earth" shot
    const labelDefs: [string, () => THREE.Vector3][] = [
      ["Sun", () => new THREE.Vector3(0, 1.25, 0)],
      ["Aditya-L1 · L1", () => craft.position.clone().add(new THREE.Vector3(0, 0.35, 0))],
      ["Earth · 1.5 million km from L1", () => earth.position.clone().add(new THREE.Vector3(0, 0.55, 0))],
    ];
    const labels = labelDefs.map(([text]) => {
      const d = document.createElement("div");
      d.className = "scene-label";
      d.textContent = text;
      el.appendChild(d);
      return d;
    });

    // Resize
    const resize = () => {
      const w = el.clientWidth || window.innerWidth;
      const h = el.clientHeight || window.innerHeight;
      renderer.setSize(w, h, false);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    };
    resize();
    window.addEventListener("resize", resize);

    // Loop
    let lastT = performance.now();
    let raf = 0;
    let time = 0;
    let shiftNow = KEYS[0].shift;
    const camPos = new THREE.Vector3(...KEYS[0].pos);
    const camLook = new THREE.Vector3();
    const tmp = new THREE.Vector3();
    const stars = scene.getObjectByName("stars")!;

    const frame = () => {
      raf = requestAnimationFrame(frame);
      if (document.hidden) return;
      const nowT = performance.now();
      const dt = Math.min((nowT - lastT) / 1000, 0.05);
      lastT = nowT;
      time += dt * (reduced ? 0.25 : 1);
      const st = state.current ?? { progress: 0, flare: 0, px: 0, py: 0 };

      // Automatic small flares every ~11 s, plus whatever the page asks for (the X-class day section).
      const phase = time % 11;
      const auto = Math.exp(-phase * 1.1) * Math.min(1, phase / 0.15) * 0.55;
      const flare = Math.max(auto, st.flare);
      uniforms.uTime.value = time;
      uniforms.uFlare.value += (flare - uniforms.uFlare.value) * Math.min(1, dt * 8);
      loops.forEach((m) => (m.uniforms.uFlare.value = uniforms.uFlare.value));

      sun.rotation.y += dt * (reduced ? 0.01 : 0.06); // the Sun turns
      stars.rotation.y += dt * 0.004;

      // Flare flash follows the active region as it rotates
      tmp.copy(region).multiplyScalar(1.04);
      sun.localToWorld(tmp);
      flash.position.copy(tmp);
      flashU.uFlare.value = uniforms.uFlare.value;
      flashU.uRing.value = st.flare > 0.05 ? (time * 0.6) % 1 : Math.min(1, phase / 2.2);

      // Spacecraft: halo-orbit wobble, faces the Sun, wing tracks the light
      craft.position.set(CRAFT[0] + Math.sin(time * 0.31) * 0.06, CRAFT[1] + Math.sin(time * 0.47) * 0.05, CRAFT[2] + Math.cos(time * 0.31) * 0.06);
      craft.lookAt(0, 0, 0);
      craft.rotateZ(Math.sin(time * 0.2) * 0.15);
      earth.rotation.y += dt * 0.12;
      moon.position.set(EARTH[0] + Math.cos(time * 0.25) * 0.75, EARTH[1] + Math.sin(time * 0.25) * 0.12, EARTH[2] + Math.sin(time * 0.25) * 0.75);

      // Camera along the scroll path, eased, with pointer parallax
      const k = cameraAt(Math.min(1, Math.max(0, st.progress)));
      const w = renderer.domElement.width;
      const h = renderer.domElement.height;
      const portrait = w / h < 0.9;
      if (portrait) k.pos.sub(k.look).multiplyScalar(1.35).add(k.look); // phones: step back so text has room
      const ease = reduced ? 1 : Math.min(1, dt * 3.2);
      camPos.lerp(k.pos.add(new THREE.Vector3(st.px * 0.25, -st.py * 0.18, 0)), ease);
      camLook.lerp(k.look, ease);
      shiftNow += (k.shift - shiftNow) * ease;
      camera.position.copy(camPos);
      camera.lookAt(camLook);
      camera.setViewOffset(w, h, portrait ? 0 : -shiftNow * w, portrait ? -0.3 * h : 0, w, h); // portrait: a "sunrise" low in the frame
      fill.position.copy(camera.position);
      corona.quaternion.copy(camera.quaternion);
      flash.quaternion.copy(camera.quaternion);
      earthU.uSunDir.value.copy(earth.position).negate().normalize().transformDirection(camera.matrixWorldInverse);

      renderer.render(scene, camera);

      const show = Math.max(0, 1 - Math.abs(st.progress - 0.64) / 0.045);
      labels.forEach((d, k) => {
        if (show <= 0.01) {
          d.style.opacity = "0";
          return;
        }
        const v = labelDefs[k][1]().project(camera);
        d.style.opacity = String(show);
        d.style.transform = `translate(${((v.x + 1) / 2) * el.clientWidth}px, ${((1 - v.y) / 2) * el.clientHeight}px) translate(-50%, -100%)`;
      });
    };
    frame();

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", resize);
      craft.traverse((o) => {
        const m = o as THREE.Mesh;
        m.geometry?.dispose();
        const mat = m.material as THREE.Material | THREE.Material[] | undefined;
        (Array.isArray(mat) ? mat : mat ? [mat] : []).forEach((x) => x.dispose());
      });
      disposables.forEach((d) => d.dispose());
      renderer.dispose();
      renderer.domElement.remove();
      labels.forEach((d) => d.remove());
    };
  }, [state]);

  return <div ref={host} className="scene" aria-hidden="true" />;
}
