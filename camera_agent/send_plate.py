"""Computer-side integration adapter: send already-recognized plate to Flask.
This is NOT OCR. It intentionally does not claim to access USB cameras in Render.
"""
import json
import os
import sys
from urllib.request import Request, urlopen
from urllib.error import HTTPError

if len(sys.argv)!=2:
    raise SystemExit('使用方式：python camera_agent/send_plate.py ABC-1234')
url=os.environ.get('PARKING_API_URL','http://127.0.0.1:5000').rstrip('/')
token=os.environ.get('CAMERA_TOKEN','')
if not token:
    raise SystemExit('請設定 CAMERA_TOKEN（與 Flask 的 CAMERA_TOKEN 相同）')
request=Request(url+'/api/camera/recognize',data=json.dumps({'plate':sys.argv[1]}).encode(),headers={
    'Authorization':'Bearer '+token,'Content-Type':'application/json'},method='POST')
try:
    with urlopen(request,timeout=15) as response:
        print(json.dumps(json.load(response),ensure_ascii=False,indent=2))
except HTTPError as err:
    print(err.read().decode('utf-8','replace'))
    raise
