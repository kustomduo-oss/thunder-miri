/* 썬더미리 — 위치 설정, 레이더, 웹푸시 연결 */
const CONFIG = {
  SUPABASE_URL: "https://pdlohzenslwbiyoxwjom.supabase.co",
  SUPABASE_ANON_KEY: "sb_publishable_5GA_EH7mqRbkWe-UEWEL2Q_xf5cn3kF",
  VAPID_PUBLIC_KEY: "BDpsQ-TxN1fOcZL5JX863gvyPT5QD78S8k94lIEDFZnhUXdEy_ReIxVGmSLeFRWtjxO4EvECDEdsWfTGADfocHQ"
};

const state = { lat:null, lon:null, nx:null, ny:null, dong:null };
const $ = id => document.getElementById(id);
const SOUND_CHECK_KEY = "dongtaniSoundCheckPassed";
const ALERT_PROFILE_KEY = "thunder_alert_profile";
const SAVED_LOCATION_KEY = "thunder_saved_location";

function readAlertProfile(){
  try{
    const profile=JSON.parse(localStorage.getItem(ALERT_PROFILE_KEY) || "{}");
    return profile && typeof profile === "object" ? profile : {};
  }catch(error){
    return {};
  }
}

function saveLocationProfile(extra={}){
  if(!Number.isFinite(state.lat) || !Number.isFinite(state.lon) || state.nx==null || state.ny==null) return;
  try{
    const profile={
      ...readAlertProfile(),
      ...extra,
      dong:state.dong,
      lat:state.lat,
      lon:state.lon,
      nx:state.nx,
      ny:state.ny
    };
    const savedLocation={dong:state.dong,lat:state.lat,lon:state.lon,nx:state.nx,ny:state.ny};
    localStorage.setItem("thunder_grid", `${state.nx}_${state.ny}`);
    localStorage.setItem(SAVED_LOCATION_KEY, JSON.stringify(savedLocation));
    localStorage.setItem(ALERT_PROFILE_KEY, JSON.stringify(profile));
  }catch(error){ /* 저장이 막혀도 현재 이용은 계속합니다. */ }
}

function readSavedLocation(){
  const candidates=[];
  try{ candidates.push(JSON.parse(localStorage.getItem(SAVED_LOCATION_KEY) || "{}")); }catch(error){}
  candidates.push(readAlertProfile());
  return candidates.find(item => item && item.lat != null && item.lon != null && item.lat !== "" && item.lon !== "" &&
    Number.isFinite(Number(item.lat)) && Number.isFinite(Number(item.lon))) || null;
}

function toast(message){
  const element = $("toast");
  element.textContent = message;
  element.classList.add("show");
  window.setTimeout(() => element.classList.remove("show"), 3000);
}

/* 소리 적응 확인은 '선택 안내'일 뿐, 알림 가입을 막지 않는다.
   이 서비스의 목적은 소리 훈련이 아니라 '무방비 노출을 막는 알림'이기 때문. */
function setSoundCheckPassed(passed){
  try{
    if(passed) localStorage.setItem(SOUND_CHECK_KEY, "v1");
    else localStorage.removeItem(SOUND_CHECK_KEY);
  }catch(error){ /* 저장이 막혀도 현재 이용은 계속합니다. */ }
}

function stopSoundMethod(){
  setSoundCheckPassed(false);
  if($("soundStopMessage")) $("soundStopMessage").hidden = false;
  if($("soundStopMessage")) $("soundStopMessage").scrollIntoView({behavior:"smooth", block:"center"});
}

if($("soundPass")) $("soundPass").addEventListener("click", () => {
  setSoundCheckPassed(true);
  if($("soundStopMessage")) $("soundStopMessage").hidden = true;
  $("soundPass").textContent = "확인 완료";
});
if($("soundStop")) $("soundStop").addEventListener("click", stopSoundMethod);
if($("checkAgain")) $("checkAgain").addEventListener("click", () => {
  $("soundStopMessage").hidden = true;
  document.getElementById("sound-check").scrollIntoView({behavior:"smooth", block:"start"});
});

const userAgent = navigator.userAgent || "";
const isIOS = /iPad|iPhone|iPod/.test(userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
const isStandalone = window.matchMedia("(display-mode: standalone)").matches || window.navigator.standalone === true;

function toGrid(lat, lon){
  const RE=6371.00877, GRID=5.0, SLAT1=30.0, SLAT2=60.0, OLON=126.0, OLAT=38.0, XO=43, YO=136;
  const DEGRAD=Math.PI/180.0;
  const re=RE/GRID, slat1=SLAT1*DEGRAD, slat2=SLAT2*DEGRAD, olon=OLON*DEGRAD, olat=OLAT*DEGRAD;
  let sn=Math.tan(Math.PI*0.25+slat2*0.5)/Math.tan(Math.PI*0.25+slat1*0.5);
  sn=Math.log(Math.cos(slat1)/Math.cos(slat2))/Math.log(sn);
  let sf=Math.tan(Math.PI*0.25+slat1*0.5);
  sf=Math.pow(sf,sn)*Math.cos(slat1)/sn;
  let ro=Math.tan(Math.PI*0.25+olat*0.5);
  ro=re*sf/Math.pow(ro,sn);
  let ra=Math.tan(Math.PI*0.25+lat*DEGRAD*0.5);
  ra=re*sf/Math.pow(ra,sn);
  let theta=lon*DEGRAD-olon;
  if(theta>Math.PI) theta-=2.0*Math.PI;
  if(theta<-Math.PI) theta+=2.0*Math.PI;
  theta*=sn;
  return { nx:Math.floor(ra*Math.sin(theta)+XO+0.5), ny:Math.floor(ro-ra*Math.cos(theta)+YO+0.5) };
}

/* ── 첫 화면 지도 ────────────────────────────────────
   위치를 입력하면 우리 집에 핑을 찍고 알림 기준 원(50km/30km)을 그린다.
   "내 위치가 잡혔다"를 눈으로 바로 확인시켜 주는 것이 목적.       */
let heroMap = null, heroLayer = null;

/* 배경지도: 브이월드(국토교통부). 실패 시 OSM으로 자동 전환.
   레이더 페이지와 같은 설정을 쓰고, 선택도 함께 기억한다(thunder_basemap). */
const VWORLD_KEY = "12A21CCD-E7FC-3E4E-B6A5-F8DE7A32A24D";
let baseLayer = null, fellBack = false;
const osmLayer = () => L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
  { maxZoom:18, attribution:"© OpenStreetMap 기여자" });

function updateRangeLabelScale(){
  if(!heroMap) return;
  const scale = Math.min(1.45, Math.max(.9, 1 + (heroMap.getZoom() - 7) * .15));
  heroMap.getContainer().style.setProperty("--range-label-scale", scale.toFixed(2));
}

function setBasemap(type){
  try{ localStorage.setItem("thunder_basemap", type); }catch(e){}
  document.querySelectorAll(".hero-base button").forEach(b =>
    b.setAttribute("aria-pressed", String(b.dataset.base === type)));
  if(!heroMap || fellBack) return;
  if(baseLayer) heroMap.removeLayer(baseLayer);
  baseLayer = L.tileLayer(
    `https://api.vworld.kr/req/wmts/1.0.0/${VWORLD_KEY}/${type}/{z}/{y}/{x}.png`,
    { maxZoom:18, attribution:'© <a href="https://www.vworld.kr/" target="_blank" rel="noopener">VWorld</a>' }
  );
  baseLayer.on("tileerror", () => {
    if(fellBack) return;
    fellBack = true;
    if(baseLayer) heroMap.removeLayer(baseLayer);
    osmLayer().addTo(heroMap);
  });
  baseLayer.addTo(heroMap);
  baseLayer.setZIndex(1);
}

function initHeroMap(){
  const el = document.getElementById("heroMap");
  if(!el || typeof L === "undefined" || heroMap) return;
  heroMap = L.map(el, { zoomControl:true, attributionControl:true })
             .setView([36.5, 127.8], 6);
  heroMap.attributionControl.setPrefix(false);
  heroMap.on("zoomend", updateRangeLabelScale);
  heroMap.on("moveend", updateLightningViewportControl);
  updateRangeLabelScale();
  let saved = "Base";
  try{ saved = localStorage.getItem("thunder_basemap") || "Base"; }catch(e){}
  setBasemap(saved);
  heroLayer = L.layerGroup().addTo(heroMap);
  document.querySelectorAll(".hero-base button").forEach(b =>
    b.addEventListener("click", () => setBasemap(b.dataset.base)));
  document.getElementById("heroLightningViewport")?.addEventListener("click", toggleLightningViewport);
}

function pinHome(lat, lon, label){
  if(!heroMap) initHeroMap();
  if(!heroMap) return;
  heroLayer.clearLayers();

  // 50km 접근은 청록색, 30km 임박은 주황색으로 구분한다.
  const circle50 = L.circle([lat,lon], { radius:50000, color:"#007f95", weight:3, opacity:1,
                        fillColor:"#00a4ba", fillOpacity:.07 }).addTo(heroLayer);
  const circle30 = L.circle([lat,lon], { radius:30000, color:"#df5b1d", weight:3.5, opacity:1,
                        fillColor:"#f27a32", fillOpacity:.15 }).addTo(heroLayer);
  const bounds50 = circle50.getBounds();
  const bounds30 = circle30.getBounds();
  const labelVerticalScale = .5;
  const labelHorizontalScale = Math.sqrt(3) / 2;
  const label50 = [
    lat + (bounds50.getNorth() - lat) * labelVerticalScale,
    lon + (bounds50.getEast() - lon) * labelHorizontalScale
  ];
  const label30 = [
    lat + (bounds30.getSouth() - lat) * labelVerticalScale,
    lon + (bounds30.getEast() - lon) * labelHorizontalScale
  ];
  L.marker(label50, { icon:L.divIcon({
    className:"", iconSize:[40,20], iconAnchor:[0,20],
    html:'<div class="range-distance-label range-50">50km</div>'
  }), interactive:false }).addTo(heroLayer);
  L.marker(label30, { icon:L.divIcon({
    className:"", iconSize:[40,20], iconAnchor:[0,0],
    html:'<div class="range-distance-label range-30">30km</div>'
  }), interactive:false }).addTo(heroLayer);
  L.marker([lat,lon], { icon: L.divIcon({
      className:"", iconSize:[34,38], iconAnchor:[17,36],
      html:'<div class="hero-location-pin" title="등록 위치"><span></span></div>'
  }), keyboard:false }).addTo(heroLayer);

  heroMap.setView([lat,lon], heroRadarMode === "lightning" ? 7 : 8);
  const status = document.getElementById("mapStatus");
  if(status) status.textContent = (label || "우리 동네") + " 낙뢰 감시 중";

  // 그 동네 전용 레이더가 있으면 그것으로, 없으면 전국판을 계속 쓴다
  heroLightningViewFitted=false;
  loadRadar(`${state.nx}_${state.ny}`, true);
}

/* ── 히어로 레이더: 현재 관측 + 미래 강수예측 타임바 ────────────────── */
const RADAR_BASE = `${CONFIG.SUPABASE_URL}/storage/v1/object/public/radar`;
let radarOverlay = null, strikeLayer = null;
let tl = [], tlIdx = 0, tlTimer = null;
let heroRadarMode = "lightning", heroRadarObs = null, heroForecastData = null, heroRadarKey = "national";
let heroLightningStrikes = [], heroLightningVisible = [], heroLightningIdx = 5, heroLightningTimer = null, heroLightningViewFitted = false, heroLightningShowingAll = false;

function fmtClock(d){ return `${String(d.getHours()).padStart(2,"0")}:${String(d.getMinutes()).padStart(2,"0")}`; }
function parseStrikeTime(value){
  const s = String(value || "").replace(/\D/g, "");
  if(s.length < 12) return null;
  return new Date(+s.slice(0,4), +s.slice(4,6)-1, +s.slice(6,8), +s.slice(8,10), +s.slice(10,12), +(s.slice(12,14) || 0));
}
function strikeAge(value){
  const at = parseStrikeTime(value);
  return at && !Number.isNaN(at.getTime()) ? Math.max(0, Math.floor((Date.now() - at.getTime()) / 60000)) : 0;
}
function strikeAgeClass(age){
  if(age < 10) return "age-0";
  if(age < 20) return "age-1";
  if(age < 30) return "age-2";
  if(age < 40) return "age-3";
  if(age < 50) return "age-4";
  return "age-5";
}
function lightningWindow(step){
  return [{ min:50, max:60, label:"50~60분 전" },
          { min:40, max:50, label:"40~50분 전" },
          { min:30, max:40, label:"30~40분 전" },
          { min:20, max:30, label:"20~30분 전" },
          { min:10, max:20, label:"10~20분 전" },
          { min:0, max:10, label:"최근 1시간" }][step];
}
function lightningClockLabel(step){
  const time = new Date();
  time.setSeconds(0,0);
  time.setMinutes(Math.floor(time.getMinutes()/10)*10 - (5-step)*10);
  return fmtClock(time);
}
function updateLegendTicks(){
  // 색 구간은 "지금부터 N분 전" 기준이라 눈금도 현재 시각에서 거꾸로 센다.
  const now = Date.now();
  document.querySelectorAll("#heroLightningLegend .lg-ticks span").forEach(el => {
    const ago = +el.getAttribute("data-ago") || 0;
    el.textContent = fmtClock(new Date(now - ago * 60000));
  });
}
function updateLightningClock(step){
  const label = lightningClockLabel(step);
  const time = document.getElementById("heroLightningTime");
  const range = document.getElementById("heroLightningRange");
  if(time) time.textContent = label;
  if(range) range.setAttribute("aria-valuetext", `${label}까지의 낙뢰 관측`);
}
function focusLightningMap(){
  if(!heroMap) return;
  heroLightningShowingAll=false;
  const center = state.lat!=null ? [state.lat,state.lon] : [36.5,127.8];
  heroMap.setView(center,7,{animate:false});
  heroLightningViewFitted=true;
}
function updateLightningViewportControl(){
  const button = document.getElementById("heroLightningViewport");
  if(!button || !heroMap || heroRadarMode !== "lightning"){
    if(button) button.hidden=true;
    return;
  }
  if(heroLightningShowingAll){
    button.textContent="⌂ 우리 동네 화면으로";
    button.setAttribute("aria-label","우리 동네 지도 화면으로 돌아가기");
    button.hidden=false;
    return;
  }
  const bounds=heroMap.getBounds();
  const outside=heroLightningVisible.filter(s => !bounds.contains([s.lat,s.lon])).length;
  button.textContent=`⚡ 지도 밖 최근 낙뢰 ${outside}건 · 위치 보기`;
  button.setAttribute("aria-label",`현재 지도 밖의 최근 낙뢰 ${outside}건 위치 보기`);
  button.hidden=outside===0;
}
function toggleLightningViewport(){
  if(!heroMap) return;
  if(heroLightningShowingAll){
    focusLightningMap();
    return;
  }
  const points=heroLightningVisible
    .map(s => [Number(s.lat),Number(s.lon)])
    .filter(([lat,lon]) => Number.isFinite(lat) && Number.isFinite(lon));
  if(!points.length) return;
  heroLightningShowingAll=true;
  if(points.length===1) heroMap.setView(points[0],7,{animate:false});
  else heroMap.fitBounds(L.latLngBounds(points),{padding:[36,36],maxZoom:7,animate:false});
  updateLightningViewportControl();
}
function renderHeroStrikes(step){
  heroLightningIdx = Math.max(0, Math.min(5, step));
  const range = document.getElementById("heroLightningRange");
  if(range) range.value = heroLightningIdx;
  if(!strikeLayer) strikeLayer = L.layerGroup();
  strikeLayer.clearLayers();
  const current = lightningWindow(heroLightningIdx);
  const visible = heroLightningStrikes.filter(s => {
    const age = strikeAge(s.tm);
    return age >= current.min && age < 60;
  }).sort((a,b) => strikeAge(b.tm) - strikeAge(a.tm));
  heroLightningVisible=visible;
  visible.forEach(s => {
    const age = strikeAge(s.tm);
    const at = parseStrikeTime(s.tm);
    const boltW = age < 10 ? 24 : 19;
    const boltH = age < 10 ? 27 : 22;
    L.marker([s.lat,s.lon], {
      zIndexOffset:100000 - Math.min(age,60) * 1000,
      icon:L.divIcon({
      className:"", iconSize:[boltW,boltH], iconAnchor:[boltW/2,boltH/2],
      html:`<div class="hero-bolt ${strikeAgeClass(age)} preview-compact" style="--bolt-w:${boltW}px;--bolt-h:${boltH}px" aria-hidden="true"></div>` }),
      title:`${at ? fmtClock(at) + " · " : ""}${age < 1 ? "방금" : age + "분 전"} 관측된 낙뢰`
    }).addTo(strikeLayer);
  });
  const inWindow = heroLightningStrikes.filter(s => {
    const age = strikeAge(s.tm);
    return age >= current.min && age < current.max;
  }).length;
  updateLightningClock(heroLightningIdx);
  updateLegendTicks();
  const status = document.getElementById("heroLightningStatus");
  if(status) status.textContent = heroLightningIdx === 5
    ? `최근 1시간 이내 낙뢰 관측 ${visible.length}건`
    : `${current.label} 관측 ${inWindow}건 · 현재까지 누적 ${visible.length}건`;
  window.requestAnimationFrame(updateLightningViewportControl);
}
function stopHeroLightning(){
  clearInterval(heroLightningTimer); heroLightningTimer=null;
  const button=document.getElementById("heroLightningPlay");
  if(button) button.textContent="▶";
}
function toggleHeroLightning(){
  if(heroLightningTimer) return stopHeroLightning();
  const button=document.getElementById("heroLightningPlay");
  if(button) button.textContent="❚❚";
  if(heroLightningIdx >= 5) renderHeroStrikes(0);
  heroLightningTimer=setInterval(() => renderHeroStrikes(heroLightningIdx >= 5 ? 0 : heroLightningIdx+1), 1100);
}
function setHeroRadarMode(mode){
  const modeChanged = heroRadarMode !== mode;
  heroRadarMode = mode;
  const isLightning = mode === "lightning";
  const isWalk = mode === "walk";
  const forecastTab = document.getElementById("heroForecastTab");
  const lightningTab = document.getElementById("heroLightningTab");
  const walkTab = document.getElementById("heroWalkTab");
  if(forecastTab) forecastTab.setAttribute("aria-selected", String(mode === "forecast"));
  if(lightningTab) lightningTab.setAttribute("aria-selected", String(isLightning));
  if(walkTab) walkTab.setAttribute("aria-selected", String(isWalk));
  const legend = document.getElementById("heroLightningLegend");
  const lightningStatus = document.getElementById("heroLightningStatus");
  const timeline = document.getElementById("heroTimeline");
  const lightningTimeline = document.getElementById("heroLightningTimeline");
  const kind = document.getElementById("heroKind");
  const walkPanel = document.getElementById("walkWeatherPanel");
  if(legend) legend.hidden = !isLightning;
  if(lightningStatus) lightningStatus.hidden = !isLightning;
  if(timeline) timeline.hidden = isLightning;
  if(lightningTimeline) lightningTimeline.hidden = !isLightning;
  if(kind) kind.hidden = isLightning;
  if(walkPanel) walkPanel.hidden = !isWalk;
  if(radarOverlay) radarOverlay.setOpacity(isLightning ? 0 : .82);
  if(strikeLayer && heroMap){
    if(isLightning && !heroMap.hasLayer(strikeLayer)) strikeLayer.addTo(heroMap);
    if(!isLightning && heroMap.hasLayer(strikeLayer)) heroMap.removeLayer(strikeLayer);
  }
  if(isLightning){
    tlStop();
    renderHeroStrikes(heroLightningIdx);
    if(heroMap && (modeChanged || !heroLightningViewFitted)){
      focusLightningMap();
    }
  }
  else{
    heroLightningShowingAll=false;
    updateLightningViewportControl();
    stopHeroLightning();
    if(modeChanged && heroMap && state.lat!=null) heroMap.setView([state.lat,state.lon],8,{animate:false});
    if(isWalk) renderWalkWeather();
  }
  const status = document.getElementById("mapStatus");
  if(status) status.textContent = isLightning ? "5분마다 확인하는 최근 낙뢰 관측" : (isWalk ? "산책 전 우리 동네 2시간 비 예보" : "앞으로 예상되는 강수 영역");
  window.setTimeout(() => heroMap && heroMap.invalidateSize(), 0);
}

function renderWalkWeather(){
  const title = document.getElementById("walkWeatherTitle");
  const detail = document.getElementById("walkWeatherDetail");
  const timeline = document.getElementById("walkWeatherTimeline");
  if(!title || !detail || !timeline) return;
  if(heroRadarKey === "national"){
    title.textContent = "알림 받을 주소를 먼저 검색해주세요.";
    detail.textContent = "주소를 확인하면 우리 동네 주변의 2시간 비 예보를 보여드려요.";
    timeline.replaceChildren();
    return;
  }
  const now = new Date();
  const frames = (heroForecastData?.frames || [])
    .map(frame => ({
      ...frame,
      at:new Date(frame.valid_at),
      localKnown:Object.prototype.hasOwnProperty.call(frame,"local_rain_px"),
      rain:Number(frame.local_rain_px || 0) > 0
    }))
    .filter(frame => frame.at >= now && frame.at-now <= 130*60*1000)
    .sort((a,b) => a.at-b.at)
    .slice(0,4);
  const currentKnown = Object.prototype.hasOwnProperty.call(heroRadarObs || {},"local_rain_cells");
  const forecastKnown = frames.length > 0 && frames.every(frame => frame.localKnown);
  const rainingNow = Number(heroRadarObs?.local_rain_cells || 0) > 0;
  const firstRain = frames.find(frame => frame.rain);
  const firstDry = frames.find(frame => !frame.rain);
  if(!currentKnown || !forecastKnown){
    title.textContent = "우리 동네 비 예보를 새 기준으로 갱신 중이에요.";
    detail.textContent = "등록 위치 반경 5km의 강수 자료가 준비되면 정확하게 안내할게요.";
  }else if(!frames.length){
    title.textContent = "지금은 2시간 비 예보를 불러올 수 없어요.";
    detail.textContent = "잠시 뒤 다시 확인하거나 강수 예측 지도를 참고해주세요.";
  }else if(rainingNow){
    title.textContent = "현재 우리 동네 주변에 비구름이 있어요.";
    detail.textContent = firstDry ? `약 ${Math.max(10,Math.round((firstDry.at-now)/600000)*10)}분 뒤 비구름이 약해질 가능성이 있어요.` : "앞으로 2시간 동안 비구름이 이어질 가능성이 있어요.";
  }else if(firstRain){
    title.textContent = `약 ${Math.max(10,Math.round((firstRain.at-now)/600000)*10)}분 뒤 비구름이 다가올 수 있어요.`;
    detail.textContent = "산책한다면 예상 시각 전에 돌아오는 편이 좋아요.";
  }else{
    title.textContent = "앞으로 2시간 동안 뚜렷한 비 예보가 없어요.";
    detail.textContent = "지금 산책하기 괜찮아 보여요. 출발 전 지도를 한 번 더 확인해주세요.";
  }
  timeline.replaceChildren(...frames.map(frame => {
    const item = document.createElement("span");
    item.className = !frame.localKnown ? "" : (frame.rain ? "rain" : "dry");
    item.innerHTML = `<b>${fmtClock(frame.at)}</b>${!frame.localKnown ? "갱신 중" : (frame.rain ? "비 가능" : "비 없음")}`;
    return item;
  }));
}
function fmtGap(mins){
  const a = Math.abs(mins);
  if(a < 3) return "지금";
  const s = a >= 60 ? `${Math.floor(a/60)}시간${a%60 ? " "+(a%60)+"분" : ""}` : `${a}분`;
  return mins < 0 ? `${s} 전` : `${s} 뒤`;
}

function tlShow(i){
  if(!tl.length || !heroMap) return;
  tlIdx = (i + tl.length) % tl.length;
  const f = tl[tlIdx];
  const range = document.getElementById("heroRange");
  if(range) range.value = tlIdx;

  if(!radarOverlay){
    radarOverlay = L.imageOverlay(f.image,
      [[f.bounds.south,f.bounds.west],[f.bounds.north,f.bounds.east]], { opacity:.82 }).addTo(heroMap);
    radarOverlay.bringToFront();
  }else{
    radarOverlay.setBounds([[f.bounds.south,f.bounds.west],[f.bounds.north,f.bounds.east]]);
    radarOverlay.setUrl(f.image);
  }

  const gap = Math.round((f.at.getTime() - Date.now())/60000);
  const t = document.getElementById("heroTime");
  if(t) t.textContent = f.kind === "obs" ? `현재 ${fmtClock(f.at)}` : `${fmtClock(f.at)} (${fmtGap(gap)})`;
  const kind = document.getElementById("heroKind");
  if(kind){
    kind.innerHTML = f.kind === "obs"
      ? "<b>관측</b> · 실제로 내린 비입니다."
      : (f.rain_px === 0 ? "<b>예측</b> · 이 시각엔 예보된 비가 없습니다."
                         : "<b>예측</b> · 기상청 초단기 강수예측(앞으로 올 비)입니다.");
  }
}

function tlStop(){ clearInterval(tlTimer); tlTimer=null; const b=document.getElementById("heroPlay"); if(b) b.textContent="▶"; }
function tlToggle(){
  if(tlTimer) return tlStop();
  const b=document.getElementById("heroPlay"); if(b) b.textContent="❚❚";
  if(tlIdx >= tl.length-1) tlIdx = 0;
  tlTimer = setInterval(() => tlShow(tlIdx >= tl.length-1 ? 0 : tlIdx+1), 900);
}

async function loadRadar(key, silentFail){
  try{
    const [oRes, fRes, nRes] = await Promise.all([
      fetch(`${RADAR_BASE}/${key}.json?t=${Date.now()}`),
      fetch(`${RADAR_BASE}/${key}_forecast.json?t=${Date.now()}`).catch(() => null),
      key === "national" ? Promise.resolve(null) : fetch(`${RADAR_BASE}/national.json?t=${Date.now()}`).catch(() => null)
    ]);
    if(!oRes.ok) throw new Error(oRes.status);
    const obs = await oRes.json();
    heroRadarObs = obs;
    const fc = fRes && fRes.ok ? await fRes.json() : null;
    const nationalObs = nRes && nRes.ok ? await nRes.json() : null;
    heroForecastData = fc;
    heroRadarKey = key;
    heroLightningStrikes = (key === "national" ? obs.lightning : nationalObs?.lightning) || obs.lightning || [];

    // 강수 예측은 과거 재생이 아니라 현재 관측을 출발점으로 미래만 보여준다.
    const items = [{ kind:"obs", image:obs.image, bounds:obs.bounds, at:new Date(obs.observed_at) }];
    (fc?.frames || []).forEach(f =>
      items.push({ kind:"fcst", image:f.image, bounds:fc.bounds, at:new Date(f.valid_at), rain_px:f.rain_px }));
    items.sort((a,b) => a.at - b.at);
    tl = items;

    const nowIdx = 0;
    const range = document.getElementById("heroRange");
    if(range) range.max = Math.max(0, tl.length-1);
    tl.forEach(f => { const im = new Image(); im.src = f.image; });
    tlShow(nowIdx < 0 ? tl.length-1 : nowIdx);

    // 낙뢰 표시
    if(!strikeLayer) strikeLayer = L.layerGroup().addTo(heroMap);
    renderHeroStrikes(heroLightningIdx);

    const status = document.getElementById("mapStatus");
    if(status && key === "national") status.textContent = "지금 전국 비구름 · 위치를 입력하면 우리 동네로";
    setHeroRadarMode(heroRadarMode);
    return true;
  }catch(e){
    if(!silentFail){
      const status = document.getElementById("mapStatus");
      if(status) status.textContent = "지금은 레이더를 불러올 수 없어요";
    }
    return false;
  }
}

async function refreshWeather(){
  const button=document.getElementById("weatherRefresh");
  if(!button || button.disabled) return;
  button.disabled=true;
  button.classList.add("is-loading");
  button.setAttribute("aria-busy","true");
  const status=document.getElementById("mapStatus");
  if(status) status.textContent="최신 기상정보를 확인하고 있어요…";
  const key=state.nx!=null ? `${state.nx}_${state.ny}` : "national";
  const ok=await loadRadar(key);
  if(ok){
    if(heroRadarMode==="walk") renderWalkWeather();
    if(status) status.textContent=`${fmtClock(new Date())} 최신 기상정보로 업데이트`;
  }
  button.disabled=false;
  button.classList.remove("is-loading");
  button.removeAttribute("aria-busy");
}

document.addEventListener("click", e => {
  if(e.target && e.target.id === "heroPlay") tlToggle();
  if(e.target && e.target.id === "heroForecastTab") setHeroRadarMode("forecast");
  if(e.target && e.target.id === "heroLightningTab") setHeroRadarMode("lightning");
  if(e.target && e.target.id === "heroWalkTab") openWalkWeather();
  if(e.target && e.target.id === "heroLightningPlay") toggleHeroLightning();
  if(e.target && (e.target.id === "weatherRefresh" || e.target.closest?.("#weatherRefresh"))) refreshWeather();
});

async function openWalkWeather(){
  let key = state.nx != null ? `${state.nx}_${state.ny}` : "";
  if(!key){
    try{ key = localStorage.getItem("thunder_grid") || ""; }catch(error){}
  }
  if(new URLSearchParams(location.search).get("preview") === "walk-rain") key = "69_106";
  if(!key){
    toast("우리 동네 예보를 보려면 주소를 먼저 검색해주세요.");
    document.getElementById("addressField")?.scrollIntoView({behavior:"smooth",block:"center"});
    return;
  }
  if(heroRadarKey !== key) await loadRadar(key, true);
  setHeroRadarMode("walk");
}
document.addEventListener("input", e => {
  if(e.target && e.target.id === "heroRange"){ tlStop(); tlShow(+e.target.value); }
  if(e.target && e.target.id === "heroLightningRange"){ stopHeroLightning(); renderHeroStrikes(+e.target.value); }
});

function setLocation(lat, lon, dongHint, {persist=true}={}){
  setGeoStatus("");   // 위치가 정해졌으니 이전 안내(권한 거부 등)는 치운다
  state.lat=lat;
  state.lon=lon;
  const grid=toGrid(lat,lon);
  state.nx=grid.nx;
  state.ny=grid.ny;
  state.dong=shortLocationLabel(dongHint) || null;
  $("locText").textContent=(state.dong || "선택한 주소") + " · 알림 위치 확인됨";
  $("locResult").classList.add("show");
  $("addressField").classList.add("has-location");
  $("ctaBtn").disabled=false;
  $("ctaBtn").textContent="🚨 필수 · 알림 설정 완료하기";
  pinHome(lat, lon, state.dong);
  if(persist) saveLocationProfile();
}

function restoreSavedLocation(){
  const profile=readSavedLocation();
  if(!profile) return false;
  const lat=Number(profile.lat);
  const lon=Number(profile.lon);

  setLocation(lat, lon, profile.dong || "선택한 주소", {persist:false});
  if($("addrInput") && profile.dong) $("addrInput").value=profile.dong;
  window.setTimeout(() => heroMap && heroMap.invalidateSize(), 0);
  return true;
}

function openPushLightningView(){
  const params=new URLSearchParams(location.search);
  if(!params.has("push")) return false;

  // 푸시로 들어왔을 때만 마지막 탭 상태를 무시하고 가장 최근 낙뢰를 보여준다.
  stopHeroLightning();
  heroLightningIdx=5;
  setHeroRadarMode("lightning");

  window.setTimeout(() => {
    renderHeroStrikes(5);
    if(heroMap){
      heroMap.invalidateSize();
      focusLightningMap();
    }
    document.getElementById("radar")?.scrollIntoView({behavior:"auto",block:"start"});
  },120);

  // 일반 재접속까지 푸시 진입으로 오인하지 않도록 일회성 표시를 주소에서 지운다.
  params.delete("push");
  const query=params.toString();
  history.replaceState(null,"",`${location.pathname}${query ? `?${query}` : ""}#radar`);
  return true;
}

function refreshSavedMap(){
  if(!restoreSavedLocation()) return;
  window.setTimeout(() => {
    if(!heroMap) return;
    heroMap.invalidateSize();
    if(heroRadarMode === "lightning"){
      focusLightningMap();
    }else{
      heroMap.setView([state.lat,state.lon],8,{animate:false});
    }
  },120);
}

// OpenStreetMap은 좁은 곳 → 넓은 곳 순으로 준다(미국식: 용암동, 상당구, 청주시, 충청북도).
// 한국식(충청북도 청주시 상당구 용암동)으로 뒤집고, 행정구역 이름만 골라낸다.
// 접미사로 거르면 아파트단지명("솔빛마을")·별칭("신제주")·도로명 같은 잉여 항목도 같이 떨어진다.
const SIDO_RE=/(특별자치도|특별자치시|특별시|광역시|도)$/;
const SIGUNGU_RE=/(시|군|구)$/;
const DONG_RE=/(동|읍|면|리|가)$/;

function shortLocationLabel(label){
  if(!label) return "";
  const parts=label.split(",")
    .map(part => part.trim())
    .filter(part => part && part !== "대한민국" && !/^\d{5}$/.test(part))
    .reverse();                                   // 넓은 곳 → 좁은 곳
  if(!parts.length) return "";

  const picked=[];
  const sido=parts.find(part => SIDO_RE.test(part));
  if(sido) picked.push(sido);
  // 시·군·구는 "청주시 상당구"처럼 두 단계가 함께 쓰인다
  picked.push(...parts.filter(part => part!==sido && SIGUNGU_RE.test(part)).slice(0,2));
  const dong=parts.find(part => !picked.includes(part) && DONG_RE.test(part));
  if(dong) picked.push(dong);

  // 한국 행정구역이 하나도 안 잡히면(해외 좌표 등) 넓은 쪽부터 그대로 쓴다
  return (picked.length ? picked : parts.slice(-4)).join(" ");
}

$("addrBtn").addEventListener("click", async () => {
  const query=$("addrInput").value.trim();
  if(!query){ toast("동네를 입력해주세요"); return; }
  $("addrBtn").textContent="검색 중";
  $("addrBtn").disabled=true;
  const hit=await forwardGeocode(query);
  $("addrBtn").textContent="검색";
  $("addrBtn").disabled=false;
  if(!hit){ toast("주소를 찾지 못했습니다. 도로명이나 시·군·구를 함께 입력해보세요"); return; }
  setLocation(hit.lat,hit.lon,hit.label || query);
});

$("addrInput").addEventListener("keydown", event => {
  if(event.key==="Enter"){
    event.preventDefault();
    $("addrBtn").click();
  }
});

// ----------------------------------------------------------------
// 현재 위치로 등록
// ----------------------------------------------------------------
// 폰 GPS는 정확하지만 PC는 와이파이·IP 기반이라 수 km씩 틀릴 수 있다.
// 그래서 잡은 위치를 지도 핀 + 동네 이름으로 보여주고 사용자가 눈으로 확인하게 한다.
const KOREA_BOUNDS={latMin:33,latMax:39,lonMin:124,lonMax:132};   // DB INSERT 정책과 같은 범위

function setGeoStatus(message,{error=false}={}){
  const el=$("geoStatus");
  if(!message){ el.hidden=true; el.textContent=""; el.classList.remove("is-error"); return; }
  el.hidden=false;
  el.textContent=message;
  el.classList.toggle("is-error",error);
}

async function reverseGeocode(lat,lon){
  try{
    const response=await fetch(`https://nominatim.openstreetmap.org/reverse?format=json&addressdetails=1&accept-language=ko&zoom=16&lat=${lat}&lon=${lon}`);
    if(!response.ok) return null;
    const json=await response.json();
    return json.display_name || null;
  }catch(error){
    return null;
  }
}

function currentPosition(){
  return new Promise((resolve,reject) => {
    navigator.geolocation.getCurrentPosition(resolve,reject,{
      enableHighAccuracy:true,
      timeout:10000,
      maximumAge:60000
    });
  });
}

async function useCurrentLocation(){
  const button=$("geoBtn");
  if(!navigator.geolocation){
    setGeoStatus("이 브라우저는 위치 확인을 지원하지 않아요. 아래에서 주소로 찾아주세요.",{error:true});
    return;
  }

  button.disabled=true;
  button.classList.add("is-loading");
  setGeoStatus("현재 위치를 확인하는 중이에요…");

  try{
    const position=await currentPosition();
    const {latitude:lat,longitude:lon,accuracy}=position.coords;

    if(lat<KOREA_BOUNDS.latMin || lat>KOREA_BOUNDS.latMax || lon<KOREA_BOUNDS.lonMin || lon>KOREA_BOUNDS.lonMax){
      setGeoStatus("한국 밖으로 확인돼요. 아래에서 주소로 찾아주세요.",{error:true});
      return;
    }

    const label=await reverseGeocode(lat,lon);
    setLocation(lat,lon,label);

    // 오차가 크면(주로 PC) 사용자가 지도를 보고 판단하도록 알려준다
    if(Number.isFinite(accuracy) && accuracy>3000){
      setGeoStatus(`위치를 잡았지만 오차가 약 ${Math.round(accuracy/1000)}km예요. 지도의 핀이 우리 동네가 맞는지 확인해주세요.`);
    }else{
      setGeoStatus("현재 위치를 등록했어요. 지도에서 확인해보세요.");
    }
  }catch(error){
    if(error && error.code===1){
      setGeoStatus("위치 권한이 거부됐어요. 아래에서 주소로 찾거나, 브라우저 설정에서 위치를 허용해주세요.",{error:true});
    }else if(error && error.code===3){
      setGeoStatus("위치 확인이 오래 걸려요. 다시 시도하거나 아래에서 주소로 찾아주세요.",{error:true});
    }else{
      setGeoStatus("위치를 확인하지 못했어요. 아래에서 주소로 찾아주세요.",{error:true});
    }
  }finally{
    button.disabled=false;
    button.classList.remove("is-loading");
  }
}

$("geoBtn").addEventListener("click",useCurrentLocation);

async function forwardGeocode(query){
  try{
    const response=await fetch(`https://nominatim.openstreetmap.org/search?format=json&addressdetails=1&accept-language=ko&countrycodes=kr&limit=1&q=${encodeURIComponent(query)}`);
    if(!response.ok) return null;
    const json=await response.json();
    if(!json.length) return null;
    return {lat:parseFloat(json[0].lat), lon:parseFloat(json[0].lon), label:json[0].display_name};
  }catch(error){
    return null;
  }
}

function closeNotificationSheet(){
  $("notifySheet").hidden=true;
  document.body.style.overflow="";
}

function showIosNotificationGuide(){
  $("iosInstallGuide").hidden=false;
  $("directNotifyGuide").hidden=true;
  window.setTimeout(() => $("iosGuideDone").focus(),0);
}

function showDirectNotificationGuide(){
  $("iosInstallGuide").hidden=true;
  $("directNotifyGuide").hidden=false;
  window.setTimeout(() => $("allowNotifyBtn").focus(),0);
}

function openNotificationSheet(){
  if(isIOS && !isStandalone) showIosNotificationGuide();
  else showDirectNotificationGuide();
  $("notifySheet").hidden=false;
  document.body.style.overflow="hidden";
}

$("ctaBtn").addEventListener("click", () => {
  if(state.nx==null){ toast("먼저 위치를 등록해주세요"); return; }
  openNotificationSheet();
});

$("notifySheetClose").addEventListener("click", closeNotificationSheet);
$("notifySheetBackdrop").addEventListener("click", closeNotificationSheet);
$("iosGuideDone").addEventListener("click", closeNotificationSheet);
$("showIosGuide").addEventListener("click", showIosNotificationGuide);
$("showDirectGuide").addEventListener("click", showDirectNotificationGuide);
document.addEventListener("keydown", event => {
  if(event.key==="Escape" && !$("notifySheet").hidden) closeNotificationSheet();
});

$("allowNotifyBtn").addEventListener("click", completeSubscription);

async function syncInlineSubscriptionStatus(){
  const panel=$("inlineSubscriptionStatus");
  if(!panel || !("serviceWorker" in navigator)) return;
  try{
    const registration=await navigator.serviceWorker.getRegistration();
    const subscription=registration && await registration.pushManager.getSubscription();
    panel.hidden=!subscription;
    if(subscription){
      let profile={};
      profile=readAlertProfile();
      $("inlineSubscriptionLocation").textContent=(profile.dong ? profile.dong+"에서 " : "현재 기기에서 ")+"천둥번개 알림을 받고 있습니다.";
    }
  }catch(error){
    panel.hidden=true;
  }
}

$("inlineAlertOffButton").addEventListener("click", () => {
  const sharedOffButton=document.getElementById("alertOffButton");
  if(sharedOffButton) sharedOffButton.click();
  else toast("상단 메뉴의 알림 관리에서 알림을 꺼주세요");
});
window.addEventListener("thunder-subscription-changed", syncInlineSubscriptionStatus);

async function completeSubscription(){
  if(state.nx==null){ closeNotificationSheet(); toast("먼저 주소를 등록해주세요"); return; }

  if(isIOS && !isStandalone){
    openNotificationSheet();
    return;
  }

  $("allowNotifyBtn").disabled=true;
  $("allowNotifyBtn").textContent="알림 연결 중…";

  if(!("Notification" in window) || !("serviceWorker" in navigator) || !("PushManager" in window)){
    toast("이 브라우저에서는 웹푸시 알림을 사용할 수 없습니다");
    resetNotifyButton();
    return;
  }

  let permission=Notification.permission;
  try{
    if(permission==="default") permission=await Notification.requestPermission();
  }catch(error){
    toast("알림 권한 확인창을 열지 못했습니다. 브라우저 설정을 확인해주세요");
    resetNotifyButton();
    return;
  }
  if(permission!=="granted"){
    toast("알림을 받으려면 알림 권한을 허용해주세요");
    resetNotifyButton();
    return;
  }

  let subscription=null;
  try{
    const registration=await navigator.serviceWorker.register("sw.js?v=push-radar-3");
    await navigator.serviceWorker.ready;
    subscription=await registration.pushManager.getSubscription();
    if(!subscription){
      subscription=await registration.pushManager.subscribe({
        userVisibleOnly:true,
        applicationServerKey:urlBase64ToUint8Array(CONFIG.VAPID_PUBLIC_KEY)
      });
    }
  }catch(error){
    console.warn("push subscribe 실패:",error);
  }

  if(!subscription){
    toast("알림 등록에 실패했습니다. 새로고침 후 다시 시도해주세요");
    resetNotifyButton();
    return;
  }

  const payload={
    lat:state.lat,
    lon:state.lon,
    nx:state.nx,
    ny:state.ny,
    dong:state.dong,
    subscription:subscription.toJSON ? subscription.toJSON() : subscription
  };

  try{
    const response=await fetch(`${CONFIG.SUPABASE_URL}/rest/v1/subscribers`,{
      method:"POST",
      headers:{"Content-Type":"application/json","apikey":CONFIG.SUPABASE_ANON_KEY},
      body:JSON.stringify(payload)
    });
    if(!response.ok){
      console.warn("저장 실패:",response.status,await response.text());
      try{ await subscription.unsubscribe(); }catch(error){}
      toast("저장 중 문제가 생겼습니다. 잠시 후 다시 시도해주세요");
      resetNotifyButton();
      return;
    }
  }catch(error){
    console.warn("저장 실패:",error);
    try{ await subscription.unsubscribe(); }catch(unsubscribeError){}
    toast("네트워크 오류로 저장하지 못했습니다");
    resetNotifyButton();
    return;
  }

  try{
    const registration=await navigator.serviceWorker.ready;
    await registration.showNotification("썬더미리 알림 연결 완료",{
      body:"우리 아이를 위한 낙뢰 알림을 켰습니다. 천둥이 가까워지면 미리 알려드릴게요.",
      icon:"thundermiri-icon-192.png",
      badge:"thundermiri-icon-192.png",
      tag:"welcome"
    });
  }catch(error){
    console.warn("환영 알림 실패:",error);
  }

  // 재접속해도 같은 위치의 핀과 반경을 복원할 수 있게 정확한 좌표를 기억해둔다.
  saveLocationProfile();

  // 다음 방문부터는 소개 문구 대신 레이더를 먼저 보여준다(가입을 끝낸 기기 표시).
  try{ localStorage.setItem("thunder_returning","1"); }catch(error){}

  closeNotificationSheet();
  $("formView").style.display="none";
  $("successView").classList.add("show");
  $("signup").scrollIntoView({behavior:"smooth",block:"start"});
  window.dispatchEvent(new CustomEvent("thunder-subscription-changed"));
}

function resetNotifyButton(){
  $("allowNotifyBtn").disabled=false;
  $("allowNotifyBtn").textContent="알림 허용하기";
}

function urlBase64ToUint8Array(base64String){
  const padding="=".repeat((4-base64String.length%4)%4);
  const base64=(base64String+padding).replace(/-/g,"+").replace(/_/g,"/");
  const raw=atob(base64);
  const output=new Uint8Array(raw.length);
  for(let index=0;index<raw.length;index++) output[index]=raw.charCodeAt(index);
  return output;
}

initHeroMap();
updateLightningClock(heroLightningIdx);
if(!restoreSavedLocation()) loadRadar("national"); // 저장 위치가 없을 때만 전국 화면을 보여준다.
openPushLightningView();
setInterval(() => loadRadar(state.nx!=null ? `${state.nx}_${state.ny}` : "national", true), 5*60*1000);
syncInlineSubscriptionStatus();

// iPhone 홈 화면 웹 앱은 페이지 복귀나 앱 재개 때 기존 화면을 그대로 되살릴 수 있다.
// 그때 Leaflet의 화면 크기와 저장 위치를 다시 적용해 핀과 반경이 사라지지 않게 한다.
window.addEventListener("pageshow", event => {
  if(event.persisted) refreshSavedMap();
});
document.addEventListener("visibilitychange", () => {
  if(document.visibilityState === "visible") refreshSavedMap();
});
window.addEventListener("hashchange", () => {
  if(location.hash === "#radar") refreshSavedMap();
});
