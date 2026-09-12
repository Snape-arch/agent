"use strict";
/* Small deterministic experiments; no arbitrary code execution or model calls. */
(() => {
  function vector(raw) {
    const parts=raw.trim().split(/[,，\s]+/).map(Number);
    if(parts.length!==3||parts.some(x=>!Number.isFinite(x)||Math.abs(x)>1e6))throw Error("请输入 3 个有限数字，用逗号分隔，绝对值不超过 1000000。");
    return parts;
  }
  function compare(a,b){const dot=a.reduce((s,x,i)=>s+x*b[i],0),na=Math.hypot(...a),nb=Math.hypot(...b);return {dot,cosine:na&&nb?dot/(na*nb):null};}
  function attention(mask){const q=[[1,0],[0,1],[1,1]],scores=q.map(a=>q.map(b=>a.reduce((s,x,i)=>s+x*b[i],0)/Math.sqrt(2)));return scores.map((row,i)=>{const ex=row.map((x,j)=>mask&&j>i?0:Math.exp(x-Math.max(...row)));const sum=ex.reduce((a,b)=>a+b,0);return ex.map(x=>x/sum);});}
  const lora=rank=>({full:4096*4096,trainable:2*4096*rank});
  const html=id=>{
    if(id==="linear")return `<h3>小实验：方向相似，数值一定接近吗？</h3><p>试着把向量 B 的每个数乘以 10，观察点积与余弦分别怎样变化。</p><div class="lab-inputs"><label>向量 A<input data-lab-input="a" value="1, 2, 3" aria-label="向量 A"></label><label>向量 B<input data-lab-input="b" value="2, 4, 6" aria-label="向量 B"></label></div>`;
    if(id==="attention")return `<h3>小实验：未来的信息在哪里被挡住？</h3><p>固定 Q = K = [[1,0], [0,1], [1,1]]，计算 softmax(QKᵀ / √2)。每一行表示当前 token 对三个位置的权重。</p><label class="check"><input data-lab-input="mask" type="checkbox" checked>启用因果 mask</label>`;
    if(id==="finetune")return `<h3>小实验：rank 改变了多少训练参数？</h3><p>以一个 4096 × 4096 线性层为例，仅统计 LoRA 的 A、B 两个矩阵，不包含偏置与优化器状态。</p><label>Rank <input data-lab-input="rank" aria-label="LoRA rank" type="range" min="1" max="64" value="8"></label>`;
    return "";
  };
  function mount(host,id){const content=html(id);if(!content)return;host.innerHTML=`<article class="card lab"><span class="eyebrow">TRY IT HERE / 即时实验</span>${content}<div class="lab-output" role="status" aria-live="polite"></div><p class="small">本地确定性计算，不计入掌握证据。把观察与解释写进下面的学习笔记。</p></article>`;const out=host.querySelector(".lab-output");
    const update=()=>{try{if(id==="linear"){const result=compare(vector(host.querySelector('[data-lab-input="a"]').value),vector(host.querySelector('[data-lab-input="b"]').value));out.textContent=`点积：${result.dot.toFixed(3)}　余弦相似度：${result.cosine===null?"未定义（存在零向量）":result.cosine.toFixed(3)}`;}
      else if(id==="attention"){const rows=attention(host.querySelector('[data-lab-input="mask"]').checked);out.innerHTML=`<table><caption>注意力权重（行和为 1，显示值经四舍五入）</caption><thead><tr><th scope="col">当前位置</th><th scope="col">位置 1</th><th scope="col">位置 2</th><th scope="col">位置 3</th></tr></thead><tbody>${rows.map((row,i)=>`<tr><th scope="row">Token ${i+1}</th>${row.map(x=>`<td style="background:rgba(64,151,113,${x*.6})">${x.toFixed(3)}</td>`).join("")}</tr>`).join("")}</tbody></table>`;}
      else {const rank=Number(host.querySelector('[data-lab-input="rank"]').value),r=lora(rank);out.textContent=`Rank ${rank} · 可训练参数 ${r.trainable.toLocaleString()} / 原矩阵参数 ${r.full.toLocaleString()}（${(r.trainable/r.full*100).toFixed(2)}%）`;}
    }catch(e){out.textContent=e.message;}};
    host.addEventListener("input",update);update();
  }
  const api={vector,compare,attention,lora,mount};
  if(typeof module!=="undefined"&&module.exports)module.exports=api;
  else window.AcademyLabs=api;
})();
