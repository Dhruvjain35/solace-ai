import { useEffect, useRef } from 'react';

// Animated "silk" gradient — flowing domain-warped noise in Solace greens,
// rendered on a single fullscreen WebGL quad. This is the cinematic backdrop
// that mirrors cruisenow.ai's hero. Falls back to a static CSS gradient if
// WebGL is unavailable or the user prefers reduced motion.
const FRAG = `
precision highp float;
uniform vec2 u_res;
uniform float u_time;

// hash + value noise + fbm
float hash(vec2 p){ return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
float noise(vec2 p){
  vec2 i = floor(p); vec2 f = fract(p);
  vec2 u = f*f*(3.0-2.0*f);
  return mix(mix(hash(i+vec2(0.,0.)), hash(i+vec2(1.,0.)), u.x),
             mix(hash(i+vec2(0.,1.)), hash(i+vec2(1.,1.)), u.x), u.y);
}
float fbm(vec2 p){
  float v = 0.0; float a = 0.5;
  for(int i=0;i<5;i++){ v += a*noise(p); p *= 2.0; a *= 0.5; }
  return v;
}

void main(){
  vec2 uv = gl_FragCoord.xy / u_res.xy;
  vec2 p = uv * 3.0;
  float t = u_time * 0.06;

  // domain warp -> silky flowing bands
  vec2 q = vec2(fbm(p + vec2(0.0, t)), fbm(p + vec2(5.2, -t)));
  vec2 r = vec2(fbm(p + 4.0*q + vec2(1.7, 9.2) + t),
                fbm(p + 4.0*q + vec2(8.3, 2.8) - t));
  float f = fbm(p + 4.0*r);

  // green palette: deep -> emerald -> mint, with a near-black floor
  vec3 ink   = vec3(0.035, 0.058, 0.050);
  vec3 deep  = vec3(0.024, 0.231, 0.180);
  vec3 emer  = vec3(0.043, 0.420, 0.325);
  vec3 mint  = vec3(0.122, 0.749, 0.561);

  vec3 col = mix(ink, deep, smoothstep(0.0, 0.7, f));
  col = mix(col, emer, smoothstep(0.45, 0.95, f + 0.25*r.x));
  col = mix(col, mint, smoothstep(0.78, 1.05, f + 0.35*q.y));

  // gentle vignette toward the bottom so text reads
  float vig = smoothstep(1.15, 0.15, uv.y);
  col *= mix(0.82, 1.0, vig);

  gl_FragColor = vec4(col, 1.0);
}
`;

const VERT = `
attribute vec2 a_pos;
void main(){ gl_Position = vec4(a_pos, 0.0, 1.0); }
`;

export default function SilkBackground({ className = '' }: { className?: string }) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const gl = canvas.getContext('webgl', { antialias: true, alpha: false });
    if (!gl) {
      canvas.style.background =
        'linear-gradient(160deg,#063B2E 0%,#0B6B53 55%,#0A0F0D 100%)';
      return;
    }

    const compile = (type: number, src: string) => {
      const s = gl.createShader(type)!;
      gl.shaderSource(s, src);
      gl.compileShader(s);
      return s;
    };
    const prog = gl.createProgram()!;
    gl.attachShader(prog, compile(gl.VERTEX_SHADER, VERT));
    gl.attachShader(prog, compile(gl.FRAGMENT_SHADER, FRAG));
    gl.linkProgram(prog);
    gl.useProgram(prog);

    const buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(
      gl.ARRAY_BUFFER,
      new Float32Array([-1, -1, 3, -1, -1, 3]),
      gl.STATIC_DRAW
    );
    const loc = gl.getAttribLocation(prog, 'a_pos');
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);

    const uRes = gl.getUniformLocation(prog, 'u_res');
    const uTime = gl.getUniformLocation(prog, 'u_time');

    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = canvas.clientWidth * dpr;
      canvas.height = canvas.clientHeight * dpr;
      gl.viewport(0, 0, canvas.width, canvas.height);
      gl.uniform2f(uRes, canvas.width, canvas.height);
    };
    resize();
    window.addEventListener('resize', resize);

    let raf = 0;
    const start = performance.now();
    const render = (now: number) => {
      gl.uniform1f(uTime, (now - start) / 1000);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
      if (!reduce) raf = requestAnimationFrame(render);
    };
    if (reduce) {
      gl.uniform1f(uTime, 12);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
    } else {
      raf = requestAnimationFrame(render);
    }

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener('resize', resize);
    };
  }, []);

  return <canvas ref={ref} className={`h-full w-full ${className}`} aria-hidden />;
}
