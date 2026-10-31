/** Build in a fresh workspace staging folder; publish assets and retain old files in output. */
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {execFileSync} from 'node:child_process';
const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const source = path.join(repo,'integrations/clawvision');
const session = 'build-'+Date.now();
const stage = path.join(repo,'clawos/output/vision-builds',session);
const destination = path.join(repo,'clawos/static/vision');
const archive = path.join(repo,'clawos/output/vision-builds',session+'-previous');
if (path.relative(repo,destination) !== path.join('clawos','static','vision') || fs.existsSync(destination) && fs.lstatSync(destination).isSymbolicLink()) throw new Error('Invalid publication directory');
fs.mkdirSync(stage,{recursive:true});
execFileSync(process.execPath,[path.join(source,'node_modules/typescript/bin/tsc'),'-b'],{cwd:source,stdio:'inherit'});
execFileSync(process.execPath,[path.join(source,'node_modules/vite/bin/vite.js'),'build','--outDir',stage],{cwd:source,stdio:'inherit'});
const entry = path.join(stage,'index.html');
fs.writeFileSync(entry,fs.readFileSync(entry,'utf8').replace(/\r\n/g,'\n').replace(/\r/g,'\n'));
const notices=['react','react-dom','three','lucide-react'].map(name=>{
  const root=path.join(source,'node_modules',name);
  const license=['LICENSE','LICENSE.md','LICENSE.txt'].map(n=>path.join(root,n)).find(p=>fs.existsSync(p));
  if(!license)throw new Error('Missing license: '+name);
  return name+'\n'+fs.readFileSync(license,'utf8');
}).join('\n\n');
fs.writeFileSync(path.join(stage,'THIRD_PARTY_NOTICES.txt'),notices);
function files(root,prefix=''){return fs.readdirSync(root,{withFileTypes:true}).flatMap(e=>e.isDirectory()?files(path.join(root,e.name),path.join(prefix,e.name)):[path.join(prefix,e.name)]);}
const fresh=files(stage);const keep=new Set(fresh);
if(fs.existsSync(destination))for(const relative of files(destination))if(!keep.has(relative)){
  const current=path.resolve(destination,relative), saved=path.resolve(archive,relative);
  if(!current.startsWith(destination+path.sep)||!saved.startsWith(archive+path.sep))throw new Error('Invalid archive path');
  fs.mkdirSync(path.dirname(saved),{recursive:true});fs.renameSync(current,saved);
}
// HTML last: all newly referenced assets exist before the entry point changes.
for(const relative of fresh.sort((a,b)=>Number(a==='index.html')-Number(b==='index.html'))){
  const target=path.join(destination,relative);fs.mkdirSync(path.dirname(target),{recursive:true});fs.copyFileSync(path.join(stage,relative),target);
}
console.log(`Published ${fresh.length} frontend files; previous assets retained in output.`);
