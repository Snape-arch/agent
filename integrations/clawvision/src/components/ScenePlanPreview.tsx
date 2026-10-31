import { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { OBJLoader } from 'three/examples/jsm/loaders/OBJLoader.js';
import { STLLoader } from 'three/examples/jsm/loaders/STLLoader.js';
import { createThreeBudgetMonitor } from '../visualizations/threeBudget';
import type { ScenePlan, ScenePreviewAsset, SceneVariant } from '../scenarioApi';

function disposeObject(root: THREE.Object3D) {
  const materials = new Set<THREE.Material>(), textures = new Set<THREE.Texture>(), geometries = new Set<THREE.BufferGeometry>();
  root.traverse((node) => {
    if (!(node instanceof THREE.Mesh)) return;
    geometries.add(node.geometry);
    for (const material of Array.isArray(node.material) ? node.material : [node.material]) {
      materials.add(material);
      for (const value of Object.values(material)) if (value instanceof THREE.Texture) textures.add(value);
    }
  });
  textures.forEach((value) => value.dispose()); materials.forEach((value) => value.dispose()); geometries.forEach((value) => value.dispose());
}

export default function ScenePlanPreview({ plan, asset, variant }: { plan: ScenePlan; asset: ScenePreviewAsset; variant: SceneVariant }) {
  const mount = useRef<HTMLDivElement>(null), update = useRef<(next: SceneVariant) => void>();
  const current = useRef(variant); current.current = variant;
  const [error, setError] = useState(''), [loading, setLoading] = useState(true);
  useEffect(() => {
    const element = mount.current; if (!element) return;
    setError(''); setLoading(true);
    let renderer: THREE.WebGLRenderer;
    try { renderer = new THREE.WebGLRenderer({ antialias: true }); }
    catch { setLoading(false); setError('无法建立 WebGL 预览。场景计划仍可导出。'); return; }
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2)); renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = 1;
    element.appendChild(renderer.domElement);
    const budget = createThreeBudgetMonitor(renderer, 'evaluation-scene', { assetId: asset.assetId });
    const scene = new THREE.Scene(); scene.background = new THREE.Color(plan.manifest.config.background);
    const camera = new THREE.PerspectiveCamera(46, 1, .01, 100);
    const key = new THREE.DirectionalLight('#ffffff', 1);
    scene.add(new THREE.AmbientLight('#ffffff', .7), key);
    const material = new THREE.MeshStandardMaterial({ color: plan.manifest.config.materialColor });
    const occluder = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), new THREE.MeshStandardMaterial({ color: '#343434', roughness: 1, side: THREE.DoubleSide }));
    scene.add(occluder);
    let disposed = false, root: THREE.Group | undefined;
    const position = (azimuth: number, elevation: number, distance: number) => {
      const a = THREE.MathUtils.degToRad(azimuth), e = THREE.MathUtils.degToRad(elevation);
      return new THREE.Vector3(Math.sin(a) * Math.cos(e), Math.sin(e), Math.cos(a) * Math.cos(e)).multiplyScalar(distance);
    };
    const render = (next: SceneVariant) => {
      if (disposed || !root) return;
      const p = next.parameters;
      camera.position.copy(position(p.cameraAzimuth, p.cameraElevation, p.cameraDistance)); camera.lookAt(0, 0, 0);
      key.position.copy(position(p.lightAzimuth, p.lightElevation, 5)); key.intensity = p.lightIntensity;
      material.roughness = p.roughness; material.metalness = p.metalness;
      occluder.visible = p.occluderSize > 0; occluder.scale.setScalar(p.occluderSize);
      const right = new THREE.Vector3(1, 0, 0).applyQuaternion(camera.quaternion);
      occluder.position.copy(camera.position).multiplyScalar(.5).addScaledVector(right, .35);
      occluder.quaternion.copy(camera.quaternion);
      budget.beginFrame(); renderer.render(scene, camera); budget.endFrame();
    };
    const resize = () => { if (disposed || !element.clientWidth) return; renderer.setSize(element.clientWidth, element.clientWidth); render(current.current); };
    const observer = new ResizeObserver(resize); observer.observe(element); resize(); update.current = render;
    const fail = (reason: unknown) => { if (!disposed) { setLoading(false); setError(reason instanceof Error ? reason.message : '资产解析失败'); } };
    const loaded = (object: THREE.Object3D) => {
      if (disposed) { disposeObject(object); return; }
      const bounds = new THREE.Box3().setFromObject(object), sphere = bounds.getBoundingSphere(new THREE.Sphere());
      let vertices = 0, meshes = 0;
      object.traverse((node) => { if (node instanceof THREE.Mesh) { vertices += node.geometry.getAttribute('position')?.count ?? 0; meshes++; } });
      if (!meshes || vertices > 2_000_000 || meshes > 2000 || !Number.isFinite(sphere.radius) || sphere.radius <= 0) {
        disposeObject(object); fail(new Error('资产为空、边界无效或超过预览预算（200 万顶点 / 2000 网格）')); return;
      }
      // Dispose original materials/textures; the plan explicitly overrides them.
      const oldMaterials = new Set<THREE.Material>(), oldTextures = new Set<THREE.Texture>();
      object.traverse((node) => {
        if (!(node instanceof THREE.Mesh)) return;
        if (!node.geometry.getAttribute('normal')) node.geometry.computeVertexNormals();
        for (const item of Array.isArray(node.material) ? node.material : [node.material]) {
          oldMaterials.add(item); for (const value of Object.values(item)) if (value instanceof THREE.Texture) oldTextures.add(value);
        }
        node.material = material;
      });
      oldTextures.forEach((item) => item.dispose()); oldMaterials.forEach((item) => item.dispose());
      root = new THREE.Group(); root.add(object); root.scale.setScalar(1 / sphere.radius); root.position.copy(sphere.center).multiplyScalar(-1 / sphere.radius);
      scene.add(root); setLoading(false); render(current.current);
    };
    try {
      const raw = atob(asset.base64), bytes = Uint8Array.from(raw, (char) => char.charCodeAt(0)); budget.addTransferredBytes(bytes.byteLength);
      if (asset.format === 'obj') loaded(new OBJLoader().parse(new TextDecoder().decode(bytes)));
      else if (asset.format === 'stl') loaded(new THREE.Mesh(new STLLoader().parse(bytes.buffer)));
      else {
        const manager = new THREE.LoadingManager(); manager.setURLModifier((url) => {
          if (url.startsWith('data:') || url.startsWith('blob:')) return url;
          throw new Error('预览仅接受内嵌 GLB 资源，请将外部纹理和网格打包进 GLB');
        });
        new GLTFLoader(manager).parse(bytes.buffer, '', (value) => loaded(value.scene), fail);
      }
    } catch (reason) { fail(reason); }
    return () => { disposed = true; update.current = undefined; observer.disconnect(); disposeObject(scene); material.dispose(); budget.dispose(); renderer.dispose(); renderer.forceContextLoss(); renderer.domElement.remove(); };
  }, [asset, plan]);
  useEffect(() => { update.current?.(variant); }, [variant]);
  return <div><div className="scene-plan-preview" ref={mount} aria-label="保存场景的 3D 预览" />
    {loading && <p role="status">正在解析已核验的资产…</p>}{error && <p role="alert">{error}</p>}
    <p className="evaluation-note">预览按保存参数显示静态模型。遮挡块尺寸不代表图像遮挡比例，预览未生成标注。</p></div>;
}
