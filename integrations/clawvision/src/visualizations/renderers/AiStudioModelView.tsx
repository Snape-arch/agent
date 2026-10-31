import { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { RoundedBoxGeometry } from 'three/examples/jsm/geometries/RoundedBoxGeometry.js';
import { TransformControls } from 'three/examples/jsm/controls/TransformControls.js';
import type { StudioPlan } from '../../api';
import { createThreeBudgetMonitor } from '../threeBudget';

export interface AiStudioModelData {
  plan: StudioPlan;
  beforePlan?: StudioPlan;
  textureUrl?: string;
  onPlanChange?: (plan: StudioPlan) => void;
  highlightNames?: string[];
  transformSpace?: 'world' | 'local';
  transformSnap?: number;
}

function geometryFor(part: StudioPlan['parts'][number], curve: number) {
  const [x = 1, y = 1, z = 1] = part.size;
  switch (part.shape) {
    case 'sphere': return new THREE.SphereGeometry(x, 24, 16);
    case 'cylinder': return new THREE.CylinderGeometry(x, z || x, y, 28);
    case 'torus': return new THREE.TorusGeometry(x, Math.max(.025, y), 12, 40);
    case 'capsule': return new THREE.CapsuleGeometry(x, Math.max(.05, y - x * 2), 8, 18);
    case 'roundedBox': return new RoundedBoxGeometry(x, y, z, 5, Math.min(x, y, z) * Math.min(.24, Math.max(.01, part.bevel ?? curve * .08)));
    default: return new THREE.BoxGeometry(x, y, z);
  }
}

function materialFor(part: StudioPlan['parts'][number], texture?: THREE.Texture, ghost = false, textureStrength = .72) {
  if (ghost) return new THREE.MeshBasicMaterial({ color: '#ff8d78', wireframe: true, transparent: true, opacity: .35 });
  if (part.booleanOperation === 'subtract') return new THREE.MeshBasicMaterial({ color: '#ff5d78', wireframe: true, transparent: true, opacity: .48 });
  const material = part.material;
  const options: THREE.MeshStandardMaterialParameters = {
    color: texture ? new THREE.Color(part.color).lerp(new THREE.Color('#ffffff'), textureStrength) : part.color,
    roughness: material === 'metal' ? .28 : material === 'glass' ? .08 : .72,
    metalness: material === 'metal' ? .68 : .06,
    transparent: material === 'glass',
    opacity: material === 'glass' ? .58 : 1,
  };
  if (texture && textureStrength > .02) options.map = texture;
  return new THREE.MeshStandardMaterial(options);
}

export function AiStudioModelView({ data }: { data: AiStudioModelData }) {
  const mountRef = useRef<HTMLDivElement>(null);
  const [nodes, setNodes] = useState<string[]>([]);
  const [autoRotate, setAutoRotate] = useState(false);
  const [overlay, setOverlay] = useState(Boolean(data.beforePlan));
  const [selectedNode, setSelectedNode] = useState('');
  const [transformMode, setTransformMode] = useState<'translate' | 'rotate' | 'scale'>('translate');
  const transformRef = useRef<TransformControls>();
  const meshesRef = useRef(new Map<string, THREE.Mesh>());
  const state = useRef({ autoRotate, overlay });
  state.current = { autoRotate, overlay };

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return;
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(42, mount.clientWidth / mount.clientHeight, .1, 100);
    camera.position.set(6.2, 4.4, 7.2);
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    renderer.setSize(mount.clientWidth, mount.clientHeight);
    renderer.shadowMap.enabled = true;
    mount.appendChild(renderer.domElement);
    const budget = createThreeBudgetMonitor(renderer, 'ai-studio');
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    const transform = new TransformControls(camera, renderer.domElement); transform.setMode(transformMode); transform.setSpace(data.transformSpace ?? 'world');
    const snap = data.transformSnap && data.transformSnap > 0 ? data.transformSnap : null; transform.setTranslationSnap(snap); transform.setScaleSnap(snap); transform.setRotationSnap(snap ? THREE.MathUtils.degToRad(snap * 15) : null); transformRef.current = transform;
    const transformHelper = transform.getHelper(); scene.add(transformHelper);
    transform.addEventListener('dragging-changed', (event) => { controls.enabled = !(event as unknown as { value: boolean }).value; });
    const ambient = new THREE.HemisphereLight('#d9fff2', '#17211d', 1.25);
    const key = new THREE.DirectionalLight('#ffffff', 2.4); key.position.set(5, 8, 6); key.castShadow = true;
    const rim = new THREE.DirectionalLight('#7aa7ff', 1.1); rim.position.set(-5, 3, -4);
    scene.add(ambient, key, rim, new THREE.GridHelper(12, 12, '#31584a', '#182a24'));
    const root = new THREE.Group(); scene.add(root);
    const texture = data.textureUrl ? new THREE.TextureLoader().load(data.textureUrl) : undefined;
    if (texture) { texture.colorSpace = THREE.SRGBColorSpace; texture.wrapS = texture.wrapT = THREE.RepeatWrapping; texture.repeat.set(data.plan.parameters.textureRepeatX ?? 1, data.plan.parameters.textureRepeatY ?? 1); }
    const meshMap = new Map<string, THREE.Mesh>(); meshesRef.current = meshMap;
    const build = (plan: StudioPlan, ghost = false) => {
      const group = new THREE.Group(); group.name = plan.name;
      const scale = plan.parameters.scale || 1;
      plan.parts.forEach((part) => {
        const mesh = new THREE.Mesh(geometryFor(part, plan.parameters.curveStrength), materialFor(part, texture, ghost, plan.parameters.textureStrength ?? .72));
        mesh.name = part.name; mesh.position.fromArray(part.position); mesh.rotation.fromArray(part.rotation as [number, number, number]);
        if (!ghost && data.highlightNames?.includes(part.name) && mesh.material instanceof THREE.MeshStandardMaterial) { mesh.material.emissive.set('#f59e0b'); mesh.material.emissiveIntensity = .75; }
        mesh.castShadow = !ghost; mesh.receiveShadow = !ghost; mesh.userData.ghost = ghost; group.add(mesh); if (!ghost) meshMap.set(part.name, mesh);
      });
      if (!ghost && plan.parameters.connectionDensity > .05 && plan.parts.length > 2) {
        const visibleConnections = Math.max(1, Math.round((plan.parts.length - 1) * plan.parameters.connectionDensity));
        const positions = plan.parts.slice(0, visibleConnections + 1).map((part) => new THREE.Vector3().fromArray(part.position));
        const connector = new THREE.Line(new THREE.BufferGeometry().setFromPoints(positions), new THREE.LineBasicMaterial({ color: plan.parameters.color, transparent: true, opacity: .45 }));
        connector.name = 'Structural connections'; group.add(connector);
      }
      group.scale.setScalar(scale); root.add(group); return group;
    };
    const current = build(data.plan);
    const before = data.beforePlan ? build(data.beforePlan, true) : undefined;
    setNodes([data.plan.name, ...data.plan.parts.map((part) => part.name)].slice(0, 32));
    const box = new THREE.Box3().setFromObject(current); const center = box.getCenter(new THREE.Vector3()); const size = box.getSize(new THREE.Vector3());
    current.position.x -= center.x; current.position.z -= center.z; current.position.y -= box.min.y;
    if (before) { before.position.copy(current.position); before.visible = state.current.overlay; }
    if (selectedNode && meshMap.get(selectedNode)) transform.attach(meshMap.get(selectedNode)!);
    const persistTransform = () => {
      const object = transform.object;
      if (!(object instanceof THREE.Mesh) || !data.onPlanChange) return;
      const updated = data.plan.parts.map((part) => part.name === object.name ? { ...part,
        position: object.position.toArray(), rotation: [object.rotation.x, object.rotation.y, object.rotation.z],
        size: part.size.map((value, index) => value * object.scale.toArray()[index]),
      } : part);
      data.onPlanChange({ ...data.plan, parts: updated });
    };
    transform.addEventListener('mouseUp', persistTransform);
    const maxSize = Math.max(size.x, size.y, size.z, 1); camera.position.set(maxSize * 1.8, maxSize * 1.25, maxSize * 2.05); controls.target.set(0, size.y * .45, 0);
    let frame = 0;
    const animate = () => { budget.beginFrame(); if (state.current.autoRotate) root.rotation.y += .004; if (before) before.visible = state.current.overlay; controls.update(); renderer.render(scene, camera); budget.endFrame(); frame = requestAnimationFrame(animate); };
    animate();
    const resize = () => { if (!mount.clientWidth || !mount.clientHeight) return; camera.aspect = mount.clientWidth / mount.clientHeight; camera.updateProjectionMatrix(); renderer.setSize(mount.clientWidth, mount.clientHeight); };
    const observer = new ResizeObserver(resize); observer.observe(mount);
    return () => { cancelAnimationFrame(frame); observer.disconnect(); transform.removeEventListener('mouseUp', persistTransform); transform.detach(); transform.dispose(); controls.dispose(); root.traverse((object) => { if (object instanceof THREE.Mesh) { object.geometry.dispose(); const materials = Array.isArray(object.material) ? object.material : [object.material]; materials.forEach((item) => item.dispose()); } }); texture?.dispose(); budget.dispose(); renderer.dispose(); renderer.domElement.remove(); };
  }, [data.plan, data.beforePlan, data.textureUrl, data.onPlanChange, data.highlightNames, data.transformSpace, data.transformSnap]);

  useEffect(() => { transformRef.current?.setMode(transformMode); }, [transformMode]);
  useEffect(() => { transformRef.current?.setSpace(data.transformSpace ?? 'world'); const snap = data.transformSnap && data.transformSnap > 0 ? data.transformSnap : null; transformRef.current?.setTranslationSnap(snap); transformRef.current?.setScaleSnap(snap); transformRef.current?.setRotationSnap(snap ? THREE.MathUtils.degToRad(snap * 15) : null); }, [data.transformSpace, data.transformSnap]);
  const select = (node: string) => { setSelectedNode(node); const mesh = meshesRef.current.get(node); if (mesh) transformRef.current?.attach(mesh); };

  return <div className="ai-model-plugin">
    <div className="ai-model-stage" ref={mountRef} />
    <div className="ai-model-toolbar"><label><input type="checkbox" checked={autoRotate} onChange={(event) => setAutoRotate(event.target.checked)} /> 自动旋转</label><label><input type="checkbox" checked={overlay} disabled={!data.beforePlan} onChange={(event) => setOverlay(event.target.checked)} /> 前后叠加</label><select aria-label="Transform Gizmo 模式" value={transformMode} onChange={(event) => setTransformMode(event.target.value as typeof transformMode)}><option value="translate">移动</option><option value="rotate">旋转</option><option value="scale">缩放</option></select><span>{data.plan.parts.length} parts · {data.plan.parameters.material}</span></div>
    <div className="ai-node-tree"><strong>模型节点树</strong>{nodes.map((node, index) => <button className={selectedNode === node ? 'active' : ''} onClick={() => select(node)} key={`${node}-${index}`} style={{ paddingLeft: index ? 12 : 0 }}>{index ? '├─' : ''}{node}</button>)}</div>
  </div>;
}
