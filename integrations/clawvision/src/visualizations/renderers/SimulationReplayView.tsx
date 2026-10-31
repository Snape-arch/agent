import { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';

export interface SimulationFrame { step: number; points: Array<[number, number, number]>; trajectory: Array<[number, number, number]>; vectors: Array<{ origin: [number, number, number]; direction: [number, number, number] }> }

export function SimulationReplayView({ frames }: { frames: SimulationFrame[] }) {
  const mountRef = useRef<HTMLDivElement>(null); const [index, setIndex] = useState(0); const [playing, setPlaying] = useState(false); const current = useRef(index); current.current = index;
  useEffect(() => { if (!playing || frames.length < 2) return; const timer = window.setInterval(() => setIndex((value) => (value + 1) % frames.length), 500); return () => clearInterval(timer); }, [playing, frames.length]);
  useEffect(() => {
    const mount = mountRef.current; if (!mount) return; const scene = new THREE.Scene(); const camera = new THREE.PerspectiveCamera(48, mount.clientWidth / mount.clientHeight, .1, 100); camera.position.set(7, 5, 8);
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true }); renderer.setPixelRatio(Math.min(devicePixelRatio, 2)); renderer.setSize(mount.clientWidth, mount.clientHeight); mount.appendChild(renderer.domElement); const controls = new OrbitControls(camera, renderer.domElement); controls.enableDamping = true; scene.add(new THREE.GridHelper(12, 12, '#24443a', '#152620'));
    const pointGeometry = new THREE.BufferGeometry(); const pointMaterial = new THREE.PointsMaterial({ color: '#7cf7c8', size: .12 }); const cloud = new THREE.Points(pointGeometry, pointMaterial); scene.add(cloud);
    const lineGeometry = new THREE.BufferGeometry(); const lineMaterial = new THREE.LineBasicMaterial({ color: '#ffb86b' }); const trajectory = new THREE.Line(lineGeometry, lineMaterial); scene.add(trajectory); const arrows = new THREE.Group(); scene.add(arrows);
    let shown = -1; let frameId = 0; const animate = () => { const frame = frames[current.current]; if (frame && shown !== current.current) { pointGeometry.setFromPoints(frame.points.map((point) => new THREE.Vector3(...point))); lineGeometry.setFromPoints(frame.trajectory.map((point) => new THREE.Vector3(...point))); arrows.clear(); frame.vectors.slice(0, 18).forEach((vector) => arrows.add(new THREE.ArrowHelper(new THREE.Vector3(...vector.direction).normalize(), new THREE.Vector3(...vector.origin), .6, '#82aaff', .16, .08))); shown = current.current; } controls.update(); renderer.render(scene, camera); frameId = requestAnimationFrame(animate); }; animate();
    const resize = () => { camera.aspect = mount.clientWidth / mount.clientHeight; camera.updateProjectionMatrix(); renderer.setSize(mount.clientWidth, mount.clientHeight); }; window.addEventListener('resize', resize);
    return () => { window.removeEventListener('resize', resize); cancelAnimationFrame(frameId); controls.dispose(); pointGeometry.dispose(); pointMaterial.dispose(); lineGeometry.dispose(); lineMaterial.dispose(); arrows.children.forEach((child) => { if (child instanceof THREE.ArrowHelper) { child.line.geometry.dispose(); child.cone.geometry.dispose(); } }); renderer.dispose(); mount.removeChild(renderer.domElement); };
  }, [frames]);
  return <div className="simulation-plugin"><div className="simulation-stage" ref={mountRef} /><div className="timeline-controls"><button onClick={() => setPlaying((value) => !value)}>{playing ? '暂停' : '播放'}</button><input aria-label="仿真时间轴" type="range" min="0" max={Math.max(0, frames.length - 1)} value={index} onChange={(event) => { setPlaying(false); setIndex(Number(event.target.value)); }} /><span>state {frames[index]?.step ?? 0}</span><b>点云 · 轨迹 · 向量场</b></div></div>;
}
