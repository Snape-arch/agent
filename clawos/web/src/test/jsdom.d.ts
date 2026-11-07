// Minimal surface used by the isolated shared-script tests; jsdom ships no TS types.
declare module 'jsdom' {
  export class JSDOM {
    constructor(html:string,options:{runScripts:'outside-only';pretendToBeVisual:boolean});
    readonly window:Window & typeof globalThis;
  }
}
