import {Info} from 'lucide-react';
import '../../../../clawos/static/assets/context-help.js';

/** Optional explanation only; action, consent and failure details stay visible. */
export function ContextHelp({label,text,visibleLabel=false}:{label:string;text:string;visibleLabel?:boolean}){
  return <button type="button" className="context-help-trigger" aria-label={label} data-context-help={text}><Info size={16} aria-hidden="true"/>{visibleLabel&&<span>{label}</span>}</button>;
}
