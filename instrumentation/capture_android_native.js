// Experimental native-only observer for Meta AI Android 290.1.0.42.163.
// Offsets belong to the installed arm64 libstartup.so; no Java bridge used.
'use strict';
let sequence=0;
const emit=(event,data)=>console.log(JSON.stringify({event,sequence:sequence++,timestamp:new Date().toISOString(),...data}));
const hex=(p,n)=>Array.from(new Uint8Array(p.readByteArray(n)),b=>b.toString(16).padStart(2,'0')).join('');
const mod=Process.getModuleByName('libstartup.so');
if(mod.size!==17784832)throw Error('Unexpected libstartup.so size');
const specs=[['plaintext_tx',0xe4a5b4],['relay_tx',0xe49b4c],['wire_rx',0xe4b8d0],['wire_frame_rx',0xe4b964]];
// Confirm JNI registration-table pointers before using this build's offsets.
for(const [table,code] of [[0x10a5c18,0xe4a5b4],[0x10a5980,0xe49b4c],[0x10a5e40,0xe4b8d0]]){
 if(!mod.base.add(table+16).readPointer().equals(mod.base.add(code))) throw Error('JNI table/build mismatch');
}
let directHooked=false;
function observeDirect(env){
 if(directHooked)return;
 directHooked=true;
 Interceptor.attach(env.readPointer().add(229*Process.pointerSize).readPointer(),{onEnter(args){
  try{
   const n=Number(args[2].toString());if(n<1||n>16384)return;
   const caller=this.returnAddress;
   if(caller.compare(mod.base)<0||caller.compare(mod.base.add(mod.size))>=0)return;
   emit('native_to_java_buffer',{caller:caller.sub(mod.base).toString(),length:n,hex:hex(args[1],n)});
  }catch(e){emit('capture_error',{hook:'native_to_java',message:String(e)});}
 }});
}
for(const offset of [0xe4b888,0xe4c008]) Interceptor.attach(mod.base.add(offset),{onEnter(args){observeDirect(args[0]);}});
let derives=0;
Interceptor.attach(mod.base.add(0xe4b00c),{
 onEnter(args){this.sample=derives++<32;if(!this.sample)return;this.cache=args[4];this.id=derives;try{emit('kdf_enter',{id:this.id,parameters:hex(args[3],12)});}catch(e){emit('capture_error',{hook:'kdf',message:String(e)});}},
 onLeave(){if(!this.sample)return;try{if(this.cache.add(32).readU8()!==1)throw Error('ECDH cache invalid');emit('ecdh_shared_secret',{id:this.id,hex:hex(this.cache,32)});}catch(e){emit('capture_error',{hook:'kdf',message:String(e)});}}
});
for(const [event,offset] of specs){
 Interceptor.attach(mod.base.add(offset),{
  onEnter(args){
   try{
    const env=args[0],buffer=args[2],start=args[3].toInt32(),n=args[4].toInt32();
    if(n<0||n>1048576||start<0)throw Error('Invalid buffer bounds');
    observeDirect(env);
    const table=env.readPointer();
    const addr=new NativeFunction(table.add(230*Process.pointerSize).readPointer(),'pointer',['pointer','pointer']);
    const capacity=new NativeFunction(table.add(231*Process.pointerSize).readPointer(),'int64',['pointer','pointer']);
    const p=addr(env,buffer),cap=Number(capacity(env,buffer).toString());
    if(p.isNull()||start+n>cap)throw Error('Not a valid direct buffer');
    emit(event,{object:args[1].toString(),length:n,hex:hex(p.add(start),n)});
   }catch(e){emit('capture_error',{hook:event,message:String(e)});}
  }
 });
 emit('hook_ready',{hook:event,offset});
}
emit('native_observer_ready',{module:mod.name,size:mod.size});
