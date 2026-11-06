"""Flask integration tests; skipped only in an environment without Flask installed."""
import re
import pytest
flask = pytest.importorskip('flask')
from app import create_app

@pytest.fixture
def client(tmp_path):
    app=create_app({'TESTING':True, 'APP_ENV':'development','SECRET_KEY':'a-test-only-secret',
                    'ADMIN_PASSWORD':'secure-local-test-password','DATABASE_URL':'sqlite:///'+str(tmp_path/'api.db'),
                    'DEVICE_TOKEN':'test-device-token','CAMERA_TOKEN':'test-camera-token','SEED_DEMO':True})
    return app.test_client()

def authenticate(client):
    page=client.get('/login')
    token=re.search(rb'name="csrf" value="([^"]+)"',page.data).group(1).decode()
    response=client.post('/login',data={'password':'secure-local-test-password','csrf':token})
    assert response.status_code==302
    with client.session_transaction() as sess:
        return {'X-CSRF-Token':sess['csrf']}

def test_public_is_redacted(client):
    response=client.get('/api/public/status')
    assert response.status_code==200
    assert 'last_plate' not in response.json
    assert 'available' in response.json
    assert client.get('/api/status').status_code==401

def test_requires_csrf(client):
    authenticate(client)
    assert client.post('/api/sim/sensors',json={'sensor':'A','detected':True}).status_code==403

def test_browser_sim_flow(client):
    headers=authenticate(client)
    def post(path,data):
        response=client.post(path,json=data,headers=headers)
        assert response.status_code==200, response.json
        return response.json
    post('/api/sim/sensors',{'sensor':'A','detected':True})
    post('/api/passage/authorize',{'plate':'ABC-1234'})
    post('/api/gate/open',{'plate':'ABC-1234'})
    post('/api/sim/sensors',{'sensor':'B','detected':True})
    post('/api/sim/sensors',{'sensor':'A','detected':False})
    post('/api/sim/sensors',{'sensor':'B','detected':False})
    assert client.get('/api/status',headers=headers).json['active_visits']==1

def test_device_token(client):
    unauth=client.post('/api/device/state',json={'boot_id':'testboot12','sequence':1,'sensors':{}})
    assert unauth.status_code==401
    headers=authenticate(client)
    assert client.post('/api/mode',json={'mode':'HARDWARE'},headers=headers).status_code==200
    result=client.post('/api/device/state',json={'boot_id':'testboot12','sequence':1,
            'sensors':{'P1':True},'gate':'CLOSED'},headers={'Authorization':'Bearer test-device-token'})
    assert result.status_code==200
    assert client.get('/api/status',headers=headers).json['occupied']==1


def test_reset_all_requires_csrf_and_confirmation(client):
    headers=authenticate(client)
    assert client.post('/api/sim/reset-all',json={'confirmation':'RESET_SIM_ALL'}).status_code==403
    assert client.post('/api/sim/reset-all',json={},headers=headers).status_code==400
    client.post('/api/plates',json={'plate':'ZZZ-5555'},headers=headers)
    result=client.post('/api/sim/reset-all',json={'confirmation':'RESET_SIM_ALL'},headers=headers)
    assert result.status_code==200
    assert len(client.get('/api/plates',headers=headers).json['items'])==5
    assert client.get('/api/records',headers=headers).json['items']==[]


def test_no_open_without_valid_whitelisted_plate(client):
    headers=authenticate(client)
    def post(path,data):
        return client.post(path,json=data,headers=headers)
    assert post('/api/sim/sensors',{'sensor':'A','detected':True}).status_code==200
    assert post('/api/passage/authorize',{'plate':'XYZ-9999'}).status_code==400
    assert post('/api/gate/open',{'plate':'XYZ-9999'}).status_code==400
    assert client.get('/api/status',headers=headers).json['gate']=='CLOSED'
    assert post('/api/passage/authorize',{'plate':'ABC-1234'}).status_code==200
    assert post('/api/gate/open',{'plate':'XYZ-9999'}).status_code==400
    assert client.get('/api/status',headers=headers).json['gate']=='CLOSED'
