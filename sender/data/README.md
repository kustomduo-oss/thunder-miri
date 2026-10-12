# 관리자 텔레그램용 대한민국 육지 경계

`south-korea-municipalities-2018.geojson`은 아래 시군구 경계 원본을 수정 없이 저장한 자료입니다.

- 원자료 제공: 통계청 통계지리정보서비스(SGIS), 2018년 12월 24일 수집
- 배포: southkorea/southkorea-maps
- 고정 버전: fe65e05e549d04083e52f380a7e9166a8ea0a01e
- 원본: https://raw.githubusercontent.com/southkorea/southkorea-maps/fe65e05e549d04083e52f380a7e9166a8ea0a01e/kostat/2018/json/skorea-municipalities-2018-geo.json
- 이용 조건: 공공누리 제1유형(출처 표시)
- 이용 조건 원문: https://github.com/southkorea/southkorea-maps/blob/fe65e05e549d04083e52f380a7e9166a8ea0a01e/kostat/2018/json/LICENSE.md

남한 본토와 원본에 수록된 부속 도서의 폴리곤으로 판정합니다. 영해/EEZ의
법적 경계가 아닙니다. 관리자 알림은 국내 육지·도서와 그 경계에서 약 50km
이내의 연안 해상을 대상으로 합니다(EPSG:5179 미터 거리). 외국 육지는
아래 별도 경계 자료로 제외합니다. 해안선 오차,
낙뢰 관측 위치 오차, 자료 작성 이후 매립지 등은 완벽히 반영하지 못합니다.
파일 오류 시 사각형 필터로 되돌아가지 않고 관리자 감지 알림만 보류합니다.
사용자 거리별 푸시 및 레이더 표시에는 적용하지 않습니다.

시도 경계판에는 홍도·가거도가 누락되어 시군구 경계판(1,558개 폴리곤)을
선택했습니다. 제주, 울릉도, 독도 동도/서도, 백령도, 대청도, 연평도,
흑산도, 홍도, 마라도, 가거도, 강화도, 거제도의 대표 육지 좌표를 테스트합니다.
모든 작은 바위섬의 수록 여부를 전수 검증한 것은 아닙니다.

## 외국 육지 제외 자료

geoBoundaries gbOpen의 고정 버전 `9469f09` ADM0 원본을 사용합니다.
국내 경계에 들어가는 좌표를 먼저 판정하므로 독도는 국내 섬으로 포함됩니다.

- 북한 `exclude-PRK.geojson`: World Food Programme / OCHA ROAP,
  CC BY 3.0 IGO. https://www.geoboundaries.org/api/current/gbOpen/PRK/ADM0/
- 일본 `exclude-JPN.geojson`: 일본 국토교통성 국토수치정보 / geoBoundaries,
  CC BY 4.0. 이용 조건: https://nlftp.mlit.go.jp/ksj/other/agreement.html#agree-01
  메타데이터:
  https://www.geoboundaries.org/api/current/gbOpen/JPN/ADM0/
- 중국 `exclude-CHN.geojson`: geoBoundaries / Wikimedia Commons, Public Domain.
  https://www.geoboundaries.org/api/current/gbOpen/CHN/ADM0/
- 원본 URL 공통 형식:
  `https://media.githubusercontent.com/media/wmgeolab/geoBoundaries/9469f09/releaseData/gbOpen/{ISO}/ADM0/geoBoundaries-{ISO}-ADM0.geojson`

50km는 관리자 모니터링용 운영 기준으로, 법적 영해/해양 관할권을 뜻하지 않습니다.
