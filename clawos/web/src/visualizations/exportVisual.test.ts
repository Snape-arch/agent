import { afterEach, describe, expect, it } from 'vitest';
import { csvText, serializeVisualSvg } from './exportVisual';
afterEach(()=>{document.body.innerHTML='';});
describe('Portable teaching visualization exports',()=>{
  it('preserves quotes, commas, newlines and Chinese CSV headers',()=>{
    expect(csvText([{'列,名':'他说"可以"\n下一行',n:2}],['列,名','n'])).toBe('\ufeff"列,名",n\r\n"他说""可以""\n下一行",2\r\n');
  });
  it('resolves page-only styles and includes report provenance in standalone SVG',async()=>{
    document.body.innerHTML='<style>.test-chart path{stroke:rgb(53,105,83);fill:none}</style><svg class="test-chart" viewBox="0 0 100 100"><path d="M0 0L10 10"/></svg>';
    const blob=serializeVisualSvg(document.querySelector('svg')!,{report:'synthetic-report',hash:'fixture-hash'});
    const text=await new Promise<string>((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result));reader.onerror=reject;reader.readAsText(blob);});
    expect(text).toContain('rgb(53,105,83)');expect(text).toContain('fixture-hash');expect(text).toContain('http://www.w3.org/2000/svg');
  });
});
