"""ESP32 MicroPython hardware adapter. Requires wiring verification first.

Important: TLS server-certificate validation varies by MicroPython build;
validate TLS or use a trusted local gateway before deploying outside a lab.
"""
import network
import ujson
import urequests
import urandom
from time import sleep_ms, ticks_ms, ticks_diff
from config import SENSOR_PINS, SERVO_PIN, HEARTBEAT_MS
from secrets import WIFI_SSID, WIFI_PASSWORD, API_BASE_URL, DEVICE_TOKEN
from sensors import Sensors
from gate import Gate

if SERVO_PIN is None or any(x is None for x in SENSOR_PINS.values()):
    raise RuntimeError('GPIO 尚未確認，硬體程式停止，避免誤動作')
if not API_BASE_URL.startswith('https://'):
    raise RuntimeError('遠端 API 必須使用 HTTPS')
if DEVICE_TOKEN.startswith('REPLACE_') or WIFI_SSID.startswith('REPLACE_'):
    raise RuntimeError('請先設定 firmware/secrets.py')

wlan=network.WLAN(network.STA_IF)
wlan.active(True)
wlan.connect(WIFI_SSID,WIFI_PASSWORD)
for _ in range(80):
    if wlan.isconnected(): break
    sleep_ms(250)
if not wlan.isconnected():
    raise RuntimeError('Wi-Fi 連線失敗')

sensors=Sensors()
gate=Gate(sensors)
seq=0
boot_id="%08x%08x" % (urandom.getrandbits(32),urandom.getrandbits(32))
pending=[]
last_beat=ticks_ms()
last_poll=ticks_ms()
seen_cmd_ids=set()


def api(method,path,data=None):
    headers={'Authorization':'Bearer '+DEVICE_TOKEN,'Accept':'application/json'}
    if data is not None: headers['Content-Type']='application/json'
    url=API_BASE_URL.rstrip('/')+path
    response=None
    try:
        if method=='GET': response=urequests.get(url,headers=headers)
        else: response=urequests.post(url,data=ujson.dumps(data),headers=headers)
        if response.status_code>=400:
            raise OSError('API 回覆 '+str(response.status_code))
        return response.json()
    finally:
        if response is not None: response.close()


def next_seq():
    global seq
    seq+=1
    return seq


while True:
    # Physical debounce and safety controls remain active regardless of internet.
    for key,detected in sensors.poll():
        pending.append({'sequence':next_seq(),'boot_id':boot_id,'sensor':key,'detected':detected})
    gate.safety_tick()
    now=ticks_ms()
    try:
        # Transmit edges in exact order. Do not send a later snapshot before edges.
        while pending:
            result=api('POST','/api/device/events',pending[0])
            if not result.get('accepted'):
                raise OSError('事件未被接受：'+str(result))
            pending.pop(0)
        if ticks_diff(now,last_beat)>=HEARTBEAT_MS:
            api('POST','/api/device/state',{'sequence':next_seq(), 'boot_id':boot_id, 'sensors':sensors.stable, 'gate':gate.state})
            last_beat=now
        if ticks_diff(now,last_poll)>=950:
            result=api('GET','/api/device/commands')
            for command in result.get('items',[]):
                cmd_id=command['id']; action=command['action']
                if cmd_id in seen_cmd_ids:
                    continue
                ok=False
                if action=='OPEN': ok=gate.open()
                elif action=='CLOSE': ok=gate.close()
                message='已執行' if ok else '偵測到障礙物，禁止關閘'
                try:
                    api('POST','/api/device/ack',{'id':cmd_id,'success':ok,'gate':gate.state,'result':message})
                    seen_cmd_ids.add(cmd_id)
                except Exception as e:
                    print('ACK 發送失敗，等待重試：',e)
            last_poll=now
    except Exception as exc:
        # Do NOT close gate automatically on failed network requests.
        print('網路/服務異常：',exc)
        sleep_ms(400)
    sleep_ms(35)
