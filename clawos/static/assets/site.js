const canvas = document.getElementById("starfield");
if (canvas) {
  const ctx = canvas.getContext("2d");
  let stars = [];
  function resizeStars() {
    canvas.width = innerWidth * devicePixelRatio;
    canvas.height = innerHeight * devicePixelRatio;
    stars = Array.from({ length: 150 }, () => ({
      x: Math.random() * canvas.width,
      y: Math.random() * canvas.height,
      z: Math.random() * 1 + .2,
      r: Math.random() * 1.6 + .25
    }));
  }
  addEventListener("resize", resizeStars);
  resizeStars();
  function drawStars() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    for (const s of stars) {
      s.y += s.z * .22 * devicePixelRatio;
      if (s.y > canvas.height) s.y = 0;
      ctx.globalAlpha = .18 + s.z * .45;
      ctx.fillStyle = s.z > .8 ? "#58f0ff" : "#ffffff";
      ctx.beginPath();
      ctx.arc(s.x, s.y, s.r * devicePixelRatio, 0, Math.PI * 2);
      ctx.fill();
    }
    requestAnimationFrame(drawStars);
  }
  drawStars();
}

const layers = [...document.querySelectorAll(".layer")];
if (layers.length) {
  let mx = 0, my = 0, sy = 0;
  addEventListener("pointermove", e => {
    mx = e.clientX / innerWidth - .5;
    my = e.clientY / innerHeight - .5;
  });
  addEventListener("scroll", () => { sy = scrollY; });
  function parallax() {
    for (const el of layers) {
      const d = Number(el.dataset.depth || 0);
      const rx = -my * d * 8;
      const ry = mx * d * 12;
      el.style.transform = `translate3d(${mx * d * 100}px, ${my * d * 76 + sy * d * .13}px, ${d * 180}px) rotateX(${rx}deg) rotateY(${ry}deg)`;
    }
    requestAnimationFrame(parallax);
  }
  parallax();
}

(() => {
  const page = document.querySelector(".claw-home-v2");
  if (!page) return;

  const nav = document.getElementById("homeNav");
  const onScrollNav = () => {
    if (nav) nav.classList.toggle("scrolled", window.scrollY > 56);
  };
  addEventListener("scroll", onScrollNav, { passive: true });
  onScrollNav();

  const revealItems = document.querySelectorAll(".reveal-up,.reveal-card,.scan-card");
  const revealObserver = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (entry.isIntersecting) entry.target.classList.add("in-view");
      else entry.target.classList.remove("in-view");
    }
  }, { threshold: 0.16, rootMargin: "0px 0px -8% 0px" });
  revealItems.forEach((el, index) => {
    el.style.setProperty("--i", String(index % 8));
    revealObserver.observe(el);
  });

  const parallaxEls = [...document.querySelectorAll(".parallax-3d")];
  const tiltEls = [...document.querySelectorAll(".parallax-tilt")];
  let mouseX = 0;
  let mouseY = 0;
  addEventListener("pointermove", (event) => {
    mouseX = event.clientX / innerWidth - 0.5;
    mouseY = event.clientY / innerHeight - 0.5;
  }, { passive: true });

  function animateHomeParallax() {
    const scroll = scrollY;
    for (const el of parallaxEls) {
      const speed = Number(el.dataset.speed || 0);
      const base = el.classList.contains("hero-arm") ? "scale(1) rotateY(0deg)" : "";
      el.style.transform = `${base} translate3d(${mouseX * 30}px, ${scroll * speed + mouseY * 18}px, 0) rotateY(${mouseX * 8}deg) rotateX(${-mouseY * 5}deg)`;
    }
    for (const el of tiltEls) {
      el.style.transform = `rotateY(${mouseX * 16 - 10}deg) rotateX(${-mouseY * 10 + 3}deg)`;
    }
    requestAnimationFrame(animateHomeParallax);
  }
  animateHomeParallax();

  const particleField = document.getElementById("particleField");
  if (particleField && !particleField.childElementCount) {
    for (let i = 0; i < 42; i++) {
      const dot = document.createElement("i");
      dot.className = "particle";
      dot.style.left = `${Math.random() * 100}%`;
      dot.style.top = `${Math.random() * 100}%`;
      const size = 1 + Math.random() * 2.4;
      dot.style.width = `${size}px`;
      dot.style.height = `${size}px`;
      dot.style.transform = `translateZ(${-800 - Math.random() * 2000}px)`;
      dot.style.opacity = String(0.1 + Math.random() * 0.32);
      particleField.appendChild(dot);
    }
  }

  const depthSection = document.querySelector(".cinematic-depth-section");
  const depthCamera = document.querySelector(".depth-camera");
  const depthPlanes = [...document.querySelectorAll(".depth-plane")];
  const textPlanes = [...document.querySelectorAll(".text-plane")];
  function updateDepthScene() {
    if (!depthSection || !depthCamera) return;
    const rect = depthSection.getBoundingClientRect();
    const total = Math.max(1, rect.height + innerHeight);
    const progress = Math.min(1, Math.max(0, (innerHeight - rect.top) / total));
    const z = -500 + progress * 3500;
    const ry = -3 + progress * 8;
    const rx = progress > 0.8 ? -5 * (progress - 0.8) / 0.2 : 0;
    depthCamera.style.transform = `translateZ(${z}px) rotateY(${ry}deg) rotateX(${rx}deg)`;
    depthPlanes.forEach((plane, index) => {
      const local = Math.min(1, Math.max(0, (progress - index * 0.055) / 0.28));
      const pz = -2500 + index * 500 + local * 1500;
      plane.style.opacity = String(local * (index === depthPlanes.length - 1 ? 0.28 : 1));
      if (!plane.classList.contains("grid-floor") && !plane.classList.contains("ghost-arm")) {
        plane.style.transform = `translateZ(${pz}px)`;
      }
    });
    textPlanes.forEach((plane, index) => {
      const start = index === 0 ? 0.28 : 0.38;
      const end = index === 0 ? 0.68 : 0.74;
      const enter = Math.min(1, Math.max(0, (progress - start) / 0.16));
      const leave = Math.min(1, Math.max(0, (progress - end) / 0.12));
      const visible = Math.max(0, enter - leave);
      plane.style.opacity = String(visible);
      plane.style.transform = `translateY(${(1 - enter) * 80 - leave * 60}px) rotateX(${(1 - enter) * 35}deg) translateZ(${leave * 700}px)`;
    });
  }
  addEventListener("scroll", updateDepthScene, { passive: true });
  addEventListener("resize", updateDepthScene, { passive: true });
  updateDepthScene();

  function drawScanCard(card) {
    const img = card.querySelector("img");
    const canvas = card.querySelector("canvas");
    if (!img || !canvas) return;
    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    if (!ctx) return;
    const tint = (card.dataset.tint || "37,99,235").split(",").map(Number);
    const dpr = Math.min(devicePixelRatio || 1, 2);
    const rect = canvas.getBoundingClientRect();
    const width = Math.max(160, Math.floor(rect.width));
    const height = Math.max(190, Math.floor(rect.height));
    canvas.width = Math.floor(width * dpr);
    canvas.height = Math.floor(height * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    const offscreen = document.createElement("canvas");
    const off = offscreen.getContext("2d", { willReadFrequently: true });
    if (!off) return;
    const rows = 220;
    const cols = 120;
    offscreen.width = cols;
    offscreen.height = rows;

    const srcAspect = img.naturalWidth / img.naturalHeight;
    const dstAspect = cols / rows;
    let sx = 0, sy = 0, sw = img.naturalWidth, sh = img.naturalHeight;
    if (srcAspect > dstAspect) {
      sw = img.naturalHeight * dstAspect;
      sx = (img.naturalWidth - sw) / 2;
    } else {
      sh = img.naturalWidth / dstAspect;
      sy = (img.naturalHeight - sh) / 2;
    }
    off.drawImage(img, sx, sy, sw, sh, 0, 0, cols, rows);
    const data = off.getImageData(0, 0, cols, rows).data;
    const progress = card.classList.contains("in-view") ? 1 : 0.08;
    const lineHeight = height / rows;
    const colWidth = width / cols;
    ctx.fillStyle = "#ebebeb";
    ctx.fillRect(0, 0, width, height);
    const scanY = rows * progress;
    for (let y = 0; y < rows; y++) {
      const reveal = y < scanY ? 1 : Math.max(0, Math.min(1, (scanY + 5 - y) / 5));
      for (let x = 0; x < cols; x++) {
        const idx = (y * cols + x) * 4;
        const lum = 0.299 * data[idx] + 0.587 * data[idx + 1] + 0.114 * data[idx + 2];
        const darkness = 1 - lum / 255;
        if (darkness < 0.07) continue;
        const noise = ((x * 7 + y * 13) % 5) / 5;
        const len = reveal > 0 ? darkness * colWidth * 1.2 * reveal : (0.28 + noise * 0.4) * colWidth;
        const alpha = reveal > 0 ? (0.13 + darkness * 0.68) * reveal : 0.05;
        ctx.fillStyle = `rgba(${tint[0]},${tint[1]},${tint[2]},${alpha})`;
        ctx.fillRect(x * colWidth + (y % 2 ? colWidth * 0.3 : 0), y * lineHeight, Math.max(0.3, len), Math.max(0.4, lineHeight - 0.1));
      }
    }
    if (progress > 0.05 && progress < 0.98) {
      ctx.strokeStyle = "rgba(255,255,255,.6)";
      ctx.lineWidth = 0.8;
      ctx.beginPath();
      ctx.moveTo(0, scanY * lineHeight);
      ctx.lineTo(width, scanY * lineHeight);
      ctx.stroke();
    }
    ctx.strokeStyle = "rgba(0,0,0,.04)";
    ctx.strokeRect(0, 0, width, height);
  }

  const scanCards = [...document.querySelectorAll(".scan-card")];
  function refreshScanCards() {
    scanCards.forEach(drawScanCard);
  }
  scanCards.forEach((card) => {
    const img = card.querySelector("img");
    if (img && !img.complete) img.addEventListener("load", () => drawScanCard(card), { once: true });
  });
  addEventListener("resize", refreshScanCards, { passive: true });
  setTimeout(refreshScanCards, 120);
  setInterval(refreshScanCards, 900);
})();
