import type * as THREE from "three";

/** 视口尺寸（渲染循环与 resize 共用）。 */
export interface ViewportSize {
  width: number;
  height: number;
}

/**
 * 场景上下文：后续业务模块统一从这里取 scene / camera / renderer，
 * 避免各自 new 一套渲染器。脚手架只提供最小可运行实例。
 */
export interface SceneContext {
  scene: THREE.Scene;
  camera: THREE.PerspectiveCamera;
  renderer: THREE.WebGLRenderer;
  mesh: THREE.Mesh;
  size: ViewportSize;
}
