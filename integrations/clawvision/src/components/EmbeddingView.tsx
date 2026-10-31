import { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import type { EmbeddingPoint } from '../domain';

const colors = ['#7cf7c8', '#ffb86b', '#82aaff', '#ff7ca8', '#c9a7ff'];

export function EmbeddingView({ points }: { points: EmbeddingPoint[] }) {
  const mountRef = useRef<HTMLDivElement>(null);
  const [autoRotate, setAutoRotate] = useState(true);

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return;
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(48, mount.clientWidth / mount.clientHeight, 0.1, 100);
    camera.position.set(7, 5, 8);
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    renderer.setSize(mount.clientWidth, mount.clientHeight);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    mount.appendChild(renderer.domElement);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.autoRotateSpeed = 0.55;
    controls.autoRotate = autoRotate;

    const positions = new Float32Array(points.length * 3);
    const vertexColors = new Float32Array(points.length * 3);
    points.forEach((point, index) => {
      positions.set([point.x, point.y, point.z], index * 3);
      const color = new THREE.Color(point.correct ? colors[point.cluster] : '#ff4747');
      vertexColors.set([color.r, color.g, color.b], index * 3);
    });
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    geometry.setAttribute('color', new THREE.BufferAttribute(vertexColors, 3));
    const material = new THREE.PointsMaterial({ size: 0.13, vertexColors: true, transparent: true, opacity: 0.92, sizeAttenuation: true });
    const cloud = new THREE.Points(geometry, material);
    scene.add(cloud);
    scene.add(new THREE.GridHelper(10, 10, '#24443a', '#152620'));

    let frame = 0;
    const animate = () => {
      controls.autoRotate = autoRotate;
      controls.update();
      renderer.render(scene, camera);
      frame = requestAnimationFrame(animate);
    };
    animate();
    const resize = () => {
      camera.aspect = mount.clientWidth / mount.clientHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(mount.clientWidth, mount.clientHeight);
    };
    window.addEventListener('resize', resize);
    return () => {
      window.removeEventListener('resize', resize);
      cancelAnimationFrame(frame);
      controls.dispose();
      geometry.dispose();
      material.dispose();
      renderer.dispose();
      mount.removeChild(renderer.domElement);
    };
  }, [points, autoRotate]);

  return (
    <div className="embedding-wrap">
      <div ref={mountRef} className="embedding-canvas" />
      <button className="canvas-control" onClick={() => setAutoRotate((value) => !value)}>{autoRotate ? '暂停旋转' : '自动旋转'}</button>
      <div className="canvas-label">UMAP · 180 vectors · 拖动旋转 / 滚轮缩放</div>
    </div>
  );
}
