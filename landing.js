/* 동탄이네 천둥번개 알림이 — 영상 반응 확인, 위치 설정, 웹푸시 연결 */
const CONFIG = {
  SUPABASE_URL: "https://pdlohzenslwbiyoxwjom.supabase.co",
  SUPABASE_ANON_KEY: "sb_publishable_5GA_EH7mqRbkWe-UEWEL2Q_xf5cn3kF",
  VAPID_PUBLIC_KEY: "BDpsQ-TxN1fOcZL5JX863gvyPT5QD78S8k94lIEDFZnhUXdEy_ReIxVGmSLeFRWtjxO4EvECDEdsWfTGADfocHQ"
};

const state = { lat:null, lon:null, nx:null, ny:null, dong:null, cooldown:20 };
const $ = id => document.getElementById(id);
const SOUND_CHECK_KEY = "dongtaniSoundCheckPassed";

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

if(isIOS){
  $("iosGuide").classList.add("current-device");
  if(isStandalone) $("iosGuide").querySelector("span").textContent = "홈 화면에서 실행 중입니다. 아래에서 위치와 알림을 설정하세요.";
}else{
  $("otherGuide").classList.add("current-device");
}

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

function initHeroMap(){
  const el = document.getElementById("heroMap");
  if(!el || typeof L === "undefined" || heroMap) return;
  heroMap = L.map(el, {
    zoomControl:false, attributionControl:false,
    dragging:false, scrollWheelZoom:false, doubleClickZoom:false,
    touchZoom:false, keyboard:false, tap:false
  }).setView([36.5, 127.8], 6);
  L.tileLayer(
    "https://api.vworld.kr/req/wmts/1.0.0/12A21CCD-E7FC-3E4E-B6A5-F8DE7A32A24D/midnight/{z}/{y}/{x}.png",
    { maxZoom:18 }
  ).addTo(heroMap);
  heroLayer = L.layerGroup().addTo(heroMap);
}

function pinHome(lat, lon, label){
  if(!heroMap) initHeroMap();
  if(!heroMap) return;
  heroLayer.clearLayers();

  // 50km = 접근(바깥, 옅게) / 30km = 임박(안쪽, 진하게) — 목업과 같은 위계
  L.circle([lat,lon], { radius:50000, color:"#3cc4dc", weight:1.2, opacity:.75,
                        fillColor:"#3cc4dc", fillOpacity:.06 }).addTo(heroLayer);
  L.circle([lat,lon], { radius:30000, color:"#6fd8ea", weight:1.6, opacity:.95,
                        fillColor:"#3cc4dc", fillOpacity:.12 }).addTo(heroLayer);
  L.marker([lat,lon], { icon: L.divIcon({
      className:"", iconSize:[64,64], iconAnchor:[32,32],
      html:'<div class="hero-pin">우리 집</div>'
  }), keyboard:false }).addTo(heroLayer);

  heroMap.setView([lat,lon], 8);
  const status = document.getElementById("mapStatus");
  if(status) status.textContent = (label || "우리 동네") + " 낙뢰 감시 중";
}

function setLocation(lat, lon, dongHint){
  state.lat=lat;
  state.lon=lon;
  const grid=toGrid(lat,lon);
  state.nx=grid.nx;
  state.ny=grid.ny;
  state.dong=dongHint || null;
  $("locText").textContent=(state.dong || "현재 위치") + ` · 격자 ${grid.nx},${grid.ny}`;
  $("locResult").classList.add("show");
  $("ctaBtn").disabled=false;
  $("ctaBtn").textContent="우리 동네 낙뢰 알림 받기";
  pinHome(lat, lon, state.dong);
}

$("locBtn").addEventListener("click", () => {
  if(!navigator.geolocation){ toast("이 브라우저는 위치 기능을 지원하지 않습니다"); return; }
  $("locBtn").textContent="위치 확인 중…";
  navigator.geolocation.getCurrentPosition(position => {
    setLocation(position.coords.latitude, position.coords.longitude);
    $("locBtn").textContent="현재 위치 다시 가져오기";
  }, error => {
    $("locBtn").textContent="현재 위치 가져오기";
    toast(error.code===1 ? "위치 권한을 허용하거나 동네 검색을 이용해주세요" : "위치를 가져오지 못했습니다");
  }, {enableHighAccuracy:true, timeout:10000});
});

$("addrBtn").addEventListener("click", async () => {
  const query=$("addrInput").value.trim();
  if(!query){ toast("동네를 입력해주세요"); return; }
  $("addrBtn").textContent="검색 중";
  $("addrBtn").disabled=true;
  const hit=await forwardGeocode(query);
  $("addrBtn").textContent="검색";
  $("addrBtn").disabled=false;
  if(!hit){ toast("주소를 찾지 못했습니다. 시·군·구와 동을 함께 입력해보세요"); return; }
  setLocation(hit.lat,hit.lon,query);
});

$("addrInput").addEventListener("keydown", event => {
  if(event.key==="Enter"){
    event.preventDefault();
    $("addrBtn").click();
  }
});

document.querySelectorAll(".iv-btn").forEach(button => button.addEventListener("click", () => {
  document.querySelectorAll(".iv-btn").forEach(item => item.classList.remove("active"));
  button.classList.add("active");
  state.cooldown=parseInt(button.dataset.min,10);
}));

async function forwardGeocode(query){
  try{
    const response=await fetch(`https://nominatim.openstreetmap.org/search?format=json&accept-language=ko&countrycodes=kr&limit=1&q=${encodeURIComponent(query)}`);
    if(!response.ok) return null;
    const json=await response.json();
    if(!json.length) return null;
    return {lat:parseFloat(json[0].lat), lon:parseFloat(json[0].lon)};
  }catch(error){
    return null;
  }
}

$("ctaBtn").addEventListener("click", async () => {
  if(state.nx==null){ toast("먼저 위치를 등록해주세요"); return; }

  if(isIOS && !isStandalone){
    $("installRequired").hidden=false;
    $("installRequired").scrollIntoView({behavior:"smooth", block:"center"});
    return;
  }

  $("ctaBtn").disabled=true;
  $("ctaBtn").textContent="알림 연결 중…";

  if(!("Notification" in window) || !("serviceWorker" in navigator) || !("PushManager" in window)){
    toast("이 브라우저에서는 웹푸시 알림을 사용할 수 없습니다");
    resetCta();
    return;
  }

  let permission=Notification.permission;
  if(permission==="default") permission=await Notification.requestPermission();
  if(permission!=="granted"){
    toast("알림을 받으려면 알림 권한을 허용해주세요");
    resetCta();
    return;
  }

  let subscription=null;
  try{
    const registration=await navigator.serviceWorker.register("sw.js");
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
    resetCta();
    return;
  }

  const payload={
    dog_name:$("dogName").value.trim() || null,
    lat:state.lat,
    lon:state.lon,
    nx:state.nx,
    ny:state.ny,
    dong:state.dong,
    cooldown_min:state.cooldown,
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
      toast("저장 중 문제가 생겼습니다. 잠시 후 다시 시도해주세요");
      resetCta();
      return;
    }
  }catch(error){
    console.warn("저장 실패:",error);
    toast("네트워크 오류로 저장하지 못했습니다");
    resetCta();
    return;
  }

  try{
    const registration=await navigator.serviceWorker.ready;
    await registration.showNotification("동탄이네 천둥번개 알림이 연결 완료",{
      body:`${$("dogName").value.trim() || "우리 아이"}를 위한 낙뢰 알림을 켰습니다. 천둥이 가까워지면 미리 알려드릴게요.`,
      icon:"icon-192.png",
      badge:"icon-192.png",
      tag:"welcome"
    });
  }catch(error){
    console.warn("환영 알림 실패:",error);
  }

  // 레이더 화면이 '우리 동네'를 보여줄 수 있게 격자를 기억해둔다
  try{ localStorage.setItem("thunder_grid", state.nx+"_"+state.ny); }catch(e){}

  $("successDog").textContent=$("dogName").value.trim() || "우리 아이";
  $("formView").style.display="none";
  $("successView").classList.add("show");
  $("signup").scrollIntoView({behavior:"smooth",block:"start"});
});

function resetCta(){
  $("ctaBtn").disabled=false;
  $("ctaBtn").textContent="우리 동네 낙뢰 알림 받기";
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
