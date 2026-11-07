import { afterEach, expect, it } from 'vitest';
import { cleanup,render,screen } from '@testing-library/react';
import { CadModelView } from './renderers/CadModelView';
afterEach(cleanup);
it('reports missing asset content before creating a procedural fallback or WebGL context',async()=>{
  render(<CadModelView data={{name:'missing.obj',format:'obj',assetId:'asset_missing'}}/>);
  expect(await screen.findByRole('alert')).toHaveTextContent('没有可读取的预览内容');expect(document.querySelector('canvas')).toBeNull();
});
it('declares a required format conversion instead of parsing an unsupported asset as GLTF',async()=>{
  render(<CadModelView data={{name:'model.step',format:'step' as never,base64:'synthetic-fixture'}}/>);
  expect(await screen.findByRole('alert')).toHaveTextContent('需要转换');expect(document.querySelector('canvas')).toBeNull();
});
