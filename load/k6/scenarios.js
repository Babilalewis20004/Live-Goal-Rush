// k6 load scenarios (Phase 7 §28).  Run through Docker so the generator sits on the compose network and uses real
// threads (a Python generator tops out near 30-40 rps of this traffic):
//
//   python apps/api/scripts/make_loadtest_data.py --dsn postgresql://... --out load/k6/world.json
//   docker run --rm -i --network live-goal_default -v "$PWD/load/k6:/k6" -e BASE=http://api:8000 -e SCENARIO=home \
//       -e VUS=100 -e DURATION=30s grafana/k6 run /k6/scenarios.js
//
// SCENARIO is one of: home, live, search, spike, community, websocket -- or one of the capacity probes below, which
// have no think time and exist to find what one API process can do flat out: ping (framework only), cached (one cached
// match endpoint), searchhot (the same search repeatedly), searchcold (a different search every time).  Thresholds make the run fail (non-zero
// exit) when p95 latency or the error rate crosses the launch targets in docs/operations/load-testing.md.
import http from "k6/http";
import ws from "k6/ws";
import { check, sleep } from "k6";
import { Counter, Trend } from "k6/metrics";

const BASE = __ENV.BASE || "http://api:8000";
const API = `${BASE}/api/v1`;
const SCENARIO = __ENV.SCENARIO || "home";
const VUS = parseInt(__ENV.VUS || "100");
const DURATION = __ENV.DURATION || "30s";
const world = JSON.parse(open("/k6/world.json"));

const pick = (list) => list[Math.floor(Math.random() * list.length)];
const serverErrors = new Counter("server_errors"); // 5xx and transport failures (429 is the rate limiter working)
const wsConnectMs = new Trend("ws_connect_ms", true);
const wsDropped = new Counter("ws_dropped");

// 429 (rate limit) and 4xx validation answers are not failures of the server.
http.setResponseCallback(http.expectedStatuses({ min: 200, max: 499 }));

const ramp = (target) => ({
  executor: "ramping-vus",
  startVUs: 0,
  stages: [
    { duration: "10s", target },
    { duration: DURATION, target },
    { duration: "5s", target: 0 },
  ],
  gracefulRampDown: "5s",
});

const scenarios = {
  home: { home: { ...ramp(VUS), exec: "home" } },
  live: { live: { ...ramp(VUS), exec: "live" } },
  search: { search: { ...ramp(VUS), exec: "search" } },
  // idle -> peak x4 in 20 s, hold, drop: kick-off of a derby
  spike: {
    spike: {
      executor: "ramping-vus",
      startVUs: 0,
      stages: [
        { duration: "10s", target: Math.round(VUS * 0.1) },
        { duration: "20s", target: VUS * 4 },
        { duration: DURATION, target: VUS * 4 },
        { duration: "10s", target: 0 },
      ],
      exec: "spike",
    },
  },
  community: { community: { ...ramp(VUS), exec: "community" } },
  websocket: { websocket: { ...ramp(VUS), exec: "websocket" } },
  // capacity probes: closed loop, no sleeping
  ping: { ping: { ...ramp(VUS), exec: "ping" } },
  cached: { cached: { ...ramp(VUS), exec: "cached" } },
  searchhot: { searchhot: { ...ramp(VUS), exec: "searchhot" } },
  searchcold: { searchcold: { ...ramp(VUS), exec: "searchcold" } },
};

export const options = {
  scenarios: scenarios[SCENARIO],
  thresholds: {
    http_req_failed: [{ threshold: "rate<0.01", abortOnFail: false }],
    http_req_duration: ["p(95)<1000"],
    server_errors: ["count<50"],
  },
  summaryTrendStats: ["avg", "min", "med", "p(90)", "p(95)", "p(99)", "max"],
};

function track(res) {
  if (res.status >= 500 || res.status === 0) serverErrors.add(1);
  return res;
}

export function home() {
  // the four calls the Next.js home page makes per visit
  const responses = http.batch([
    ["GET", `${API}/matches/live`],
    ["GET", `${API}/matches/today`],
    ["GET", `${API}/matches/upcoming`],
    ["GET", `${API}/discovery/home`],
  ]);
  responses.forEach(track);
  check(responses[0], { "live 200": (r) => r.status === 200 });
  sleep(1 + Math.random() * 2);
}

export function live() {
  const id = pick(world.match_ids);
  const suffix = pick(["", "", "/events", "/statistics", "/lineups", "/form", "/head-to-head", "/insights"]);
  track(http.get(`${API}/matches/live`));
  const r = track(http.get(`${API}/matches/${id}${suffix}`));
  check(r, { "match page ok": (res) => res.status === 200 });
  sleep(1 + Math.random() * 3);
}

export function search() {
  const word = pick(world.team_names.concat(["goal", "transfer", "derby", "league", "cup"]));
  const q = word.slice(0, Math.max(2, word.length - Math.floor(Math.random() * 4)));
  const headers = { "X-Forwarded-For": `198.51.100.${1 + Math.floor(Math.random() * 250)}` };
  const r = track(http.get(`${API}/${pick(["search", "search/suggestions"])}?q=${encodeURIComponent(q)}`, { headers }));
  check(r, { "search ok": (res) => res.status === 200 });
  sleep(0.5 + Math.random());
}

export function spike() {
  const mix = [
    () => http.get(`${API}/matches/live`),
    () => http.get(`${API}/matches/today`),
    () => http.get(`${API}/matches/${pick(world.match_ids)}`),
    () => http.get(`${API}/matches/${pick(world.match_ids)}/events`),
    () => http.get(`${API}/discovery/home`),
    () => http.get(`${API}/teams/${pick(world.team_ids)}`),
    () => http.get(`${API}/articles/${pick(world.slugs)}`),
    () => http.get(`${API}/comments?target_type=match&target_id=${pick(world.match_ids)}`),
  ];
  track(pick(mix)());
  sleep(0.5 + Math.random() * 2);
}

export function community() {
  const token = pick(world.tokens);
  const params = { headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" } };
  const roll = Math.random();
  let r;
  if (roll < 0.4) {
    r = http.get(`${API}/comments?target_type=match&target_id=${pick(world.match_ids)}`, params);
  } else if (roll < 0.65) {
    r = http.post(
      `${API}/comments`,
      JSON.stringify({ target_type: "match", target_id: pick(world.match_ids), body: `What a game! ${Math.random()}` }),
      params,
    );
  } else if (roll < 0.9) {
    r = http.put(
      `${API}/reactions/article/${pick(world.article_ids)}`,
      JSON.stringify({ kind: pick(["thumbs_up", "fire", "wow", "goal", "heart", "laugh", "clap"]) }),
      params,
    );
  } else {
    r = http.get(`${API}/polls/${pick(world.poll_ids)}`, params);
  }
  track(r);
  sleep(1 + Math.random() * 2);
}

export function ping() {
  track(http.get(`${BASE}/health/live`));
}

export function cached() {
  track(http.get(`${API}/matches/${world.match_ids[0]}/head-to-head`));
}

export function searchhot() {
  track(http.get(`${API}/search?q=arsenal`, { headers: { "X-Forwarded-For": `198.51.100.${1 + Math.floor(Math.random() * 250)}` } }));
}

let coldCounter = 0;
export function searchcold() {
  coldCounter += 1;
  const word = world.team_names[coldCounter % world.team_names.length];
  track(
    http.get(`${API}/search?q=${encodeURIComponent(word.slice(0, 3 + (coldCounter % 4)) + String.fromCharCode(97 + (coldCounter % 26)))}`, {
      headers: { "X-Forwarded-For": `198.51.100.${1 + Math.floor(Math.random() * 250)}` },
    }),
  );
}

export function websocket() {
  const path = Math.random() < 0.5 ? "/ws/matches" : `/ws/matches/${pick(world.match_ids)}`;
  const url = `${BASE.replace("http", "ws")}${path}`;
  const started = Date.now();
  const res = ws.connect(url, { headers: { Origin: "http://localhost:3000" } }, (socket) => {
    socket.on("open", () => {
      wsConnectMs.add(Date.now() - started);
      socket.setInterval(() => socket.send(JSON.stringify({ type: "PING" })), 5000);
    });
    socket.on("error", () => wsDropped.add(1));
    socket.setTimeout(() => socket.close(), 30000);
  });
  check(res, { "ws upgraded": (r) => r && r.status === 101 });
}
