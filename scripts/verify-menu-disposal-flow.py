#!/usr/bin/env python3
"""Run built menu/disposal/stock JARs against one uniquely named tmpfs MariaDB.
No project .env, application DB, existing containers or persistent volumes are used.
"""
import base64
import concurrent.futures
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
MODULES = ['FoodMaterialsService', 'MenusService', 'DisposalsService']

def command(*args, **kwargs):
    return subprocess.run(args, check=True, capture_output=True, **kwargs)

def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]

def request(port, path, method='GET', body=None, token=None):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    req = urllib.request.Request(f'http://127.0.0.1:{port}' + path, method=method,
        headers=headers, data=None if body is None else json.dumps(body).encode())
    try:
        response = urllib.request.urlopen(req, timeout=15)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        raw = response.read()
        return response.status, json.loads(raw) if raw else {}

def main():
    jars = {}
    for module in MODULES:
        found = [p for p in (ROOT/module/'build/libs').glob('*.jar') if not p.name.endswith('-plain.jar')]
        if len(found) != 1:
            raise SystemExit(f'Build {module} bootJar first; expected exactly one executable jar.')
        jars[module] = found[0]
    if Path('/usr/libexec/java_home').exists():
        java = command('/usr/libexec/java_home', '-v', '21').stdout.decode().strip() + '/bin/java'
    else:
        java = shutil.which('java')
        if not java:
            raise SystemExit('Java 21 is required')
    container = 'erpmsa-domain-e2e-' + secrets.token_hex(6)
    processes = []
    logs = []
    created = False
    report = {}
    with tempfile.TemporaryDirectory(prefix='erpmsa-domain-e2e-') as temporary:
        folder = Path(temporary)
        password = secrets.token_hex(24)
        env_file = folder/'database.env'
        env_file.write_text(f'MARIADB_ROOT_PASSWORD={password}\nMARIADB_USER=account\nMARIADB_PASSWORD={password}\nMARIADB_DATABASE=itemdb\n')
        env_file.chmod(0o600)
        try:
            command('docker', 'run', '-d', '--rm', '--name', container, '--label', 'erpmsa.test=domain-e2e',
                '--tmpfs', '/var/lib/mysql:rw', '-p', '127.0.0.1::3306', '--env-file', str(env_file), 'mariadb:10.11')
            created = True
            for _ in range(90):
                health = subprocess.run(['docker','exec',container,'healthcheck.sh','--connect','--innodb_initialized'],capture_output=True)
                if health.returncode == 0:
                    break
                time.sleep(1)
            else:
                raise RuntimeError('Temporary database did not become ready')
            inspected = json.loads(command('docker','inspect',container).stdout)[0]
            assert inspected['Config']['Labels']['erpmsa.test']=='domain-e2e'
            assert '/var/lib/mysql' in inspected['HostConfig']['Tmpfs']
            db_port = inspected['NetworkSettings']['Ports']['3306/tcp'][0]['HostPort']
            sql = ''.join(f"CREATE DATABASE {schema}; GRANT ALL ON {schema}.* TO 'account'@'%';" for schema in ['inventorydb','menusdb','disposalsdb'])
            command('docker','exec','-i',container,'sh','-ec',
                'MYSQL_PWD="$MARIADB_ROOT_PASSWORD" exec mariadb -uroot',input=sql.encode())
            command(str(ROOT/'scripts/generate-jwt-keys.sh'),'domain-e2e',str(folder/'keys'))
            ports = {module: free_port() for module in MODULES}
            # Do not inherit SPRING_APPLICATION_JSON, datasource URLs or JVM option overrides.
            common = dict(PATH=os.environ.get("PATH", "/usr/bin:/bin"), LANG="en_US.UTF-8", DB_PASSWORD=password, JWT_ISSUER='domain-e2e', JWT_AUDIENCE='domain-e2e',
                JWT_PUBLIC_KEY_DIRECTORY=str(folder/'keys/public'), EUREKA_CLIENT_ENABLED='false',
                SPRING_CLOUD_DISCOVERY_ENABLED='false', FOOD_MATERIAL_DISCOVERY_ENABLED='false',
                FOOD_MATERIAL_SERVICE_BASE_URL=f'http://127.0.0.1:{ports["FoodMaterialsService"]}')
            for prefix,schema in [('FOOD_MATERIAL','itemdb'),('FOOD_MATERIAL_INVENTORY','inventorydb'),('MENUS','menusdb'),('DISPOSALS','disposalsdb')]:
                common[prefix+'_DB_URL']=f'jdbc:mariadb://127.0.0.1:{db_port}/{schema}'
                common[prefix+'_DB_USERNAME']='account'
                common[prefix+'_DB_PASSWORD']=password
            common['FOOD_MATERIAL_FLYWAY_BASELINE_ON_MIGRATE']='false'
            common['FOOD_MATERIAL_INVENTORY_FLYWAY_BASELINE_ON_MIGRATE']='false'
            for module,prefix in [('FoodMaterialsService','FOOD_MATERIAL'),('MenusService','MENUS'),('DisposalsService','DISPOSALS')]:
                log = (folder/(module+'.log')).open('w'); logs.append(log)
                env = dict(common); env[prefix+'_SERVER_PORT']=str(ports[module])
                processes.append(subprocess.Popen([java,'-Xmx384m','-jar',str(jars[module])],
                    env=env,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT))
            for module in MODULES:
                for _ in range(90):
                    if any(p.poll() is not None for p in processes):
                        raise RuntimeError('Application exited before readiness')
                    try:
                        if request(ports[module],'/actuator/health')[0] == 200:
                            break
                    except (OSError,urllib.error.URLError):
                        pass
                    time.sleep(1)
                else:
                    raise RuntimeError(module+' readiness timed out')
            def token(account):
                def encode(value):
                    return base64.urlsafe_b64encode(json.dumps(value,separators=(',',':')).encode()).rstrip(b'=')
                now=int(time.time())
                content=encode({'alg':'RS256','typ':'JWT','kid':'domain-e2e'})+b'.'+encode({
                    'iss':'domain-e2e','aud':'domain-e2e','sub':str(account),'iat':now,'exp':now+600,
                    'token_type':'access','email':'fixture@example.com','role':'ROLE_USER'})
                signature=command('openssl','dgst','-sha256','-sign',str(folder/'keys/private/domain-e2e.pem'),input=content).stdout
                return (content+b'.'+base64.urlsafe_b64encode(signature).rstrip(b'=')).decode()
            owner,other = token(1),token(2)
            food,menus,disposals = (ports[m] for m in MODULES)
            status,body=request(menus,'/menus','POST',{'name':'김치볶음밥','price':12000},owner)
            assert status==201
            menu=body['menuId']
            assert request(menus,f'/menus/{menu}',token=other)[0]==404
            assert request(menus,f'/menus/{menu}','DELETE',token=owner)[0]==204
            assert request(menus,f'/menus/{menu}',token=owner)[1]['status']=='INACTIVE'
            status,body=request(food,'/foodmaterials','POST',{'sku':'E2E-001','name':'식자재','unitPrice':1000},owner)
            assert status==201
            material=body['foodMaterialId']
            assert request(food,'/foodmaterials/inventories','POST',{'foodMaterialId':material,'initialQuantity':20},owner)[0]==201
            payload={'requestId':'E2E-DISPOSAL','foodMaterialId':material,'quantity':3,'reason':'기한 경과'}
            # Exercise real HTTP, independent DBs and simultaneous application processes.
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
                outcomes=list(executor.map(lambda _:request(disposals,'/disposals','POST',payload,owner),range(8)))
            assert all(code==200 and result['status']=='COMPLETED' for code,result in outcomes), [(c,r.get('status')) for c,r in outcomes]
            assert len({r['disposalId'] for _,r in outcomes})==1
            identifier=outcomes[0][1]['disposalId']
            assert request(disposals,f'/disposals/{identifier}',token=other)[0]==404
            assert request(food,f'/foodmaterials/inventories/{material}',token=owner)[1]['onHandQuantity']==17
            ledger=request(food,f'/foodmaterials/inventories/{material}/movements',token=owner)[1]
            assert ledger['totalElements']==2
            assert sum(m['movementType']=='DISPOSAL' for m in ledger['movements'])==1
            rejected=request(disposals,'/disposals','POST',dict(payload,requestId='TOO-MUCH',quantity=18),owner)
            assert rejected[0]==409 and rejected[1]['status']=='REJECTED'
            assert request(food,f'/foodmaterials/inventories/{material}',token=owner)[1]['onHandQuantity']==17
            report={'scope':'three real service JARs, direct HTTP, temporary MariaDB; no Gateway/Eureka or remote CI',
                'menuLifecycle':True,'tenantBoundary':True,'simultaneousDisposalRequests':8,
                'disposalRecordsForRequest':1,'stockBefore':20,'stockAfter':17,'ledgerRows':2,'disposalLedgerRows':1,
                'insufficientStockRejected':True}
        finally:
            for process in processes:
                if process.poll() is None:
                    process.terminate()
            for process in processes:
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait()
            for log in logs:
                log.close()
            if created:
                command('docker','rm','-f',container)
        report['temporaryResourcesRemoved']=True
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__':
    main()
