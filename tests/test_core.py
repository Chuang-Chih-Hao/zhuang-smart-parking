import tempfile
from pathlib import Path
from datetime import timedelta
from parking.models import SystemState, utcnow
import pytest
from parking.core import ParkingController, DEFAULT_DEMO_PLATES

@pytest.fixture
def ctl():
    with tempfile.TemporaryDirectory() as d:
        c=ParkingController('sqlite:///'+str(Path(d)/'test.db'),seed_demo=True)
        yield c

def step(c,key,value):
    c.sim_sensor(key,value)

def auth_open(c,plate):
    c.authorize(plate)
    c.gate_action('OPEN')

def entry(c,plate='ABC-1234'):
    step(c,'A',True)
    auth_open(c,plate)
    step(c,'B',True)
    step(c,'A',False)
    step(c,'B',False)
    c.gate_action('CLOSE')

def exit(c,plate='ABC-1234'):
    step(c,'B',True)
    auth_open(c,plate)
    step(c,'A',True)
    step(c,'B',False)
    step(c,'A',False)
    c.gate_action('CLOSE')

def test_entry_exit_and_time(ctl):
    entry(ctl)
    assert ctl.status()['active_visits']==1
    assert ctl.status()['available']==3
    exit(ctl)
    assert ctl.status()['active_visits']==0
    records=ctl.records()
    assert records[0]['plate']=='ABC-1234'
    assert records[0]['left_at'] is not None
    assert records[0]['duration_seconds'] >= 0

def test_unlisted_plate_denied(ctl):
    step(ctl,'A',True)
    with pytest.raises(ValueError,match='白名單'):
        ctl.authorize('XYZ-9999')
    with pytest.raises(ValueError,match='授權'):
        ctl.gate_action('OPEN')

def test_safety_blocks_closing(ctl):
    step(ctl,'A',True)
    auth_open(ctl,'ABC-1234')
    step(ctl,'S',True)
    with pytest.raises(ValueError,match='禁止關閉'):
        ctl.gate_action('CLOSE')

def test_unapproved_crossing_does_not_create_visit(ctl):
    step(ctl,'A',True)
    step(ctl,'B',True)
    step(ctl,'A',False)
    step(ctl,'B',False)
    assert ctl.status()['active_visits']==0

def test_occupancy_and_reservation(ctl):
    step(ctl,'P1',True)
    assert ctl.status()['occupied']==1
    assert ctl.status()['available']==3
    step(ctl,'A',True)
    ctl.authorize('ABC-1234')
    assert ctl.status()['available']==2

def test_duplicate_entry_denied(ctl):
    entry(ctl)
    step(ctl,'A',True)
    with pytest.raises(ValueError,match='在場紀錄'):
        ctl.authorize('ABC-1234')

def test_hardware_rejects_browser_sim(ctl):
    ctl.mode('HARDWARE')
    with pytest.raises(ValueError,match='實體模式'):
        ctl.sim_sensor('A',True)
    assert ctl.device_event({'sequence':1,'boot_id':'boot123456','sensor':'A','detected':True})['accepted']
    assert ctl.status()['direction']=='ENTRY'
    assert not ctl.device_event({'sequence':1,'boot_id':'boot123456','sensor':'B','detected':True})['accepted']

def test_safe_gate_never_close_when_ab_occupied(ctl):
    step(ctl,'B',True)
    with pytest.raises(ValueError,match='禁止關閉'):
        ctl.gate_action('CLOSE')

def test_missing_active_exit_denied(ctl):
    step(ctl,'B',True)
    with pytest.raises(ValueError,match='在場紀錄'):
        ctl.authorize('ABC-1234')

def test_reboot_resets_sequence(ctl):
    ctl.mode('HARDWARE')
    assert ctl.device_state({'boot_id':'firstboot1','sequence':42,'gate':'CLOSED','sensors':{}})['accepted']
    assert ctl.device_state({'boot_id':'secondboot1','sequence':1,'gate':'CLOSED','sensors':{}})['accepted']
    assert ctl.status()['device_online']

def test_full_lot_denies_new_entry(ctl):
    for k in ('P1','P2','P3','P4'):
        step(ctl,k,True)
    step(ctl,'A',True)
    with pytest.raises(ValueError,match='已滿'):
        ctl.authorize('ABC-1234')


def test_five_default_demo_plates(ctl):
    rows={r['plate']:r for r in ctl.plates()}
    assert set(rows)==set(DEFAULT_DEMO_PLATES)
    assert all(r['enabled'] for r in rows.values())


def test_unlisted_exit_is_denied_even_when_parked(ctl):
    entry(ctl)
    ctl.remove_plate('ABC-1234')
    step(ctl,'B',True)
    with pytest.raises(ValueError,match='白名單'):
        ctl.authorize('ABC-1234')
    with pytest.raises(ValueError,match='授權'):
        ctl.gate_action('OPEN')
    assert ctl.status()['gate']=='CLOSED'
    assert ctl.status()['active_visits']==1


def test_revoked_plate_and_mismatched_input_never_open(ctl):
    step(ctl,'A',True)
    ctl.authorize('ABC-1234')
    with pytest.raises(ValueError,match='不一致'):
        ctl.gate_action('OPEN',client_plate='ABC-5333')
    assert ctl.status()['gate']=='CLOSED'
    ctl.remove_plate('ABC-1234')
    with pytest.raises(ValueError,match='白名單'):
        ctl.gate_action('OPEN',client_plate='ABC-1234')
    assert ctl.status()['gate']=='CLOSED'


def test_full_reset_restores_clean_demo_baseline(ctl):
    entry(ctl)
    ctl.add_plate('ZZZ-5555', '自訂測試')
    step(ctl,'P1',True)
    step(ctl,'B',True)
    ctl.reset_all_sim()
    state=ctl.status()
    assert state['mode']=='SIM'
    assert state['gate']=='CLOSED' and state['phase']=='IDLE'
    assert all(not val for val in state['sensors'].values())
    assert state['last_plate'] is None and state['alert'] is None
    assert state['events']==[] and state['active_visits']==0
    assert state['available']==4 and ctl.records()==[]
    assert set(row['plate'] for row in ctl.plates())==set(DEFAULT_DEMO_PLATES)


def test_full_reset_forbidden_in_hardware(ctl):
    ctl.mode('HARDWARE')
    with pytest.raises(ValueError,match='模擬模式'):
        ctl.reset_all_sim()


def test_sim_manual_operating_time_does_not_expire_after_50_seconds(ctl):
    step(ctl,'A',True)
    with ctl.Session.begin() as db:
        db.get(SystemState,1).started_at=utcnow()-timedelta(seconds=75)
    assert ctl.status()['phase']=='WAIT_SECOND'
    ctl.authorize('ABC-1234')
    ctl.gate_action('OPEN',client_plate='ABC-1234')
    step(ctl,'B',True)
    step(ctl,'A',False)
    step(ctl,'B',False)
    assert ctl.status()['active_visits']==1
    assert ctl.records()[0]['entered_at'] is not None


def test_one_click_sim_entry_then_exit_persists_visit(ctl):
    step(ctl,'A',True)
    ctl.authorize('ABC-1234')
    ctl.gate_action('OPEN',client_plate='ABC-1234')
    outcome=ctl.complete_sim_passage()
    assert outcome == {'plate':'ABC-1234','direction':'ENTRY','recorded':True}
    assert ctl.status()['active_visits']==1
    assert ctl.status()['phase']=='IDLE'
    assert ctl.status()['sensors']['A'] is False
    assert ctl.status()['sensors']['B'] is False
    ctl.gate_action('CLOSE')
    step(ctl,'P1',True)
    step(ctl,'B',True)
    ctl.authorize('ABC-1234')
    ctl.gate_action('OPEN',client_plate='ABC-1234')
    outcome=ctl.complete_sim_passage()
    assert outcome['direction']=='EXIT'
    assert ctl.status()['active_visits']==0
    assert ctl.records()[0]['left_at'] is not None


def test_one_click_sim_needs_authorization_open_gate_and_clear_safety(ctl):
    step(ctl,'A',True)
    with pytest.raises(ValueError,match='驗證白名單'):
        ctl.complete_sim_passage()
    ctl.authorize('ABC-1234')
    with pytest.raises(ValueError,match='開閘'):
        ctl.complete_sim_passage()
    ctl.gate_action('OPEN')
    step(ctl,'S',True)
    with pytest.raises(ValueError,match='防夾'):
        ctl.complete_sim_passage()
    assert ctl.status()['active_visits']==0
    step(ctl,'S',False)
    ctl.complete_sim_passage()
    assert ctl.status()['active_visits']==1


def test_one_click_sim_not_available_in_hardware(ctl):
    ctl.mode('HARDWARE')
    with pytest.raises(ValueError,match='只有模擬模式'):
        ctl.complete_sim_passage()
