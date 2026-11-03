'use strict';
// CI guard injected into the reviewed synthetic frontend checks.
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const artifact = path.resolve(process.env.P4B_ARTIFACT);
const phase = path.resolve(process.env.P4B_PHASE);
const repo = path.resolve(process.env.P4B_REPO);
const originalAppend = fs.appendFileSync.bind(fs);
const originalWrite = fs.writeFileSync.bind(fs);
function deny(code) {
  originalAppend(path.join(phase, 'node-offline-events.jsonl'), JSON.stringify({kind:'blocked',code,pid:process.pid})+'\n');
  try { originalWrite(path.join(artifact, 'offline-guard-violation.flag'), code, {flag:'wx'}); } catch (error) { if(error.code!=='EEXIST') throw error; }
  process.exit(91);
}
function inside(value, root) {
  const relative = path.relative(root,value);
  return relative==='' || (!relative.startsWith('..'+path.sep) && relative!=='..' && !path.isAbsolute(relative));
}
function fileCheck(value, writing=false) {
  if (typeof value==='number') return;
  if (value instanceof URL) value=require('node:url').fileURLToPath(value);
  if (Buffer.isBuffer(value)) value=value.toString();
  if (typeof value!=='string') deny('unsupported_node_file_path');
  const resolved=path.resolve(value);
  if(path.basename(resolved).startsWith('.env')) deny('node_private_file_read');
  if(writing ? !inside(resolved,phase) : !(inside(resolved,path.join(repo,'frontend')) || inside(resolved,phase))) deny('node_file_boundary');
}
for (const name of ['readFileSync','readFile','openSync','open','readdirSync','readdir','statSync','stat','lstatSync','lstat']) {
  const original=fs[name].bind(fs);
  fs[name]=function(value,...rest) { fileCheck(value, name.startsWith('open') && typeof rest[0]==='string' && /[wa+]/.test(rest[0])); return original(value,...rest); };
}
for (const name of ['writeFileSync','writeFile','appendFileSync','appendFile','unlinkSync','unlink','mkdirSync','mkdir','rmSync','rm','rmdirSync','rmdir']) {
  const original=fs[name].bind(fs);
  fs[name]=function(value,...rest) { fileCheck(value,true); return original(value,...rest); };
}
// Load trusted builtins and evaluate their lazy exported-function getters before
// replacing any dependency exports. Node 24 exposes BlockList through a getter.
const blockedModules=['net','tls','dgram','http','https','http2','dns','child_process','worker_threads'];
const blockedExports=blockedModules.map(mod=>require('node:'+mod));
const replacements=[];
for(const object of blockedExports) {
  for(const key of Object.keys(object)) if(typeof object[key]==='function') {
    const descriptor=Object.getOwnPropertyDescriptor(object,key);
    if(!descriptor) deny('node_guard_export_descriptor_missing');
    if(!descriptor.configurable && !(Object.hasOwn(descriptor,'value') && descriptor.writable)) {
      deny('node_guard_export_not_protectable');
    }
    replacements.push({object,key,descriptor});
  }
}
for(const {object,key,descriptor} of replacements) {
  try {
    Object.defineProperty(object,key,{
      value:function(){deny('node_network_or_process_forbidden');},
      enumerable:descriptor.enumerable,configurable:false,writable:false
    });
  } catch(error) { deny('node_guard_export_protection_failed'); }
}
if(globalThis.fetch) globalThis.fetch=function(){deny('node_live_fetch_forbidden');};
const allowedBuiltins=new Set(Module.builtinModules.map(name=>name.replace(/^node:/,'')));
const originalLoad=Module._load;
Module._load=function(request,...rest) {
  const builtin=allowedBuiltins.has(request.replace(/^node:/,''));
  const parent=rest[0];
  const base=parent && parent.filename && !parent.filename.endsWith('[eval]') ? path.dirname(parent.filename) : repo;
  const candidate=(path.isAbsolute(request) || request.startsWith('./') || request.startsWith('../')) ? path.resolve(base,request) : '';
  const frontendModule=path.join(repo,'frontend','analytics.js');
  const allowedFrontend=candidate===frontendModule || candidate+'.js'===frontendModule;
  if(!builtin && !allowedFrontend) deny('node_external_module_forbidden');
  return originalLoad.call(this,request,...rest);
};
originalAppend(path.join(phase,'node-offline-events.jsonl'),JSON.stringify({kind:'guard_loaded',pid:process.pid})+'\n');
