// Run with: node --test tests/panel_client.test.cjs
// Execute the real controller with simulated DOM/HTTP; never contact a service.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const vm = require('node:vm');
const source = readFileSync(join(__dirname, '../app/static/agenda/panel.js'), 'utf8');
const tick = () => new Promise(setImmediate);
const response = (body, status=200) => ({ok:status<400, status, json:async()=>body});
const calendar = tag => ({tag, start:'2026-11-02', barbers:['Obed','Jesús']});
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes,no)=>{resolve=yes;reject=no;});
  return {promise,resolve,reject};
}
async function harness() {
  const elements = new Map(), timers = new Map(), buttons = [{disabled:false},{disabled:false}];
  let timerId=0;
  const element = id => {
    if(!elements.has(id)) elements.set(id, {
      value:'', innerHTML:'', textContent:'', options:[], open:false,
      addEventListener(){}, setAttribute(){}, replaceChildren(){this.value='';},
    });
    return elements.get(id);
  };
  const context = vm.createContext({
    document:{getElementById:element, querySelectorAll:()=>buttons, addEventListener(){}},
    window:{addEventListener(){}}, navigator:{}, URLSearchParams, AbortController,
    setTimeout(fn){const id=++timerId;timers.set(id,fn);return id;},
    clearTimeout(id){timers.delete(id);}, setInterval(){},
    fetch:async()=>response({detail:'Inicia sesión'},401), frames:[],
  });
  const run = code => vm.runInContext(code,context);
  run(source);
  await tick();
  run("user={csrf:'test',scope:'Obed'}; render=()=>frames.push(data.tag);");
  element('from').value='2026-11-02';
  element('barber').value='Obed';
  const expire = () => {assert.equal(timers.size,1); [...timers.values()][0]();};
  return {context,run,element,timers,buttons,expire};
}
function stalledFetch(url, options) {
  return new Promise((resolve,reject)=>options.signal.addEventListener('abort',()=>{
    const error = new Error('aborted'); error.name='AbortError'; reject(error);
  }));
}

test('a stuck calendar request times out and the next refresh can recover',async()=>{
  const h=await harness(); h.context.fetch=stalledFetch;
  const first=h.run('refresh()');
  const rejected=assert.rejects(first,/Revisa tu conexión/);
  h.expire(); await rejected;
  assert.equal(h.run('loading'),null);
  h.context.fetch=async()=>response(calendar('recovered'));
  await h.run('refresh()');
  assert.deepEqual([...h.context.frames],['recovered']);
  assert.equal(h.timers.size,0);
});

test('timed-out writes release controls, report uncertainty and are never retried',async()=>{
  const h=await harness(); let calls=0;
  h.context.fetch=(...args)=>{calls++;return stalledFetch(...args);};
  const pending=h.run("mutate(()=>api('/appointments/1/state',{method:'POST'}))");
  assert(h.buttons.every(b=>b.disabled));
  h.expire(); await pending;
  assert.equal(calls,1);
  assert.match(h.element('message').textContent,/No pude confirmar si el cambio se guardó/);
  assert(h.buttons.every(b=>!b.disabled));
  assert.equal(h.run('busy'),false);
});

test('timeout covers a stalled response body as well as the initial connection',async()=>{
  const h=await harness();
  h.context.fetch=async(url,options)=>({ok:true,status:200,json:()=>stalledFetch(url,options)});
  const pending=h.run("api('/calendar')");
  const rejected=assert.rejects(pending,/Revisa tu conexión/);
  await tick(); h.expire(); await rejected;
  assert.equal(h.timers.size,0);
});

test('rapid filter changes discard old data and coalesce into one latest request',async()=>{
  const h=await harness(), requests=[];
  h.context.fetch=url=>{const request=deferred();requests.push({url,...request});return request.promise;};
  const one=h.run('refresh()');
  h.element('barber').value='Jesús'; const two=h.run('refresh()');
  h.element('from').value='2026-11-03'; const three=h.run('refresh()');
  requests[0].resolve(response(calendar('obsolete')));
  await tick();
  assert.equal(h.context.frames.length,0);
  assert.equal(requests.length,2);
  assert.match(requests[1].url,/start=2026-11-03/);
  assert.match(requests[1].url,/barber=Jes%C3%BAs/);
  requests[1].resolve(response(calendar('latest')));
  await Promise.all([one,two,three]);
  assert.deepEqual([...h.context.frames],['latest']);
  assert.equal(requests.length,2);
});

test('a mutation during polling discards the pre-mutation response',async()=>{
  const h=await harness(), old=deferred(); let reads=0, writes=0;
  h.context.fetch=(url,options)=>{
    if(options.method==='POST'){writes++;return Promise.resolve(response({ok:true}));}
    return ++reads===1?old.promise:Promise.resolve(response(calendar('after-save')));
  };
  const polling=h.run('refresh()');
  const mutation=h.run("mutate(()=>api('/appointments/1/state',{method:'POST'}))");
  await tick(); old.resolve(response(calendar('before-save')));
  await Promise.all([polling,mutation]);
  assert.deepEqual([...h.context.frames],['after-save']);
  assert.equal(writes,1); assert.equal(reads,2);
  assert.equal(h.element('message').textContent,'Cambio guardado.');
});

test('a saved change followed by a failed refresh is not reported as a failed save',async()=>{
  const h=await harness(); let writes=0;
  h.context.fetch=async(url,options)=>{
    if(options.method==='POST'){writes++;return response({ok:true});}
    throw new TypeError('offline');
  };
  await h.run("mutate(()=>api('/appointments/1/state',{method:'POST'}))");
  assert.match(h.element('message').textContent,/El cambio se guardó, pero/);
  assert.equal(writes,1); assert(h.buttons.every(b=>!b.disabled));
});

test('late calendar responses cannot render after logout',async()=>{
  const h=await harness(), request=deferred(); h.context.fetch=()=>request.promise;
  const pending=h.run('refresh()'); h.run('loginView()');
  request.resolve(response(calendar('private'))); await pending;
  assert.equal(h.context.frames.length,0); assert.equal(h.run('data'),null);
});

test('invalid successful write responses do not claim the save succeeded',async()=>{
  const h=await harness();
  h.context.fetch=async()=>({ok:true,status:200,json:async()=>{throw new SyntaxError('invalid JSON');}});
  await assert.rejects(h.run("api('/appointments/1/state',{method:'POST'})"),/No pude confirmar/);
});
