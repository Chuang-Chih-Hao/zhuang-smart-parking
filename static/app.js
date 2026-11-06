'use strict';
const $ = id => document.getElementById(id);
const csrf = document.querySelector('meta[name="csrf-token"]').content;
const sensorNames = {P1:'P1 車位',P2:'P2 車位',P3:'P3 車位',P4:'P4 車位',A:'A 外側',B:'B 內側',S:'S 防夾'};
const titles = {overview:'即時總覽',passage:'通道監控',sim:'感測器模擬',vehicles:'車牌白名單',records:'進出紀錄',settings:'系統設定'};
let last = null;
let currentPage = 'overview';
let notificationTimeout;

async function api(url, method='GET', body) {
  const options = {method, headers:{'Accept':'application/json','X-CSRF-Token':csrf}};
  if (body !== undefined) {options.headers['Content-Type']='application/json'; options.body=JSON.stringify(body);}
  let res = await fetch(url, options);
  if (res.status===401) {window.location.assign('/login'); throw Error('登入已失效');}
  const data = await res.json().catch(()=>({error:'伺服器未傳回 JSON'}));
  if (!res.ok) throw Error(data.error || `HTTP ${res.status}`);
  return data;
}
function showToast(msg, isError=false) {
  const node=$('toast'); node.textContent=msg; node.className='toast shown'+(isError?' error':'');
  clearTimeout(notificationTimeout); notificationTimeout=setTimeout(()=>node.className='toast',4600);
}
const escapeHtml = str=>String(str??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
const dateText = str=>str?new Date(str).toLocaleString('zh-TW',{hour12:false}):'—';
function duration(total) { const n=Math.max(0,Math.floor(total)); const h=Math.floor(n/3600),m=Math.floor(n%3600/60),s=n%60;return `${h}時 ${m}分 ${s}秒`; }
const setText=(id,v)=>$(id).textContent=v;
function paint(s) {
  last = s;
  setText('modeBadge',s.mode==='SIM'?'◈ 模擬模式':s.device_online?'● ESP32 已連線':'● ESP32 離線');
  $('modeBadge').className='pill '+(s.mode==='SIM'?'sim':s.device_online?'good':'bad');
  setText('totalSpaces',s.capacity);setText('available',s.available);setText('occupied',s.occupied);setText('activeVisits',s.active_visits);
  setText('syncInfo',s.mode==='SIM'?'● 模擬資料':s.device_online?'● 實體即時資料':'● 硬體離線，資料可能過期');
  setText('gateDiagram','閘門：'+gateLabel(s.gate));setText('gateState',gateLabel(s.gate));
  setText('deviceState',s.mode==='SIM'?'模擬中':s.device_online?'已連線':'離線');
  for (const key of ['A','B','S']) {const el=$('state'+key);el.textContent=s.sensors[key]?'偵測到物體':'安全／未觸發';el.className=s.sensors[key]?'status-danger':'status-good';}
  document.querySelectorAll('.space').forEach(el=>{const key=el.dataset.sensor, busy=s.sensors[key]; el.classList.toggle('busy',busy);el.classList.toggle('empty-space',!busy);el.disabled=s.mode!=='SIM';el.querySelector('.space-state').textContent=busy?'已占用':'空車位';});
  $('mismatch').classList.toggle('hidden',!s.mismatch);
  setText('phaseBadge',s.phase);setText('passDirection',s.direction==='ENTRY'?'進場 A → B':s.direction==='EXIT'?'離場 B → A':'尚未判定');
  setText('passPhase',phaseLabel(s.phase));setText('permitPlate',s.permit_plate||'尚未授權');setText('lastPlate',s.last_plate||'—');
  $('passAlert').classList.toggle('hidden',!s.alert);setText('passAlert',s.alert||'');
  $('events').innerHTML=s.events.length?s.events.map(e=>`<div class="event"><span class="event-mark ${e.kind==='ALERT'?'warning':''}"></span><div><div>${escapeHtml(e.message)}</div><small>${dateText(e.at)} · ${escapeHtml(e.kind)}</small></div></div>`).join(''):'<div class="empty">目前還沒有事件</div>';
  document.querySelectorAll('.mode-choice').forEach(el=>el.classList.toggle('chosen',el.dataset.mode===s.mode));
  document.querySelectorAll('.sensor-toggle').forEach(el=>{const v=s.sensors[el.dataset.sensor];el.classList.toggle('active',v);el.disabled=s.mode!=='SIM';const tag=el.querySelector('.sensor-indicator');tag.textContent=v?'已觸發':'未觸發';});
  $('resetSim').disabled=s.mode!=='SIM';
  $('resetAllSim').disabled=s.mode!=='SIM';
  const unlocked=s.phase==='WAIT_SECOND' && !!s.permit_plate && s.permit_plate===$('passPlate').value.trim().toUpperCase();
  $('gateOpen').disabled=!unlocked;
  $('completeSimPassage').disabled=!(s.mode==='SIM' && s.gate==='OPEN' &&
    ['WAIT_SECOND','CROSSING'].includes(s.phase) && !!s.permit_plate &&
    s.permit_plate===$('passPlate').value.trim().toUpperCase() && !s.sensors.S);
  const lock=$('gateLockNotice');
  lock.classList.toggle('hidden',unlocked || s.gate==='OPEN');
  lock.textContent=s.phase==='IDLE'?'🔒 請先觸發 A 或 B，再完成白名單驗證。':'🔒 尚未通過白名單驗證，或輸入車牌與授權不一致：禁止開閘。';
}
function gateLabel(g) {return ({CLOSED:'已關閉',OPEN:'已開啟',OPENING:'開啟中',CLOSING:'關閉中',UNKNOWN:'狀態未知'})[g]||g;}
function phaseLabel(p) {return ({IDLE:'等待車輛',WAIT_SECOND:'等待驗證與通過',CROSSING:'通過中，等待清空',ALERT:'異常／需確認'})[p]||p;}
async function refresh() {try{paint(await api('/api/status'));}catch(err){if(!String(err).includes('登入'))showToast('狀態更新失敗：'+err.message,true);}}
async function change(url,body,method='POST') {try {const result=await api(url,method,body);await refresh();return result;}catch(err){showToast(err.message,true);return null;}}
function showPage(page) {currentPage=page;document.querySelectorAll('.page').forEach(el=>el.classList.toggle('active',el.id==='page-'+page));document.querySelectorAll('.nav-item').forEach(el=>el.classList.toggle('active',el.dataset.page===page));setText('pageTitle',titles[page]);document.querySelector('.sidebar').classList.remove('open');if(page==='vehicles')refreshPlates();if(page==='records')refreshRecords();}
async function refreshPlates(){try{const {items}=await api('/api/plates');$('platesTable').innerHTML=items.length?items.map(p=>`<tr><td class="mono">${escapeHtml(p.plate)}</td><td>${escapeHtml(p.note||'—')}</td><td><span class="table-pill ${p.enabled?'green-pill':'gray-pill'}">${p.enabled?'已啟用':'停用'}</span></td><td>${p.enabled?`<button class="tiny danger" data-remove="${escapeHtml(p.plate)}">停用</button>`:'—'}</td></tr>`).join(''):'<tr><td colspan="4" class="empty">尚未建立車牌</td></tr>';}catch(err){showToast(err.message,true);}}
async function refreshRecords(){try{const {items}=await api('/api/records');$('recordsTable').innerHTML=items.length?items.map(r=>`<tr><td class="mono">${escapeHtml(r.plate)}</td><td>${dateText(r.entered_at)}</td><td>${dateText(r.left_at)}</td><td>${duration(r.duration_seconds)}</td><td><span class="table-pill ${r.left_at?'gray-pill':'green-pill'}">${r.left_at?'已離場':'在場中'}</span></td></tr>`).join(''):'<tr><td colspan="5" class="empty">目前沒有任何進出紀錄</td></tr>';}catch(err){showToast(err.message,true);}}
for(const [key,label] of Object.entries(sensorNames)) {const btn=document.createElement('button');btn.type='button';btn.className='sensor-toggle';btn.dataset.sensor=key;btn.innerHTML=`<span class="sensor-title">${label}</span><span class="sensor-indicator">未觸發</span>`;btn.addEventListener('click',()=>toggleSensor(key));$('sensorButtons').append(btn);}
async function toggleSensor(sensor){if(!last||last.mode!=='SIM')return;const next=!last.sensors[sensor];await change('/api/sim/sensors',{sensor,detected:next});}
document.querySelectorAll('.space').forEach(el=>el.addEventListener('click',()=>toggleSensor(el.dataset.sensor)));
document.querySelectorAll('.nav-item').forEach(el=>el.addEventListener('click',()=>showPage(el.dataset.page)));
$('mobileMenu').addEventListener('click',()=>document.querySelector('.sidebar').classList.toggle('open'));
$('authorize').addEventListener('click',async()=>{const r=await change('/api/passage/authorize',{plate:$('passPlate').value});if(r)showToast(`${r.plate}：${r.direction==='ENTRY'?'進場':'離場'}驗證通過`);});
$('passPlate').addEventListener('input',()=>{if(last)paint(last);});
$('gateOpen').addEventListener('click',async()=>{const r=await change('/api/gate/open',{plate:$('passPlate').value});if(r)showToast('開閘操作已送出');});
$('completeSimPassage').addEventListener('click',async()=>{
  const result=await change('/api/sim/complete-passage',{});
  if(result){
    await refreshRecords();
    showToast(result.plate+(result.direction==='ENTRY'?' 進場':' 離場')+'已完成，進出紀錄已儲存');
  }
});
$('gateClose').addEventListener('click',async()=>{const r=await change('/api/gate/close',{});if(r)showToast('關閘操作已送出');});
$('resetSim').addEventListener('click',async()=>{if(confirm('確定重設模擬感測器與閘門？進出紀錄不會刪除。')){await change('/api/sim/reset',{});}});
$('resetAllSim').addEventListener('click',async()=>{
  if(!confirm('⚠ 確定清空所有模擬資料？\n這會永久刪除進出紀錄、系統事件、待處理命令及自訂白名單，並恢復預設五組示範車牌。此操作無法復原。'))return;
  const result=await change('/api/sim/reset-all',{confirmation:'RESET_SIM_ALL'});
  if(result){$('passPlate').value='';await refreshPlates();await refreshRecords();showToast('已清空所有模擬資料，並恢復預設五組白名單');}
});
$('addPlateForm').addEventListener('submit',async e=>{e.preventDefault();const r=await change('/api/plates',{plate:$('newPlate').value,note:$('plateNote').value});if(r){$('newPlate').value='';$('plateNote').value='';refreshPlates();showToast('已儲存車牌白名單');}});
$('platesTable').addEventListener('click',async e=>{const plate=e.target.dataset.remove;if(plate&&confirm(`確定停用 ${plate}？`)){const r=await change('/api/plates/'+encodeURIComponent(plate),undefined,'DELETE');if(r)refreshPlates();}});
$('refreshRecords').addEventListener('click',refreshRecords);
document.querySelectorAll('.mode-choice').forEach(el=>el.addEventListener('click',async()=>{if(!last||el.dataset.mode===last.mode)return;if(confirm('切換模式前請確認閘門已關閉且通道清空。確定切換？')){await change('/api/mode',{mode:el.dataset.mode});}}));
$('logout').addEventListener('click',async()=>{try{await api('/logout','POST');window.location.assign('/login');}catch(err){showToast(err.message,true);}});
function clock(){setText('clock',new Date().toLocaleTimeString('zh-TW',{hour12:false}));}
clock();setInterval(clock,1000);refresh();setInterval(refresh,2000);
