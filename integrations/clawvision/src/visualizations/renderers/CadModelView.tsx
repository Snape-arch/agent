import { useEffect, useRef, useState } from 'react';
import { integrated, visionApiUrl } from '../../clawos';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { TransformControls } from 'three/examples/jsm/controls/TransformControls.js';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { OBJLoader } from 'three/examples/jsm/loaders/OBJLoader.js';
import { STLLoader } from 'three/examples/jsm/loaders/STLLoader.js';
import { SkeletonHelper } from 'three/src/helpers/SkeletonHelper.js';
import { createThreeBudgetMonitor } from '../threeBudget';

export interface CadModelResource { name: string; mimeType: string; base64: string }
export interface CadTransform { name: string; translation: number[]; rotation: number[]; scale: number[] }
export interface CadModelData {
  name: string; format?: 'glb' | 'gltf' | 'obj' | 'stl'; base64?: string; resources?: CadModelResource[]; version?: number;
  assetId?: string; streamUrl?: string; byteSize?: number;
  beforeBase64?: string; beforeResources?: CadModelResource[]; textureUrl?: string; editable?: boolean; selectedNodeNames?: string[];
  highlightNames?: string[]; transformSpace?: 'world' | 'local'; transformSnap?: number; onNodeSelect?: (name: string) => void; onTransform?: (change: CadTransform) => void;
}

function decode(base64: string) { const binary = atob(base64); const bytes = new Uint8Array(binary.length); for (let index = 0; index < binary.length; index++) bytes[index] = binary.charCodeAt(index); return bytes; }

export function CadModelView({ data }: { data: CadModelData }) {
  const mountRef = useRef<HTMLDivElement>(null);
  const [color, setColor] = useState('#7cf7c8');
  const [material, setMaterial] = useState<'original' | 'standard' | 'wireframe' | 'normal'>('original');
  const [light, setLight] = useState(1.4); const [overlay, setOverlay] = useState(.35); const [nodes, setNodes] = useState<string[]>(['Scene']); const [transformMode, setTransformMode] = useState<'translate' | 'rotate' | 'scale'>('translate');
  const [clips,setClips]=useState<string[]>([]); const [selectedClip,setSelectedClip]=useState(''); const [playing,setPlaying]=useState(true); const [showSkeleton,setShowSkeleton]=useState(false); const [loadProgress,setLoadProgress]=useState(0);
  const settings = useRef({ color, material, light, overlay, playing, selectedClip, showSkeleton, onNodeSelect: data.onNodeSelect, onTransform: data.onTransform }); settings.current = { color, material, light, overlay, playing, selectedClip, showSkeleton, onNodeSelect: data.onNodeSelect, onTransform: data.onTransform };

  useEffect(() => {
    const mount = mountRef.current; if (!mount) return;
    const scene = new THREE.Scene(); const camera = new THREE.PerspectiveCamera(46, mount.clientWidth / mount.clientHeight, .1, 100); camera.position.set(5, 3.5, 6);
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true }); renderer.outputColorSpace=THREE.SRGBColorSpace;renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=1.05;renderer.setPixelRatio(Math.min(devicePixelRatio, 2)); renderer.setSize(mount.clientWidth, mount.clientHeight); mount.appendChild(renderer.domElement); const budget=createThreeBudgetMonitor(renderer,'cad-model',{assetId:data.assetId});
    const controls = new OrbitControls(camera, renderer.domElement); controls.enableDamping = true; const transform = new TransformControls(camera, renderer.domElement); transform.setMode(transformMode); transform.setSpace(data.transformSpace ?? 'world'); const snap = data.transformSnap && data.transformSnap > 0 ? data.transformSnap : null; transform.setTranslationSnap(snap); transform.setScaleSnap(snap); transform.setRotationSnap(snap ? THREE.MathUtils.degToRad(snap * 15) : null); scene.add(transform.getHelper());
    transform.addEventListener('dragging-changed', (event) => { controls.enabled = !(event as unknown as { value: boolean }).value; });
    transform.addEventListener('mouseUp', () => { const object = transform.object; if (!object) return; settings.current.onTransform?.({ name: object.name, translation: object.position.toArray(), rotation: object.quaternion.toArray(), scale: object.scale.toArray() }); });
    const ambient = new THREE.AmbientLight('#b8d5ca', .7); const key = new THREE.DirectionalLight('#ffffff', light); key.position.set(4, 7, 5); scene.add(ambient, key, new THREE.GridHelper(10, 10, '#24443a', '#152620'));
    const root = new THREE.Group(); scene.add(root); let disposed = false; const editableObjects: THREE.Object3D[] = []; let mixer:THREE.AnimationMixer|undefined; let activeAction:THREE.AnimationAction|undefined; let availableAnimations:THREE.AnimationClip[]=[]; const clock=new THREE.Clock(); const skeletons:SkeletonHelper[]=[];
    const uploadedTexture = data.textureUrl ? new THREE.TextureLoader().load(data.textureUrl) : undefined;
    const applyMaterials = () => root.traverse((object) => {
      if (!(object instanceof THREE.Mesh) || object.userData.before) return;
      const selected=data.selectedNodeNames?.includes(object.name) || data.highlightNames?.includes(object.name);
      if (settings.current.material !== 'original') {
        const old = Array.isArray(object.material) ? object.material : [object.material]; old.forEach((item) => item.dispose());
        object.material = settings.current.material === 'normal' ? new THREE.MeshNormalMaterial() : new THREE.MeshStandardMaterial({ color: settings.current.color, ...(uploadedTexture ? { map: uploadedTexture } : {}), roughness: .42, metalness: .18, wireframe: settings.current.material === 'wireframe', transparent: true, opacity: .95 });
      }
      const materials=Array.isArray(object.material)?object.material:[object.material]; materials.forEach((item) => { if (item instanceof THREE.MeshStandardMaterial) { item.emissive.set(selected ? '#f59e0b' : '#000000'); item.emissiveIntensity=selected ? .65 : 0; } }); object.geometry.computeVertexNormals();
    });
    const fit = () => { root.position.set(0, 0, 0); root.scale.setScalar(1); const box = new THREE.Box3().setFromObject(root); const size = box.getSize(new THREE.Vector3()).length() || 1; const center = box.getCenter(new THREE.Vector3()); root.position.set(-center.x, -box.min.y, -center.z); root.scale.setScalar(3.8 / size); };
    const addObject = (object: THREE.Object3D, before = false, animations:THREE.AnimationClip[] = []) => {
      const names: string[]=[]; let fallback=0; object.traverse((child) => { if (!child.name) child.name=`${child.type} ${fallback++}`; if (before && child instanceof THREE.Mesh) { child.userData.before = true; child.material = new THREE.MeshBasicMaterial({ color: '#ff9b85', wireframe: true, transparent: true, opacity: settings.current.overlay }); } else if (!before) { names.push(child.name); if (child instanceof THREE.Mesh) {editableObjects.push(child);const materials=Array.isArray(child.material)?child.material:[child.material];materials.forEach((item)=>{if(item instanceof THREE.MeshStandardMaterial){for(const map of [item.map,item.normalMap,item.roughnessMap,item.metalnessMap,item.aoMap,item.emissiveMap])if(map){map.anisotropy=renderer.capabilities.getMaxAnisotropy();map.needsUpdate=true;}}});} } });
      if(!before&&animations.length){availableAnimations=animations;mixer=new THREE.AnimationMixer(object);setClips(animations.map((clip,index)=>clip.name||`Animation ${index+1}`));const clip=animations[0];setSelectedClip(clip.name||'Animation 1');activeAction=mixer.clipAction(clip);activeAction.play();}
      if(!before)object.traverse((child)=>{if(child instanceof THREE.SkinnedMesh){const helper=new SkeletonHelper(child);helper.visible=settings.current.showSkeleton;skeletons.push(helper);scene.add(helper);}});
      root.add(object); if (!before) setNodes(names.slice(0,64)); applyMaterials(); fit(); const selected=data.selectedNodeNames?.[0]; if (data.editable && selected) { const target=editableObjects.find((item)=>item.name===selected || item.parent?.name===selected); if (target) transform.attach(target); }
    };
    const load = (source?: string | Uint8Array, format?: string, before = false, resources: CadModelResource[] = []) => {
      if (!source || !format) return;
      const bytes = typeof source === 'string' ? decode(source) : source;
      const arrayBuffer=bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength) as ArrayBuffer;
      try {
        if (format === 'obj') return addObject(new OBJLoader().parse(new TextDecoder().decode(bytes)), before);
        if (format === 'stl') return addObject(new THREE.Mesh(new STLLoader().parse(arrayBuffer)), before);
        const manager = new THREE.LoadingManager(); const urls = new Map(resources.map((resource) => [resource.name.replaceAll('\\', '/').split('/').pop()!, `data:${resource.mimeType};base64,${resource.base64}`])); manager.setURLModifier((url) => urls.get(decodeURIComponent(url).replaceAll('\\', '/').split('/').pop()!) ?? url);
        new GLTFLoader(manager).parse(format === 'gltf' ? new TextDecoder().decode(bytes) : arrayBuffer, '', (gltf) => !disposed && addObject(gltf.scene, before, gltf.animations), (error) => console.error('CAD model parse failed', error));
      } catch (error) { console.error('CAD model parse failed', error); }
    };
    const loadStream = async(url:string,format:string) => { try { const token=integrated()?null:sessionStorage.getItem('clawvision.api-token');const response=await fetch(visionApiUrl(url),{headers:token?{Authorization:`Bearer ${token}`}:{}});if(!response.ok||!response.body)throw new Error(`asset stream failed: ${response.status}`);const reader=response.body.getReader();const chunks:Uint8Array[]=[];let received=0;const total=Number(response.headers.get('Content-Length')||data.byteSize||0);while(true){const {value,done}=await reader.read();if(done)break;if(value){chunks.push(value);received+=value.byteLength;budget.addTransferredBytes(value.byteLength);setLoadProgress(total?Math.round(received/total*100):0);}}const bytes=new Uint8Array(received);let offset=0;chunks.forEach((chunk)=>{bytes.set(chunk,offset);offset+=chunk.length;});if(!disposed)load(bytes,format);setLoadProgress(100);}catch(error){console.error('CAD asset streaming failed',error);} };
    const addProceduralFallback = () => {
      const assembly = new THREE.Group(); assembly.name = 'Parametric Assembly';
      const bodyMaterial = new THREE.MeshStandardMaterial({ color: '#64e7bc', roughness: .3, metalness: .45 });
      const accentMaterial = new THREE.MeshStandardMaterial({ color: '#163d34', roughness: .5, metalness: .2 });
      const body = new THREE.Mesh(new THREE.BoxGeometry(2.6, .65, 1.45), bodyMaterial); body.name = 'Main Body'; body.position.y = .65;
      const deck = new THREE.Mesh(new THREE.BoxGeometry(1.65, .35, 1.05), accentMaterial); deck.name = 'Upper Deck'; deck.position.y = 1.15;
      assembly.add(body, deck);
      for (const side of [-1, 1]) {
        const mount = new THREE.Mesh(new THREE.CylinderGeometry(.28, .28, .55, 32), bodyMaterial.clone()); mount.name = `Mount ${side < 0 ? 'Left' : 'Right'}`; mount.rotation.z = Math.PI / 2; mount.position.set(side * 1.55, .65, 0); assembly.add(mount);
      }
      addObject(assembly);
    };
    const raycaster=new THREE.Raycaster(); const pointer=new THREE.Vector2(); const selectAt=(event:PointerEvent)=>{ if(!data.editable || transform.dragging) return; const rect=renderer.domElement.getBoundingClientRect(); pointer.set((event.clientX-rect.left)/rect.width*2-1,-((event.clientY-rect.top)/rect.height)*2+1); raycaster.setFromCamera(pointer,camera); const hit=raycaster.intersectObjects(editableObjects,false)[0]?.object; if(hit){transform.attach(hit);settings.current.onNodeSelect?.(hit.name);} }; renderer.domElement.addEventListener('pointerdown',selectAt);
    if (data.streamUrl && data.format) void loadStream(data.streamUrl,data.format); else if (data.base64 && data.format) load(data.base64, data.format, false, data.resources); else addProceduralFallback();
    if (data.beforeBase64) load(data.beforeBase64, data.format, true, data.beforeResources);
    let materialKey = `${settings.current.color}:${settings.current.material}`; let clipKey=''; let frame = 0; const animate = () => { budget.beginFrame(); const nextMaterialKey = `${settings.current.color}:${settings.current.material}`; if (nextMaterialKey !== materialKey) { materialKey = nextMaterialKey; applyMaterials(); } if(mixer){const wanted=settings.current.selectedClip;if(wanted&&wanted!==clipKey){activeAction?.stop();const clip=availableAnimations.find((item,index)=>(item.name||`Animation ${index+1}`)===wanted);if(clip){activeAction=mixer.clipAction(clip);activeAction.play();clipKey=wanted;}}mixer.timeScale=settings.current.playing?1:0;mixer.update(clock.getDelta());}skeletons.forEach((helper)=>{helper.visible=settings.current.showSkeleton;helper.update();}); key.intensity = settings.current.light; root.traverse((object) => { if (object instanceof THREE.Mesh && object.userData.before && object.material instanceof THREE.MeshBasicMaterial) object.material.opacity = settings.current.overlay; }); controls.update(); renderer.render(scene, camera); budget.endFrame(); frame = requestAnimationFrame(animate); }; animate();
    const resize = () => { if(!mount.clientWidth||!mount.clientHeight)return; camera.aspect = mount.clientWidth / mount.clientHeight; camera.updateProjectionMatrix(); renderer.setSize(mount.clientWidth, mount.clientHeight); }; const observer=new ResizeObserver(resize);observer.observe(mount);
    return () => { disposed = true; observer.disconnect(); cancelAnimationFrame(frame); renderer.domElement.removeEventListener('pointerdown',selectAt); transform.detach();transform.dispose();controls.dispose();mixer?.stopAllAction();skeletons.forEach((helper)=>{scene.remove(helper);helper.dispose();}); root.traverse((object) => { if (object instanceof THREE.Mesh) { object.geometry.dispose(); const mats = Array.isArray(object.material) ? object.material : [object.material]; mats.forEach((item) => item.dispose()); } }); uploadedTexture?.dispose(); budget.dispose(); renderer.dispose(); renderer.domElement.remove(); };
  }, [data.assetId,data.streamUrl,data.byteSize,data.base64, data.beforeBase64, data.format, data.resources, data.beforeResources, data.textureUrl, data.editable, data.selectedNodeNames, data.highlightNames, data.transformSpace, data.transformSnap, transformMode]);

  return <div className="cad-plugin"><div className="cad-stage" ref={mountRef}>{loadProgress>0&&loadProgress<100&&<div className="worker-progress"><span style={{width:`${loadProgress}%`}}/><b>Streaming asset · {loadProgress}%</b></div>}</div><div className="cad-controls"><label>显示<select value={material} onChange={(event) => setMaterial(event.target.value as typeof material)}><option value="original">Original PBR</option><option value="standard">Override</option><option value="wireframe">Wireframe</option><option value="normal">Normal</option></select></label>{material==='standard'&&<label>颜色<input type="color" value={color} onChange={(event) => setColor(event.target.value)} /></label>}<label>灯光<input type="range" min="0" max="3" step="0.1" value={light} onChange={(event) => setLight(Number(event.target.value))} /></label><label>叠加<input type="range" min="0" max="1" step="0.05" value={overlay} onChange={(event) => setOverlay(Number(event.target.value))} /></label>{clips.length>0&&<><button onClick={()=>setPlaying((value)=>!value)}>{playing?'暂停动画':'播放动画'}</button><select aria-label="动画片段" value={selectedClip} onChange={(event)=>setSelectedClip(event.target.value)}>{clips.map((clip)=><option key={clip}>{clip}</option>)}</select><label><input type="checkbox" checked={showSkeleton} onChange={(event)=>setShowSkeleton(event.target.checked)}/>骨骼</label></>}{data.editable&&<select aria-label="语义网格 Transform 模式" value={transformMode} onChange={(event)=>setTransformMode(event.target.value as typeof transformMode)}><option value="translate">移动</option><option value="rotate">旋转</option><option value="scale">缩放</option></select>}</div><div className="model-tree"><strong>模型节点树 · v{data.version ?? 1}</strong>{nodes.map((node, index) => <button className={data.selectedNodeNames?.includes(node)?'active':''} onClick={()=>data.onNodeSelect?.(node)} key={`${node}-${index}`} style={{ paddingLeft: `${Math.min(index, 4) * 6}px` }}>└ {node}</button>)}</div></div>;
}
