import {afterEach,beforeEach,describe,expect,it} from 'vitest';
import {JSDOM} from 'jsdom';
import source from '../../../../clawos/static/assets/context-help.js?raw';

// Exercise the same controller served to legacy HTML and bundled by React.
let dom:JSDOM;
beforeEach(()=>{
  dom=new JSDOM('<!doctype html><button id="a" class="context-help-trigger" aria-describedby="existing" data-context-help="Optional explanation">Help</button><button id="b" class="context-help-trigger" data-context-help="Second explanation">Other help</button><button id="step" data-context-help="Step timing">Next step</button><p id="outside">Outside</p>',{runScripts:'outside-only',pretendToBeVisual:true});
  dom.window.eval(source);
});
afterEach(()=>dom.window.close());
const el=(id:string)=>dom.window.document.getElementById(id)!;
const tip=()=>dom.window.document.querySelector('[role="tooltip"]');
const event=(node:Element,type:string,relatedTarget:Element|null=null)=>node.dispatchEvent(new dom.window.MouseEvent(type,{bubbles:true,relatedTarget}));
const pause=()=>new Promise(resolve=>setTimeout(resolve,180));

describe('Shared contextual help',()=>{
  it('opens on keyboard focus, describes its trigger and restores existing semantics on Escape',()=>{
    el('a').focus();expect(tip()?.textContent).toBe('Optional explanation');
    expect(el('a').getAttribute('aria-describedby')).toBe('existing '+tip()?.id);
    el('a').dispatchEvent(new dom.window.KeyboardEvent('keydown',{key:'Escape',bubbles:true}));
    expect(tip()).toBeNull();expect(el('a').getAttribute('aria-describedby')).toBe('existing');expect(dom.window.document.activeElement).toBe(el('a'));
  });
  it('allows pointer travel into the popup and dismisses after leaving it',async()=>{
    event(el('a'),'pointerover');const popup=tip()!;
    event(el('a'),'pointerout',popup);event(popup,'pointerover',el('a'));await pause();expect(tip()).toBe(popup);
    event(popup,'pointerout',el('outside'));await pause();expect(tip()).toBeNull();
  });
  it('pins on the first click after focus, survives pointer exit, and toggles closed',async()=>{
    el('a').focus();event(el('a'),'click');event(el('a'),'pointerout',el('outside'));await pause();expect(tip()).not.toBeNull();
    event(el('a'),'click');expect(tip()).toBeNull();
  });
  it('dismisses pinned help on outside interaction and maintains only one popup',()=>{
    event(el('a'),'click');event(el('outside'),'pointerdown');expect(tip()).toBeNull();
    el('a').focus();el('b').focus();expect(dom.window.document.querySelectorAll('[role="tooltip"]')).toHaveLength(1);expect(tip()?.textContent).toBe('Second explanation');expect(el('a').getAttribute('aria-describedby')).toBe('existing');
  });
  it('uses text only and cleans up after a routed trigger unmounts',async()=>{
    el('a').setAttribute('data-context-help','<img src=x onerror=alert(1)>');el('a').focus();
    expect(tip()?.querySelector('img')).toBeNull();expect(tip()?.textContent).toContain('<img');
    el('a').remove();await Promise.resolve();expect(tip()).toBeNull();
  });
  it('clamps to the viewport, flips above a bottom-edge trigger and updates on scroll',()=>{
    Object.defineProperty(dom.window,'innerWidth',{value:390});Object.defineProperty(dom.window,'innerHeight',{value:700});
    el('a').getBoundingClientRect=()=>({left:370,right:390,top:650,bottom:682,width:20,height:32,x:370,y:650,toJSON(){}});
    el('a').focus();tip()!.getBoundingClientRect=()=>({width:320,height:100} as DOMRect);
    dom.window.dispatchEvent(new dom.window.Event('resize'));expect((tip() as HTMLElement).style.left).toBe('58px');expect((tip() as HTMLElement).style.top).toBe('542px');
    el('a').getBoundingClientRect=()=>({left:0,right:20,top:-50,bottom:-18} as DOMRect);
    dom.window.document.dispatchEvent(new dom.window.Event('scroll'));expect(tip()).toBeNull();
  });
  it('does not steal navigation clicks and does not install duplicate listeners',()=>{
    let clicks=0;el('step').addEventListener('click',()=>clicks++);dom.window.eval(source);event(el('step'),'click');expect(clicks).toBe(1);
    event(el('a'),'click');expect(tip()).not.toBeNull();event(el('a'),'click');expect(tip()).toBeNull();
  });
});
