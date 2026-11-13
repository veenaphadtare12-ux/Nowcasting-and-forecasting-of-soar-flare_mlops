// GLSL for the landing-page solar scene. Everything is procedural (no textures): 3D simplex noise
// (Ashima Arts / Stefan Gustavson, MIT licence) drives the granulation, active regions, corona rays and loops.

export const NOISE = /* glsl */ `
vec3 mod289(vec3 x){return x-floor(x*(1.0/289.0))*289.0;}
vec4 mod289(vec4 x){return x-floor(x*(1.0/289.0))*289.0;}
vec4 permute(vec4 x){return mod289(((x*34.0)+10.0)*x);}
vec4 taylorInvSqrt(vec4 r){return 1.79284291400159-0.85373472095314*r;}
float snoise(vec3 v){
  const vec2 C=vec2(1.0/6.0,1.0/3.0);
  const vec4 D=vec4(0.0,0.5,1.0,2.0);
  vec3 i=floor(v+dot(v,C.yyy));
  vec3 x0=v-i+dot(i,C.xxx);
  vec3 g=step(x0.yzx,x0.xyz);
  vec3 l=1.0-g;
  vec3 i1=min(g.xyz,l.zxy);
  vec3 i2=max(g.xyz,l.zxy);
  vec3 x1=x0-i1+C.xxx;
  vec3 x2=x0-i2+C.yyy;
  vec3 x3=x0-D.yyy;
  i=mod289(i);
  vec4 p=permute(permute(permute(i.z+vec4(0.0,i1.z,i2.z,1.0))+i.y+vec4(0.0,i1.y,i2.y,1.0))+i.x+vec4(0.0,i1.x,i2.x,1.0));
  float n_=0.142857142857;
  vec3 ns=n_*D.wyz-D.xzx;
  vec4 j=p-49.0*floor(p*ns.z*ns.z);
  vec4 x_=floor(j*ns.z);
  vec4 y_=floor(j-7.0*x_);
  vec4 x=x_*ns.x+ns.yyyy;
  vec4 y=y_*ns.x+ns.yyyy;
  vec4 h=1.0-abs(x)-abs(y);
  vec4 b0=vec4(x.xy,y.xy);
  vec4 b1=vec4(x.zw,y.zw);
  vec4 s0=floor(b0)*2.0+1.0;
  vec4 s1=floor(b1)*2.0+1.0;
  vec4 sh=-step(h,vec4(0.0));
  vec4 a0=b0.xzyw+s0.xzyw*sh.xxyy;
  vec4 a1=b1.xzyw+s1.xzyw*sh.zzww;
  vec3 p0=vec3(a0.xy,h.x);
  vec3 p1=vec3(a0.zw,h.y);
  vec3 p2=vec3(a1.xy,h.z);
  vec3 p3=vec3(a1.zw,h.w);
  vec4 norm=taylorInvSqrt(vec4(dot(p0,p0),dot(p1,p1),dot(p2,p2),dot(p3,p3)));
  p0*=norm.x;p1*=norm.y;p2*=norm.z;p3*=norm.w;
  vec4 m=max(0.5-vec4(dot(x0,x0),dot(x1,x1),dot(x2,x2),dot(x3,x3)),0.0);
  m=m*m;
  return 105.0*dot(m*m,vec4(dot(p0,x0),dot(p1,x1),dot(p2,x2),dot(p3,x3)));
}
float fbm(vec3 p){
  float s=0.0; float a=0.5;
  for(int i=0;i<5;i++){ s+=a*snoise(p); p=p*2.02+vec3(1.7,9.2,3.1); a*=0.5; }
  return s;
}
`;

export const SUN_VERT = /* glsl */ `
varying vec3 vPos;
varying vec3 vNormal;
varying vec3 vView;
void main(){
  vPos = position;
  vNormal = normalize(normalMatrix * normal);
  vec4 mv = modelViewMatrix * vec4(position, 1.0);
  vView = -mv.xyz;
  gl_Position = projectionMatrix * mv;
}
`;

export const SUN_FRAG = /* glsl */ `
uniform float uTime;
uniform float uFlare;
varying vec3 vPos;
varying vec3 vNormal;
varying vec3 vView;
${NOISE}
void main(){
  vec3 p = normalize(vPos);
  float t = uTime;
  // Domain-warped convection cells + fine granulation that boils over time.
  vec3 q = p * 2.6 + vec3(0.0, t * 0.015, 0.0);
  float warp = fbm(q + vec3(fbm(q * 1.6 + t * 0.04)));
  float gran = snoise(p * 34.0 + vec3(t * 0.25)) * 0.5 + 0.5;
  float n = 0.7 * warp + 0.3 * (gran - 0.5);
  // Active regions (bright plage) and sunspots, fixed to the surface so they rotate with the Sun.
  float region = smoothstep(0.35, 0.75, snoise(p * 1.4 + vec3(3.1, 0.0, 1.7)));
  float spotField = snoise(p * 5.0 + vec3(7.0, 2.0, 4.0));
  float umbra = smoothstep(0.62, 0.78, spotField) * region;
  float penumbra = smoothstep(0.48, 0.62, spotField) * region;

  vec3 deep = vec3(0.42, 0.05, 0.0);
  vec3 mid = vec3(1.0, 0.40, 0.05);
  vec3 hot = vec3(1.0, 0.85, 0.52);
  vec3 col = mix(deep, mid, smoothstep(-0.45, 0.25, n));
  col = mix(col, hot, smoothstep(0.15, 0.65, n));
  col += region * vec3(1.0, 0.62, 0.25) * (0.18 + 0.9 * uFlare) * (0.6 + gran);
  col = mix(col, col * 0.45, penumbra * 0.8);
  col = mix(col, vec3(0.12, 0.02, 0.0), umbra * 0.9);

  float mu = clamp(dot(normalize(vNormal), normalize(vView)), 0.0, 1.0);
  col *= 0.30 + 0.95 * pow(mu, 0.55);              // limb darkening
  col += vec3(1.0, 0.45, 0.12) * pow(1.0 - mu, 4.0) * 0.9; // chromospheric rim
  gl_FragColor = vec4(col * (1.15 + 0.35 * uFlare), 1.0);
}
`;

export const BILLBOARD_VERT = /* glsl */ `
varying vec2 vUv;
void main(){
  vUv = uv;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`;

// Corona on a camera-facing plane through the Sun's centre (the Sun's depth hides the inner part).
export const CORONA_FRAG = /* glsl */ `
uniform float uTime;
uniform float uFlare;
uniform float uSize;
varying vec2 vUv;
${NOISE}
void main(){
  vec2 p = (vUv - 0.5) * uSize;
  float r = length(p);
  float d = r - 1.0;
  vec2 dir = p / max(r, 1e-4);
  float rays = fbm(vec3(dir * 2.2, d * 1.2 - uTime * 0.10));
  float fine = snoise(vec3(dir * 9.0, uTime * 0.06));
  float glow = exp(-d * 3.0) * (0.55 + 0.75 * rays)
             + exp(-d * 10.0) * 1.1
             + 0.22 * exp(-d * 0.9) * (0.5 + 0.5 * fine);
  glow *= smoothstep(-0.02, 0.03, d);
  glow *= smoothstep(uSize * 0.5, uSize * 0.32, r);
  vec3 col = mix(vec3(1.0, 0.38, 0.08), vec3(1.0, 0.86, 0.6), exp(-d * 5.0));
  gl_FragColor = vec4(col * glow * (0.85 + 1.4 * uFlare), 1.0);
}
`;

// Magnetic loops: plasma pulses flowing along each tube.
export const LOOP_VERT = /* glsl */ `
varying vec2 vUv;
varying vec3 vNormal;
varying vec3 vView;
void main(){
  vUv = uv;
  vNormal = normalize(normalMatrix * normal);
  vec4 mv = modelViewMatrix * vec4(position, 1.0);
  vView = -mv.xyz;
  gl_Position = projectionMatrix * mv;
}
`;

export const LOOP_FRAG = /* glsl */ `
uniform float uTime;
uniform float uFlare;
uniform float uSeed;
varying vec2 vUv;
varying vec3 vNormal;
varying vec3 vView;
void main(){
  float s = vUv.x;
  float flow = 0.5 + 0.5 * sin(s * 26.0 - uTime * (2.0 + uSeed) + uSeed * 10.0);
  float edge = 1.0 - abs(dot(normalize(vNormal), normalize(vView)));
  float ends = smoothstep(0.0, 0.08, s) * smoothstep(1.0, 0.92, s);
  float a = (0.35 + 0.65 * flow) * (0.4 + 0.8 * edge) * ends;
  vec3 col = mix(vec3(1.0, 0.35, 0.08), vec3(1.0, 0.85, 0.55), flow);
  gl_FragColor = vec4(col * a * (0.9 + 1.6 * uFlare), 1.0);
}
`;

// Solar wind: particles stream radially outwards and recycle (all motion in the vertex shader).
export const WIND_VERT = /* glsl */ `
uniform float uTime;
uniform float uPixel;
attribute vec3 aDir;
attribute float aSeed;
varying float vAlpha;
void main(){
  float speed = 0.25 + aSeed * 0.45;
  float travel = mod(uTime * speed + aSeed * 9.0, 9.0);
  vec3 pos = aDir * (1.08 + travel);
  vAlpha = smoothstep(0.0, 0.6, travel) * smoothstep(9.0, 3.0, travel);
  vec4 mv = modelViewMatrix * vec4(pos, 1.0);
  gl_PointSize = uPixel * (1.5 + aSeed * 2.5) * (6.0 / -mv.z);
  gl_Position = projectionMatrix * mv;
}
`;

export const WIND_FRAG = /* glsl */ `
varying float vAlpha;
void main(){
  vec2 c = gl_PointCoord - 0.5;
  float a = smoothstep(0.5, 0.0, length(c));
  gl_FragColor = vec4(vec3(1.0, 0.72, 0.4) * a * vAlpha * 0.9, 1.0);
}
`;

// Flare flash + expanding shock ring (camera-facing plane at the active region).
export const FLASH_FRAG = /* glsl */ `
uniform float uFlare;
uniform float uRing;
varying vec2 vUv;
void main(){
  vec2 p = (vUv - 0.5) * 2.0;
  float r = length(p);
  float core = exp(-r * r * 30.0) * uFlare * 2.2;
  float halo = exp(-r * 5.0) * uFlare * 0.6;
  float ring = smoothstep(0.06, 0.0, abs(r - uRing)) * (1.0 - uRing) * 0.9 * step(0.01, uRing);
  vec3 col = vec3(1.0, 0.9, 0.75) * core + vec3(1.0, 0.55, 0.2) * (halo + ring);
  gl_FragColor = vec4(col, 1.0);
}
`;

export const EARTH_FRAG = /* glsl */ `
uniform vec3 uSunDir;
uniform float uTime;
varying vec3 vPos;
varying vec3 vNormal;
varying vec3 vView;
${NOISE}
void main(){
  vec3 p = normalize(vPos);
  float land = smoothstep(0.05, 0.12, fbm(p * 2.2 + vec3(4.0)));
  float cloud = smoothstep(0.1, 0.6, fbm(p * 4.0 + vec3(uTime * 0.02, 0.0, 0.0)));
  vec3 col = mix(vec3(0.03, 0.14, 0.38), vec3(0.16, 0.36, 0.16), land);
  col = mix(col, vec3(0.95), cloud * 0.7);
  vec3 n = normalize(vNormal);
  float day = clamp(dot(n, normalize(uSunDir)), 0.0, 1.0);
  float rim = pow(1.0 - clamp(dot(n, normalize(vView)), 0.0, 1.0), 3.0);
  col = col * (0.04 + 1.1 * day) + vec3(0.3, 0.6, 1.0) * rim * (0.25 + day);
  gl_FragColor = vec4(col, 1.0);
}
`;
