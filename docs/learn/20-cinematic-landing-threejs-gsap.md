# Lesson 20: The cinematic landing page (three.js, GLSL shaders, GSAP ScrollTrigger, Lenis)

## What we built
The page at `/` (`frontend/src/landing/`) tells the project's story as one scroll:

| Section | What moves | Real data? |
|---|---|---|
| Hero | A rotating 3D Sun with a boiling surface, corona, magnetic loops, solar wind and automatic small flares. Aditya-L1 sits in front; the word "SUN" fills with plasma | `/health` status chip |
| Numbers | Pinned outline numbers count up and fill from the bottom (homage to *The Reef Line*) | facts from `docs/PRESENTATION_FACTS.md` |
| Sliding words | Two rows of giant words slide in opposite directions with the scroll | — |
| X-class day | **Scroll = time** through 24 April 2026. The SoLEXS light curve draws itself, GOES flare labels pop up, a tilting "device" shows the three models' probabilities and ALERT state, and X-ray counts rain into a jar (homage to *Rainy Day*). The 3D Sun flares as the real count rate rises | `/replay/2026-04-24?step=2` |
| Pipeline | A spine line draws itself; each step lights up with a live badge. The camera pulls back to show Sun, Aditya-L1 and Earth on one line, with labels projected from 3D | `/pipeline/status` |
| Results | Holdout2 TSS bars next to the best simple baseline; underpowered M targets hatched | `/results` |
| Tiers / finale | What works, what is hard, what is next; links into the console; "ADITYA-L1" fills as you reach the end | — |

The dashboard pages (`/latest`, `/replay`, …) are unchanged. The landing page is **lazy-loaded** (`React.lazy`),
so three.js only downloads when someone opens `/`.

## The four tools
1. **three.js** draws 3D with WebGL. We create a `Scene`, a `PerspectiveCamera` and a `WebGLRenderer`, add meshes,
   and call `renderer.render(scene, camera)` every animation frame.
2. **GLSL shaders** are tiny programs that run on the graphics card for every pixel. The Sun has no image texture:
   `SUN_FRAG` in `shaders.ts` computes its colour from **3D simplex noise** (`snoise`) and **fBm** (several noise
   layers added together). Ideas to notice:
   - *Domain warping*: `fbm(q + fbm(q))` turns smooth noise into convection-like cells.
   - *Limb darkening*: `pow(mu, 0.55)`, where `mu` is the angle between the surface and the viewer, so the edge of the disc is darker, as on the real Sun.
   - *Noise in object space*: the pattern rides with the mesh, so `sun.rotation.y += dt * 0.06` really rotates
     sunspots and active regions.
   - *Billboards*: the corona and the flare flash are flat planes that copy the camera's rotation every frame.
   - *Particles on the GPU*: the solar wind moves in the vertex shader (`WIND_VERT`), so 2,200 particles cost almost
     nothing on the CPU.
3. **GSAP + ScrollTrigger** link animation to the scroll position. `scrub: true` means "the animation's progress
   *is* the scroll progress"; `onUpdate(self.progress)` gives us a 0→1 number we use to drive anything (counters,
   SVG clip widths, card tilt, the Sun's flare level).
4. **Lenis** smooths the wheel scroll. It feeds ScrollTrigger (`lenis.on("scroll", ScrollTrigger.update)`) and runs
   on GSAP's ticker so both share one clock.

## Patterns worth copying
- **Refs, not state, for 60 fps values.** Scroll progress and flare level live in `useRef` objects. Writing React
  state 60 times a second would re-render the page.
- **Sticky instead of pinning.** Each "pinned" section is a tall section (e.g. `height: 460vh`) with a
  `position: sticky` child. ScrollTrigger only reports progress. This is robust with React and with Lenis.
- **One camera path, many sections.** `SolarScene.tsx` has keyframes (`KEYS`); `Landing.tsx` maps each section's
  scroll range to a slice of the path (`SCENE`). Moving a section never breaks the camera.
- **Screen-space framing.** `camera.setViewOffset(...)` slides the rendered image sideways, so the Sun sits right
  of the headline without moving the 3D camera. On portrait screens the Sun becomes a "sunrise" at the bottom.
- **Accessibility.** `prefers-reduced-motion` turns off smooth scrolling and card tilt and slows the Sun. Canvases
  are `aria-hidden`. The outline numbers carry an `aria-label`. Focus rings stay visible.
- **Honesty in the story.** The X-class day lies *inside* the models' fit period, and the page says so; the scores
  shown are holdout2 scores with their baselines next to them.

## Try it
```
cd frontend
npm run dev          # http://localhost:5173 (API must be on :8000, e.g. scripts\up.ps1)
```
1. Scroll slowly through the X-class day. Note the clock time when the "≥M within 60 min" badge first turns red,
   then check that time in the Replay page.
2. In `SolarScene.tsx` change `sun.rotation.y += dt * 0.06` to `0.6`. Save it: hot reload shows a fast-spinning Sun.
   Change it back.
3. Turn on "reduce motion" in Windows (Settings → Accessibility → Visual effects → Animation effects off), reload, and
   compare.

## Credits
The design takes ideas (not code) from two sites in the Claude Website Library (futurepedia.io): *The Reef Line*
(pinned stats filling their outline, sliding giant words, self-drawing lines, tiers) and *Rainy Day* (a tilting
device and things raining into a jar that counts up). Fonts: Big Shoulders Display, Newsreader, JetBrains Mono (SIL
OFL, self-hosted via Fontsource). Noise: Ashima Arts / Stefan Gustavson (MIT).
