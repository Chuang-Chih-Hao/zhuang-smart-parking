'use strict';
const q=id=>document.getElementById(id);
async function refresh(){try{const r=await fetch('/api/public/status',{cache:'no-store'});if(!r.ok)throw Error('API 異常');const s=await r.json();const offline=s.mode==='HARDWARE'&&!s.device_online;q('publicAvailable').textContent=offline?'--':s.available;q('publicTotal').textContent=s.capacity;q('publicOccupied').textContent=s.occupied;const full=s.available===0;q('publicLabel').textContent=offline?'設備離線，車位資訊暫停更新':full?'車位已滿':'歡迎入場';q('publicLabel').className='display-indicator '+(offline||full?'full':'');q('publicStatus').textContent=offline?'⚠ ESP32 離線，資料可能過期':`資料來源：${s.mode==='SIM'?'模擬測試':'即時硬體'} · 每 3 秒更新`;}
catch(e){q('publicLabel').textContent='暫時無法取得資料';q('publicLabel').className='display-indicator full';q('publicStatus').textContent='連線異常，請稍後重試';}}
refresh();setInterval(refresh,3000);
