"use strict";

const $ = (selector) => document.querySelector(selector);
const escapeHTML = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const number = (value, digits = 0) => value == null ? "—" : new Intl.NumberFormat("en", {maximumFractionDigits: digits}).format(value);
const percent = (value) => value == null ? "—" : `${number(value * 100, 1)}%`;
const scoreAt = (kana, gamma) => Object.entries(kana.discounted_values).find(([g]) => Number(g) === Number(gamma))?.[1];
const state = {data:null, game:null, visible:0, timer:null, mode:"all", query:"", kana:"ず", metric:"mass", gamma:0.85};

function setQuery(key, value) {
  const url = new URL(location.href);
  url.searchParams.set(key, value);
  history.replaceState(null, "", url);
}

function modeLabel(id) {
  return state.data.models.find((m) => m.id === id)?.mode ?? "Unknown";
}

function renderModels() {
  const rows = state.data.models.filter((m) =>
    (state.mode === "all" || (state.mode === "thinking" ? m.thinking === true : m.thinking === false)) &&
    `${m.name} ${m.mode} ${m.model}`.toLowerCase().includes(state.query));
  $("#model-rows").innerHTML = rows.map((m) => `<tr>
    <td><div class="model-cell"><span class="model-symbol" aria-hidden="true">${m.thinking ? "↝" : "↗"}</span><div><strong>${escapeHTML(m.name)}</strong><small>${escapeHTML(m.mode)}</small></div></div></td>
    <td>${m.appearances}</td><td>${m.wins} <span class="muted">/</span> ${m.losses}</td>
    <td><div class="validity-cell"><span>${percent(m.validity)}<small class="cell-detail">${m.valid_moves} / ${m.submissions} accepted</small></span><span class="mini-track" aria-hidden="true"><i style="width:${m.validity * 100}%"></i></span></div></td>
    <td>${number(m.completion_tokens)}<small class="cell-detail">reasoning + final output</small></td>
  </tr>`).join("") || '<tr><td colspan="5">No configurations match. Try another filter.</td></tr>';
}

function failureName(ending) {
  return {ENDS_IN_N:"Ends in ん", INVALID_WORD:"Not in vocabulary", WRONG_START:"Wrong starting kana", REPEATED_WORD:"Repeated word", MALFORMED_OUTPUT:"Malformed answer"}[ending] ?? ending.replaceAll("_", " ").toLowerCase();
}

function selectGame(id, updateURL = true) {
  stopReplay();
  state.game = state.data.games.find((g) => g.id === id) ?? state.data.games[0];
  if (!state.game) return;
  state.visible = state.game.turns.length;
  if (updateURL) setQuery("game", state.game.id);
  renderGameOptions();
  renderGame();
}

function renderGameOptions() {
  $("#game-list").innerHTML = state.data.games.map((game, index) => `<button class="game-option ${game.id === state.game.id ? "active" : ""}" data-game="${escapeHTML(game.id)}" aria-pressed="${game.id === state.game.id}">
    <span class="mono">GAME ${String(index + 1).padStart(2,"0")} · OPENING ${escapeHTML(game.opening)}</span>
    <strong>${game.same_configuration ? "Thinking vs thinking" : "Thinking vs non-thinking"}</strong>
    <span class="game-option-foot"><span>${game.turns.length} turns</span><span class="mini-result">${escapeHTML(failureName(game.ending))}</span></span></button>`).join("");
}

function frequencyText(estimate) {
  if (!estimate) return "Frequency unmatched";
  return `${number(estimate.lower,2)}${estimate.upper !== estimate.lower ? `–${number(estimate.upper,2)}` : ""} / million`;
}

function renderGame() {
  const game = state.game;
  const index = state.data.games.indexOf(game) + 1;
  $("#match-kicker").textContent = `GAME ${String(index).padStart(2,"0")} / ${game.same_configuration ? "SAME-CONFIGURATION SELF-PLAY" : "CROSS-MODE PILOT"}`;
  $("#match-title").textContent = game.same_configuration ? "Thinking against itself." : "Two modes. One word chain.";
  $("#match-players").textContent = `P1 ${modeLabel(game.players[0])} · P2 ${modeLabel(game.players[1])}`;
  $("#match-opening").textContent = game.opening;
  $("#turn-range").max = game.turns.length;
  $("#turn-range").value = state.visible;
  $("#turn-label").textContent = `${state.visible} / ${game.turns.length}`;
  $("#replay-back").disabled = state.visible <= 1;
  $("#replay-next").disabled = state.visible >= game.turns.length;
  $("#move-list").innerHTML = game.turns.slice(0,state.visible).map((turn) => `<li class="move-row ${turn.outcome !== "VALID" ? "invalid" : ""}">
    <span class="turn-player">${String(turn.turn).padStart(2,"0")} <span class="player-dot p${turn.player_index + 1}" aria-label="Player ${turn.player_index + 1}">P${turn.player_index + 1}</span></span>
    <span class="move-word"><span lang="ja">${escapeHTML(turn.word || "(empty)")}</span><small>${escapeHTML(turn.romanization)}</small></span>
    <span class="move-meaning">${escapeHTML(turn.meaning)}<small>${escapeHTML(frequencyText(turn.frequency))}</small></span>
  </li>`).join("");
  const complete = state.visible === game.turns.length;
  const last = game.turns[game.turns.length - 1];
  $("#match-result").classList.toggle("in-progress", !complete);
  $("#match-result").innerHTML = complete ? `<span class="result-icon" aria-hidden="true">×</span><div><strong>P${last.player_index + 1}: ${escapeHTML(failureName(game.ending))}. ${game.winner_index == null ? "No winner." : `P${game.winner_index + 1} wins.`}</strong><p>${escapeHTML(game.ending_description)} Required starting kana: <span lang="ja">${escapeHTML(last.required_kana)}</span>.</p></div>` : `<span class="result-icon" aria-hidden="true">↝</span><div><strong>Through turn ${state.visible}</strong><p>Next required kana: <span lang="ja">${escapeHTML(game.turns[state.visible - 1]?.next_kana ?? game.opening)}</span>. Continue the replay to reveal the result.</p></div>`;
}

function stopReplay() {
  if (state.timer) clearInterval(state.timer);
  state.timer = null;
  $("#replay-play").textContent = "▶ Replay";
}

function updateVisible(value) {
  state.visible = Math.max(1,Math.min(Number(value),state.game.turns.length));
  renderGame();
}

function atlasRows() {
  return state.data.atlas.kana.filter((k) => k.safe_replies > 0 && !"ぁぃぅぇぉっゃゅょゎゕゖ".includes(k.kana));
}

function tileColors(t) {
  const rgb = [237,240,225].map((v,i) => Math.round(v + t * ([70,95,73][i] - v)));
  const linear = rgb.map((v) => {const x = v / 255; return x <= 0.04045 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4;});
  const luminance = 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
  return {background:`rgb(${rgb.join(',')})`,text:luminance > 0.179 ? '#000000' : '#ffffff'};
}

function renderAtlas() {
  const rows = atlasRows();
  const metricValue = (k) => state.metric === "mass" ? Math.log1p(k.frequency_mass_per_million) : state.metric === "count" ? Math.log1p(k.safe_replies) : scoreAt(k,state.gamma);
  const measured = rows.filter((k) => !k.unsupported_by_frequency_model);
  const values = (state.metric === "count" ? rows : measured).map(metricValue);
  const low = Math.min(...values), high = Math.max(...values);
  $("#legend-low").textContent = state.metric === "score" ? "Lower pressure" : "Fewer options";
  $("#legend-high").textContent = state.metric === "score" ? "Higher pressure" : "More options";
  $("#kana-grid").innerHTML = rows.map((k) => {
    const t = Math.max(0,Math.min(1,(metricValue(k) - low) / (high - low || 1)));
    const {background,text} = tileColors(t);
    return `<button class="kana-tile ${k.kana === state.kana ? "selected" : ""} ${k.unsupported_by_frequency_model ? "unsupported" : ""}" style="background:${background};color:${text}" data-kana="${escapeHTML(k.kana)}" aria-label="${escapeHTML(k.kana)}: ${k.safe_replies} dictionary replies${k.unsupported_by_frequency_model ? ', no frequency support' : ''}" aria-pressed="${k.kana === state.kana}" title="${escapeHTML(k.kana)} · ${number(k.safe_replies)} dictionary replies · ${number(k.frequency_mass_per_million,2)} mass per million" lang="ja">${escapeHTML(k.kana)}</button>`;
  }).join("");
  const k = rows.find((row) => row.kana === state.kana) ?? measured[0];
  if (!k) return;
  state.kana = k.kana;
  const transitions = Object.entries(k.ending_probabilities).sort((a,b) => b[1] - a[1]).slice(0,5);
  $("#kana-detail").innerHTML = `<div class="kana-detail-top"><span class="detail-kana" lang="ja">${escapeHTML(k.kana)}</span><span class="mono">STARTING WITH<br>${escapeHTML(k.kana)} / INITIAL GRAPH</span></div>
    <div class="detail-metric"><span>Safe dictionary replies</span><strong>${number(k.safe_replies)}</strong></div>
    <div class="detail-metric"><span>Frequency-covered replies</span><strong>${number(k.covered_safe_replies)}</strong></div>
    <div class="detail-metric"><span>Frequency mass / million</span><strong>${number(k.frequency_mass_per_million,2)}</strong></div>
    <div class="detail-metric"><span>Effective replies · entropy</span><strong>${number(k.effective_replies_entropy,1)}</strong></div>
    <div class="detail-metric"><span>Pressure · γ ${state.gamma}</span><strong>${k.unsupported_by_frequency_model ? "Not interpreted" : number(scoreAt(k,state.gamma),3)}</strong></div>
    ${k.unsupported_by_frequency_model ? '<p class="detail-alert">No frequency-covered replies. This is a data-coverage gap, not a proven dead end or winning move.</p>' : ""}
    ${k.kana === "ん" ? '<p class="detail-alert">Words ending in ん lose immediately. This kana cannot be reached by a safe move.</p>' : ""}
    <div class="transition-label">${transitions.length ? "LIKELY NEXT ENDINGS · SAFE POLICY" : "NO MEASURED NEXT-ENDING DISTRIBUTION"}</div>
    ${transitions.map(([kana,p]) => `<div class="transition-row"><span lang="ja">${escapeHTML(kana)}</span><span class="transition-bar" aria-hidden="true"><i style="width:${p * 100}%"></i></span><small>${percent(p)}</small></div>`).join("")}`;
}

function renderDepth() {
  const data = state.data.diagnostics.log_depth_decomposition;
  const rows = data?.[Object.keys(data).find((g) => Number(g) === 0.99)] ?? [];
  const four = rows.find((r) => r.depth === 4);
  $("#depth-insight").textContent = four ? `Even with a 0.99 discount, four terms of lookahead have a ${four.cumulative_vs_infinite_spearman.toFixed(4)} rank correlation with the infinite score. Distant turns mostly stop distinguishing the starting kana.` : "Depth diagnostics are not available in this snapshot.";
  $("#depth-bars").innerHTML = rows.filter((r) => [1,2,4,8].includes(r.depth)).map((r) => `<div class="depth-bar"><span>${r.depth} term${r.depth === 1 ? "" : "s"}</span><span class="depth-bar-track" aria-hidden="true"><i style="width:${Math.max(0,r.cumulative_vs_infinite_spearman) * 100}%"></i></span><span>${r.cumulative_vs_infinite_spearman.toFixed(4)}</span></div>`).join("");
}

const viewIDs = ['pilot','games','failures','atlas','method'];

function activateView(id, {updateHash = false, scroll = false} = {}) {
  if (!viewIDs.includes(id)) id = 'pilot';
  if (id !== 'games') stopReplay();
  document.querySelectorAll('[data-view-panel]').forEach((panel) => {panel.hidden = panel.id !== id;});
  document.querySelectorAll('[data-view]').forEach((button) => {
    const selected = button.dataset.view === id;
    button.classList.toggle('active',selected);
    button.setAttribute('aria-selected',String(selected));
    button.tabIndex = selected ? 0 : -1;
  });
  document.querySelectorAll('.header nav a').forEach((a) => a.classList.toggle('current',a.getAttribute('href') === `#${id}`));
  if (updateHash && location.hash !== `#${id}`) {
    const url = new URL(location.href);
    url.hash = id;
    history.pushState(null,'',url);
  }
  if (scroll) $('.view-nav-wrap').scrollIntoView({block:'start',behavior:'instant'});
}

function renderFailureAnalysis() {
  const games = state.data.games;
  $('#failure-breakdown').innerHTML = Object.entries(state.data.failures).map(([ending,count]) => `<article class="failure-category"><p class="eyebrow">${escapeHTML(failureName(ending).toUpperCase())}</p><div class="failure-count"><strong>${count}</strong><span>of ${games.length} completed games<br>${percent(count / games.length)} of observed endings</span></div><div class="failure-share" aria-hidden="true"><i style="width:${count / games.length * 100}%"></i></div><p>${ending === 'ENDS_IN_N' ? 'A dictionary word can still lose immediately when its final kana is ん.' : 'The submitted reading was not accepted by the frozen JMdict-derived noun vocabulary.'}</p></article>`).join('');
  $('#failure-examples').innerHTML = games.filter((g) => g.turns.length).map((g) => {
    const last = g.turns[g.turns.length - 1];
    return `<article class="failure-example"><div class="failure-example-top"><span class="mono">GAME ${String(games.indexOf(g) + 1).padStart(2,'0')} / P${last.player_index + 1} / TURN ${last.turn}</span><span class="small-pill">${escapeHTML(failureName(g.ending))}</span></div><h3 lang="ja">${escapeHTML(last.word)}</h3><p class="failure-roman mono">${escapeHTML(last.romanization)}</p><p>${escapeHTML(g.ending_description)}</p><p class="table-note">Required starting kana: <span lang="ja">${escapeHTML(last.required_kana)}</span> · ${escapeHTML(modeLabel(g.players[last.player_index]))}</p><button class="example-replay text-link" data-replay-game="${escapeHTML(g.id)}">Inspect this game ↗</button></article>`;
  }).join('');
  $('#infrastructure-note').textContent = `${state.data.summary.excluded_games} infrastructure failure excluded from competitive outcomes. ${state.data.excluded.map((e) => e.reason).join(' ')}`;
}

function renderChainPatterns() {
  const longest = Math.max(1,...state.data.games.map((g) => g.turns.length));
  $('#chain-length-bars').innerHTML = state.data.games.map((g,index) => {
    const valid = g.turns.filter((t) => t.outcome === 'VALID').length;
    const rejected = g.turns.length - valid;
    return `<button class="chain-length-row" data-replay-game="${escapeHTML(g.id)}" aria-label="Inspect game ${index + 1}: ${valid} accepted moves, ${rejected} rejected"><span class="mono">GAME ${String(index + 1).padStart(2,'0')}</span><span class="chain-length-track" aria-hidden="true"><i class="accepted" style="width:${valid / longest * 100}%"></i><i class="rejected" style="width:${rejected / longest * 100}%"></i></span><span class="chain-length-count">${valid}<span> + ${rejected}</span></span></button>`;
  }).join('');
}

function bindViews() {
  const tabs = [...document.querySelectorAll('[data-view]')];
  tabs.forEach((button,index) => {
    button.addEventListener('click',() => activateView(button.dataset.view,{updateHash:true}));
    button.addEventListener('keydown',(event) => {
      let next;
      if (event.key === 'ArrowRight') next = (index + 1) % tabs.length;
      if (event.key === 'ArrowLeft') next = (index + tabs.length - 1) % tabs.length;
      if (event.key === 'Home') next = 0;
      if (event.key === 'End') next = tabs.length - 1;
      if (next == null) return;
      event.preventDefault();
      activateView(tabs[next].dataset.view,{updateHash:true});
      tabs[next].focus({preventScroll:true});
      tabs[next].scrollIntoView({block:'nearest',inline:'nearest'});
    });
  });
  document.addEventListener('click',(event) => {
    const replay = event.target.closest('[data-replay-game]');
    if (replay) {selectGame(replay.dataset.replayGame); activateView('games',{updateHash:true,scroll:true}); return;}
    const link = event.target.closest('a[href^="#"]');
    if (link && viewIDs.includes(link.hash.slice(1))) {
      event.preventDefault();
      activateView(link.hash.slice(1),{updateHash:true,scroll:true});
    }
  });
  window.addEventListener('hashchange',() => activateView(location.hash.slice(1)));
  window.addEventListener('popstate',() => activateView(location.hash.slice(1)));
  activateView(location.hash.slice(1));
}

function bindControls() {
  document.querySelectorAll("[data-mode]").forEach((button) => button.addEventListener("click",() => {
    state.mode = button.dataset.mode;
    document.querySelectorAll("[data-mode]").forEach((b) => {const active = b === button; b.classList.toggle("active",active); b.setAttribute("aria-pressed",active);});
    renderModels();
  }));
  $("#model-search").addEventListener("input",(event) => {state.query = event.target.value.toLowerCase(); renderModels();});
  $("#game-list").addEventListener("click",(event) => {const button = event.target.closest("[data-game]"); if (button) selectGame(button.dataset.game);});
  $("#replay-back").addEventListener("click",() => {stopReplay(); updateVisible(state.visible - 1);});
  $("#replay-next").addEventListener("click",() => {stopReplay(); updateVisible(state.visible + 1);});
  $("#turn-range").addEventListener("input",(event) => {stopReplay(); updateVisible(event.target.value);});
  $("#replay-play").addEventListener("click",() => {
    if (state.timer) {stopReplay(); return;}
    if (state.visible >= state.game.turns.length) updateVisible(1);
    $("#replay-play").textContent = "Ⅱ Pause";
    state.timer = setInterval(() => {
      updateVisible(state.visible + 1);
      $("#move-list").scrollTop = $("#move-list").scrollHeight;
      if (state.visible >= state.game.turns.length) stopReplay();
    },950);
  });
  document.addEventListener("visibilitychange",() => {if (document.hidden) stopReplay();});
  $("#atlas-metric").addEventListener("change",(event) => {state.metric = event.target.value; renderAtlas();});
  $("#atlas-gamma").addEventListener("change",(event) => {state.gamma = Number(event.target.value); setQuery("gamma",state.gamma); renderAtlas();});
  $("#kana-grid").addEventListener("click",(event) => {const button = event.target.closest("[data-kana]"); if (button) {state.kana = button.dataset.kana; setQuery("kana",state.kana); renderAtlas(); $("#kana-grid").querySelector(`[data-kana="${CSS.escape(state.kana)}"]`)?.focus({preventScroll:true});}});
}

async function initialize() {
  try {
    const response = await fetch("data/results.json");
    if (!response.ok) throw new Error(`Data request failed (${response.status})`);
    state.data = await response.json();
    if (state.data.schema_version !== 2 || state.data.is_sample_data) throw new Error("Expected a public pilot snapshot, not placeholder results");
    const summary = state.data.summary;
    $("#stat-games").textContent = summary.completed_games;
    $("#stat-models").textContent = summary.configurations;
    $("#stat-moves").textContent = `${summary.valid_moves} / ${summary.submissions}`;
    $("#stat-validity").textContent = `${percent(summary.validity)} of submissions accepted`;
    $("#stat-openings").textContent = summary.openings.join(" · ");
    $("#stat-excluded").textContent = `${summary.excluded_games} infrastructure failure excluded`;
    $("#snapshot-date").textContent = `PILOT / ${new Date(summary.last_match_at).toLocaleDateString("en-GB",{day:"2-digit",month:"short",year:"numeric",timeZone:"UTC"}).toUpperCase()}`;
    $("#failure-summary").innerHTML = Object.entries(state.data.failures).map(([ending,count]) => `<div class="failure-item"><strong>${count}</strong><span>${escapeHTML(failureName(ending))}<small>${ending === "ENDS_IN_N" ? "fatal final kana" : "referee rejection"}</small></span></div>`).join("");
    const defaultGame = state.data.games.find((g) => g.turns.length === 6);
    const params = new URLSearchParams(location.search);
    if (atlasRows().some((k) => k.kana === params.get("kana"))) state.kana = params.get("kana");
    const gammas = state.data.atlas.gammas;
    if (params.has("gamma") && gammas.some((g) => g === Number(params.get("gamma")))) state.gamma = Number(params.get("gamma"));
    if (!gammas.includes(state.gamma)) state.gamma = gammas[0];
    $("#atlas-gamma").innerHTML = gammas.map((g) => `<option value="${g}" ${g === state.gamma ? "selected" : ""}>${g}</option>`).join("");
    renderModels(); selectGame(params.get("game") ?? defaultGame?.id,false); renderAtlas(); renderDepth();
    renderFailureAnalysis(); renderChainPatterns(); bindControls(); bindViews();
  } catch (error) {
    $("#load-error").hidden = false;
    $("#load-error").textContent = `The snapshot could not be loaded. Serve the web folder over HTTP (or GitHub Pages), rather than opening index.html directly. ${error.message}`;
    $("#model-rows").innerHTML = '<tr><td colspan="5">Pilot data unavailable. Please reload or inspect the public JSON.</td></tr>';
  }
}

initialize();
