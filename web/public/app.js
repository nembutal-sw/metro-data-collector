const $ = (selector) => document.querySelector(selector);

const api = async (path, options = {}) => {
  const response = await fetch(path, {
    ...options,
    headers: { Accept: "application/json", ...(options.headers || {}) },
  });
  if (!response.ok) {
    const error = new Error(`${response.status} ${response.statusText}`);
    error.status = response.status;
    throw error;
  }
  return response.json();
};

const text = (tag, value, className) => {
  const element = document.createElement(tag);
  element.textContent = value ?? "—";
  if (className) element.className = className;
  return element;
};

const statusClass = (status) => {
  if (status === "ENABLED") return "enabled";
  if (status?.startsWith("DISABLED")) return "disabled";
  return "pending";
};

const statusLabel = (status) => ({
  ENABLED: "활성",
  PENDING_KEY: "인증키 필요",
  PENDING_REVIEW: "검토 중",
  DISABLED_ROBOTS: "robots 차단",
  DISABLED_TERMS: "이용조건 차단",
  DISABLED_TECHNICAL: "기술적 차단",
}[status] || status);

const formatDate = (value) => value
  ? new Intl.DateTimeFormat("ko-KR", { dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Seoul" }).format(new Date(value))
  : "—";

const formatClock = (value) => value
  ? new Intl.DateTimeFormat("ko-KR", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Asia/Seoul" }).format(new Date(value))
  : "—";

const minutes = (seconds) => `${Math.ceil(Number(seconds || 0) / 60)}분`;

const showToast = (message) => {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.add("visible");
  window.setTimeout(() => toast.classList.remove("visible"), 2800);
};

const renderCoverage = (sources) => {
  const body = $("#coverage-body");
  body.replaceChildren();
  sources.forEach((source) => {
    const row = document.createElement("tr");
    row.append(text("td", source.name));
    row.append(text("td", source.kind));
    row.append(text("td", source.coverage));
    const statusCell = document.createElement("td");
    statusCell.append(text("span", statusLabel(source.access_status), `status-pill ${statusClass(source.access_status)}`));
    row.append(statusCell);
    row.append(text("td", source.license_name || (source.terms_unspecified ? "조건 미명시 · 기본 활성" : "확인 중")));
    body.append(row);
  });
  $("#metric-sources").textContent = sources.length.toLocaleString("ko-KR");
  const enabled = sources.filter((source) => source.access_status === "ENABLED").length;
  $("#metric-enabled").textContent = `${enabled}개 수집원 활성`;
};

const renderLines = (lines) => {
  const grid = $("#line-grid");
  grid.replaceChildren();
  lines.forEach((line) => {
    const card = document.createElement("article");
    card.className = "line-card";
    const badge = text("span", line.code.replace("SEOUL_", ""), "line-badge");
    badge.style.setProperty("--line-color", line.color || "#0052a4");
    const copy = document.createElement("div");
    copy.append(text("h3", line.name_ko));
    const operators = (line.operators || []).map((item) => `${item.name} · ${item.role}`).join(" / ");
    copy.append(text("p", operators || "운영기관 정보 없음"));
    card.append(badge, copy, text("span", line.transport_mode, "mode"));
    grid.append(card);
  });
  $("#metric-lines").textContent = lines.length.toLocaleString("ko-KR");
};

const renderStations = (stations) => {
  const target = $("#station-results");
  target.replaceChildren();
  if (!stations.length) {
    target.append(text("p", "검색 결과가 없습니다.", "empty-state"));
    return;
  }
  stations.forEach((station) => {
    const row = document.createElement("article");
    row.className = "station-row";
    const copy = document.createElement("div");
    copy.append(text("h3", station.name_ko));
    copy.append(text("small", `${station.canonical_code}${station.name_en ? ` · ${station.name_en}` : ""}`));
    const lines = document.createElement("div");
    lines.className = "station-lines";
    (station.lines || []).forEach((line) => lines.append(text("span", `${line.line_name} · ${line.station_code}`)));
    row.append(copy, lines);
    target.append(row);
  });
};

const renderTravelTime = (route) => {
  const target = $("#travel-time-result");
  target.replaceChildren();
  const summary = document.createElement("article");
  summary.className = "travel-summary";
  summary.append(
    text("strong", `${route.duration_minutes.toLocaleString("ko-KR")}분`),
    text("span", `${route.origin_station} → ${route.destination_station}`),
    text("small", `${formatClock(route.departure_at)} 출발 · ${formatClock(route.arrival_at)} 도착 · ${route.transfer_count ? `환승 ${route.transfer_count}회` : "환승 없음"}`),
  );
  const breakdown = document.createElement("div");
  breakdown.className = "travel-breakdown";
  [
    ["첫 열차 대기", minutes(route.initial_wait_seconds)],
    ["열차 이동", minutes(route.in_vehicle_seconds)],
    ["환승 보행", minutes(route.transfer_walk_seconds)],
    ["환승 열차 대기", minutes(route.transfer_wait_seconds)],
  ].forEach(([label, value]) => {
    const metric = document.createElement("span");
    metric.append(text("small", label), text("b", value));
    breakdown.append(metric);
  });
  const legs = document.createElement("div");
  legs.className = "travel-legs";
  route.legs.forEach((leg) => {
    const item = document.createElement("div");
    if (leg.kind === "RIDE") {
      item.append(
        text("b", leg.line_name),
        text("span", `${formatClock(leg.departure_at)} ${leg.from_station} → ${formatClock(leg.arrival_at)} ${leg.to_station}`),
        text("small", `${leg.station_count}개 구간 · ${minutes(leg.duration_seconds)} · ${leg.destination || leg.direction} 방면`),
      );
    } else {
      item.className = "transfer-leg";
      item.append(
        text("b", `${leg.station} 환승`),
        text("span", `${leg.from_line_name} → ${leg.to_line_name}`),
        text("small", `보행 ${minutes(leg.walking_seconds)} + 대기 ${minutes(leg.waiting_seconds)} · 다음 열차 ${formatClock(leg.departure_at)}${leg.estimated ? " · 보행시간 추정" : ""}`),
      );
    }
    legs.append(item);
  });
  const path = text("p", route.stations.join(" · "), "travel-path");
  const estimatedTransfers = route.legs.some((leg) => leg.kind === "TRANSFER" && leg.estimated);
  const basis = text("small", `${route.basis}${estimatedTransfers ? " · 공식 환승값 미확보 구간은 역별 기본값 사용" : ""}`, "travel-basis");
  target.append(summary, breakdown, legs, path, basis);
};

const renderOperations = (jobs, alerts) => {
  const jobsTarget = $("#jobs-list");
  jobsTarget.replaceChildren();
  if (!jobs.length) jobsTarget.append(text("p", "아직 실행된 동기화 작업이 없습니다.", "empty-state"));
  jobs.slice(0, 8).forEach((job) => {
    const item = document.createElement("div");
    item.className = "operation-item";
    item.append(text("b", job.source_name), text("span", job.status), text("small", formatDate(job.created_at)));
    jobsTarget.append(item);
  });

  const alertsTarget = $("#alerts-list");
  alertsTarget.replaceChildren();
  if (!alerts.length) alertsTarget.append(text("p", "현재 활성 운행 알림이 없습니다.", "empty-state"));
  alerts.slice(0, 8).forEach((alert) => {
    const item = document.createElement("div");
    item.className = "operation-item";
    item.append(text("b", alert.title), text("span", alert.alert_type), text("small", alert.description || formatDate(alert.starts_at)));
    alertsTarget.append(item);
  });

  if (jobs.length) {
    $("#metric-sync").textContent = jobs[0].status;
    $("#metric-sync-detail").textContent = formatDate(jobs[0].created_at);
  }
};

const renderApiUsage = (usage) => {
  const target = $("#api-usage-list");
  target.replaceChildren();
  usage.forEach((item) => {
    const blocked = item.blocked_until && new Date(item.blocked_until) > new Date();
    const row = document.createElement("div");
    row.className = "operation-item";
    row.append(
      text("b", item.provider.replaceAll("_", " ")),
      text("span", blocked ? "일시 차단" : `${Number(item.remaining_count).toLocaleString("ko-KR")}건 남음`),
      text("small", `${Number(item.request_count).toLocaleString("ko-KR")} / ${Number(item.daily_budget).toLocaleString("ko-KR")}건 사용${blocked ? ` · ${formatDate(item.blocked_until)}까지` : ""}`),
    );
    target.append(row);
  });
};

const refresh = async () => {
  try {
    const [health, stats, sources, lines, jobs, alerts, apiUsage] = await Promise.all([
      api("/health"),
      api("/api/v1/stats"),
      api("/api/v1/sources/coverage"),
      api("/api/v1/lines"),
      api("/api/v1/sync/jobs?limit=20"),
      api("/api/v1/service-alerts"),
      api("/api/v1/api-usage"),
    ]);
    const state = $("#system-state");
    state.className = "system-state online";
    state.lastChild.textContent = health.database === "ok" ? "시스템 정상" : "확인 필요";
    renderCoverage(sources);
    renderLines(lines);
    renderOperations(jobs, alerts);
    renderApiUsage(apiUsage);
    $("#metric-lines").textContent = Number(stats.line_count).toLocaleString("ko-KR");
    $("#metric-stations").textContent = Number(stats.station_count).toLocaleString("ko-KR");
    $("#metric-sources").textContent = Number(stats.source_count).toLocaleString("ko-KR");
    $("#metric-enabled").textContent = `${stats.enabled_source_count}개 수집원 활성`;
    if (stats.last_sync_at) {
      $("#metric-sync").textContent = "완료";
      $("#metric-sync-detail").textContent = formatDate(stats.last_sync_at);
    }
    $("#updated-at").textContent = `마지막 화면 갱신 ${formatDate(new Date().toISOString())}`;
  } catch (error) {
    const state = $("#system-state");
    state.className = "system-state offline";
    state.lastChild.textContent = "API 연결 실패";
    showToast("데이터 API에 연결하지 못했습니다.");
  }
};

let stationSearchSequence = 0;
let stationSearchTimer;

const searchStations = async (query) => {
  const sequence = ++stationSearchSequence;
  if (!query) {
    renderStations([]);
    $("#station-results").replaceChildren(text("p", "한 글자부터 역 이름을 검색할 수 있습니다.", "empty-state"));
    return;
  }
  try {
    const stations = await api(`/api/v1/stations?q=${encodeURIComponent(query)}&limit=50`);
    if (sequence === stationSearchSequence) renderStations(stations);
  } catch (error) {
    if (sequence === stationSearchSequence) showToast("역 검색 중 오류가 발생했습니다.");
  }
};

$("#station-search").addEventListener("submit", async (event) => {
  event.preventDefault();
  window.clearTimeout(stationSearchTimer);
  await searchStations($("#station-query").value.trim());
});

$("#station-query").addEventListener("input", (event) => {
  window.clearTimeout(stationSearchTimer);
  const query = event.target.value.trim();
  stationSearchTimer = window.setTimeout(() => searchStations(query), 250);
});

const normalizedStationName = (value) => {
  const normalized = String(value || "").replace(/\s+/g, "").toLocaleLowerCase("ko-KR");
  return normalized.length > 1 && normalized.endsWith("역") ? normalized.slice(0, -1) : normalized;
};

const mergeStationSuggestions = (stations) => {
  const merged = new Map();
  stations.forEach((station) => {
    const key = normalizedStationName(station.name_ko);
    if (!merged.has(key)) {
      merged.set(key, { ...station, lines: [], lineKeys: new Set() });
    }
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

const setupStationCombobox = (inputSelector, listSelector) => {
  const input = $(inputSelector);
  const list = $(listSelector);
  let timer;
  let requestSequence = 0;
  let suggestions = [];
  let activeIndex = -1;

  const close = () => {
    list.hidden = true;
    input.setAttribute("aria-expanded", "false");
    input.removeAttribute("aria-activedescendant");
    activeIndex = -1;
  };

  const setActive = (index) => {
    const options = [...list.querySelectorAll(".station-suggestion")];
    options.forEach((option) => option.classList.remove("active"));
    if (!options.length) return;
    activeIndex = (index + options.length) % options.length;
    const option = options[activeIndex];
    option.classList.add("active");
    input.setAttribute("aria-activedescendant", option.id);
    option.scrollIntoView({ block: "nearest" });
  };

  const choose = (index) => {
    const station = suggestions[index];
    if (!station) return;
    input.value = station.name_ko;
    input.dataset.selectedStation = station.name_ko;
    input.classList.add("station-selected");
    close();
  };

  const render = (query) => {
    list.replaceChildren();
    if (!suggestions.length) {
      list.append(text("p", "일치하는 역이 없습니다.", "suggestion-empty"));
    } else {
      let currentGroup;
      suggestions.forEach((station, index) => {
        const group = normalizedStationName(station.name_ko).startsWith(normalizedStationName(query))
          ? "첫 글자 일치"
          : "이름에 포함";
        if (group !== currentGroup) {
          list.append(text("p", group, "suggestion-group-label"));
          currentGroup = group;
        }
        const option = document.createElement("button");
        option.type = "button";
        option.id = `${list.id}-option-${index}`;
        option.className = "station-suggestion";
        option.setAttribute("role", "option");
        option.dataset.index = String(index);
        const stationCopy = document.createElement("span");
        stationCopy.className = "suggestion-station-name";
        stationCopy.append(text("strong", station.name_ko), text("small", station.name_en || "역 선택"));
        const lineList = document.createElement("span");
        lineList.className = "suggestion-lines";
        station.lines.slice(0, 4).forEach((line) => lineList.append(text("i", line.line_name)));
        option.append(stationCopy, lineList, text("b", "선택", "suggestion-select-label"));
        list.append(option);
      });
    }
    list.hidden = false;
    input.setAttribute("aria-expanded", "true");
  };

  const search = async () => {
    const query = input.value.trim();
    const sequence = ++requestSequence;
    if (!query) {
      suggestions = [];
      close();
      return;
    }
    try {
      const stations = await api(`/api/v1/stations?q=${encodeURIComponent(query)}&limit=40`);
      if (sequence !== requestSequence) return;
      suggestions = mergeStationSuggestions(stations);
      activeIndex = -1;
      render(query);
    } catch (error) {
      if (sequence !== requestSequence) return;
      close();
      showToast("역 목록을 불러오지 못했습니다.");
    }
  };

  input.addEventListener("input", () => {
    input.classList.remove("station-selected");
    delete input.dataset.selectedStation;
    window.clearTimeout(timer);
    timer = window.setTimeout(search, 180);
  });
  input.addEventListener("focus", () => {
    if (input.value.trim()) search();
  });
  input.addEventListener("blur", () => window.setTimeout(close, 150));
  input.addEventListener("keydown", (event) => {
    if (event.key === "ArrowDown" && !list.hidden) {
      event.preventDefault();
      setActive(activeIndex + 1);
    } else if (event.key === "ArrowUp" && !list.hidden) {
      event.preventDefault();
      setActive(activeIndex - 1);
    } else if (event.key === "Enter" && !list.hidden && activeIndex >= 0) {
      event.preventDefault();
      choose(activeIndex);
    } else if (event.key === "Escape") {
      close();
    }
  });
  list.addEventListener("pointerdown", (event) => event.preventDefault());
  list.addEventListener("click", (event) => {
    const option = event.target.closest(".station-suggestion");
    if (option) choose(Number(option.dataset.index));
  });
  return { close };
};

const originStationPicker = setupStationCombobox("#origin-station", "#origin-suggestions");
const destinationStationPicker = setupStationCombobox("#destination-station", "#destination-suggestions");

$("#travel-time-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  originStationPicker.close();
  destinationStationPicker.close();
  const origin = $("#origin-station").value.trim();
  const destination = $("#destination-station").value.trim();
  const departureAt = $("#departure-at").value;
  const walkingMode = $("#walking-mode").value;
  const transferBuffer = $("#transfer-buffer").value;
  const apiKey = $("#route-api-key").value.trim();
  if (!origin || !destination || !apiKey) return;
  window.sessionStorage.setItem("metro-route-api-key", apiKey);
  const button = event.currentTarget.querySelector("button");
  button.disabled = true;
  button.textContent = "계산 중…";
  $("#travel-time-result").replaceChildren(text("p", "활성 시간표에서 경로를 계산하고 있습니다.", "empty-state"));
  try {
    const query = new URLSearchParams({
      origin,
      destination,
      departure_at: departureAt,
      walking_mode: walkingMode,
      transfer_buffer_seconds: transferBuffer,
    });
    const route = await api(`/api/v1/travel-time?${query.toString()}`, {
      headers: { "X-API-Key": apiKey },
    });
    renderTravelTime(route);
  } catch (error) {
    const message = error.status === 404
      ? "두 역을 잇는 활성 시간표 경로를 찾지 못했습니다. 역 이름을 확인해 주세요."
      : "소요시간 계산 중 오류가 발생했습니다.";
    $("#travel-time-result").replaceChildren(text("p", message, "empty-state"));
    showToast(message);
  } finally {
    button.disabled = false;
    button.textContent = "시간표 경로 찾기";
  }
});

$("#departure-at").value = new Intl.DateTimeFormat("sv-SE", {
  year: "numeric", month: "2-digit", day: "2-digit",
  hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Asia/Seoul",
}).format(new Date()).replace(" ", "T");
$("#route-api-key").value = window.sessionStorage.getItem("metro-route-api-key") || "";

$("#refresh-button").addEventListener("click", async () => {
  await refresh();
  showToast("운영 정보를 새로 불러왔습니다.");
});

refresh();
