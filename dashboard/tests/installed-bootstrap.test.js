const test=require('node:test'),assert=require('node:assert/strict'),fs=require('fs'),path=require('path');
const {initialize,registry}=require('../installed-runtime');
test('first launch is offline, separates private data and preserves it on later launch',()=>{
 const source=path.resolve(__dirname,'../..'),stage=process.env.FACTORY_TEST_DISTRIBUTION_STAGE||JSON.parse(fs.readFileSync(path.join(source,'.runtime/runtime-smoke-current.json'),'utf8')).root;
 const home=fs.mkdtempSync(path.join(source,'.runtime/bootstrap-test-'));
 const app={getPath:()=>home,getVersion:()=> '1.3.0'};
 const root=initialize(app,stage);assert.equal(registry(root).projects.length,10);
 const pointer=path.join(root,'.runtime/updates/active_rules.json');const before=fs.readFileSync(pointer,'utf8');assert.equal(JSON.parse(before).bundled,true);
 const env=path.join(root,'.env');fs.writeFileSync(env,'OPENAI_API_KEY=isolated-bootstrap-key\n');
 fs.writeFileSync(path.join(root,'.runtime/hidden_projects.json'),JSON.stringify({projects:['pet_transport']}));
 initialize(app,stage);assert.equal(fs.readFileSync(env,'utf8'),'OPENAI_API_KEY=isolated-bootstrap-key\n');assert.equal(registry(root).projects.length,9);
 assert.equal(fs.readFileSync(pointer,'utf8'),before);
 assert.equal(path.dirname(process.env.ROAD_RESCUE_PYTHON),path.join(stage,'python'));
});
test('upgrade prepares compatible bundled rules offline and preserves old evidence',()=>{
 const source=path.resolve(__dirname,'../..'),stage=process.env.FACTORY_TEST_DISTRIBUTION_STAGE;
 assert.ok(stage,'Supply the verified current distribution stage');
 const home=fs.mkdtempSync(path.join(source,'.runtime/bootstrap-upgrade-')),root=path.join(home,'workspace'),old=path.join(root,'.runtime/rules/1');
 const baseline=JSON.parse(fs.readFileSync(path.join(stage,'engine/distribution/baseline-rules.json'),'utf8'));
 for(const name of baseline.files){const target=path.join(old,name);fs.mkdirSync(path.dirname(target),{recursive:true});fs.copyFileSync(path.join(stage,'engine',name),target);}
 const manifest=path.join(old,'manifest.json');fs.writeFileSync(manifest,JSON.stringify({version:'1',bundled:true,app_version:'1.3.1'}));
 const pointer=path.join(root,'.runtime/updates/active_rules.json');fs.mkdirSync(path.dirname(pointer),{recursive:true});fs.writeFileSync(pointer,JSON.stringify({version:'1',bundled:true}));
 const env=path.join(root,'.env'),hidden=path.join(root,'.runtime/hidden_projects.json'),history=path.join(root,'prompts/library/frozen-evidence.json');
 fs.mkdirSync(path.dirname(history),{recursive:true});fs.writeFileSync(env,'ISOLATED_OFFLINE_CHECK=1\n');fs.writeFileSync(hidden,JSON.stringify({projects:['pet_transport']}));fs.writeFileSync(history,'{"frozen_rules_version":"1"}\n');
 const preserved=[manifest,env,hidden,history,path.join(old,'projects/truck_rescue/variable_catalog.json')].map(file=>[file,fs.readFileSync(file)]);
 const app={getPath:()=>home,getVersion:()=> '1.4.3'};initialize(app,stage);
 const active=JSON.parse(fs.readFileSync(pointer,'utf8'));assert.equal(active.bundled,true);assert.equal(active.previous,'1');assert.notEqual(active.version,'1');
 for(const [file,bytes] of preserved)assert.deepEqual(fs.readFileSync(file),bytes);
 assert.equal(registry(root).projects.length,9);assert.equal(JSON.parse(fs.readFileSync(path.join(root,'.runtime/updates/bootstrap_status.json'),'utf8')).state,'refreshed');
});
