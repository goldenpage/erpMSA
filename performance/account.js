// Account(로그인·회원가입·토큰 갱신) 부하 시나리오. performance/account_lab.py가 실행 조건을 넘긴다.
// 설계와 판정 기준: docs/load-test-design.md §13
import http from 'k6/http';
import { check, sleep } from 'k6';
import exec from 'k6/execution';
import { Counter } from 'k6/metrics';

const fixture = JSON.parse(open(__ENV.FIXTURE_FILE || '/work/results/account-fixture.json'));
const BASE = __ENV.BASE_URL || 'http://gateway-server:7070';
const SCENARIO = __ENV.SCENARIO || 'login';
const LABEL = __ENV.LABEL || 'account-run';
const RUN_NO = Number(__ENV.RUN_NO || 0);
const DOMAIN = fixture.domain;
const JSON_HEADERS = { 'Content-Type': 'application/json' };

// 실패로 세지 않을 상태. 판정은 check와 아래 카운터가 담당한다.
const OK_200 = http.expectedStatuses(200);
const OK_201 = http.expectedStatuses(201);
const OK_401 = http.expectedStatuses(401);
const OK_403 = http.expectedStatuses(403);
const OK_REGISTER_RACE = http.expectedStatuses(201, 409);
const OK_REFRESH_RACE = http.expectedStatuses(200, 401);

const unexpected5xx = new Counter('account_unexpected_5xx');
const registerCreated = new Counter('account_register_created');
const dupGroupOk = new Counter('account_dup_group_ok');
const dupGroupBad = new Counter('account_dup_group_bad');
const refreshOk = new Counter('account_refresh_ok');
const replayRejected = new Counter('account_refresh_replay_rejected');
const replayAccepted = new Counter('account_refresh_replay_accepted');
const raceOk = new Counter('account_refresh_race_ok');
const raceBad = new Counter('account_refresh_race_bad'); // 같은 토큰으로 두 요청이 모두 성공(이중 사용)
const raceInconclusive = new Counter('account_refresh_race_inconclusive'); // 인프라 오류 등으로 판정 불가
const sessionLost = new Counter('account_session_lost');

// 결정적 해시: 같은 iteration은 실행마다 같은 계정·분기를 고른다.
export function hash(n) {
  n = Math.imul(n ^ (n >>> 16), 0x45d9f3b); n = Math.imul(n ^ (n >>> 16), 0x45d9f3b);
  return (n ^ (n >>> 16)) >>> 0;
}
export function pad(value, width) { return String(value).padStart(width, '0'); }

// seed 규칙: seq % 100 == 0 → SUSPENDED, == 1 → PENDING, 나머지 ACTIVE (account_lab.py와 동일해야 함)
export function statusOf(seq) { const r = seq % 100; return r === 0 ? 'SUSPENDED' : r === 1 ? 'PENDING' : 'ACTIVE'; }
export function activeCount(accounts) { return Math.floor(accounts / 100) * 98; }
export function activeSeq(k, accounts) {
  const n = activeCount(accounts);
  const i = ((k % n) + n) % n;
  return Math.floor(i / 98) * 100 + (i % 98) + 2;
}
export function seededEmail(seq) { return `acct-${pad(seq, 8)}@${DOMAIN}`; }

// "50:2m,100:2m" → ramping-arrival-rate stages
export function parseStages(text) {
  return text.split(',').map(part => {
    const [target, duration] = part.trim().split(':');
    if (!/^\d+$/.test(target) || !/^\d+[smh]$/.test(duration)) throw new Error(`Invalid stage: ${part}`);
    return { target: Number(target), duration };
  });
}

function arrival(execName, rateEnv, stagesEnv) {
  const maxVUs = Number(__ENV.MAX_VUS || 500);
  const preAllocatedVUs = Number(__ENV.PRE_VUS || Math.min(maxVUs, 100));
  if (stagesEnv) {
    return { executor: 'ramping-arrival-rate', exec: execName, startRate: Number(__ENV.START_RATE || 1), timeUnit: '1s',
      stages: parseStages(stagesEnv), preAllocatedVUs, maxVUs };
  }
  return { executor: 'constant-arrival-rate', exec: execName, rate: Number(rateEnv || 20), timeUnit: '1s',
    duration: __ENV.DURATION || '60s', preAllocatedVUs, maxVUs };
}

const EXEC = { me: 'me', login: 'login_scenario', register: 'register', 'register-dup': 'register_dup' };

function scenarios() {
  switch (SCENARIO) {
    case 'me': case 'login': case 'register': case 'register-dup':
      return { [SCENARIO]: arrival(EXEC[SCENARIO], __ENV.RATE, __ENV.STAGES) };
    case 'login-attack':
      return {
        normal: { ...arrival('normal_login', __ENV.NORMAL_RATE || 10, null), duration: __ENV.DURATION || '10m' },
        attack: { ...arrival('attack_login', __ENV.RATE, __ENV.STAGES), startTime: __ENV.ATTACK_DELAY || '60s' },
      };
    case 'session':
      return { session: __ENV.STAGES
        ? { executor: 'ramping-vus', exec: 'session', startVUs: 0, stages: parseStages(__ENV.STAGES), gracefulRampDown: '30s' }
        : { executor: 'constant-vus', exec: 'session', vus: Number(__ENV.VUS || 100), duration: __ENV.DURATION || '10m' } };
    default:
      throw new Error(`Unknown SCENARIO ${SCENARIO}`);
  }
}

export const options = {
  scenarios: scenarios(),
  batchPerHost: 12,
  thresholds: {
    http_req_failed: ['rate<0.01'], checks: ['rate>0.99'], dropped_iterations: ['count==0'],
    account_unexpected_5xx: ['count==0'], account_dup_group_bad: ['count==0'],
    account_refresh_replay_accepted: ['count==0'], account_refresh_race_bad: ['count==0'],
  },
  summaryTrendStats: ['avg', 'p(50)', 'p(90)', 'p(95)', 'p(99)', 'max'],
};

function count5xx(response) { if (response.status >= 500 || response.status === 0) unexpected5xx.add(1); }
function codeOf(response) { try { return response.json('code'); } catch (_) { return null; } }
function refreshCookie(response) { const c = response.cookies.refreshToken; return c && c.length ? c[0].value : null; }

function postLogin(email, password, kind, expected) {
  const response = http.post(`${BASE}/account/auth/login`, JSON.stringify({ email, password }), {
    headers: JSON_HEADERS, tags: { name: 'POST /account/auth/login', kind }, responseCallback: expected, timeout: '10s' });
  count5xx(response);
  return response;
}

function refresh(token, tags, expected) {
  return http.post(`${BASE}/account/auth/refresh`, null, {
    cookies: { refreshToken: { value: token, replace: true } }, tags, responseCallback: expected, timeout: '10s' });
}

export function setup() {
  if (SCENARIO !== 'me') return {};
  const response = postLogin(seededEmail(activeSeq(0, fixture.accounts)), fixture.password, 'setup', OK_200);
  if (response.status !== 200) throw new Error(`setup login failed: ${response.status}`);
  return { token: response.json('accessToken') };
}

// A0: 인증 오버헤드 기준선 (BCrypt 없음)
export function me(data) {
  const response = http.get(`${BASE}/account/auth/me`, {
    headers: { Authorization: `Bearer ${data.token}` }, tags: { name: 'GET /account/auth/me' }, responseCallback: OK_200 });
  count5xx(response);
  check(response, { 'me 200': r => r.status === 200 });
}

// A1·A7: 시드 계정 로그인. LOGIN_SET=all이면 로그인 불가 상태(403)도 섞는다.
export function login_scenario() {
  const i = exec.scenario.iterationInTest;
  if ((__ENV.LOGIN_SET || 'active') === 'all') {
    const seq = (hash(i + 17) % fixture.accounts) + 1;
    const status = statusOf(seq);
    const response = postLogin(seededEmail(seq), fixture.password, status === 'ACTIVE' ? 'active' : 'forbidden',
      status === 'ACTIVE' ? OK_200 : OK_403);
    check(response, { 'login status matches account state': r => status === 'ACTIVE'
      ? r.status === 200 && !!r.json('accessToken') && !!refreshCookie(r)
      : r.status === 403 && codeOf(r) === 'ACCOUNT_LOGIN_FORBIDDEN' });
    return;
  }
  const response = postLogin(seededEmail(activeSeq(hash(i + 17), fixture.accounts)), fixture.password, 'active', OK_200);
  check(response, { 'login 200 with tokens': r => r.status === 200 && !!r.json('accessToken') && !!refreshCookie(r) });
}

// A4: 정상 로그인 유지 + 실패 로그인 폭주
export function normal_login() {
  const i = exec.scenario.iterationInTest;
  const response = postLogin(seededEmail(activeSeq(hash(i + 29), fixture.accounts)), fixture.password, 'normal', OK_200);
  check(response, { 'normal login 200': r => r.status === 200 });
}
export function attack_login() {
  const i = exec.scenario.iterationInTest;
  const kind = __ENV.ATTACK_KIND || 'wrongpw';
  const email = kind === 'unknown' ? `nobody-r${pad(RUN_NO, 2)}-${i}@${DOMAIN}` : seededEmail(activeSeq(hash(i + 31), fixture.accounts));
  const response = postLogin(email, `wrong-${hash(i)}-password`, `attack-${kind}`, OK_401);
  check(response, { 'attack rejected 401': r => r.status === 401 && codeOf(r) === 'INVALID_CREDENTIALS' });
}

function registerBody(email, businessId, i) {
  return JSON.stringify({ email, businessId, password: `Lt-${hash(i + 7)}-pass`, name: `Load ${i}`.slice(0, 50),
    phone: '01012345678', storeName: 'Load Register', storeType: 'RETAIL', storeCategory: 'TEST', marketingAgreed: false });
}

// A2: 고유 신규 가입. b_id = 7 + 실행번호 2자리 + iteration 7자리
export function register() {
  const i = exec.scenario.iterationInTest;
  if (i >= 10000000) exec.test.abort('register iteration space exhausted');
  const response = http.post(`${BASE}/account/auth/register`,
    registerBody(`reg-r${pad(RUN_NO, 2)}-${i}@${DOMAIN}`, `7${pad(RUN_NO, 2)}${pad(i, 7)}`, i), {
      headers: JSON_HEADERS, tags: { name: 'POST /account/auth/register' }, responseCallback: OK_201, timeout: '15s' });
  count5xx(response);
  if (response.status === 201) registerCreated.add(1);
  check(response, { 'register 201': r => r.status === 201 && Number.isInteger(r.json('accountId')) });
}

// A5: 같은 이메일(DUP_MODE=email) 또는 같은 사업자번호(DUP_MODE=bid)로 동시 가입
export function register_dup() {
  const g = exec.scenario.iterationInTest;
  if (g >= 1000000) exec.test.abort('duplicate group space exhausted');
  const size = Math.min(10, Math.max(2, Number(__ENV.DUP_SIZE || 4)));
  const mode = __ENV.DUP_MODE || 'email';
  const requests = [];
  for (let m = 0; m < size; m++) {
    const email = mode === 'email' ? `dup-r${pad(RUN_NO, 2)}-${g}@${DOMAIN}` : `dup-r${pad(RUN_NO, 2)}-${g}-${m}@${DOMAIN}`;
    const bid = `6${pad(RUN_NO, 2)}${pad(g, 6)}${mode === 'email' ? m : 0}`;
    requests.push({ method: 'POST', url: `${BASE}/account/auth/register`, body: registerBody(email, bid, g * 10 + m),
      params: { headers: JSON_HEADERS, tags: { name: 'POST /account/auth/register', kind: `dup-${mode}` },
        responseCallback: OK_REGISTER_RACE, timeout: '15s' } });
  }
  const responses = http.batch(requests);
  responses.forEach(count5xx);
  const created = responses.filter(r => r.status === 201).length;
  const conflicts = responses.filter(r => r.status === 409
    && ['EMAIL_ALREADY_EXISTS', 'BUSINESS_ID_ALREADY_EXISTS', 'ACCOUNT_CONFLICT'].includes(codeOf(r))).length;
  const ok = created === 1 && conflicts === size - 1;
  (ok ? dupGroupOk : dupGroupBad).add(1);
  check(responses, { 'duplicate group: exactly one 201, rest 409': () => ok });
}

// A3: 로그인 → 주기적 API 호출 → 주기적 갱신(회전). 일부는 이전 토큰 재사용·동시 갱신을 섞는다.
let state = null;
let loginFailures = 0;
export function session() {
  const vu = exec.vu.idInTest;
  if (!state) {
    const response = postLogin(seededEmail(activeSeq(hash(vu + 101), fixture.accounts)), fixture.password, 'session-start', OK_200);
    if (!check(response, { 'session login 200': r => r.status === 200 })) {
      // 실패한 세션이 매초 재로그인하면 BCrypt 부하를 증폭한다. 지수 백오프(최대 30초)와 지터를 둔다.
      sessionLost.add(1);
      loginFailures += 1;
      sleep(Math.min(30, 2 ** loginFailures) * (0.5 + Math.random()));
      return;
    }
    loginFailures = 0;
    state = { access: response.json('accessToken'), refresh: refreshCookie(response), refreshedAt: Date.now(), n: 0 };
  }
  const me = http.get(`${BASE}/account/auth/me`, { headers: { Authorization: `Bearer ${state.access}` },
    tags: { name: 'GET /account/auth/me' }, responseCallback: OK_200 });
  count5xx(me);
  check(me, { 'session me 200': r => r.status === 200 });

  if (Date.now() - state.refreshedAt >= Number(__ENV.REFRESH_EVERY || 60) * 1000) {
    state.n += 1;
    const roll = hash(vu * 7919 + state.n) % 100;
    const old = state.refresh;
    let winner = null;
    if (roll < Number(__ENV.RACE_PCT || 2)) {
      const tags = { name: 'POST /account/auth/refresh', kind: 'race' };
      const pair = http.batch([
        { method: 'POST', url: `${BASE}/account/auth/refresh`, body: null, params: { cookies: { refreshToken: { value: old, replace: true } }, tags, responseCallback: OK_REFRESH_RACE } },
        { method: 'POST', url: `${BASE}/account/auth/refresh`, body: null, params: { cookies: { refreshToken: { value: old, replace: true } }, tags, responseCallback: OK_REFRESH_RACE } },
      ]);
      pair.forEach(count5xx);
      const won = pair.filter(r => r.status === 200);
      const lost = pair.filter(r => r.status === 401);
      if (won.length > 1) raceBad.add(1);
      else if (won.length === 1 && lost.length === 1) raceOk.add(1);
      else raceInconclusive.add(1);
      winner = won[0] || null;
    } else {
      const response = refresh(old, { name: 'POST /account/auth/refresh', kind: 'rotate' }, OK_200);
      count5xx(response);
      check(response, { 'refresh 200 rotated': r => r.status === 200 && refreshCookie(r) && refreshCookie(r) !== old });
      if (response.status === 200) winner = response;
    }
    if (!winner) { sessionLost.add(1); state = null; return; }
    refreshOk.add(1);
    state.access = winner.json('accessToken'); state.refresh = refreshCookie(winner); state.refreshedAt = Date.now();
    if (roll >= 100 - Number(__ENV.REPLAY_PCT || 5)) {
      const replay = refresh(old, { name: 'POST /account/auth/refresh', kind: 'replay' }, OK_401);
      count5xx(replay);
      if (replay.status === 401) replayRejected.add(1);
      else if (replay.status === 200) replayAccepted.add(1);
    }
  }
  sleep(Number(__ENV.THINK || 5));
}

export function handleSummary(data) {
  return { [`${__ENV.RESULTS_DIR || '/work/results'}/${LABEL}.json`]: JSON.stringify(data, null, 2) };
}
