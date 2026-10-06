// Verify the compiled hardware policy through Hayba, without benchmarking or changing settings.
import {writeFileSync} from 'node:fs';
import {HaybaClient,discoverPort} from '../GameFlow/bpgraph.mjs';
const client=new HaybaClient(discoverPort(process.cwd()),20000);
await client.connect();
const cases=[
 ['strong_12gb',11943,32,8,2000,4,4],
 ['consumer_4gb',4096,16,8,2000,1,1],
 ['consumer_entry',4096,16,4,150,0,0,'NVIDIA GeForce GTX 1650'],
 ['strong_16gb_ram',11943,16,8,2000,3,3],
 ['strong_8gb_vram',8192,32,8,2000,3,3],
 ['unbenchmarked',11943,32,8,-1,3,3],
 ['weak_cpu',11943,32,4,2000,3,3],
];
const results=[];
try {
 for(const [name,vram,ram,cores,score,level,texture,gpu='NVIDIA GeForce RTX 5070'] of cases){
  const script=`import unreal\nimport json\ns=unreal.SaskartaHardwareSpecs()\ns.set_editor_property('gpu_name',${JSON.stringify(gpu)})\ns.set_editor_property('vendor_id',4318)\ns.set_editor_property('vrammb',${vram})\ns.set_editor_property('ramgb',${ram})\ns.set_editor_property('cpu_cores',${cores})\ns.set_editor_property('cpu_score',150.0)\ns.set_editor_property('gpu_score',${score}.0)\ns.set_editor_property('display_resolution',unreal.IntPoint(1920,1080))\np=unreal.SaskartaHardwareProfileLibrary.recommend(s)\nprint(json.dumps({'level':p.recommended_level,'texture':p.texture_quality,'shadow':p.shadow_quality,'gi':p.global_illumination_quality,'effects':p.effects_quality,'foliage':p.foliage_quality,'pct':p.screen_percentage,'reasons':p.reasons}))`;
  const reply=await client.send('python_run',{script});
  if(!reply.ok||reply.data.ok===false)throw new Error(JSON.stringify(reply));
  const actual=JSON.parse(reply.data.stdout);
  const passed=actual.level===level&&actual.texture===texture&&(vram!==4096||(actual.shadow<=1&&actual.gi<=1&&actual.effects<=1));
  results.push({name,expected:{level,texture},actual,passed});
  console.log(`${passed?'PASS':'FAIL'} ${name}: preset ${actual.level}, textures ${actual.texture}`);
 }
 writeFileSync('Saved/Verification/ConsumerPerf/profiles.json',JSON.stringify(results,null,2));
 if(results.some(r=>!r.passed))process.exitCode=1;
} finally {client.close();}
