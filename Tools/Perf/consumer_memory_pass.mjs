// Bounded Hayba texture pass: resident game art only, one texture saved per call.
import {copyFileSync,existsSync,mkdirSync,writeFileSync} from 'node:fs';
import {dirname,join} from 'node:path';
import {HaybaClient,discoverPort} from '../GameFlow/bpgraph.mjs';
const client=new HaybaClient(discoverPort(process.cwd()),20000);
await client.connect();
const output='Saved/Verification/ConsumerPerf';mkdirSync(output,{recursive:true});
const backup='Saved/Backups/ConsumerPerf_20261005';
async function py(script){const r=await client.send('python_run',{script});if(!r.ok)throw new Error(JSON.stringify(r));const d=r.data;if(d.ok===false||d.stdout_truncated)throw new Error(JSON.stringify(d));return JSON.parse(d.stdout);}
const prefixes=['/Game/ZY_Summit/','/Game/Ziyun_Scenes/','/Game/AshesOfBazaar/','/Game/SaskartaGaea/Characters/Carrier/','/Game/SaskartaGaea/Characters/Traveller/'];
const scan=`import unreal\nimport json\nrows=[]\nprefixes=${JSON.stringify(prefixes)}\nfor t in unreal.ObjectIterator(unreal.Texture2D):\n    p=t.get_path_name()\n    if any(p.startswith(pre) for pre in prefixes) and max(t.blueprint_get_size_x(),t.blueprint_get_size_y())>2048:\n        rows.append({'path':p,'x':t.blueprint_get_size_x(),'y':t.blueprint_get_size_y(),'max':t.get_editor_property('max_texture_size'),'never':t.get_editor_property('never_stream'),'power':str(t.get_editor_property('power_of_two_mode'))})\nrows.sort(key=lambda r:r['path'])\nprint(json.dumps({'total':len(rows),'rows':rows[OFFSET:OFFSET+20]}))\n`;
const targets=[];
try {
 let total=1;
 for(let offset=0;offset<total;offset+=20){const r=await py(scan.replace('OFFSET:OFFSET+20',`${offset}:${offset+20}`));total=r.total;targets.push(...r.rows);}
 writeFileSync(join(output,'texture_before.json'),JSON.stringify(targets,null,2));
 console.log(`Found ${targets.length} oversized art textures.`);
 const bad=targets.filter(r=>r.max===0||r.max>2048);
 console.log(`2K cap check before: ${bad.length ? 'FAIL' : 'PASS'} (${bad.length} above target).`);
 const results=[];
 for(const target of bad){
  const rel='Content/'+target.path.split('.')[0].slice('/Game/'.length)+'.uasset';
  const dest=join(backup,rel);mkdirSync(dirname(dest),{recursive:true});if(!existsSync(dest))copyFileSync(rel,dest);
  const p=JSON.stringify(target.path);
  const power=(target.x&(target.x-1))!==0||(target.y&(target.y-1))!==0;
  const r=await py(`import unreal\nimport json\nt=unreal.load_asset(${p})\nt.set_editor_property('max_texture_size',2048)\n${power?"t.set_editor_property('power_of_two_mode',unreal.TexturePowerOfTwoSetting.PAD_TO_POWER_OF_TWO)\n":''}assert unreal.EditorAssetLibrary.save_loaded_asset(t,False)\nassert t.get_editor_property('max_texture_size')==2048\nprint(json.dumps({'path':t.get_path_name(),'max':t.get_editor_property('max_texture_size'),'padded':${power?'True':'False'}}))\n`);
  results.push(r);writeFileSync(join(output,'texture_applied.json'),JSON.stringify(results,null,2));
  if(results.length%10===0||results.length===bad.length)console.log(`Saved ${results.length}/${bad.length} textures.`);
 }
 console.log(`2K cap check after: PASS (${results.length} saved/read back).`);
} finally {client.close();}
