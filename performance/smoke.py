#!/usr/bin/env python3
"""End-to-end verification against the disposable lab only; no tokens are printed."""
import concurrent.futures
import http.cookiejar
import json
import secrets
import threading
import time
import urllib.error
import urllib.request
import lab

def main():
    lab.verify_lab()
    lab.wait_gateway()
    number = secrets.randbelow(10**10)
    password = secrets.token_urlsafe(24)
    email = f'smoke-{number}@example.com'
    status, body = lab.request('/account/auth/register','POST',{
        'email':email,'businessId':f'{number:010}','password':password,'name':'Lab Smoke',
        'phone':'01012345678','storeName':'Lab','storeType':'RETAIL','storeCategory':'TEST','marketingAgreed':False})
    assert status == 201, f'registration: {status}'
    account = json.loads(body)['accountId']
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

    def auth(path, body=None):
        req=urllib.request.Request(lab.GATEWAY+path,method='POST',
            data=json.dumps(body).encode() if body is not None else b'',headers={'Content-Type':'application/json'})
        with opener.open(req,timeout=10) as response: return response.status,json.loads(response.read() or b'{}')

    def refresh_value(): return next(cookie.value for cookie in jar if cookie.name=='refreshToken')
    def replay(value):
        req=urllib.request.Request(lab.GATEWAY+'/account/auth/refresh',method='POST',data=b'',headers={'Cookie':'refreshToken='+value})
        try:
            with urllib.request.urlopen(req,timeout=10) as response: return response.status
        except urllib.error.HTTPError as error: return error.code

    status, login = auth('/account/auth/login',{'email':email,'password':password})
    assert status == 200
    token=login['accessToken']
    # New service processes must route to their own authenticated, explicitly incomplete contracts.
    for path,name in [('menus','MenusService'),('notices','NoticesService'),('bills','BillsService'),('purchase','PurchaseService'),('disposals','DisposalsService')]:
        for _ in range(60):
            code,payload=lab.request('/'+path,token=token)
            if code==501: break
            time.sleep(1)
        assert code==501, f'{name} route: {code}'
        assert json.loads(payload)['service']==name
        assert json.loads(payload)['code']=='ENDPOINT_NOT_IMPLEMENTED'
        assert lab.request('/'+path)[0]==401
    assert lab.request('/items',token=token)[0]==404
    assert lab.request('/orders',token=token)[0]==404
    old=refresh_value()
    assert auth('/account/auth/refresh')[0] == 200
    rotated=refresh_value()
    assert old != rotated and replay(old) == 401
    assert auth('/account/auth/logout')[0] == 204 and replay(rotated) == 401
    assert lab.request('/foodmaterials')[0] == 401
    status,body=lab.request('/foodmaterials','POST',{'sku':f'SMOKE-{number}','name':'Smoke','unitPrice':1000},token)
    assert status == 201, f'item: {status}'
    item=json.loads(body)['foodMaterialId']
    status,body=lab.request('/inventories','POST',{'itemId':item,'initialQuantity':20},token)
    assert status == 201, f'inventory: {status}'
    version=json.loads(body)['version']
    barrier=threading.Barrier(10)
    def adjustment(i):
        barrier.wait(timeout=10)
        return i,lab.request(f'/inventories/{item}/adjustments','POST',{
            'requestId':f'PARALLEL-{number}-{i}','quantityDelta':-1,'version':version,'reason':'parallel lab verification'},token)[0]
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        outcomes=list(executor.map(adjustment,range(10)))
    assert sorted(status for _,status in outcomes) == [200]+[409]*9, outcomes
    winner=next(i for i,status in outcomes if status==200)
    status,body=lab.request(f'/inventories/{item}',token=token)
    assert status==200 and json.loads(body)['onHandQuantity']==19
    current=json.loads(body)['version']
    assert lab.request(f'/inventories/{item}/adjustments','POST',{
        'requestId':f'PARALLEL-{number}-{winner}','quantityDelta':-1,'version':current,'reason':'duplicate'},token)[0] == 409
    status,body=lab.request(f'/inventories/{item}/movements',token=token)
    assert status==200 and json.loads(body)['totalElements']==2
    other=json.loads((lab.RESULTS/'users.json').read_text())[0]['token']
    assert lab.request(f'/inventories/{item}',token=other)[0]==404

    for _ in range(30):
        count=int(lab.sql(f"SELECT COUNT(*) FROM auditdb.audit_event WHERE aggregate_id='{account}';"))
        if count==1: break
        time.sleep(1)
    assert count==1
    payload=lab.sql(f"SELECT payload FROM mydb.account_outbox_event WHERE aggregate_id='{account}';")
    event=json.loads(payload.replace('\\n','\n'))
    event['traceId']='future-optional-field'
    record=f'{account}|'+json.dumps(event)+'\n'
    producer=['exec','-T','kafka','/opt/kafka/bin/kafka-console-producer.sh','--bootstrap-server','kafka:9092',
        '--topic','account.lifecycle.v1','--property','parse.key=true','--property','key.separator=|']
    lab.compose(*producer,input=record+record,capture=True)
    invalid = '{"probe":"DLT-' + str(number) + '"'  # deliberately missing closing brace
    lab.compose(*producer,input='invalid|' + invalid + '\n',capture=True)
    dlt=lab.compose('exec','-T','kafka','/opt/kafka/bin/kafka-console-consumer.sh','--bootstrap-server','kafka:9092',
        '--topic','account.lifecycle.v1.DLT','--from-beginning','--timeout-ms','15000',capture=True,check=False)
    assert invalid in dlt.stdout.splitlines(), 'This run\'s invalid event did not reach DLT'
    assert int(lab.sql(f"SELECT COUNT(*) FROM auditdb.audit_event WHERE aggregate_id='{account}';"))==1
    lab.save('smoke',{'refreshRotation':True,'oldRefreshRejected':True,'logoutReplayRejected':True,
        'foodMaterialsInternalInventoryRouting':True,'designedServiceRoutes':5,'legacyRoutesRemoved':True,'parallelAdjustments':{'success':1,'conflict':9,'quantity':19,'movements':2},
        'tenantBoundary':True,'duplicateEventCount':1,'malformedEventDlt':True})
    print('PASS: RSA auth/refresh/logout, FoodMaterials→internal Inventory, 10 concurrent adjustments, tenant boundary, duplicate event and DLT')

if __name__=='__main__': main()
