import tempfile
from pathlib import Path
import pytest
from parking.core import ParkingController

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
