class BoardFreshness {
 constructor(io){this.io=io;this.token=null;this.generation=0;this.running=false;this.pending=false;this.failures=0;this.lastChecked=null;this.lastUpdated=null;}
 accepted(snapshot){this.generation++;this.token=snapshot?.freshness_token||null;this.pending=false;this.lastUpdated=new Date();this.publish('updated');}
 publish(kind){this.io.status({kind,pending:this.pending,lastChecked:this.lastChecked,lastUpdated:this.lastUpdated,failures:this.failures});}
 async check(force=false){
  if(this.running||!this.io.ready()||!this.io.visible())return;
  this.running=true;const context=this.io.capture(),generation=this.generation;
  const valid=()=>generation===this.generation&&this.io.current(context);
  try{
   const marker=await this.io.poll(context);if(!valid())return;
   if(typeof marker.freshness_token!=='string'||!marker.freshness_token)throw new Error('更新检查响应不完整');
   this.lastChecked=new Date();this.failures=0;
   if(marker.system_version&&marker.system_version!==this.io.version){this.publish('upgrade');return;}
   if(!force&&marker.freshness_token===this.token){this.publish(this.pending?'pending':'checked');return;}
   this.pending=true;
   if(this.io.blocked()){this.publish('pending');return;}
   this.publish('loading');
   const snapshot=await this.io.read(context);if(!valid())return;
   // A form/video may have opened while the read was in flight.
   if(this.io.blocked()){this.publish('pending');return;}
   this.io.apply(snapshot,context);this.failures=0;
  }catch(error){if(valid()){this.failures++;this.publish('error');}}
  finally{this.running=false;}
 }
}
