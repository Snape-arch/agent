/* Perspective-projected WebGL sphere impostors. No CDN, no idle animation loop. */
"use strict";
window.AcademyGraph3D = class {
  constructor(host, nodes, select, fallback) {
    this.host=host; this.nodes=nodes; this.select=select; this.yaw=-.18; this.pitch=.22; this.zoom=1; this.selected=""; this.visible=new Set(nodes.map(n=>n.id)); this.disposed=false;
    this.canvas=document.createElement("canvas"); this.canvas.setAttribute("aria-label","三维知识依赖图；拖动旋转，滚轮缩放，也可使用节点按钮和列表视图"); host.prepend(this.canvas);
    this.labels=document.createElement("div");this.labels.className="graph-labels";host.append(this.labels);
    this.gl=this.canvas.getContext("webgl",{alpha:true,antialias:true});
    if(!this.gl){this.dispose();fallback();return;}
    const depth={}; const byId=Object.fromEntries(nodes.map(n=>[n.id,n]));
    const level=id=>depth[id]??(depth[id]=byId[id].prerequisites.length?1+Math.max(...byId[id].prerequisites.map(level)):0);
    const groups={}; nodes.forEach(n=>{let l=level(n.id);(groups[l]??=[]).push(n);});
    this.points=nodes.map((n,i)=>{let l=level(n.id), siblings=groups[l], j=siblings.indexOf(n); return {node:n,xyz:[(l-2)*.82,(j-(siblings.length-1)/2)*1.0+Math.sin(l*1.3)*.3,Math.sin(i*2.2)*.7]};});
    this.buttons=this.points.map(p=>{let b=document.createElement("button"); b.className="graph-label"; b.textContent=p.node.title; b.setAttribute("aria-label",p.node.title+"，查看先修关系和学习内容");b.onclick=()=>select(p.node.id);this.labels.append(b);return b;});
    const gl=this.gl;
    const shader=(type,source)=>{const s=gl.createShader(type);gl.shaderSource(s,source);gl.compileShader(s);if(!gl.getShaderParameter(s,gl.COMPILE_STATUS)){let error=gl.getShaderInfoLog(s);gl.deleteShader(s);throw Error(error);}return s;};
    try {
      const vs=shader(gl.VERTEX_SHADER,`attribute vec3 position;attribute vec3 color;attribute float radius;uniform float aspect;uniform float dpr;varying vec3 tint;void main(){gl_Position=vec4(position.x/aspect,position.y,(position.z-6.0)*0.1,position.z);gl_PointSize=radius*dpr/position.z;tint=color;}`);
      const fs=shader(gl.FRAGMENT_SHADER,`precision mediump float;varying vec3 tint;uniform float sphere;void main(){if(sphere<0.5){gl_FragColor=vec4(tint,0.65);return;}vec2 p=gl_PointCoord*2.0-1.0;float r=length(p);if(r>1.0)discard;float core=0.59;float glow=exp(-5.0*r)*0.7;if(r<core){vec3 n=vec3(p/core,sqrt(1.0-r*r/(core*core)));float light=0.3+0.7*max(dot(n,normalize(vec3(-0.5,-0.6,1.0))),0.0);float spec=pow(max(dot(n,normalize(vec3(-0.3,-0.5,1.0))),0.0),24.0);gl_FragColor=vec4(tint*light+vec3(spec*0.55),1.0);}else{gl_FragColor=vec4(tint,glow*(1.0-r)*2.0);}}`);
      this.program=gl.createProgram();gl.attachShader(this.program,vs);gl.attachShader(this.program,fs);gl.linkProgram(this.program);gl.deleteShader(vs);gl.deleteShader(fs);if(!gl.getProgramParameter(this.program,gl.LINK_STATUS))throw Error("WebGL link failed");
      this.buffer=gl.createBuffer();
    } catch {this.dispose();fallback();return;}
    let drag=null;
    this.canvas.onpointerdown=e=>{drag={x:e.clientX,y:e.clientY};this.canvas.setPointerCapture(e.pointerId);};
    this.canvas.onpointermove=e=>{if(!drag)return;this.yaw+=(e.clientX-drag.x)*.006;this.pitch=Math.max(-.9,Math.min(.9,this.pitch+(e.clientY-drag.y)*.005));drag={x:e.clientX,y:e.clientY};this.draw();};
    this.canvas.onpointerup=this.canvas.onpointercancel=()=>{drag=null;};
    this.canvas.addEventListener("wheel",e=>{e.preventDefault();this.zoom=Math.max(.65,Math.min(1.7,this.zoom-e.deltaY*.001));this.draw();},{passive:false});
    this.canvas.addEventListener("webglcontextlost",e=>{e.preventDefault();this.dispose();fallback();});
    this.observer=new ResizeObserver(()=>this.draw());this.observer.observe(host);this.draw();
  }
  update(selected,visible,mastered=[]) {this.selected=selected;this.visible=new Set(visible);this.mastered=new Set(mastered);this.draw();}
  reset(){this.yaw=-.18;this.pitch=.22;this.zoom=1;this.draw();}
  turn(amount){this.yaw+=amount;this.draw();}
  scale(amount){this.zoom=Math.max(.65,Math.min(1.7,this.zoom+amount));this.draw();}
  draw(){
    if(this.disposed||!this.program)return;
    const gl=this.gl,w=this.host.clientWidth,h=this.host.clientHeight,dpr=Math.min(devicePixelRatio||1,2),aspect=w/h;
    this.canvas.width=w*dpr;this.canvas.height=h*dpr;gl.viewport(0,0,this.canvas.width,this.canvas.height);gl.clearColor(0,0,0,0);gl.clear(gl.COLOR_BUFFER_BIT);gl.enable(gl.BLEND);gl.blendFunc(gl.SRC_ALPHA,gl.ONE_MINUS_SRC_ALPHA);gl.useProgram(this.program);
    gl.uniform1f(gl.getUniformLocation(this.program,"aspect"),aspect);gl.uniform1f(gl.getUniformLocation(this.program,"dpr"),dpr);
    const projected=this.points.map(p=>{const [x,y,z]=p.xyz,xx=x*Math.cos(this.yaw)+z*Math.sin(this.yaw),zz=-x*Math.sin(this.yaw)+z*Math.cos(this.yaw),yy=y*Math.cos(this.pitch)-zz*Math.sin(this.pitch),depth=zz*Math.cos(this.pitch)+y*Math.sin(this.pitch);return {p,cam:[xx*this.zoom,yy*this.zoom,depth+6.2]};});
    // Fit the orbit to its viewport before applying user zoom. This keeps the
    // graph readable in narrow panes instead of clustering at the center.
    const sx=projected.map(({cam})=>cam[0]/this.zoom/aspect/cam[2]),sy=projected.map(({cam})=>cam[1]/this.zoom/cam[2]);
    const cx=(Math.min(...sx)+Math.max(...sx))/2,cy=(Math.min(...sy)+Math.max(...sy))/2;
    const fit=Math.min((w-110)/w*2/(Math.max(...sx)-Math.min(...sx)),(h-220)/h*2/(Math.max(...sy)-Math.min(...sy)));
    projected.forEach(({cam})=>{cam[0]=(cam[0]/this.zoom/aspect/cam[2]-cx)*fit*this.zoom*aspect*cam[2];cam[1]=((cam[1]/this.zoom/cam[2]-cy)*fit*this.zoom-.06)*cam[2];});
    const positions=Object.fromEntries(projected.map(p=>[p.p.node.id,p.cam]));
    const related=new Set([this.selected]);const visit=id=>{const node=this.nodes.find(n=>n.id===id);node?.prerequisites.forEach(k=>{if(!related.has(k)){related.add(k);visit(k);}});};visit(this.selected);
    const paint=(data,sphere)=>{gl.bindBuffer(gl.ARRAY_BUFFER,this.buffer);gl.bufferData(gl.ARRAY_BUFFER,new Float32Array(data),gl.DYNAMIC_DRAW);for(const [name,size,offset] of [["position",3,0],["color",3,12],["radius",1,24]]){const loc=gl.getAttribLocation(this.program,name);gl.enableVertexAttribArray(loc);gl.vertexAttribPointer(loc,size,gl.FLOAT,false,28,offset);}gl.uniform1f(gl.getUniformLocation(this.program,"sphere"),sphere);gl.drawArrays(sphere?gl.POINTS:gl.LINES,0,data.length/7);};
    const edges=[];this.nodes.forEach(n=>n.prerequisites.forEach(k=>{if(!this.visible.has(n.id)||!this.visible.has(k))return;const color=related.has(n.id)&&related.has(k)?[.79,.60,.36]:[.23,.39,.52];edges.push(...positions[k],...color,1,...positions[n.id],...color,1);}));paint(edges,0);
    const vertices=[];projected.sort((a,b)=>b.cam[2]-a.cam[2]).forEach(({p,cam})=>{const id=p.node.id;if(!this.visible.has(id))return;const color=id===this.selected?[1,.77,.48]:this.mastered?.has(id)?[.56,.96,.73]:related.has(id)?[.75,.85,1]:[.40,.66,.90];vertices.push(...cam,...color,id===this.selected?235:165);});paint(vertices,1);
    this.points.forEach((p,i)=>{const [x,y,z]=positions[p.node.id],b=this.buttons[i];b.style.left=`${(x/aspect/z*.5+.5)*w}px`;b.style.top=`${(-y/z*.5+.5)*h}px`;b.hidden=!this.visible.has(p.node.id);b.classList.toggle("selected",p.node.id===this.selected);b.setAttribute("aria-pressed",String(p.node.id===this.selected));});
  }
  dispose(){this.disposed=true;this.observer?.disconnect();if(this.gl){if(this.buffer)this.gl.deleteBuffer(this.buffer);if(this.program)this.gl.deleteProgram(this.program);}this.canvas?.remove();this.labels?.remove();}
};
