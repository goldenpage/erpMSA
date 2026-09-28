"""G2 NF cases. All business fixtures are created through HTTP; SQL only reads."""
from concurrent.futures import ThreadPoolExecutor
import threading

FOOD, MENU, DISP = 'FoodMaterialsService', 'MenusService', 'DisposalsService'
CASES = ('NF-02', 'NF-04', 'NF-05', 'NF-06', 'NF-07', 'NF-08', 'NF-09', 'NF-10', 'NF-11', 'NF-12')


class FatalFailure(AssertionError):
    """A verified product failure that also prevents safe diagnostic continuation."""


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def parallel(functions, run):
    barrier = threading.Barrier(len(functions))
    def invoke(fn):
        run.concurrent_context.barrier = barrier
        try:
            return fn()
        finally:
            del run.concurrent_context.barrier
    with ThreadPoolExecutor(max_workers=len(functions)) as executor:
        futures = [executor.submit(invoke, fn) for fn in functions]
        return [future.result(timeout=60) for future in futures]


class Cases:
    def __init__(self, run):
        self.r = run
        self.sequence = 0

    def name(self, prefix):
        self.sequence += 1
        return f'{prefix}-{self.r.run_id}-{self.sequence}'

    def call(self, module, path, method='GET', body=None, expected=200, code=None, **kwargs):
        status, data = self.r.http(module, path, method, body, **kwargs)
        require(status == expected, f'{method} {path}: expected {expected}, actual {status}, body={data}')
        if code:
            require(data.get('code') == code, f'{path}: expected code {code}, actual {data}')
        return data

    def unchanged(self, before, label):
        require(self.r.snapshot() == before, label+' changed database rows')

    def material(self, stock=None, **kwargs):
        body = dict(sku=self.name('MAT').upper(), name='검증 식자재', unitPrice=1000, description='synthetic')
        body.update(kwargs)
        result = self.call(FOOD, '/foodmaterials', 'POST', body, 201)
        if stock is not None:
            self.call(FOOD, '/foodmaterials/inventories', 'POST', dict(foodMaterialId=result['foodMaterialId'], initialQuantity=stock), 201)
        return result

    def dispose(self, material, quantity, request_id=None):
        return dict(requestId=request_id or self.name('DISP'), foodMaterialId=material['foodMaterialId'], quantity=quantity, reason='검증 폐기')

    def stock(self, material):
        return self.call(FOOD, f'/foodmaterials/inventories/{material["foodMaterialId"]}')

    def ledger(self, material, quantity, types, version=None):
        mid = material['foodMaterialId']
        inv = [v for v in self.r.rows('inventory') if v['account_id'] == 101 and v['item_id'] == mid]
        require(len(inv) == 1 and inv[0]['on_hand_quantity'] == quantity, 'DB stock quantity/ownership mismatch')
        inv = inv[0]
        api = self.stock(material)
        require(api['inventoryId'] == inv['id'] and api['onHandQuantity'] == quantity and api['version'] == inv['version'], 'API/DB stock mismatch')
        if version is not None:
            require(inv['version'] == version, 'Stock version mismatch')
        rows = [v for v in self.r.rows('stock_movement') if v['account_id'] == 101 and v['item_id'] == mid]
        require([v['movement_type'] for v in rows] == types, 'DB movement type/count mismatch')
        previous = 0
        for row in rows:
            require(row['inventory_id'] == inv['id'] and row['quantity_before'] == previous, 'Ledger FK/continuity mismatch')
            require(row['quantity_after'] == previous+row['quantity_delta'], 'Ledger delta mismatch')
            previous = row['quantity_after']
        require(previous == quantity and sum(v['quantity_delta'] for v in rows) == quantity, 'Ledger sum mismatch')
        movements = self.call(FOOD, f'/foodmaterials/inventories/{mid}/movements?size=100')
        require(movements['totalElements'] == len(rows), 'API ledger row count mismatch')
        require({v['movementId'] for v in movements['movements']} == {v['id'] for v in rows}, 'API/DB ledger IDs mismatch')
        return rows

    def disposal_row(self, api, account=101):
        rows = [v for v in self.r.rows('disposal') if v['account_id'] == account and v['request_id'] == api['requestId']]
        require(len(rows) == 1, 'Expected one disposal DB row')
        row = rows[0]
        for public, db in [('disposalId','id'),('status','status'),('foodMaterialId','food_material_id'),('quantity','quantity'),
                           ('movementId','movement_id'),('quantityAfter','quantity_after'),('rejectionCode','rejection_code')]:
            require(row[db] == api[public], 'Disposal API/DB mismatch: '+public)
        if row['status'] == 'COMPLETED':
            movements = [v for v in self.r.rows('stock_movement') if v['id'] == row['movement_id']]
            require(len(movements) == 1, 'Missing disposal movement')
            movement = movements[0]
            require(movement['request_id'] == 'DISPOSAL-'+row['id'] and movement['account_id'] == account
                    and movement['item_id'] == row['food_material_id'] and movement['movement_type'] == 'DISPOSAL'
                    and movement['quantity_delta'] == -row['quantity'] and movement['quantity_after'] == row['quantity_after'],
                    'Disposal command/ledger mismatch')
        return row

    def pages(self, module, path, field, id_field, table, status=None, account=101):
        rows = [v for v in self.r.rows(table) if v['account_id'] == account and (status is None or v['status'] == status)]
        rows.sort(key=lambda v: (v['created_at'], v['id']), reverse=True)
        suffix = '&status='+status if status else ''
        full = self.call(module, path+'?size=100'+suffix, account=account)
        expected = [v['id'] for v in rows]
        require(full['totalElements'] == len(rows) and [v[id_field] for v in full[field]] == expected, 'List ordering/filter/DB mismatch '+path)
        paged = []
        for page in range(max(1, len(rows))):
            data = self.call(module, f'{path}?page={page}&size=1'+suffix, account=account)
            require(data['totalElements'] == len(rows) and data['page'] == page, 'Pagination metadata mismatch')
            paged.extend(v[id_field] for v in data[field])
        require(paged == expected and len(set(paged)) == len(paged), 'Page duplicate/omission '+path)

    def nf02(self):
        variants = {'missing': None, 'expired': self.r.token(changes={'exp': int(__import__('time').time())-60}),
                    'issuer': self.r.token(changes={'iss': 'wrong'}), 'audience': self.r.token(changes={'aud': 'wrong'}),
                    'signature': self.r.token(wrong_key=True), 'kid': self.r.token(kid='unknown'),
                    'refresh': self.r.token(changes={'token_type': 'refresh', 'jti': 'synthetic-refresh'})}
        targets = [(MENU, '/menus', dict(name='auth-test', price=100)),
                   (FOOD, '/foodmaterials', dict(sku=self.name('AUTH'), name='auth-test', unitPrice=100)),
                   (DISP, '/disposals', dict(requestId=self.name('AUTH'), foodMaterialId=1, quantity=1, reason='auth-test'))]
        for module, path, body in targets:
            self.call(module, path)  # Trusted kid/issuer/audience control for each service.
            for label, token in variants.items():
                before = self.r.snapshot()
                code = 'AUTHENTICATION_REQUIRED' if token is None else 'INVALID_ACCESS_TOKEN'
                self.call(module, path, expected=401, code=code, token=token)
                self.call(module, path, 'POST', body, 401, code, token=token)
                self.unchanged(before, module+' authentication '+label)
        self.r.manifest['authentication'] = dict(services=3, variants=list(variants), invalidRequests=42,
            issuer='g2-fixture', audience='g2-fixture', trustedKid=self.r.kid, expiryLeewaySeconds=30,
            expiredAtLeastSecondsAgo=60, source='synthetic RSA fixtures; not Account-issued tokens')

    def nf04(self):
        menus = [self.call(MENU, '/menus', 'POST', dict(name=self.name('MENU'), price=1000), 201) for _ in range(3)]
        self.menu = menus[0]
        path = '/menus/'+str(self.menu['menuId'])
        require(self.call(MENU, path) == self.menu, 'Menu detail mismatch')
        update = dict(name='수정 메뉴', description='changed', price=2500, status='ACTIVE', version=self.menu['version'])
        changed = self.call(MENU, path, 'PUT', update)
        require(changed['name'] == update['name'] and changed['price'] == 2500 and changed['version'] == self.menu['version']+1, 'Menu update mismatch')
        before = self.r.snapshot()
        self.call(MENU, path, 'PUT', update, 409, 'MENU_CONFLICT')
        self.unchanged(before, 'stale menu')
        self.call(MENU, path, 'DELETE', expected=204)
        self.menu = self.call(MENU, path)
        require(self.menu['status'] == 'INACTIVE', 'Menu not deactivated')
        for status in (None, 'ACTIVE', 'INACTIVE'):
            self.pages(MENU, '/menus', 'menus', 'menuId', 'menu', status)

    def nf05(self):
        self.food = self.material()
        self.material()
        path = '/foodmaterials/'+str(self.food['foodMaterialId'])
        require(self.call(FOOD, path) == self.food, 'Food detail mismatch')
        require(self.food['sku'] == self.food['sku'].upper(), 'SKU not normalized')
        for sku in (self.food['sku'], self.food['sku'].lower()):
            before = self.r.snapshot()
            self.call(FOOD, '/foodmaterials', 'POST', dict(sku=sku, name='duplicate', unitPrice=100), 409, 'SKU_ALREADY_EXISTS')
            self.unchanged(before, 'duplicate SKU')
        other = self.call(FOOD, '/foodmaterials', 'POST', dict(sku=self.food['sku'].lower(), name='B material', unitPrice=100), 201, account=202)
        require(other['sku'] == self.food['sku'], 'Cross-account normalized SKU mismatch')
        update = dict(name='수정 식자재', description='changed', unitPrice=1500, status='ACTIVE', version=self.food['version'])
        changed = self.call(FOOD, path, 'PUT', update)
        require(changed['name'] == update['name'] and changed['unitPrice'] == 1500 and changed['version'] == self.food['version']+1, 'Food update mismatch')
        before = self.r.snapshot()
        self.call(FOOD, path, 'PUT', update, 409, 'FOOD_MATERIAL_CONFLICT')
        self.unchanged(before, 'stale food')
        self.call(FOOD, path, 'DELETE', expected=204)
        self.food = self.call(FOOD, path)
        require(self.food['status'] == 'INACTIVE', 'Food not deactivated')
        for status in (None, 'ACTIVE', 'INACTIVE'):
            self.pages(FOOD, '/foodmaterials', 'foodMaterials', 'foodMaterialId', 'item', status)

    def nf06(self):
        self.flow = self.material(20)
        stock = self.stock(self.flow)
        path = f'/foodmaterials/inventories/{self.flow["foodMaterialId"]}/adjustments'
        body = dict(requestId=self.name('ADJ'), quantityDelta=-3, reason='검증 조정', version=stock['version'])
        adjusted = self.call(FOOD, path, 'POST', body)
        require(adjusted['inventory']['onHandQuantity'] == 17, 'Adjustment result mismatch')
        before = self.r.snapshot()
        self.call(FOOD, path, 'POST', body, 409, 'ADJUSTMENT_ALREADY_EXISTS')
        self.unchanged(before, 'duplicate adjustment')
        payload = self.dispose(self.flow, 2)
        self.completed = self.call(DISP, '/disposals', 'POST', payload)
        require(self.completed['status'] == 'COMPLETED' and self.completed['quantityAfter'] == 15, 'Disposal not completed')
        before = self.r.snapshot()
        repeated = self.call(DISP, '/disposals', 'POST', payload)
        retried = self.call(DISP, '/disposals/'+self.completed['disposalId']+'/retry', 'POST')
        require(repeated == self.completed and retried == self.completed, 'Idempotent disposal result changed')
        self.unchanged(before, 'completed retry')
        self.ledger(self.flow, 15, ['INITIAL','ADJUSTMENT','DISPOSAL'], stock['version']+2)
        self.disposal_row(self.completed)
        require(self.call(DISP, '/disposals/'+self.completed['disposalId']) == self.completed, 'Disposal detail mismatch')
        listed = self.call(FOOD, '/foodmaterials/inventories')['inventories']
        require(self.stock(self.flow) in listed, 'Flow stock absent from owner inventory list')

    def nf07(self):
        before = self.r.snapshot()
        for module, path, update in [
            (MENU, '/menus/'+str(self.menu['menuId']), dict(name='B change', price=100, status='ACTIVE', version=self.menu['version'])),
            (FOOD, '/foodmaterials/'+str(self.food['foodMaterialId']), dict(name='B change', unitPrice=100, status='ACTIVE', version=self.food['version']))]:
            self.call(module, path, expected=404, account=202)
            self.call(module, path, 'PUT', update, 404, account=202)
            self.call(module, path, 'DELETE', expected=404, account=202)
        stockpath = '/foodmaterials/inventories/'+str(self.flow['foodMaterialId'])
        self.call(FOOD, stockpath, expected=404, account=202)
        self.call(FOOD, stockpath+'/movements', expected=404, account=202)
        self.call(FOOD, stockpath+'/adjustments', 'POST', dict(requestId=self.name('B-ADJ'), quantityDelta=-1, reason='B', version=0), 404, account=202)
        dp = '/disposals/'+self.completed['disposalId']
        self.call(DISP, dp, expected=404, account=202)
        self.call(DISP, dp+'/retry', 'POST', expected=404, account=202)
        for module, path, field, key, table in [(MENU,'/menus','menus','menuId','menu'), (FOOD,'/foodmaterials','foodMaterials','foodMaterialId','item'), (DISP,'/disposals','disposals','disposalId','disposal')]:
            self.pages(module, path, field, key, table, account=202)
        require(self.call(FOOD, '/foodmaterials/inventories', account=202)['totalElements'] == 0, 'B sees A inventory')
        self.unchanged(before, 'cross-account operations')
        rejected = self.call(DISP, '/disposals', 'POST', self.dispose(self.flow, 1), 409, account=202)
        require(rejected['status'] == 'REJECTED' and rejected['rejectionCode'] == 'INVENTORY_NOT_FOUND', 'Cross-account create contract mismatch')
        self.disposal_row(rejected, 202)
        after = self.r.snapshot()
        require({k:v for k,v in before.items() if k != 'disposal'} == {k:v for k,v in after.items() if k != 'disposal'}, 'Cross-account create changed inventory/catalog')
        require(len(after['disposal']) == len(before['disposal'])+1, 'Expected exactly one B rejection')
        require([v for v in after['disposal'] if v['account_id'] == 101] == [v for v in before['disposal'] if v['account_id'] == 101], 'B creation changed A disposal')

    def nf08(self):
        before = self.r.snapshot()
        failures = []
        def invalid(module, path, method='GET', body=None):
            status, data = self.r.http(module, path, method, body)
            if status != 400 or data.get('code') != 'INVALID_REQUEST':
                failures.append(dict(module=module, method=method, path=path, expected=400, expectedCode='INVALID_REQUEST', actual=status, response=data))
        for body in (dict(name='bad', price=-1), dict(price=100)):
            invalid(MENU, '/menus', 'POST', body)
        base = self.dispose(self.flow, 1)
        for change in ({'quantity': 0}, {'quantity': -1}, {'requestId': 'x'*65}, {'reason': 'x'*256}):
            invalid(DISP, '/disposals', 'POST', dict(base, **change))
        for module, path in ((MENU,'/menus'), (FOOD,'/foodmaterials'), (FOOD,'/foodmaterials/inventories'),
                             (FOOD,f'/foodmaterials/inventories/{self.flow["foodMaterialId"]}/movements'), (DISP,'/disposals')):
            for query in ('page=-1', 'size=101'):
                invalid(module, path+'?'+query)
        self.r.manifest['inputFailures'] = failures
        if self.r.snapshot() != before:
            raise FatalFailure('Invalid input mutated DB; stop diagnostic continuation')
        require(not failures, 'Invalid input HTTP mismatch: '+str(failures))

    def nf09(self):
        for repeat in range(3):
            material = self.material(20)
            payload = self.dispose(material, 3)
            results = parallel([lambda: self.call(DISP, '/disposals', 'POST', payload) for _ in range(8)], self.r)
            require(all(v['status'] == 'COMPLETED' for v in results) and len({v['disposalId'] for v in results}) == 1, 'Concurrent idempotency failed')
            require(all(v == results[0] for v in results), 'Concurrent disposal responses differ')
            self.ledger(material, 17, ['INITIAL','DISPOSAL'], 1)
            self.disposal_row(results[0])
            before = self.r.snapshot()
            for change in ({'quantity': 4}, {'foodMaterialId': self.flow['foodMaterialId']}, {'reason': 'changed'}):
                self.call(DISP, '/disposals', 'POST', dict(payload, **change), 409, 'REQUEST_CONFLICT')
            self.unchanged(before, f'disposal request conflict repeat {repeat+1}')

    def nf10(self):
        material = self.material(20)
        rejected = self.call(DISP, '/disposals', 'POST', self.dispose(material, 21), 409)
        require(rejected['status'] == 'REJECTED' and rejected['rejectionCode'] == 'INSUFFICIENT_STOCK', 'Stock shortage contract mismatch')
        self.disposal_row(rejected)
        self.ledger(material, 20, ['INITIAL'], 0)
        self.call(FOOD, f'/foodmaterials/inventories/{material["foodMaterialId"]}/adjustments', 'POST',
                  dict(requestId=self.name('REPLENISH'), quantityDelta=2, reason='보충', version=0))
        before = self.r.snapshot()
        require(self.call(DISP, '/disposals/'+rejected['disposalId']+'/retry', 'POST', expected=409) == rejected, 'Rejected retry changed result')
        self.unchanged(before, 'rejected retry after replenishment')
        self.ledger(material, 22, ['INITIAL','ADJUSTMENT'], 1)
        missing = self.material()
        before_missing = self.r.snapshot()
        rejected_missing = self.call(DISP, '/disposals', 'POST', self.dispose(missing, 1), 409)
        require(rejected_missing['status'] == 'REJECTED' and rejected_missing['rejectionCode'] == 'INVENTORY_NOT_FOUND', 'Missing inventory contract mismatch')
        self.disposal_row(rejected_missing)
        after_missing = self.r.snapshot()
        require(all(before_missing[t] == after_missing[t] for t in ('item','inventory','stock_movement','menu')), 'Missing inventory rejection changed stock/catalog')
        for _ in range(3):
            material = self.material(20)
            payloads = [self.dispose(material, 15), self.dispose(material, 15)]
            outcomes = parallel([lambda payload=p: self.r.http(DISP, '/disposals', 'POST', payload) for p in payloads], self.r)
            require(sorted(status for status, _ in outcomes) == [200, 409], 'Concurrent shortage HTTP mismatch')
            for status, body in outcomes:
                require(body['status'] == ('COMPLETED' if status == 200 else 'REJECTED'), 'Concurrent shortage state mismatch')
                if status == 409:
                    require(body['rejectionCode'] == 'INSUFFICIENT_STOCK', 'Concurrent shortage rejection mismatch')
                self.disposal_row(body)
            self.ledger(material, 5, ['INITIAL','DISPOSAL'], 1)

    def nf11(self):
        for _ in range(3):
            material = self.material(20)
            path = f'/foodmaterials/inventories/{material["foodMaterialId"]}/adjustments'
            bodies = [dict(requestId=self.name('RACE'), quantityDelta=-1, reason='동시 조정', version=0) for _ in range(10)]
            outcomes = parallel([lambda body=b: self.r.http(FOOD, path, 'POST', body) for b in bodies], self.r)
            require(sorted(status for status, _ in outcomes) == [200]+[409]*9, 'Optimistic lock winner count mismatch')
            require(all(status == 200 or body.get('code') == 'INVENTORY_CONFLICT' for status, body in outcomes), 'Optimistic lock error code mismatch')
            rows = self.ledger(material, 19, ['INITIAL','ADJUSTMENT'], 1)
            winner = next(body for status, body in outcomes if status == 200)
            require(winner['movement']['requestId'] == rows[-1]['request_id'], 'Winning adjustment command differs from DB')

    def nf12(self):
        rows = self.r.rows('disposal')
        require(all(row['status'] in ('COMPLETED','REJECTED') for row in rows), 'Unexpected PENDING disposal in normal flow')
        for row in rows:
            result = self.call(DISP, '/disposals/'+row['id'], account=row['account_id'])
            self.disposal_row(result, row['account_id'])
        for account in (101, 202):
            for status in (None, 'COMPLETED', 'REJECTED'):
                self.pages(DISP, '/disposals', 'disposals', 'disposalId', 'disposal', status, account)


def execute(run):
    cases = Cases(run)
    run.manifest['scenarios'] = [dict(id=name, status='NOT_RUN') for name in CASES]
    run.manifest['excluded'] = {'NF-01':'G3 Account', 'NF-03':'G3 routing/501', 'NF-13':'G1 legacy / G3 migrations',
                                'NF-14':'G3 Outbox/Kafka', 'NF-15':'G3 monitoring'}
    run.manifest['migrations'] = {schema: run.sql(f"SELECT JSON_OBJECT('version',version,'success',success,'checksum',checksum) FROM {schema}.flyway_schema_history ORDER BY installed_rank") for schema in ('itemdb','inventorydb','menusdb','disposalsdb')}
    if not all(rows and all(row['success'] == 1 for row in rows) for rows in run.manifest['migrations'].values()):
        raise RuntimeError('Migration precondition missing/failed')
    run.save()
    for entry in run.manifest['scenarios']:
        dependencies = {'NF-07': ('NF-04','NF-05','NF-06'), 'NF-08': ('NF-06',),
                        'NF-09': ('NF-06',), 'NF-12': ('NF-06','NF-10')}.get(entry['id'], ())
        states = {v['id']:v['status'] for v in run.manifest['scenarios']}
        if any(states[dep] != 'PASS' for dep in dependencies):
            entry['reason'] = 'Required fixture scenario did not pass'
            run.save()
            continue
        run.scenario = entry['id']
        entry['status'] = 'RUNNING'
        run.save()
        print('RUN '+run.scenario, flush=True)
        failure = None
        try:
            getattr(cases, 'nf'+entry['id'][-2:])()
            entry['status'] = 'PASS'
        except AssertionError as exc:
            entry.update(status='FAIL', error=run.clean_text(str(exc)))
            if entry['id'] == 'NF-02' or isinstance(exc, FatalFailure):
                failure = exc
        except BaseException as exc:
            entry.update(status='BLOCKED', error=run.clean_text(type(exc).__name__+': '+str(exc)))
            failure = exc
        finally:
            try:
                snapshot = run.snapshot()
                path = run.artifact/(run.scenario+'-database.json')
                path.write_text(__import__('json').dumps(snapshot, ensure_ascii=False, indent=2)+'\n')
                entry['databaseEvidence'] = path.name
            except Exception as exc:
                entry['evidenceError'] = run.clean_text(type(exc).__name__+': '+str(exc))
                if entry['status'] == 'PASS':
                    entry['status'] = 'BLOCKED'
                if failure is None:
                    failure = RuntimeError('Database evidence collection failed: '+entry['evidenceError'])
            finally:
                run.save()
        if failure is not None:
            raise failure
        print(entry['status']+' '+run.scenario, flush=True)
