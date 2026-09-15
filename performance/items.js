import http from 'k6/http';
import { check } from 'k6';
import exec from 'k6/execution';
import { SharedArray } from 'k6/data';

const users = new SharedArray('users', () => JSON.parse(open('/work/results/users.json')));
const rate = Number(__ENV.RATE || 40);
const base = __ENV.BASE_URL || 'http://gateway-server:7070';
const profile = __ENV.PROFILE || 'mixed';
const label = __ENV.LABEL || 'run';
export const options = {
  scenarios: { listings: { executor: 'constant-arrival-rate', rate, timeUnit: '1s',
    duration: __ENV.DURATION || '60s', preAllocatedVUs: 150, maxVUs: 150 } },
  thresholds: { http_req_failed: ['rate<0.01'], checks: ['rate>0.99'], dropped_iterations: ['count==0'] },
  summaryTrendStats: ['avg', 'p(50)', 'p(95)', 'p(99)', 'max'],
};

// The iteration index deterministically reproduces accounts, pages and skew across runs.
export function requestCase(i) {
  function hash(n) { n = Math.imul(n ^ (n >>> 16), 0x45d9f3b); n = Math.imul(n ^ (n >>> 16), 0x45d9f3b); return (n ^ (n >>> 16)) >>> 0; }
  if (profile === 'fixed') return { user: users[0], size: 20, page: 0, status: 'ACTIVE' };
  const user = users[hash(i + 11) % users.length];
  const bucket = hash(i + 101) % 100;
  const status = bucket < 60 ? 'ACTIVE' : bucket < 80 ? 'INACTIVE' : null;
  const size = [20, 50, 100][hash(i + 1009) % 3];
  const available = status === 'INACTIVE' ? user.rows / 5 : status === 'ACTIVE' ? user.rows * 4 / 5 : user.rows;
  const pages = Math.max(1, Math.floor(available / size));
  const page = hash(i + 5003) % 100 < 65 ? hash(i + 9001) % Math.min(3, pages) : hash(i + 11003) % pages;
  return { user, size, page, status };
}

export default function () {
  const c = requestCase(exec.scenario.iterationInTest);
  const query = `page=${c.page}&size=${c.size}${c.status ? `&status=${c.status}` : ''}`;
  const response = http.get(`${base}/items?${query}`, {
    headers: { Authorization: `Bearer ${c.user.token}` },
    tags: { name: 'GET /items', profile, route: base.includes('gateway') ? 'gateway' : 'direct' },
    timeout: '5s',
  });
  check(response, { '200 with correct tenant data': r => {
    if (r.status !== 200) return false;
    const body = r.json();
    return Array.isArray(body.items) && body.items.length > 0 && body.items.every(item => item.sku.startsWith(`P-${c.user.accountId}-`));
  }});
}

export function handleSummary(data) {
  return { [`/work/results/${label}.json`]: JSON.stringify(data, null, 2) };
}
