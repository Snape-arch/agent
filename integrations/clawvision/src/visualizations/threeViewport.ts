/** A presentation-mode or sidebar change resizes the container, not the window. */
export function observeThreeViewport(element:HTMLElement,resize:()=>void){
  const observer=typeof ResizeObserver!=='undefined'?new ResizeObserver(resize):undefined;
  observer?.observe(element);window.addEventListener('resize',resize);
  return()=>{observer?.disconnect();window.removeEventListener('resize',resize);};
}
