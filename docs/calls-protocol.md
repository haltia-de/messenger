# Звонки MAX: как они устроены

Шаг 3 [плана звонков](https://github.com/haltia-de/haltia/blob/main/docs/plans/calls.md),
Issue #5. Документ нужен, чтобы сделать голосовой звонок 1:1, входящий и
исходящий: сигнализацию на Python, медиа на GStreamer `webrtcbin`.

**Источники.** Открытый код (SDK звонков VK, PyMax, avenarius, maxcalls и
другие, список в конце), статический разбор MAX Desktop 26.36 и **живой
захват 21 октября 2026**: четыре голосовых звонка между MAX Desktop на ПК и
MAX для Android по журналам самого MAX Desktop:

1. телефон звонит, ПК отвечает, телефон кладёт;
2. ПК звонит, телефон отвечает, ПК кладёт;
3. телефон звонит, ПК отклоняет;
4. телефон звонит и сбрасывает до ответа.

Пометки:
- **[захват]** — видно в этом захвате;
- **[код]** — видно в коде или в записях звонков в тестах avenarius;
- **[источник]** — так пишет источник, не подтверждено;
- **[вывод]** — наше заключение;
- **[проверить]** — нужен захват веб-клиента или нашего клиента (§8).

## 1. Кто с кем говорит

```
 наш клиент ──── сокет MAX (wss://api.oneme.ru/websocket, PyMax) ──── сервер MAX
    │            опкоды 78, 137, 158, 120, 121, 165
    │
    ├── HTTPS https://calls.okcdn.ru (OK vchat API) — вход, статистика; для звонка не обязателен
    │
    ├── сигнальный WebSocket wss://videowebrtc.okcdn.ru/ws2?… (JSON-команды OK Calls)
    │
    └── медиа WebRTC: ICE (STUN/TURN и ретранслятор OK), DTLS-SRTP, Opus
```

Звонки MAX работают на инфраструктуре звонков VK/OK. Сервер MAX выдаёт
параметры звонка: адрес сигнального сокета, токен, TURN и STUN. Входящий
звонок он доставляет пушем. Дальше клиент говорит с сервером звонков OK по
его протоколу, тому же, что у `@vkontakte/calls-sdk` в web.max.ru и у движка
`max-service` в MAX Desktop. **[код, захват]**

## 2. Команды сокета MAX

PyMax 2.4.1 знает номера 78, 137 и 158, но модели и обработчиков у него нет.
Пуши доходят только до обработчиков сырых кадров (`client.on_raw`), запросы
идут через `client._app.invoke(opcode, payload)`. Номеров 120, 121, 165 и 167
в его перечне нет. **[код]**

| Опкод | Направление | Зачем | Где видно |
|---|---|---|---|
| 78 `VIDEO_CHAT_START_ACTIVE` | → | начать звонок | захват |
| 137 `NOTIF_CALL_START` | ← | входящий звонок | захват |
| 158 `CALLS_TOKEN` | → | токен для API `calls.okcdn.ru` | захват |
| 120 | ← | звонок принят | захват |
| 121 | ← | входящий звонок окончен | захват |
| 165 | ← | запись в истории звонков | захват |
| 167 `VIDEO_CHAT_HANGUP` | → | положить трубку | только avenarius; MAX Desktop его не шлёт |
| 79 `VIDEO_CHAT_HISTORY` | → | история звонков `{chatId, count, marker?, direction?}` | источник |

### 2.1. Опкод 78: исходящий звонок **[захват]**

Запрос:
```json
{"conversationId": "<новый uuid4>", "calleeIds": [<id собеседника в MAX>],
 "isVideo": false, "internalParams": "<строка JSON>"}
```

`internalParams` у разных клиентов:

| Клиент | `internalParams` |
|---|---|
| MAX Desktop 26.36 **[захват]** | `{"protocolVersion":5, "platform":"DESKTOP", "deviceId":"<…>", "sdkVersion":"26.36.0", "clientAppKey":"CHFNKILGDIHBABABA", "capabilities":"3C03F"}` |
| web.max.ru **[код: OpenFlux]** | `{"deviceId":"<deviceId сессии MAX>", "sdkVersion":"2.8.9", "clientAppKey":"CNHIJPLGDIHBABABA", "platform":"WEB", "protocolVersion":5, "domainId":"", "capabilities":"2A03F"}` |
| MAX для Android **[код: avenarius]** | `platform: "ANDROID"`, `clientAppKey: "CGPGAGLGDIHBABABA"`, `capabilities: "3c03f"` |

`clientAppKey` — открытый ключ приложения звонков, свой у каждого
клиента. Он вшит в код клиентов и лежит в открытых проектах, это не секрет
аккаунта. Наша сессия MAX — веб (PyMax, `deviceType: WEB`), поэтому берём
параметры веба. Текущие `sdkVersion` и `capabilities` у web.max.ru **[проверить]**.

Ответ приходит за 0,1 с:
```json
{"conversationId": "<uuid>", "rejectedParticipants": [],
 "internalCallerParams": "<строка JSON>"}
```
Содержимое `internalCallerParams`:
```json
{"id": {"internal": <наш id в сигнализации>, "external": "<наш id в MAX>"},
 "isConcurrent": false,
 "endpoint": "wss://videowebrtc.okcdn.ru/ws2?userId=<internal>&entityType=USER&conversationId=<uuid>&token=<…>",
 "wsIpAddresses": [3 адреса], "wtEndpoint": "https://videowebrtc.okcdn.ru:23456/wt?…", "wtIpAddresses": […],
 "clientType": "ONE_ME",
 "turn": {"urls": ["turn:<ip>:19302", "turn:<ip>:19302"], "username": "<срок>:<internal>", "credential": "<base64>"},
 "stun": {"urls": ["stun:<ip>:19302"]},
 "deviceIdx": 0}
```
Отвечающий опкод 78 не шлёт: сервер отвечает ошибкой 1114. **[источник: avenarius]**

### 2.2. Опкод 137: входящий звонок **[захват]**

```json
{"callerId": <id в MAX>, "chatId": 0, "conversationId": "<uuid>", "type": "AUDIO",
 "vcp": "<длина>:<base64>", "isContact": true, "country": "RU"}
```

**`vcp`.** Строку делят по первому `:`. Слева длина распакованных данных
(в захвате 591–592), справа base64 сырого блока LZ4 (не кадра LZ4, без
заголовка). Распакованное содержимое — JSON. Ключи подтверждены захватом:

| Ключ | Что |
|---|---|
| `tkn` | токен сигнализации |
| `wse` | база сигнального сокета, `wss://videowebrtc.okcdn.ru/ws2` без параметров |
| `wsip` | его IP |
| `wte`, `wtip` | WebTransport, `https://videowebrtc.okcdn.ru:23456/wt`, и его IP (не нужен) |
| `vcae`, `vcaip` | API звонков, `https://calls.okcdn.ru`, и его IP |
| `srcp` | тип клиента звонящего, `"one_me"` |
| `et` | срок, секунды unix |
| `stne` | STUN, через запятую |
| `trne` | TURN, через запятую |
| `trnu` | имя TURN, `"<срок>:<наш id в сигнализации>"` |
| `trnp` | пароль TURN |
| `iv` | видео ли |

В Python это `lz4.block.decompress(data, uncompressed_size=n)` или свой
декодер на 25 строк. Описание `vcp` в max-api-docs («гибрид protobuf»)
неверно: это неправильно прочитанный блок LZ4. **[захват, код]**

### 2.3. Опкоды 120, 121, 165: что сообщает сервер MAX **[захват]**

- **120** `{"conversationId"}` пришёл через 0,06 с после того, как ПК
  ответил на входящий. Скорее всего, его получают все наши устройства, чтобы
  остальные перестали звонить **[вывод]**.
- **121** `{"conversationId"}` приходит, когда входящий звонок окончен: после
  разговора, после отклонения и после того, как звонящий передумал. После
  исходящего его не было. Это знак перестать звонить.
- **165** — запись в истории звонков после каждого звонка:
  ```json
  {"action": "ADD", "callHistorySync": <n>, "prevCallHistorySync": <n>,
   "callHistoryItems": [{"historyId": <n>, "callId": "<uuid>", "callerId": <n>, "messageId": <n>,
     "chatId": <n>, "callType": "AUDIO", "hangupType": "HUNGUP"|"REJECTED"|"CANCELED", "time": <n>, "durationMs": <n>}]}
  ```
  Кроме неё в чат приходит сообщение с вложением `_type: "CALL"`, которое
  PyMax разбирает (`CallAttachment`) **[код]**.

### 2.4. Опкод 158 и API `calls.okcdn.ru`

MAX Desktop берёт токен 158 сразу после пуша 137 **[захват]**:
`{"userId": <наш id в MAX>}` → `{"token", "token_lifetime_ts", "token_refresh_ts"}`.
С ним движок входит в API звонков:
`GET https://calls.okcdn.ru/api/auth/anonymLogin?application_key=…&session_data={"version":3,"client_version":1,"auth_token":"<токен 158>","device_id":"<…>"}`
→ `{api_server, external_user_id, session_key, session_secret_key, uid}`.
Сессию он держит для `/api/vchat/clientStats` (статистика во время звонка),
`/api/system/getInfo` и `/api/settings/get`. Сигнальному сокету она не
нужна: ему хватает токена из 78 или `vcp`. Поэтому нашему клиенту API не
нужен **[вывод]**.

Запасной путь без опкода 78 (так звонит maxcalls): `POST
https://calls.okcdn.ru/fb.do` с `method=auth.anonymLogin` (у веба
`client_type: "SDK_JS"`, `client_version: 1.1`), затем
`vchat.startConversation` (`conversationId`, `isVideo=false`,
`protocolVersion=5`, `externalIds=<id в MAX>`). Ответ даёт `endpoint`,
`token`, `turn_server`, `stun_server`. Подписи `sig` нет. По max-api-docs
запись звонка в чате при этом не появляется. Коды ошибок: 102/103/104 —
войти заново, 1102 CALLEE_IS_OFFLINE, 1103 NOT_FRIENDS, 1113
CALLER_IS_REJECTED, 1114 `obsolete_client*`. **[код]**

### 2.5. Опкод 167

avenarius кладёт трубку и отклоняет звонок опкодом 167 `{conversationId,
reason, peerId: "<id собеседника строкой>", internalParams}`. MAX Desktop
его не шлёт: во всех четырёх звонках он кончал звонок только командой
`hangup` в сигнальном сокете, и сервер MAX сам записывал итог (121, 165).
Для 1:1 нам хватит `hangup` **[захват, вывод]**.

## 3. Сигнальный сокет

### 3.1. Адрес

- Исходящий: `endpoint` из ответа 78 (в нём уже `userId`, `entityType`,
  `conversationId`, `token`).
- Входящий: `<wse>?userId=<trnu после последнего «:»>&entityType=USER&deviceIdx=0&conversationId=<id>&token=<tkn>`.

Параметры клиента добавляются к адресу. **[захват]** MAX Desktop:
```
appVersion=26.36.0&capabilities=3C03F&clientType=one_me&device=elementary+OS+8&locale=en&platform=DESKTOP&tgt=accept
```
У исходящего `tgt` нет. Веб-клиент по SDK и OpenFlux **[код]**:
```
platform=WEB&appVersion=1.1&version=5&device=browser&capabilities=2A03F&clientType=ONE_ME&tgt=start|accept
```
Без `appVersion` сервер отвечает «Parameter appVersion is required». При
переподключении `tgt=retry`, `recoverTs=<последний stamp>`, `peerId=<наш>`, а
адрес — `endpoint` из последнего `connection`. Нам подражать вебу: сессия у нас
веб **[вывод]**, а точный набор параметров **[проверить]**.

Простой WebSocket без подпротокола. Вебу нужны заголовки `Origin:
https://web.max.ru` и браузерный User-Agent **[вывод]**.

### 3.2. Кадры **[захват, код]**

- Клиент: `{"command": "<имя>", "sequence": n, …}`. `sequence` с 1, +1 на
  каждую команду в этом сокете.
- Сервер:
  - `{"type": "response", "response": "<команда>", "sequence": n, "stamp": …}`;
  - `{"type": "error", "sequence"?, "error"|"message", "errorCode"?, "reason"?}`;
  - `{"type": "notification", "notification": "<имя>", "stamp": …, …}`.
- Сервер шлёт текст `ping`, отвечать текстом `pong`, иначе сокет закроют
  через секунды. SDK переподключается, если 15 с не было ничего, и ждёт
  ответ на команду 10 с.
- Ошибки: `conversation-ended`, `invalid-token`, `participant-not-found`,
  `illegal-participant-state`, `service-unavailable`, `gen.obsoleteClient`.
- `participantId` — id участника в сигнализации, не id в MAX. Всегда идёт с
  `participantType: "USER"`, и с `deviceIdx`, если тот не 0. `peerId`
  собеседника — `{"id", "type": "WEB_TRANSPORT"}`.

### 3.3. Команды **[захват]**

| Команда | Тело | Когда |
|---|---|---|
| `change-media-settings` | `{mediaSettings}` | сразу после `connection`, после ответа, при выключении микрофона |
| `change-participant-state` | `{participantState: {state: {}}}` | сразу после `connection` (MAX Desktop; веб **[проверить]**) |
| `accept-call` | `{mediaSettings}` | ответить. Ответ сервера: `participantIds`, `participantTypes`, `participantDeviceIdxs` |
| `transmit-data` (SDP) | `{participantId, participantType: "USER", data: {sdp: {type, sdp, p2pRelay?}}}` | offer или answer. В answer MAX Desktop ставит `p2pRelay: true`, как в offer собеседника |
| `transmit-data` (ICE) | `{participantId, participantType: "USER", data: {candidate: {candidate, sdpMid, sdpMLineIndex}}}` | каждый кандидат отдельно; `usernameFragment` можно не слать |
| `hangup` | `{reason: "HUNGUP"\|"REJECTED"\|"CANCELED"}` | конец разговора, отказ, ответ на отмену |
| `update-media-modifiers` | `{mediaModifiers: {denoise, denoiseAnn}}` | шумоподавление на сервере; можно не слать **[вывод]** |
| `custom-data` | `{data: {sdk: {rtt, loss}}}` | отчёт о сети раз в 2 с; можно не слать **[вывод]** |
| `update-display-layout`, `enable-feature-for-roles` | | для видео и групп, не нужны |

`mediaSettings` для голоса:
```json
{"isAudioEnabled": true, "isVideoEnabled": false, "isScreenSharingEnabled": false,
 "isFastScreenSharingEnabled": false, "isAudioSharingEnabled": false}
```
MAX Desktop шлёт `accept-call` с `isAudioEnabled: false` и включает
микрофон следующим `change-media-settings`. `switch-topology` не было ни
разу.

### 3.4. Уведомления **[захват]**

| Уведомление | Поля | Смысл |
|---|---|---|
| `connection` | `peerId{id}`, `endpoint`, `conversationParams{turn, stun, serverTime, activityTimeout}`, `conversation{id, state: "ACTIVE", topology: "DIRECT", clientType, participants[…], participantsLimit, features, options}`, `isConcurrent`, `mediaModifiers` | первый кадр |
| `settings-update` | настройки видео и сети | сразу за `connection`, для голоса не нужен |
| `registered-peer` | `participantId`, `participantType`, `peerId`, `platform: "ANDROID"`, `clientType: "ONE_ME"` | устройство собеседника на связи (у него звонит) |
| `accepted-call` | `participantId`, `peerId`, `mediaSettings`, `capabilities: "3c03f"` | собеседник ответил |
| `transmitted-data` | `participantId`, `peerId`, `data{sdp{type, sdp, p2pRelay}, capabilities: "1"}` или `data{candidate{candidate, sdpMid, sdpMLineIndex, usernameFragment}}` | SDP и ICE собеседника |
| `media-settings-changed` | `participantId`, `mediaSettings` | собеседник включил или выключил микрофон |
| `hungup` | `participantId`, `externalId{type, id}`, `reason`, `deviceCount`, `traceId`, `markers` | собеседник ушёл или передумал |
| `closed-conversation` | `reason` | звонок окончен |
| `feature-set-changed`, `features-per-role-changed` | | не нужны |

Участник в `participants`: `{id, externalId{type: "ONE_ME", id: "<id в MAX>"},
state: "CALLED"|"ACCEPTED", roles: ["CREATOR"]?, mediaSettings, sessionState,
peerId, …}`. У входящего звонящий уже `ACCEPTED` и `CREATOR`, а мы `CALLED`.

## 4. Порядок звонка

### 4.1. Входящий **[захват]**

```
сокет MAX:  ← 137 {vcp, conversationId, callerId, type}
            (MAX Desktop: → 158 и anonymLogin — нам не нужно)
ws2 (tgt=accept), сразу, пока звонит:
            ← connection, settings-update
            ← transmitted-data: offer звонящего и его кандидаты — ещё ДО ответа
            → change-media-settings, change-participant-state
            ← registered-peer
по кнопке «Ответить» (здесь через 10 с):
            → accept-call {mediaSettings}
            → transmit-data answer, затем свои кандидаты
            → change-media-settings {isAudioEnabled: true}
            ICE соединяется за 0,3 с
сокет MAX:  ← 120
            … разговор …
звонящий кладёт:  ← hungup {reason: HUNGUP}, closed-conversation
мы кладём:        → hangup {reason: "HUNGUP"}
сокет MAX:  ← 121, 165 {hangupType: "HUNGUP"}
```

- **Отклонить:** `hangup {reason: "REJECTED"}` в уже открытом сокете. Сервер
  MAX отвечает 121 и 165 `REJECTED`.
- **Звонящий передумал:** `hungup {reason: "CANCELED"}` и
  `closed-conversation {reason: "CANCELED"}`. MAX Desktop отвечает
  `hangup CANCELED`, сервер MAX шлёт 121 и 165 `CANCELED`. Значит,
  отвечающий узнаёт об отмене и по сокету звонка, и по сокету MAX.
- Если звонков уже два или идёт другой, SDK отвечает `hangup {reason: "BUSY"}` **[код]**.

### 4.2. Исходящий **[захват]**

```
сокет MAX:  → 78 {conversationId, calleeIds, isVideo:false, internalParams}
            ← internalCallerParams (0,1 с)
ws2 (endpoint + параметры клиента):
            ← connection, settings-update
            → change-media-settings, change-participant-state, update-media-modifiers
            ← registered-peer       (0,3 с: у собеседника звонит)
            ← accepted-call         (собеседник ответил, здесь через 4 с)
            → transmit-data offer, затем свои кандидаты
            ← transmitted-data answer и кандидаты собеседника
            ICE соединяется за 1 с
            … разговор …
            → hangup {reason: "HUNGUP"}  (до ответа — "CANCELED")
сокет MAX:  ← 165 {hangupType: "HUNGUP"}
```

MAX Desktop шлёт offer после `accepted-call`, как avenarius. SDK шлёт его
сразу после `connection`, и сервер держит offer до ответа (так телефон
поступил во входящем). Работают оба способа; берём способ MAX Desktop.

### 4.3. Причины конца

`HUNGUP` (разговор был), `CANCELED` (звонящий до ответа), `REJECTED`
(отклонён), `MISSED`, `BUSY`. Полный список SDK: CANCELED, REJECTED, REMOVED,
HUNGUP, MISSED, BUSY, FAILED, NETWORK_ERROR, KILLED, BANNED, HAS_ACTIVE_CALL,
CALLER_IS_BLOCKED, NOT_FRIENDS, CALLEE_IS_OFFLINE, CALLEE_UNAVAILABLE,
CALLER_IS_REJECTED, SERVICE_UNAVAILABLE, SOCKET_CLOSED, ENDED, ANOTHER_DEVICE,
NOT_FOUND, TIMEOUT, CALL_TIMEOUT, OBSOLETE_CLIENT и другие.

### 4.4. Медиа **[захват]**

- **Топология** — `DIRECT` во всех звонках: одно WebRTC-соединение,
  offer/answer и ICE через `transmit-data`.
- **Ретранслятор OK вместо собеседника.** В SDP собеседника стоит
  `p2pRelay: true`. Его кандидаты типа `host` указывают на серверы OK (та же
  сеть, что у TURN и ws2), а не на телефон. Наша сторона выбрала свой `srflx`
  и UDP. Значит, голос идёт через ретранслятор OK, а по протоколу это
  обычный P2P. Для `webrtcbin` ничего особого не нужно.
- **ICE.** Серверы приходят из 78 (`turn`, `stun`), из `vcp`
  (`trne/trnu/trnp/stne`) и в `connection.conversationParams`. TURN на порту
  19302. Если `p2p_forbidden`, SDK ставит политику `relay` **[код]**.
  Кандидаты собеседника приходят раньше ответа: копить и применить после
  `set-remote-description`. ICE с `trickle renomination`.
- **SDP телефона** (offer и answer):
  - `a=group:BUNDLE 0 1`, `a=rtcp-mux`, `UDP/TLS/RTP/SAVPF`;
  - **m=audio**: PT 63 `red/48000/2` (`fmtp 111/111`) первым, PT 111
    `opus/48000/2` с `minptime=10;useinbandfec=1;dred=100;usedtx=1`,
    `transport-cc`;
  - **m=video всегда есть**, `sendrecv`, даже в голосовом звонке;
  - расширения RTP: `ssrc-audio-level`, `abs-send-time`,
    `transport-wide-cc`, `sdes:mid`;
  - **в offer `a=setup:passive`**, а не обычный `actpass`: DTLS-клиентом
    должен стать отвечающий (`a=setup:active` в answer MAX Desktop).
- **SDP MAX Desktop**: в offer Opus 111 первым, RED 63, `telephone-event`
  110, `maxaveragebitrate=64000`, `a=setup:actpass`, m=video тоже есть.
- **Переход на сервер** (`switch-topology SERVER`, SFU с каналами данных)
  не встретился. SDK делает его, если DIRECT не соединился за 5 с **[код]**.
  Мы его не делаем: на `topology-changed SERVER` кладём трубку с понятным
  сообщением **[вывод]**.

### 4.5. На `webrtcbin` **[вывод]**

- `bundle-policy=max-bundle`; `stun-server`; `add-turn-server` на каждый
  TURN. В имени TURN есть `:`, пароль в base64: в `turn://user:pass@host:port`
  их кодировать процентами.
- Входящий: `set-remote-description(offer)`. m=video принять как
  `inactive` (или трансивер `recvonly` без вывода). Дальше `create-answer`,
  `set-local-description` и `transmit-data`. Справится ли `webrtcbin` с
  `a=setup:passive` в offer и ответит ли `active`, **[проверить]** первым
  делом.
- Исходящий: трансивер аудио `sendrecv` (Opus 111) и трансивер видео
  `inactive`, затем `create-offer` и `transmit-data`; ответ —
  `set-remote-description`. Примет ли телефон offer без m=video,
  **[проверить]**; надёжнее держать m=video, как все официальные клиенты.
- RED можно не предлагать: Opus без RED собеседник примет **[проверить]**.
- Сокет ws2 — задача asyncio в потоке `Backend` (пакет `websockets` уже есть
  у PyMax). Сигналы `webrtcbin` из потоков GStreamer передавать в этот цикл
  через `call_soon_threadsafe`.

## 5. web.max.ru и MAX Desktop

| | web.max.ru | MAX Desktop 26.36 |
|---|---|---|
| Движок | `@vkontakte/calls-sdk` (JS, GPL-3.0), WebRTC браузера | `max-service`: SDK звонков VK на C++ поверх Google libwebrtc (Opus 1.5.2, libvpx, OpenH264, AV1, libsrtp2, OpenSSL 3.5) |
| Связь с MAX | SDK в той же странице, звонок через опкод 78 (`fastStart`) | Qt-приложение `max` говорит с MAX сам, а с движком — по gRPC на локальном порту (`--rpc-port`, `com.vk.calls.sdk.v1.CallAgent`: `NewCall`, `ProcessIncomingCall`, `EndCall`, `SetupDataChannel`…). Токен 158 приложение отдаёт движку (`NeedCallToken` → `CallToken`) |
| `platform`, ключ | `WEB`, `CNHIJPLGDIHBABABA` | `DESKTOP`, `CHFNKILGDIHBABABA` |
| `capabilities` | `2A03F` | `3C03F` (в одном звонке `C03F`) |
| API звонков | `https://calls.okcdn.ru/fb.do` | `https://calls.okcdn.ru/api/…` |
| Сигнализация | те же команды и уведомления | те же **[захват]** |

Сервис один, у клиентов разные типы и ключи. Наш клиент подражает
веб-клиенту. MAX для Android в захвате: `platform: "ANDROID"`,
`capabilities: "3c03f"`.

## 6. Проверки клиента

- `appVersion` в адресе ws2 обязателен; устаревший клиент получает
  `gen.obsoleteClient` или ошибку API 1114 `obsolete_client*` **[код]**.
- Значения берём как у веб-клиента (`WEB`, ключ веба) и не придумываем
  своих **[вывод]**.
- Доходит ли пуш 137 до нашей сессии PyMax, **[проверить]**. max-api-docs пишет,
  что вторая сессия с новым `deviceId` его не получала, пока не взяла
  `deviceId` браузера. Там же упомянута подписка `CHAT_SUBSCRIBE` (75). Наша
  сессия — основной вход по QR со своим `deviceId`. В захвате MAX Desktop
  шлёт 75 `{chatId, subscribe: true}`, когда открывает чат, а не ради
  звонков. 137 он получил и без этого.
- Правило проекта о правилах MAX: звонки — обычная функция человека.
  Никаких звонков без нажатия человека, никаких повторов и обзвонов.
  Большинство открытых проектов вокруг этого протокола — туннели через TURN;
  MAX может замечать странные звонки.

## 7. Открытые вопросы

1. Приходит ли 137 нашей сессии PyMax.
2. Точные `sdkVersion`, `capabilities` и параметры ws2 у web.max.ru сегодня.
3. Как `webrtcbin` отвечает на offer с `a=setup:passive`.
4. Примет ли телефон наш offer без m=video и без RED.
5. Звонки с iPhone и с web.max.ru: тоже ли DIRECT через ретранслятор.

## 8. План захвата

Есть два аккаунта: один в MAX Desktop на ПК, другой на телефоне. Ни записи,
ни их куски с токенами, номерами, id и адресами в репозиторий не попадают:
всё лежит в `scratchpad` сеанса, в документ идут только формы (ключи и
типы).

1. **MAX Desktop ↔ телефон — сделано 21 октября.** Журналы
   `~/.local/share/ONEME/logs/` (пакеты MAX) и
   `~/.local/share/ONEME/calls/calls-settings/log.txt` (движок: команды ws2,
   SDP, ICE, статистика) уже при обычном уровне журнала показывают всё нужное.
2. **Вопросы 1, 3 и 4 — на шаге 4 плана.** Отдельного пробного клиента не
   будет: звонок сразу делается в мессенджере (кнопка «Ответить», тесты,
   ревью). Первый живой звонок через него на этих двух аккаунтах и ответит
   на них. Начать с входящего: доходит ли 137 и принимает ли телефон наш
   answer на offer с `a=setup:passive`.
3. **web.max.ru в DevTools** (вопрос 2) — только если параметры веба не
   подойдут: нужен вход аккаунтом ПК в браузере.

## Источники

- Захват 21 октября 2026: MAX Desktop 26.36 ↔ MAX для Android, журналы
  MAX Desktop (`~/.local/share/ONEME/logs/`, `calls/calls-settings/log.txt`).
- `@vkontakte/calls-sdk` 2.8.12, npm, GPL-3.0: `calls-sdk.esm.js` (REST,
  сигнализация, топологии, правка SDP).
- PyMax 2.4.1 (`pymax/protocol/enums.py`, `types/domain/attachments/call.py`).
- [eizemazal/avenarius](https://github.com/eizemazal/avenarius), Kotlin,
  GPL-3.0: работающие звонки 1:1, опкоды 78 и 167, записи настоящих звонков
  в тестах (`CallSetupParserTest.kt`, `CallSession.kt`, `MaxClient.kt`).
- [icyfalc0n/maxcalls](https://github.com/icyfalc0n/maxcalls), Go, GPL-3.0:
  HTTP-путь, разбор `vcp`. Медиа не делает: это туннель на голом ICE со
  своими сообщениями, с официальным клиентом не говорит.
- [p1neappleXpress/OpenFlux](https://github.com/p1neappleXpress/OpenFlux):
  `internalParams` веб-клиента для 78, адрес отвечающего из `vcp`.
- [pr0bel1230/max-api-docs](https://github.com/pr0bel1230/max-api-docs)
  `protocol/calls.md`: кадры ws2 из HAR. Неверны разделы о `vcp` и о том,
  что 78 не начинает звонок.
- MAX Desktop 26.36, статический разбор `/usr/share/max`: `max-service`,
  `libcall-service.so` (вшитая схема `vk-call-service.proto`), `libcore.so`.
