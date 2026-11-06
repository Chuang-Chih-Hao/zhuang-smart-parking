"""Parking business logic. Does not depend on Flask; unit-testable in isolation."""
import re
import threading
from datetime import timedelta
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from .models import Base, SystemState, Plate, Visit, Event, DeviceCommand, utcnow

SENSOR_KEYS = ('P1', 'P2', 'P3', 'P4', 'A', 'B', 'S')
CAPACITY = 4
PASSAGE_TIMEOUT_SECONDS = 50
PERMIT_SECONDS = 90
DEVICE_OFFLINE_SECONDS = 12
PLATE_RE = re.compile(r'^[A-Z0-9]{2,4}-?[A-Z0-9]{3,5}$')


def stamp(value):
    return value.isoformat(timespec='seconds') + 'Z' if value else None


def normal_plate(raw):
    if not isinstance(raw, str):
        raise ValueError('請輸入正確的車牌字串')
    value = raw.strip().upper().replace(' ', '')
    if not PLATE_RE.fullmatch(value):
        raise ValueError('車牌格式錯誤，例如 ABC-1234')
    return value


class ParkingController:
    def __init__(self, database_url, seed_demo=False):
        self.lock = threading.RLock()  # Single Gunicorn worker; DB is the source of truth.
        if database_url.startswith('postgres://'):
            database_url = database_url.replace('postgres://', 'postgresql+psycopg://', 1)
        elif database_url.startswith('postgresql://'):
            database_url = database_url.replace('postgresql://', 'postgresql+psycopg://', 1)
        self.engine = create_engine(database_url, pool_pre_ping=True)
        self.Session = sessionmaker(self.engine, expire_on_commit=False)
        Base.metadata.create_all(self.engine)
        with self.Session.begin() as db:
            if not db.get(SystemState, 1):
                db.add(SystemState(id=1, sensors={k: False for k in SENSOR_KEYS}))
            if seed_demo and not db.scalar(select(Plate.id).limit(1)):
                db.add_all([Plate(plate='ABC-1234', note='範例車輛'), Plate(plate='DEF-5678', note='範例車輛')])

    @staticmethod
    def event(db, kind, message):
        db.add(Event(kind=kind, message=message))

    @staticmethod
    def count_active(db):
        return db.scalar(select(func.count(Visit.id)).where(Visit.left_at.is_(None))) or 0

    @staticmethod
    def used_slots(db, state):
        # Physical occupancy and confirmed crossings are independent measurements.
        physical = sum(bool(state.sensors.get(f'P{i}', False)) for i in range(1, 5))
        active = ParkingController.count_active(db)
        pending = int(bool(state.permit_plate and state.passage_direction == 'ENTRY'))
        return min(CAPACITY, max(physical, active) + pending)

    @staticmethod
    def clear_passage(state):
        state.phase = 'IDLE'
        state.first_sensor = None
        state.passage_direction = None
        state.started_at = None
        state.permit_plate = None
        state.permit_expires = None

    def expire(self, db, st):
        now = utcnow()
        if st.permit_plate and st.permit_expires and st.permit_expires < now:
            st.permit_plate = None
            st.permit_expires = None
            st.alert = '通行授權已過期，請重新辨識車牌'
            self.event(db, 'EXPIRED', st.alert)
        if st.phase in ('WAIT_SECOND', 'CROSSING', 'ALERT') and st.started_at and (now-st.started_at).total_seconds() > PASSAGE_TIMEOUT_SECONDS:
            if not st.sensors['A'] and not st.sensors['B'] and not st.sensors['S']:
                self.event(db, 'TIMEOUT', '通道流程超時，已清除未完成的通行事件')
                self.clear_passage(st)
            else:
                st.phase = 'ALERT'
                st.alert = '通道逾時或有物體滯留，請人工檢查'

    def status(self):
        with self.lock, self.Session.begin() as db:
            st = db.get(SystemState, 1)
            self.expire(db, st)
            occupied = sum(bool(st.sensors.get(f'P{i}', False)) for i in range(1, 5))
            active = self.count_active(db)
            used = self.used_slots(db, st)
            connected = bool(st.device_last_seen and (utcnow()-st.device_last_seen).total_seconds() < DEVICE_OFFLINE_SECONDS)
            events = db.scalars(select(Event).order_by(Event.id.desc()).limit(18)).all()
            return {
                'mode': st.mode, 'gate': st.gate, 'sensors': dict(st.sensors),
                'direction': st.passage_direction, 'phase': st.phase,
                'permit_plate': st.permit_plate, 'last_plate': st.last_plate,
                'alert': st.alert, 'capacity': CAPACITY, 'occupied': occupied,
                'active_visits': active, 'available': CAPACITY-used,
                'device_online': connected, 'device_last_seen': stamp(st.device_last_seen),
                'mismatch': (occupied != active),
                'events': [{'id': x.id, 'kind': x.kind, 'message': x.message, 'at': stamp(x.created_at)} for x in events],
            }

    def public_status(self):
        s = self.status()
        return {k: s[k] for k in ('capacity', 'occupied', 'available', 'mode', 'device_online')}

    def plates(self):
        with self.Session() as db:
            rows = db.scalars(select(Plate).order_by(Plate.plate)).all()
            return [{'id':p.id,'plate':p.plate,'note':p.note,'enabled':p.enabled} for p in rows]

    def add_plate(self, raw, note=''):
        plate = normal_plate(raw)
        if not isinstance(note,str) or len(note)>120:
            raise ValueError('備註不得超過 120 字')
        with self.lock, self.Session.begin() as db:
            exists = db.scalar(select(Plate).where(Plate.plate==plate))
            if exists:
                exists.enabled = True
                exists.note = note
            else:
                db.add(Plate(plate=plate, note=note, enabled=True))
            self.event(db, 'PLATE', f'白名單已新增或啟用 {plate}')
        return plate

    def remove_plate(self, raw):
        plate = normal_plate(raw)
        with self.lock, self.Session.begin() as db:
            row = db.scalar(select(Plate).where(Plate.plate==plate))
            if not row:
                raise ValueError('車牌不在白名單')
            row.enabled = False
            self.event(db, 'PLATE', f'白名單已停用 {plate}')

    def records(self):
        with self.Session() as db:
            rows = db.scalars(select(Visit).order_by(Visit.id.desc()).limit(150)).all()
            return [{'id':x.id,'plate':x.plate,'entered_at':stamp(x.entered_at),
                     'left_at':stamp(x.left_at), 'duration_seconds':int(((x.left_at or utcnow())-x.entered_at).total_seconds())} for x in rows]

    def mode(self, mode):
        if mode not in ('SIM','HARDWARE'):
            raise ValueError('模式只能是 SIM 或 HARDWARE')
        with self.lock, self.Session.begin() as db:
            st=db.get(SystemState,1)
            if st.mode == mode:
                return
            if st.gate != 'CLOSED' or st.sensors.get('A') or st.sensors.get('B') or st.sensors.get('S'):
                raise ValueError('切換前必須確認閘門關閉、通道安全且無車輛')
            st.mode=mode
            st.sensors={k:False for k in SENSOR_KEYS}
            st.gate='CLOSED' if mode=='SIM' else 'UNKNOWN'
            st.alert=None
            self.clear_passage(st)
            self.event(db,'MODE',f'已切換為 {mode} 模式')

    def reset_sim(self):
        with self.lock, self.Session.begin() as db:
            st=db.get(SystemState,1)
            if st.mode!='SIM':
                raise ValueError('只有模擬模式可以重設')
            st.sensors={k:False for k in SENSOR_KEYS}
            st.gate='CLOSED'
            st.alert=None
            self.clear_passage(st)
            self.event(db,'SIM','已重設模擬感測器與閘門（進出紀錄保留）')

    def apply_sensor(self, db, st, key, detected, track=True):
        if key not in SENSOR_KEYS or type(detected) is not bool:
            raise ValueError('感測器名稱或布林狀態不合法')
        old=st.sensors.get(key)
        if old == detected:
            return
        st.sensors={**st.sensors, key:detected}
        if key in ('A','B') and track:
            if detected:
                if st.phase == 'IDLE':
                    st.first_sensor=key
                    st.passage_direction='ENTRY' if key=='A' else 'EXIT'
                    st.started_at=utcnow()
                    st.phase='WAIT_SECOND'
                    st.alert=None
                    self.event(db,'DETECT',f'{key} 先觸發，疑似{("進場" if key=="A" else "離場")}')
                elif st.phase == 'WAIT_SECOND' and st.first_sensor != key:
                    if st.permit_plate and st.gate == 'OPEN' and st.permit_expires and st.permit_expires>=utcnow():
                        st.phase='CROSSING'
                        self.event(db,'CROSSING',f'{st.permit_plate} 通過閘門：{st.first_sensor} → {key}')
                    else:
                        st.phase='ALERT'
                        st.alert='通行未授權或閘門未開啟，事件不計入進出紀錄'
                        self.event(db,'ALERT',st.alert)
            elif st.phase == 'CROSSING' and not st.sensors['A'] and not st.sensors['B']:
                self.finish_crossing(db,st)
            elif st.phase == 'ALERT' and not st.sensors['A'] and not st.sensors['B'] and not st.sensors['S']:
                self.clear_passage(st)
        if key=='S' and detected:
            self.event(db,'SAFETY','防夾安全區偵測到障礙物：禁止關閉')
        self.event(db,'SENSOR',f'{key}：{("偵測到物體" if detected else "已清空")}')

    def finish_crossing(self, db, st):
        if not st.permit_plate or st.phase!='CROSSING' or st.sensors.get('S'):
            if st.sensors.get('S'):
                st.alert='安全區仍受阻，通行尚未確認'
            return
        plate=st.permit_plate
        if st.passage_direction=='ENTRY':
            if db.scalar(select(Visit.id).where(Visit.plate==plate,Visit.left_at.is_(None))):
                st.alert='此車牌已有在場紀錄，禁止重複進場'
                self.event(db,'ALERT',st.alert)
                self.clear_passage(st)
                return
            db.add(Visit(plate=plate,entered_at=utcnow()))
            self.event(db,'ENTRY',f'{plate} 進場成功，已記錄進場時間')
        elif st.passage_direction=='EXIT':
            visit=db.scalar(select(Visit).where(Visit.plate==plate,Visit.left_at.is_(None)).order_by(Visit.id.desc()))
            if not visit:
                st.alert='找不到對應的在場車牌，禁止產生離場紀錄'
                self.event(db,'ALERT',st.alert)
                self.clear_passage(st)
                return
            visit.left_at=utcnow()
            self.event(db,'EXIT',f'{plate} 離場成功，已計算停留時間')
        st.alert=None
        self.clear_passage(st)

    def sim_sensor(self,key,detected):
        with self.lock,self.Session.begin() as db:
            st=db.get(SystemState,1)
            if st.mode!='SIM':
                raise ValueError('實體模式不允許網頁模擬感測器')
            self.expire(db,st)
            self.apply_sensor(db,st,key,detected)
            if st.phase=='CROSSING' and not st.sensors['A'] and not st.sensors['B'] and not st.sensors['S']:
                self.finish_crossing(db,st)

    def authorize(self,raw):
        plate=normal_plate(raw)
        with self.lock,self.Session.begin() as db:
            st=db.get(SystemState,1)
            self.expire(db,st)
            if st.phase!='WAIT_SECOND' or not st.passage_direction:
                raise ValueError('請先觸發 A（進場）或 B（離場）感測器')
            direction=st.passage_direction
            if direction=='ENTRY':
                allowed=db.scalar(select(Plate).where(Plate.plate==plate,Plate.enabled.is_(True)))
                if not allowed:
                    raise ValueError('此車牌不在允許入場的白名單')
                if db.scalar(select(Visit.id).where(Visit.plate==plate,Visit.left_at.is_(None))):
                    raise ValueError('此車牌已有在場紀錄')
                if self.used_slots(db,st)>=CAPACITY and st.permit_plate!=plate:
                    raise ValueError('停車場已滿，無法入場')
            else:
                if not db.scalar(select(Visit.id).where(Visit.plate==plate,Visit.left_at.is_(None))):
                    raise ValueError('查無此車牌的在場紀錄')
            st.permit_plate=plate
            st.permit_expires=utcnow()+timedelta(seconds=PERMIT_SECONDS)
            st.last_plate=plate
            st.alert=None
            self.event(db,'AUTHORIZE',f'{plate} {("進場" if direction=="ENTRY" else "離場")}驗證成功')
            return {'plate':plate,'direction':direction,'valid_seconds':PERMIT_SECONDS}

    def gate_action(self,action):
        if action not in ('OPEN','CLOSE'):
            raise ValueError('閘門操作錯誤')
        with self.lock,self.Session.begin() as db:
            st=db.get(SystemState,1)
            self.expire(db,st)
            if action=='OPEN':
                if st.phase!='WAIT_SECOND' or not st.permit_plate or not st.permit_expires or st.permit_expires<utcnow():
                    raise ValueError('必須先完成有效車牌授權才能開閘')
            else:
                if any(st.sensors.get(k) for k in ('A','B','S')):
                    raise ValueError('A / B / S 尚有物體，禁止關閉閘門')
                if st.phase=='CROSSING':
                    raise ValueError('通行尚未完成，禁止關閉閘門')
            if st.mode=='SIM':
                st.gate='OPEN' if action=='OPEN' else 'CLOSED'
                self.event(db,'GATE',f'模擬閘門：{("開啟" if action=="OPEN" else "關閉")}')
                return {'mode':'SIM','gate':st.gate}
            if not st.device_last_seen or (utcnow()-st.device_last_seen).total_seconds()>DEVICE_OFFLINE_SECONDS:
                raise ValueError('ESP32 已離線，不能遠端操控閘門')
            if st.gate not in ('CLOSED','OPEN'):
                raise ValueError('等待閘門目前的動作完成')
            if action=='OPEN' and st.gate!='CLOSED':
                raise ValueError('閘門目前不是關閉狀態')
            if action=='CLOSE' and st.gate!='OPEN':
                raise ValueError('閘門目前不是開啟狀態')
            st.gate='OPENING' if action=='OPEN' else 'CLOSING'
            cmd=DeviceCommand(action=action,status='PENDING')
            db.add(cmd)
            self.event(db,'COMMAND',f'已排入 {action} 命令，等待 ESP32 回覆')
            db.flush()
            return {'mode':'HARDWARE','command_id':cmd.id,'gate':st.gate}

    def accept_boot(self,db,st,payload):
        boot_id=payload.get('boot_id')
        if not isinstance(boot_id,str) or not (8<=len(boot_id)<=64) or not re.fullmatch(r'[A-Za-z0-9_-]+',boot_id):
            raise ValueError('設備回報缺少有效的 boot_id')
        if st.device_boot_id != boot_id:
            st.device_boot_id=boot_id
            st.device_seq=-1
            self.clear_passage(st)
            st.gate='UNKNOWN'
            st.alert='ESP32 啟動或重新連線，通行流程已重置；請重新確認車道安全'
            for cmd in db.scalars(select(DeviceCommand).where(DeviceCommand.status.in_(['PENDING','SENT']))).all():
                cmd.status='FAILED'
                cmd.finished_at=utcnow()
                cmd.result='device rebooted'
            self.event(db,'DEVICE','偵測到新的 ESP32 啟動識別碼，已取消舊閘門命令')

    def device_state(self,payload):
        if not isinstance(payload,dict) or not isinstance(payload.get('sequence'),int) or type(payload['sequence']) is bool or payload['sequence']<0:
            raise ValueError('設備回報需包含非負整數 sequence')
        incoming=payload.get('sensors',{})
        if not isinstance(incoming,dict) or any(k not in SENSOR_KEYS or type(v) is not bool for k,v in incoming.items()):
            raise ValueError('設備感測器格式不合法')
        gate=payload.get('gate')
        if gate is not None and gate not in ('OPEN','CLOSED','OPENING','CLOSING','UNKNOWN'):
            raise ValueError('閘門狀態不合法')
        with self.lock,self.Session.begin() as db:
            st=db.get(SystemState,1)
            if st.mode!='HARDWARE':
                raise ValueError('目前不是實體模式')
            self.accept_boot(db,st,payload)
            if payload['sequence']<=st.device_seq:
                return {'accepted':False,'reason':'old_sequence'}
            st.device_seq=payload['sequence']
            st.device_last_seen=utcnow()
            for k,v in incoming.items():
                # A/B edges MUST arrive via device/events to preserve ordering.
                self.apply_sensor(db,st,k,v,track=(k not in ('A','B')))
            if gate is not None:
                st.gate=gate
            return {'accepted':True}

    def device_event(self,payload):
        if not isinstance(payload,dict) or not isinstance(payload.get('sequence'),int) or type(payload['sequence']) is bool or payload['sequence']<0:
            raise ValueError('事件需包含 sequence')
        key=payload.get('sensor')
        detected=payload.get('detected')
        if key not in SENSOR_KEYS or type(detected) is not bool:
            raise ValueError('事件需包含有效 sensor / detected')
        with self.lock,self.Session.begin() as db:
            st=db.get(SystemState,1)
            if st.mode!='HARDWARE':
                raise ValueError('目前不是實體模式')
            self.accept_boot(db,st,payload)
            if payload['sequence']<=st.device_seq:
                return {'accepted':False,'reason':'old_sequence'}
            if payload['sequence']>st.device_seq+1 and st.device_seq>=0:
                st.alert='偵測到設備訊息序列缺口，請檢查網路與事件順序'
                self.event(db,'ALERT',st.alert)
            st.device_seq=payload['sequence']
            st.device_last_seen=utcnow()
            self.expire(db,st)
            self.apply_sensor(db,st,key,detected)
            if st.phase=='CROSSING' and not st.sensors['A'] and not st.sensors['B'] and not st.sensors['S']:
                self.finish_crossing(db,st)
            return {'accepted':True}

    def device_commands(self):
        with self.lock,self.Session.begin() as db:
            st=db.get(SystemState,1)
            if st.mode!='HARDWARE':
                return []
            now=utcnow()
            cmds=db.scalars(select(DeviceCommand).where(DeviceCommand.status.in_(['PENDING','SENT'])).order_by(DeviceCommand.id).limit(3)).all()
            result=[]
            for c in cmds:
                if c.sent_at and (now-c.sent_at).total_seconds()<3:
                    continue
                c.sent_at=now
                c.status='SENT'
                result.append({'id':c.id,'action':c.action})
            return result

    def device_ack(self,cmd_id,success,gate,result=''):
        if type(cmd_id) is not int or type(success) is not bool or gate not in ('OPEN','CLOSED','UNKNOWN'):
            raise ValueError('ACK 格式不合法')
        with self.lock,self.Session.begin() as db:
            st=db.get(SystemState,1)
            if st.mode!='HARDWARE':
                raise ValueError('目前不是實體模式')
            cmd=db.get(DeviceCommand,cmd_id)
            if not cmd:
                raise ValueError('找不到命令')
            if cmd.status in ('DONE','FAILED'):
                return {'accepted':True,'duplicate':True}
            cmd.status='DONE' if success else 'FAILED'
            cmd.result=str(result)[:160]
            cmd.finished_at=utcnow()
            st.gate=gate
            if not success:
                st.alert='閘門命令遭 ESP32 拒絕：'+cmd.result
            self.event(db,'ACK',f'命令 #{cmd.id} {cmd.status}，閘門狀態：{gate}')
            return {'accepted':True}
