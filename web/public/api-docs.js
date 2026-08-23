const baseUrl = window.location.origin;
document.querySelectorAll("[data-base-url]").forEach((element) => {
  element.textContent = baseUrl;
});

const toast = document.querySelector("#copy-toast");
let toastTimer;

const showCopied = () => {
  if (!toast) return;
  toast.classList.add("visible");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("visible"), 1600);
};

document.querySelectorAll(".copy-button").forEach((button) => {
  button.addEventListener("click", async () => {
    const targetId = button.dataset.copyTarget;
    const selector = button.dataset.copySelector;
    const target = targetId ? document.getElementById(targetId) : document.querySelector(selector);
    if (!target) return;
    const value = target.textContent.trim();
    try {
      await navigator.clipboard.writeText(value);
      showCopied();
    } catch {
      const selection = window.getSelection();
      const range = document.createRange();
      range.selectNodeContents(target);
      selection.removeAllRanges();
      selection.addRange(range);
    }
  });
});

const jsonApi = async (path) => {
  const response = await fetch(path, { headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json();
};

const makeText = (tag, value, className) => {
  const element = document.createElement(tag);
  element.textContent = value ?? "—";
  if (className) element.className = className;
  return element;
};

const normalizedStationName = (value) => {
  const normalized = String(value || "").replace(/\s+/g, "").toLocaleLowerCase("ko-KR");
  return normalized.length > 1 && normalized.endsWith("역") ? normalized.slice(0, -1) : normalized;
};

const mergeStations = (stations) => {
  const merged = new Map();
  stations.forEach((station) => {
    const key = normalizedStationName(station.name_ko);
    if (!merged.has(key)) merged.set(key, { ...station, lines: [], lineKeys: new Set() });
    const target = merged.get(key);
    (station.lines || []).forEach((line) => {
      const lineKey = `${line.line_code}:${line.station_code}`;
      if (target.lineKeys.has(lineKey)) return;
      target.lineKeys.add(lineKey);
      target.lines.push(line);
    });
  });
  return [...merged.values()].map(({ lineKeys, ...station }) => station);
};

const renderDocsStations = (stations, query) => {
  const target = document.querySelector("#docs-station-results");
  if (!target) return;
  target.replaceChildren();
  const merged = mergeStations(stations);
  if (!merged.length) {
    target.append(makeText("p", "일치하는 등록 역이 없습니다.", "docs-empty"));
    return;
  }

  let group;
  merged.forEach((station) => {
    const nextGroup = normalizedStationName(station.name_ko).startsWith(normalizedStationName(query))
      ? "첫 글자 일치"
      : "이름에 포함";
    if (nextGroup !== group) {
      target.append(makeText("p", nextGroup, "docs-station-group"));
      group = nextGroup;
    }
    const card = document.createElement("article");
    card.className = "docs-station-card";
    const name = document.createElement("div");
    name.append(makeText("b", station.name_ko), makeText("small", `${station.name_en || "영문명 없음"} · ${station.canonical_code}`));
    const lines = document.createElement("div");
    lines.className = "docs-station-lines";
    station.lines.forEach((line) => lines.append(makeText("span", `${line.line_name} · ${line.station_code}`)));
    const copy = makeText("button", "역명 복사");
    copy.type = "button";
    copy.addEventListener("click", async () => {
      await navigator.clipboard.writeText(station.name_ko);
      showCopied();
    });
    card.append(name, lines, copy);
    target.append(card);
  });
};

let docsStationTimer;
let docsStationSequence = 0;
const searchDocsStations = async () => {
  const input = document.querySelector("#docs-station-query");
  if (!input) return;
  const query = input.value.trim();
  const sequence = ++docsStationSequence;
  if (!query) {
    renderDocsStations([], query);
    const target = document.querySelector("#docs-station-results");
    target.replaceChildren(makeText("p", "한 글자부터 역 이름을 검색할 수 있습니다.", "docs-empty"));
    return;
  }
  try {
    const stations = await jsonApi(`/api/v1/stations?q=${encodeURIComponent(query)}&limit=50`);
    if (sequence === docsStationSequence) renderDocsStations(stations, query);
  } catch {
    if (sequence === docsStationSequence) {
      const target = document.querySelector("#docs-station-results");
      target.replaceChildren(makeText("p", "역 목록을 불러오지 못했습니다.", "docs-empty"));
    }
  }
};

const stationForm = document.querySelector("#docs-station-search");
const stationInput = document.querySelector("#docs-station-query");
stationForm?.addEventListener("submit", (event) => {
  event.preventDefault();
  clearTimeout(docsStationTimer);
  searchDocsStations();
});
stationInput?.addEventListener("input", () => {
  clearTimeout(docsStationTimer);
  docsStationTimer = setTimeout(searchDocsStations, 220);
});

const statusLabel = (status) => ({
  ENABLED: "활성",
  PENDING_KEY: "인증키 필요",
  PENDING_REVIEW: "검토 중",
  DISABLED_ROBOTS: "robots 차단",
  DISABLED_TERMS: "이용조건 차단",
  DISABLED_TECHNICAL: "기술적 차단",
}[status] || status);

const statusClass = (status) => {
  if (status === "ENABLED") return "enabled";
  if (status?.startsWith("DISABLED")) return "disabled";
  return "pending";
};

const formatDate = (value) => value
  ? new Intl.DateTimeFormat("ko-KR", { dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Seoul" }).format(new Date(value))
  : "—";

const renderDocsCoverage = (sources) => {
  const body = document.querySelector("#docs-coverage-body");
  if (!body) return;
  body.replaceChildren();
  sources.forEach((source) => {
    const row = document.createElement("tr");
    row.append(makeText("td", source.name), makeText("td", source.kind), makeText("td", source.coverage));
    const status = document.createElement("td");
    status.append(makeText("span", statusLabel(source.access_status), `docs-status-pill ${statusClass(source.access_status)}`));
    row.append(status, makeText("td", source.license_name || (source.terms_unspecified ? "조건 미명시 · 기본 활성" : "확인 중")));
    body.append(row);
  });
};

const renderOperationList = (selector, items, emptyMessage, renderer) => {
  const target = document.querySelector(selector);
  if (!target) return;
  target.replaceChildren();
  if (!items.length) target.append(makeText("p", emptyMessage, "docs-empty"));
  items.slice(0, 8).forEach((item) => {
    const row = document.createElement("div");
    row.className = "docs-operation-item";
    renderer(row, item);
    target.append(row);
  });
};

const renderDocsOperations = (jobs, alerts, usage) => {
  renderOperationList("#docs-jobs-list", jobs, "아직 실행된 동기화 작업이 없습니다.", (row, job) => {
    row.append(makeText("b", job.source_name), makeText("span", job.status), makeText("small", formatDate(job.created_at)));
  });
  renderOperationList("#docs-alerts-list", alerts, "현재 활성 운행 알림이 없습니다.", (row, alert) => {
    row.append(makeText("b", alert.title), makeText("span", alert.alert_type), makeText("small", alert.description || formatDate(alert.starts_at)));
  });
  renderOperationList("#docs-api-usage-list", usage, "호출량 정보가 없습니다.", (row, item) => {
    const blocked = item.blocked_until && new Date(item.blocked_until) > new Date();
    row.append(
      makeText("b", item.provider.replaceAll("_", " ")),
      makeText("span", blocked ? "일시 차단" : `${Number(item.remaining_count).toLocaleString("ko-KR")}건 남음`),
      makeText("small", `${Number(item.request_count).toLocaleString("ko-KR")} / ${Number(item.daily_budget).toLocaleString("ko-KR")}건 사용`),
    );
  });
};

const refreshDocsStatus = async () => {
  const state = document.querySelector("#docs-system-state");
  try {
    const [health, sources, jobs, alerts, usage] = await Promise.all([
      jsonApi("/health"),
      jsonApi("/api/v1/sources/coverage"),
      jsonApi("/api/v1/sync/jobs?limit=20"),
      jsonApi("/api/v1/service-alerts"),
      jsonApi("/api/v1/api-usage"),
    ]);
    state.className = "docs-system-state online";
    state.querySelector("b").textContent = health.database === "ok" ? "시스템 정상" : "확인 필요";
    renderDocsCoverage(sources);
    renderDocsOperations(jobs, alerts, usage);
    document.querySelector("#docs-updated-at").textContent = `마지막 화면 갱신 ${formatDate(new Date().toISOString())}`;
  } catch {
    state.className = "docs-system-state offline";
    state.querySelector("b").textContent = "API 연결 실패";
  }
};

document.querySelector("#docs-refresh-status")?.addEventListener("click", refreshDocsStatus);
if (document.querySelector("#data-status")) refreshDocsStatus();
