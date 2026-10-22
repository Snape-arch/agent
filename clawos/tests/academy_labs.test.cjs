const test=require('node:test');
const assert=require('node:assert/strict');
const lab=require('../static/assets/academy-labs.js');

test('cosine is scale invariant, dot product is not',()=>{
  const a=lab.vector('1, 2, 3');
  const b=lab.vector('2，4，6');
  assert.equal(lab.compare(a,b).dot,28);
  assert.ok(Math.abs(lab.compare(a,b).cosine-1)<1e-12);
  assert.equal(lab.compare(a,[0,0,0]).cosine,null);
  assert.throws(()=>lab.vector('1,2'));
  assert.throws(()=>lab.vector('1,NaN,3'));
});
test('causal attention excludes future positions and preserves row normalization',()=>{
  for(const mask of [false,true]){
    const rows=lab.attention(mask);
    rows.forEach((row,i)=>{
      assert.ok(Math.abs(row.reduce((a,b)=>a+b,0)-1)<1e-12);
      row.forEach((x,j)=>{assert.ok(x>=0);if(mask&&j>i)assert.equal(x,0);});
    });
  }
  assert.deepEqual(lab.attention(true)[0],[1,0,0]);
  assert.ok(lab.attention(false)[0][2]>0);
});
test('LoRA counts both low-rank factors, not only one',()=>{
  assert.deepEqual(lab.lora(8),{full:16777216,trainable:65536});
  assert.equal(lab.lora(16).trainable,2*lab.lora(8).trainable);
});
