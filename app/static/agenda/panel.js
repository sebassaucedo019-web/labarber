"use strict";
const $ = id => document.getElementById(id);
const escapeText = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const h = escapeText;
let user = null, data = null, selected = '', mode = 'day', busy = false, loading = null, consentId = null, revision = 0;
const dateOf = value => value.slice(0, 10);
const dayObject = value => new Date(`${dateOf(value)}T12:00:00`);
const dayName = value => dayObject(value).toLocaleDateString('es-MX', {weekday:'long', day:'numeric', month:'long'});
const clock = value => { const [hour, minute] = value.slice(11,16).split(':'); return `${Number(hour)%12||12}:${minute}`; };
const period = value => Number(value.slice(11,13)) < 12 ? 'a. m.' : 'p. m.';
function say(message) { $('message').textContent = message; }
function loginView() { revision++; user = null; data = null; selected=''; $('from').value=''; $('barber').replaceChildren(); $('block-barber').replaceChildren(); $('workspace').hidden = true; $('login-view').hidden = false; $('content').replaceChildren(); $('notice-list').replaceChildren(); }
async function api(path, options = {}) {
  const response = await fetch(`/api/agenda${path}`, {credentials:'same-origin', cache:'no-store', ...options,
    headers:{'Content-Type':'application/json', ...(user ? {'X-CSRF-Token':user.csrf} : {}), ...options.headers}});
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401 && path !== '/login') loginView();
    throw new Error(typeof body.detail === 'string' ? body.detail : 'No se pudo completar la solicitud.');
  }
  return body;
}
async function mutate(task) {
  if (busy) return;
  busy = true; say('');
  document.querySelectorAll('button').forEach(b => b.disabled = true);
  try { await task(); await refresh(true); say('Cambio guardado.'); }
  catch (error) { say(error.message); }
  finally { busy = false; document.querySelectorAll('button').forEach(b => b.disabled = false); }
}
function card(a, nextId) {
  const actions = [];
  const started = a.starts_at <= data.now;
  const minutesUntil = (Date.parse(`${a.starts_at}Z`) - Date.parse(`${data.now}Z`)) / 60000;
  if (a.status === 'confirmed' && dateOf(a.starts_at)===dateOf(data.now) && minutesUntil<=120) actions.push(['arrived','Cliente llegó']);
  if (['confirmed','arrived'].includes(a.status) && started) actions.push(['in_service','Iniciar atención']);
  if (['confirmed','arrived','in_service'].includes(a.status) && started) actions.push(['completed','Marcar como atendido']);
  if (a.status === 'arrived') actions.push(['confirmed','Deshacer llegada']);
  if (a.status === 'confirmed' && minutesUntil<=-15) actions.push(['no_show','No asistió']);
  const index = Math.max(0, data.barbers.indexOf(a.barber)) % 3;
  return `<article class="card ${h(a.status)} ${a.id===nextId?'next':''}"><div class="card-top"><time class="time" datetime="${h(a.starts_at)}"><strong>${clock(a.starts_at)}</strong><span>${period(a.starts_at)} · 30 min</span></time><div class="person"><h3>${h(a.customer)}</h3><p class="service">${h(a.service)}</p><div class="badges"><span class="badge barber c${index}">${h(a.barber)}</span><span class="badge status">${h(a.label)}</span>${a.id===nextId?'<span class="badge">Siguiente</span>':''}</div></div></div>
  ${a.completed_at?`<p class="consent">Finalizó a las ${clock(a.completed_at)} ${period(a.completed_at)}</p>`:''}
  <div class="actions">${actions.map(([state,label])=>`<button ${state==='completed'?'class="primary"':''} data-action="state" data-id="${a.id}" data-state="${state}">${label}</button>`).join('')}</div>
  ${['confirmed','arrived','in_service'].includes(a.status)?`<div class="actions"><button class="minor" data-action="consent" data-id="${a.id}">${a.reminder_consent?'Revocar permiso de recordatorios':'Registrar permiso de recordatorios'}</button></div>`:''}</article>`;
}
function render() {
  $('business').textContent = data.business;
  $('scope-label').textContent = user.scope==='all'?'Vista general del equipo':`Tu agenda, ${user.scope}`;
  $('admin').hidden = user.scope !== 'all'; $('barber-filter').hidden = user.scope !== 'all';
  const end = new Date(`${data.start}T12:00:00`); const days = Array.from({length:7}, (_, i) => { const d=new Date(end); d.setDate(end.getDate()+i); return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`; });
  if (!days.includes(selected)) selected = days[0];
  const rows = mode==='week'?data.appointments:data.appointments.filter(a=>dateOf(a.starts_at)===selected);
  $('summary').innerHTML = [['Por atender', rows.filter(a=>['confirmed','arrived'].includes(a.status)).length],['Esperando',rows.filter(a=>a.status==='arrived').length],['Atendidos',rows.filter(a=>a.status==='completed').length]].map(([label,count])=>`<div class="metric"><strong>${count}</strong><span>${label}</span></div>`).join('');
  $('days').innerHTML = days.map(day=>`<button class="day ${data.appointments.some(a=>dateOf(a.starts_at)===day && a.status!=='cancelled')?'has':''}" data-day="${day}" aria-pressed="${day===selected}" aria-label="${h(dayName(day))}"><span>${dayObject(day).toLocaleDateString('es-MX',{weekday:'short'})}</span><strong>${dayObject(day).getDate()}</strong><i aria-hidden="true"></i></button>`).join('');
  const next = data.appointments.find(a=>a.status==='confirmed' && a.starts_at>=data.now)?.id;
  $('content').innerHTML = (mode==='week'?days:[selected]).map(day=>{
    const appointments = data.appointments.filter(a=>dateOf(a.starts_at)===day);
    return `<section><div class="day-title"><h2>${h(dayName(day))}</h2><span>${appointments.length} cita${appointments.length===1?'':'s'}</span></div><div class="cards">${appointments.length?appointments.map(a=>card(a,next)).join(''):'<div class="empty">Sin citas este día</div>'}</div></section>`;
  }).join('');
  const slots = data.available.filter(s=>dateOf(s.starts_at)===selected);
  const blocks = data.blocks.filter(b=>dateOf(b.starts_at)===selected);
  $('slots').innerHTML = `<p class="small">${h(dayName(selected))} · Los horarios reservados no se adelantan automáticamente.</p>` + data.barbers.filter(b=>!$('barber').value||$('barber').value===b).map(barber=>`<div class="slot-group"><h3>${h(barber)}</h3><div class="slot-list">${slots.filter(s=>s.barber===barber).map(s=>`<span class="slot">${h(s.starts_at.slice(11,16))}</span>`).join('')||'<p class="small">Sin horarios disponibles</p>'}</div></div>`).join('') + blocks.map(b=>`<div class="block"><p>${h(b.barber)} · ${h(b.starts_at.slice(11,16))}–${h(b.ends_at.slice(11,16))}</p><p class="small">${h(b.reason)}</p>${user.scope==='all'?`<button data-unblock="${b.id}" class="quiet">Quitar bloqueo</button>`:''}</div>`).join('');
  $('notice-mode').textContent = data.automatic_notices_enabled?'Avisos automáticos habilitados. Enviada significa aceptada por Meta; entregada requiere su confirmación.':'Avisos automáticos desactivados. No se envían recordatorios ni avisos de siguiente turno.';
  $('updated').textContent = `Actualizada ${clock(data.now)} ${period(data.now)}`;
  $('daily').setAttribute('aria-pressed', String(mode==='day')); $('weekly').setAttribute('aria-pressed', String(mode==='week'));
}
async function loadNotices() {
  if (!user || user.scope!=='all' || !$('notices').open) return;
  const currentRevision=revision;
  const labels = {pending:'Pendiente',sending:'En proceso',sent:'Enviada',delivered:'Entregada',read:'Leída',failed:'Fallida',cancelled:'Cancelada',uncertain:'Resultado incierto'};
  const kinds = {reminder:'Recordatorio',next_turn:'Próximo turno',appointment:'Cambio de cita'};
  const rows = await api('/notifications');
  if(!user||currentRevision!==revision) return;
  $('notice-list').innerHTML = rows.map(n=>`<div class="notice"><strong>${h(n.customer)} · ${h(n.barber)}</strong><span class="notice-state">${h(labels[n.status]||n.status)}</span><p>${h(kinds[n.kind]||n.kind)} · ${n.attempts} intento${n.attempts===1?'':'s'}</p>${n.error?`<p>Error: ${h(n.error)}</p>`:''}</div>`).join('')||'<p class="small">Todavía no hay notificaciones.</p>';
}
async function refresh(force=false) {
  if (!user || (busy&&!force)) return;
  if (loading) { await loading; return refresh(force); }
  let release;
  loading = new Promise(resolve=>{release=resolve;});
  const currentRevision=revision;
  try {
    const query = new URLSearchParams(); if ($('from').value) query.set('start',$('from').value); if ($('barber').value) query.set('barber',$('barber').value);
    const loaded = await api(`/calendar?${query}`);
    if(!user||currentRevision!==revision) return;
    data = loaded;
    if (!$('from').value) $('from').value = data.start;
    const current = $('barber').value;
    $('barber').innerHTML = '<option value="">Todo el equipo</option>'+data.barbers.map(b=>`<option value="${h(b)}">${h(b)}</option>`).join('');
    $('barber').value = current;
    if (!$('block-barber').options.length) $('block-barber').innerHTML=data.barbers.map(b=>`<option value="${h(b)}">${h(b)}</option>`).join('');
    render(); await loadNotices();
  } finally { loading=null; release(); }
}
async function boot() {
  try { user = await api('/session'); $('login-view').hidden=true; $('workspace').hidden=false; await refresh(); }
  catch(error) { if (user) say(error.message); }
}
$('login-form').addEventListener('submit', async e=>{
  e.preventDefault(); const form=e.currentTarget; const button=form.querySelector('button'); button.disabled=true; say('');
  try { await api('/login',{method:'POST',body:JSON.stringify(Object.fromEntries(new FormData(form)))}); form.reset(); await boot(); }
  catch(error){say(error.message);}finally{button.disabled=false;}
});
$('logout').addEventListener('click',async()=>{try{await api('/logout',{method:'POST'}); loginView();say('Sesión cerrada.');}catch(e){say(e.message);}});
$('daily').addEventListener('click',()=>{mode='day';render();}); $('weekly').addEventListener('click',()=>{mode='week';render();});
$('days').addEventListener('click',e=>{const b=e.target.closest('[data-day]');if(b){selected=b.dataset.day;render();}});
for(const id of ['from','barber']) $(id).addEventListener('change',()=>refresh().catch(e=>say(e.message)));
$('refresh').addEventListener('click',()=>refresh().then(()=>say('Agenda actualizada.')).catch(e=>say(e.message)));
$('notices').addEventListener('toggle',()=>loadNotices().catch(e=>say(e.message)));
$('content').addEventListener('click',e=>{
  const button=e.target.closest('[data-action]'); if(!button || busy) return;
  const row=data.appointments.find(a=>a.id===Number(button.dataset.id)); if(!row) return;
  if(button.dataset.action==='state') {
    const target=button.dataset.state;
    if (['completed','no_show','confirmed'].includes(target) && !confirm(`${button.textContent}: ${row.customer}, ${clock(row.starts_at)} ${period(row.starts_at)}. ¿Confirmas?`)) return;
    mutate(()=>api(`/appointments/${row.id}/state`,{method:'POST',body:JSON.stringify({state:target,expected_status:row.status})}));
  } else if(row.reminder_consent) {
    if(confirm('¿Revocar los recordatorios de esta cita?')) mutate(()=>api(`/appointments/${row.id}/consent`,{method:'POST',body:JSON.stringify({enabled:false,source:'Revocación registrada por el equipo desde la agenda'})}));
  } else { consentId=row.id; $('consent-form').reset(); $('consent-dialog').showModal(); }
});
$('consent-form').addEventListener('submit',e=>{e.preventDefault();const source=new FormData(e.currentTarget).get('source');$('consent-dialog').close();mutate(()=>api(`/appointments/${consentId}/consent`,{method:'POST',body:JSON.stringify({enabled:true,source})}));});
$('close-consent').addEventListener('click',()=>$('consent-dialog').close());
$('block-form').addEventListener('submit',e=>{e.preventDefault();const form=e.currentTarget;const f=Object.fromEntries(new FormData(form));mutate(async()=>{await api('/blocks',{method:'POST',body:JSON.stringify({barber:f.barber,starts_at:f.start,ends_at:f.end,reason:f.reason})});form.reset();});});
$('slots').addEventListener('click',e=>{const b=e.target.closest('[data-unblock]');if(b&&confirm('¿Quitar este bloqueo?'))mutate(()=>api(`/blocks/${b.dataset.unblock}`,{method:'DELETE'}));});
setInterval(()=>{if(user&&!document.hidden&&!busy&&!$('consent-dialog').open&&!document.activeElement?.matches('input,select,textarea')) refresh().catch(e=>say(`No se pudo actualizar: ${e.message}`));},15000);
document.addEventListener('visibilitychange',()=>{if(!document.hidden&&user&&!busy)refresh().catch(e=>say(e.message));});
let installPrompt;
window.addEventListener('beforeinstallprompt',e=>{e.preventDefault();installPrompt=e;$('install').hidden=false;});
$('install').addEventListener('click',async()=>{if(installPrompt){await installPrompt.prompt();installPrompt=null;$('install').hidden=true;}});
if('serviceWorker' in navigator) navigator.serviceWorker.register('/panel-sw.js',{scope:'/'}).catch(()=>{});
boot();
