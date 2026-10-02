"""Audit regression tests, isolated temporary database; no external requests."""
import os
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
with tempfile.TemporaryDirectory() as tmp:
    os.environ.update(DEMO_MODE='true', SYNC_ON_STARTUP='false', ALERTS_ENABLED='false',
                      MESSAGING_ENABLED='false', DATABASE_URL=f'sqlite:///{tmp}/test.db',
                      SECRET_KEY='audit-test-secret-01234567890123456789',
                      FIRST_ADMIN_EMAIL='admin@test.local', FIRST_ADMIN_PASSWORD='test-password')
    from fastapi.testclient import TestClient
    from app.main import app
    from app.security import verify_password
    from app.services.reports import safe_cell
    with TestClient(app) as c:
        assert c.post('/api/auth/login', json={'email':'%', 'password':'test-password'}).status_code == 401
        login=c.post('/api/auth/login', json={'email':'admin@test.local','password':'test-password'}).json()
        h={'Authorization': 'Bearer '+login['token']}
        client=c.post('/api/clients', headers=h, json={'name':'Audit Client'})
        assert client.status_code == 201, client.text
        ids=[]
        for tracking in ('AUDIT-1001','AUDIT-1002'):
            p=c.post('/api/parcels',headers=h,json={'tracking_number':tracking,'carrier':'manual','sync_now':False}).json()
            ids.append(p['id'])
        for code in ('AUDIT-100','%'):
            assert not c.post('/api/receiving/scan',headers=h,json={'code':code}).json()['found']
        assert c.post('/api/receiving/scan',headers=h,json={'code':'audit 1001'}).json()['id']==ids[0]
        assert c.get(f'/labels/{ids[0]}',headers=h).status_code==200
        assert c.get('/api/parcels/export.xlsx',headers=h).status_code==200
        assert c.post(f'/api/receiving/{ids[0]}/release',headers=h,json={}).status_code==200
        assert c.post(f'/api/receiving/{ids[0]}/receive',headers=h,json={}).status_code==409
        assert c.post(f'/api/receiving/{ids[0]}/undo',headers=h,json={}).status_code==409
        assert c.post(f'/api/receiving/{ids[0]}/release',headers=h,json={}).status_code==409
        for path in ('/%2e%2e/config.py','/%2e%2e/%2e%2e/.env','/api/does-not-exist','/static/missing.js'):
            assert c.get(path).status_code==404, path
        assert c.get('/parcels').status_code==200
        assert c.post('/api/auth/change-password',headers=h,json={'current_password':'test-password','new_password':'new-password'}).status_code==200
        assert c.get('/api/auth/me',headers=h).status_code==401
        assert not verify_password('test','pbkdf2_sha256$nothex$bad')
        assert safe_cell('=HYPERLINK("evil")').startswith("'")
        assert safe_cell(-12)==-12
    print('Audit regressions passed')
