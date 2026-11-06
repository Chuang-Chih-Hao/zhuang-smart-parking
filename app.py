"""Flask web/API entry point for 莊停車場."""
import hmac
import os
import secrets
from functools import wraps
from pathlib import Path
from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from dotenv import load_dotenv
from parking.core import ParkingController

load_dotenv()
ROOT = Path(__file__).resolve().parent


def create_app(test_config=None):
    app = Flask(__name__, template_folder='templates', static_folder='static')
    app.config.update(
        SECRET_KEY=os.environ.get('SECRET_KEY'),
        DATABASE_URL=os.environ.get('DATABASE_URL', f'sqlite:///{(ROOT / "instance" / "parking.db").as_posix()}'),
        ADMIN_PASSWORD=os.environ.get('ADMIN_PASSWORD', ''),
        DEVICE_TOKEN=os.environ.get('DEVICE_TOKEN', ''),
        CAMERA_TOKEN=os.environ.get('CAMERA_TOKEN', ''),
        APP_ENV=os.environ.get('APP_ENV', 'development'),
        SEED_DEMO=os.environ.get('SEED_DEMO', 'false').lower() == 'true',
    )
    if test_config:
        app.config.update(test_config)
    if app.config['APP_ENV'] == 'production':
        if not app.config['SECRET_KEY'] or not app.config['ADMIN_PASSWORD'] or len(app.config['ADMIN_PASSWORD']) < 12:
            raise RuntimeError('正式部署必須設定 SECRET_KEY 和至少 12 字元的 ADMIN_PASSWORD')
        app.config.update(SESSION_COOKIE_SECURE=True, PREFERRED_URL_SCHEME='https')
    elif not app.config['SECRET_KEY']:
        app.config['SECRET_KEY'] = secrets.token_hex(32)
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax', MAX_CONTENT_LENGTH=16*1024)
    if app.config['DATABASE_URL'].startswith('sqlite'):
        (ROOT / 'instance').mkdir(exist_ok=True)
    controller = ParkingController(app.config['DATABASE_URL'], seed_demo=app.config['SEED_DEMO'])
    app.extensions['parking_controller'] = controller

    def is_admin():
        return session.get('admin') is True

    def protect(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not is_admin():
                return jsonify(error='尚未登入管理員'), 401
            if request.method not in ('GET','HEAD','OPTIONS'):
                incoming = request.headers.get('X-CSRF-Token','')
                stored = session.get('csrf','')
                if not stored or not hmac.compare_digest(incoming, stored):
                    return jsonify(error='CSRF 驗證失敗，請重新整理頁面'), 403
            return fn(*args,**kwargs)
        return wrapper

    def device_protect(token_key):
        def decorator(fn):
            @wraps(fn)
            def wrapper(*args,**kwargs):
                configured=app.config[token_key]
                provided=request.headers.get('Authorization','').removeprefix('Bearer ').strip()
                if not configured or not provided or not hmac.compare_digest(configured, provided):
                    return jsonify(error='裝置驗證失敗'), 401
                return fn(*args,**kwargs)
            return wrapper
        return decorator

    def payload():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise ValueError('請提供 JSON 物件')
        return data

    @app.errorhandler(ValueError)
    def handle_value_error(error):
        return jsonify(error=str(error)), 400

    @app.after_request
    def headers(response):
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['X-Frame-Options']='DENY'
        response.headers['Referrer-Policy']='strict-origin-when-cross-origin'
        response.headers['Content-Security-Policy']="default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'"
        if request.path.startswith('/api/'):
            response.headers['Cache-Control']='no-store'
        return response

    @app.get('/healthz')
    def healthz():
        return jsonify(ok=True, service='zhuang-smart-parking')

    @app.get('/login')
    def login_page():
        if is_admin():
            return redirect(url_for('index'))
        session.setdefault('login_csrf', secrets.token_hex(24))
        return render_template('login.html', csrf=session['login_csrf'], error=None)

    @app.post('/login')
    def login():
        posted=request.form.get('csrf','')
        stored=session.get('login_csrf','')
        if not posted or not stored or not hmac.compare_digest(posted,stored):
            return 'CSRF 驗證失敗',403
        candidate=request.form.get('password','')
        secret=app.config['ADMIN_PASSWORD']
        if not secret or not hmac.compare_digest(candidate,secret):
            return render_template('login.html',csrf=stored,error='密碼錯誤或尚未設定 ADMIN_PASSWORD'),401
        session.clear()
        session['admin']=True
        session['csrf']=secrets.token_hex(24)
        return redirect(url_for('index'))

    @app.get('/')
    def index():
        if not is_admin():
            return redirect(url_for('login_page'))
        return render_template('index.html', csrf=session['csrf'])

    @app.get('/display')
    def display():
        return render_template('display.html')

    @app.post('/logout')
    @protect
    def logout():
        session.clear()
        return jsonify(ok=True)

    @app.get('/api/public/status')
    def public_status():
        return jsonify(controller.public_status())

    @app.get('/api/status')
    @protect
    def status():
        return jsonify(controller.status())

    @app.get('/api/plates')
    @protect
    def plates():
        return jsonify(items=controller.plates())

    @app.post('/api/plates')
    @protect
    def plate_create():
        data=payload()
        return jsonify(ok=True, plate=controller.add_plate(data.get('plate'),data.get('note','')))

    @app.delete('/api/plates/<path:plate>')
    @protect
    def plate_delete(plate):
        controller.remove_plate(plate)
        return jsonify(ok=True)

    @app.get('/api/records')
    @protect
    def records():
        return jsonify(items=controller.records())

    @app.post('/api/mode')
    @protect
    def mode():
        controller.mode(payload().get('mode'))
        return jsonify(ok=True)

    @app.post('/api/sim/sensors')
    @protect
    def sim_sensor():
        data=payload()
        controller.sim_sensor(data.get('sensor'),data.get('detected'))
        return jsonify(ok=True)

    @app.post('/api/sim/reset')
    @protect
    def sim_reset():
        controller.reset_sim()
        return jsonify(ok=True)

    @app.post('/api/sim/reset-all')
    @protect
    def sim_reset_all():
        if payload().get('confirmation') != 'RESET_SIM_ALL':
            raise ValueError('請先確認要清空所有模擬資料')
        controller.reset_all_sim()
        return jsonify(ok=True)

    @app.post('/api/sim/complete-passage')
    @protect
    def sim_complete_passage():
        return jsonify(ok=True, **controller.complete_sim_passage())

    @app.post('/api/passage/authorize')
    @protect
    def authorize():
        return jsonify(ok=True, **controller.authorize(payload().get('plate')))

    @app.post('/api/gate/<action>')
    @protect
    def gate(action):
        if action not in ('open','close'):
            raise ValueError('不支援的閘門操作')
        # Bind the opening command to the plate currently shown in the UI.
        current_plate = payload().get('plate') if action == 'open' else None
        return jsonify(ok=True, **controller.gate_action(action.upper(),client_plate=current_plate))

    @app.post('/api/device/state')
    @device_protect('DEVICE_TOKEN')
    def device_state():
        return jsonify(controller.device_state(payload()))

    @app.post('/api/device/events')
    @device_protect('DEVICE_TOKEN')
    def device_events():
        return jsonify(controller.device_event(payload()))

    @app.get('/api/device/commands')
    @device_protect('DEVICE_TOKEN')
    def device_commands():
        return jsonify(items=controller.device_commands())

    @app.post('/api/device/ack')
    @device_protect('DEVICE_TOKEN')
    def device_ack():
        data=payload()
        return jsonify(controller.device_ack(data.get('id'),data.get('success'),data.get('gate'),data.get('result','')))

    @app.post('/api/camera/recognize')
    @device_protect('CAMERA_TOKEN')
    def camera_recognize():
        return jsonify(ok=True,**controller.authorize(payload().get('plate')))

    return app


app = create_app()

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=False)
