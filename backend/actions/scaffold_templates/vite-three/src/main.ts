import * as THREE from "three";
import { clamp, lerp } from "./utils/math";
import type { SceneContext, ViewportSize } from "./types/scene";

function createContext(canvas: HTMLCanvasElement): SceneContext {
  const size: ViewportSize = {
    width: canvas.clientWidth || window.innerWidth,
    height: canvas.clientHeight || window.innerHeight,
  };

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x101820);

  const camera = new THREE.PerspectiveCamera(60, size.width / size.height, 0.1, 100);
  camera.position.set(0, 1.5, 5);
  camera.lookAt(0, 0, 0);

  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
  renderer.setPixelRatio(window.devicePixelRatio || 1);
  renderer.setSize(size.width, size.height);

  const mesh = new THREE.Mesh(
    new THREE.BoxGeometry(1, 1, 1),
    new THREE.MeshStandardMaterial({ color: 0x4f8cff }),
  );
  scene.add(mesh);
  scene.add(new THREE.AmbientLight(0xffffff, 1.4));
  scene.add(new THREE.DirectionalLight(0xffffff, 1.2));

  return { scene, camera, renderer, mesh, size };
}

function startRenderLoop(ctx: SceneContext): void {
  let elapsed = 0;
  const tick = (): void => {
    elapsed = clamp(elapsed + 0.016, 0, 10);
    ctx.mesh.rotation.x = lerp(ctx.mesh.rotation.x, elapsed * 0.2, 0.05);
    ctx.mesh.rotation.y += 0.01;
    ctx.renderer.render(ctx.scene, ctx.camera);
    requestAnimationFrame(tick);
  };
  tick();
}

function main(): void {
  const canvas = document.getElementById("app") as HTMLCanvasElement | null;
  if (!canvas) {
    throw new Error("canvas #app 不存在");
  }
  const ctx = createContext(canvas);
  startRenderLoop(ctx);

  window.addEventListener("resize", () => {
    const w = window.innerWidth;
    const h = window.innerHeight;
    ctx.camera.aspect = w / h;
    ctx.camera.updateProjectionMatrix();
    ctx.renderer.setSize(w, h);
  });
}

main();
