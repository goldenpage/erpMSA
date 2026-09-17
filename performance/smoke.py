#!/usr/bin/env python3
"""End-to-end verification against the disposable lab only; no tokens are printed."""
import concurrent.futures
import threading
import http.cookiejar
import json
import secrets
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
    for path,name in [('notices','NoticesService'),('bills','BillsService'),('purchase','PurchaseService')]:
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
    assert lab.request('/inventories',token=token)[0]==404
    old=refresh_value()
    assert auth('/account/auth/refresh')[0] == 200
    rotated=refresh_value()
    assert old != rotated and replay(old) == 401
    assert auth('/account/auth/logout')[0] == 204 and replay(rotated) == 401
    assert lab.request('/foodmaterials')[0] == 401
    status,body=lab.request('/foodmaterials','POST',{'sku':f'SMOKE-{number}','name':'Smoke','unitPrice':1000},token)
    assert status == 201, f'item: {status}'
    item=json.loads(body)['foodMaterialId']
    status,body=lab.request(f'/foodmaterials/{item}',token=token)
    assert status==200 and json.loads(body)['foodMaterialId']==item
    other=json.loads((lab.RESULTS/'users.json').read_text())[0]['token']
    assert lab.request(f'/foodmaterials/{item}',token=other)[0]==404

    status,body=lab.request('/foodmaterials/inventories','POST',{'foodMaterialId':item,'initialQuantity':20},token)
    assert status==201, f'inventory creation: {status}'
    version=json.loads(body)['version']
    barrier=threading.Barrier(10)
    def adjustment(i):
        barrier.wait(timeout=10)
        return i,lab.request(f'/foodmaterials/inventories/{item}/adjustments','POST',{
            'requestId':f'PARALLEL-{number}-{i}','quantityDelta':-1,'version':version,'reason':'parallel lab verification'},token)
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        outcomes=list(executor.map(adjustment,range(10)))
    assert sorted(result[0] for _,result in outcomes)==[200]+[409]*9
    for _,(code,payload) in outcomes:
        if code==409: assert json.loads(payload)['code']=='INVENTORY_CONFLICT'
    winner=next(i for i,(code,_) in outcomes if code==200)
    status,body=lab.request(f'/foodmaterials/inventories/{item}',token=token)
    assert status==200 and json.loads(body)['onHandQuantity']==19
    current=json.loads(body)['version']
    assert lab.request(f'/foodmaterials/inventories/{item}/adjustments','POST',{
        'requestId':f'PARALLEL-{number}-{winner}','quantityDelta':-1,'version':current,'reason':'duplicate'},token)[0]==409
    status,body=lab.request(f'/foodmaterials/inventories/{item}/movements',token=token)
    assert status==200 and json.loads(body)['totalElements']==2
    assert lab.request(f'/foodmaterials/inventories/{item}',token=other)[0]==404
    assert lab.request('/foodmaterials/inventories','POST',{'foodMaterialId':item,'initialQuantity':1},other)[0]==404

    code,payload=lab.request('/menus','POST',{'name':'Smoke menu','price':12000},token)
    assert code==201
    menu=json.loads(payload)['menuId']
    assert lab.request(f'/menus/{menu}',token=other)[0]==404
    assert lab.request(f'/menus/{menu}','DELETE',token=token)[0]==204
    disposal={'requestId':f'DISPOSE-{number}','foodMaterialId':item,'quantity':2,'reason':'smoke disposal'}
    for _ in range(2):
        code,payload=lab.request('/disposals','POST',disposal,token)
        assert code==200, f'disposal: {code}'
        result=json.loads(payload)
        assert result['status']=='COMPLETED' and result['quantityAfter']==17
    assert lab.request('/disposals/'+result['disposalId'],token=other)[0]==404
    code,payload=lab.request(f'/foodmaterials/inventories/{item}',token=token)
    assert code==200 and json.loads(payload)['onHandQuantity']==17

    # Publication is verified separately from the retired audit consumer.
    for _ in range(30):
        published=int(lab.sql(f"SELECT COUNT(*) FROM mydb.account_outbox_event WHERE aggregate_id='{account}' AND status='PUBLISHED';"))
        if published==1: break
        time.sleep(1)
    assert published==1
    lab.save('smoke',{'refreshRotation':True,'oldRefreshRejected':True,'logoutReplayRejected':True,
        'foodMaterialsCreateAndRead':True,'pendingServiceRoutes':3,'menuLifecycle':True,'disposalReplaySingleDeduction':True,'legacyRoutesRemoved':True,
        'tenantBoundary':True,'parallelAdjustments':{'success':1,'conflict':9,'quantity':19,'movements':2},'outboxPublished':True,'consumerVerification':False})
    print('PASS: RSA auth/refresh/logout, FoodMaterials catalog/inventory, parallel adjustments, tenant boundary, 7 designed routes and Outbox publication')

if __name__=='__main__': main()
