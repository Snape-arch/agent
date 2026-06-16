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
