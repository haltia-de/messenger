# Звонки MAX: как они устроены

Шаг 3 [плана звонков](https://github.com/haltia-de/haltia/blob/main/docs/plans/calls.md),
Issue #5. Документ нужен, чтобы сделать голосовой звонок 1:1, входящий и
исходящий: сигнализацию на Python, медиа на GStreamer `webrtcbin`.

**Состояние на 21 октября 2026: живых звонков ещё не было.** Документ собран из
открытого кода и из статического разбора MAX Desktop 26.36. Значения, которые
надо подтвердить захватом, помечены **[проверить]**, а план захвата — в конце.
Пометки источников:

- **[код]** — видно в коде или в записи настоящего звонка (тесты avenarius);
- **[источник]** — так пишет источник, на живом сервисе не подтверждено;
- **[вывод]** — наше заключение.

## 1. Кто с кем говорит

```
 наш клиент ──── сокет MAX (wss://api.oneme.ru/websocket, PyMax) ──── сервер MAX
    │            опкоды 158, 78, 137, 167, 128
    │
    ├── HTTPS https://calls.okcdn.ru/fb.do (OK vchat API) — только запасной путь
    │
    ├── сигнальный WebSocket wss://videowebrtc.okcdn.ru/ws2?… (JSON-команды OK Calls)
    │
    └── медиа WebRTC: ICE (STUN/TURN OK), DTLS-SRTP, Opus
```

Звонки MAX работают на инфраструктуре звонков VK/OK. Сервер MAX выдаёт
параметры звонка (адрес сигнального сокета, токен, TURN/STUN) и доставляет
входящий звонок пушем. Дальше клиент говорит с сервером звонков OK
по его протоколу, тому же, что у SDK `@vkontakte/calls-sdk` в web.max.ru и у
движка `max-service` в MAX Desktop. **[код]**

## 2. Команды сокета MAX

Номера — из перечня PyMax 2.4.1 и из `libcore.so` MAX Desktop (там они
`CommonPacket<OpCode=N, Calls::…>`). PyMax их знает, но не использует:
модели и обработчиков нет, 137 доходит только до обработчиков сырых кадров
(`client.on_raw`), запросы — `client._app.invoke(opcode, payload)`. **[код]**

| Опкод | Имя | Зачем |
|---|---|---|
| 78 | `VIDEO_CHAT_START_ACTIVE` | начать звонок 1:1 (исходящий) |
| 137 | `NOTIF_CALL_START` | пуш входящего звонка |
| 167 | (нет в PyMax) `VIDEO_CHAT_HANGUP` | положить трубку, отклонить |
| 158 | `CALLS_TOKEN` | токен для HTTP-пути (запасной) |
| 128 | `NOTIF_MESSAGE` | после звонка сервер пишет в чат сообщение `_type: "CALL"` |
| 79 | `VIDEO_CHAT_HISTORY` | история звонков `{chatId, count, marker?, direction?}` **[источник]** |
| 76, 84, 103, 166, 195, 69 | старт, ссылка, входящие, вход, участники, правка | для 1:1 не нужны |

### 2.1. Опкод 78: исходящий звонок **[код]**

Запрос:
```json
{"conversationId": "<новый uuid4>", "calleeIds": [<id собеседника в MAX>],
 "internalParams": "<строка JSON>", "isVideo": false}
```

`internalParams` веб-клиента (OpenFlux; совпадает с `fastStart` SDK 2.8.x):
```json
{"deviceId": "<deviceId нашей сессии MAX>", "sdkVersion": "2.8.9",
 "clientAppKey": "CNHIJPLGDIHBABABA", "platform": "WEB", "protocolVersion": 5,
 "domainId": "", "capabilities": "2A03F"}
```
`CNHIJPLGDIHBABABA` — открытый ключ приложения звонков веб-клиента MAX. Он
лежит в коде web.max.ru и в нескольких открытых проектах. Это не секрет
аккаунта. У Android свой ключ, `platform: "ANDROID"` и `capabilities: "3c03f"`. Мы ходим
в MAX как веб-клиент (PyMax, `deviceType: WEB`), значит, и параметры берём
веб-клиента. Текущую `sdkVersion` web.max.ru (в npm уже 2.8.12) **[проверить]**.

Ответ: `payload.internalCallerParams`, тоже строка JSON:
```json
{"id": {"internal": <наш id в сигнализации>, "external": "<наш id в MAX>"},
 "isConcurrent": false,
 "endpoint": "wss://videowebrtc.okcdn.ru/ws2?userId=<internal>&entityType=USER&conversationId=<uuid>&token=<…>",
 "wsIpAddresses": […], "wtEndpoint": "https://videowebrtc.okcdn.ru:23456/wt?…", "wtIpAddresses": […],
 "clientType": "ONE_ME",
 "turn": {"urls": ["turn:<ip>:<port>", …], "username": "<срок>:<internal>", "credential": "<base64>"},
 "stun": {"urls": ["stun:<ip>:<port>"]},
 "deviceIdx": 0}
```
Отвечающий опкод 78 не шлёт: сервер отвечает ошибкой 1114. **[источник: avenarius]**

### 2.2. Опкод 137: входящий звонок **[код]**

```json
{"vcp": "<длина>:<base64>", "conversationId": "<uuid>", "callerId": <id в MAX>,
 "type": "AUDIO" | "VIDEO", "chatId": 0, "isContact": true}
```
`cmd` у кадра бывает 0 и 1, по нему не фильтровать. MAX Desktop знает в этом
пуше ещё `sdpOffer`, `internalCallerParams` и `joinLink` (`libcore.so`). Приходят ли
они веб-сессии, **[проверить]**.

**`vcp`.** Строку делят по первому `:`. Слева длина распакованных данных,
справа base64 сырого блока LZ4 (не кадра LZ4, без заголовка). Распакованное
содержимое — JSON:

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

Проверено на записанном `vcp` из тестов avenarius: распаковалось ровно в
заявленную длину. Описание `vcp` в max-api-docs («гибрид protobuf») неверно:
это неправильно прочитанный блок LZ4. В Python — `lz4.block.decompress(data,
uncompressed_size=n)` или свой декодер на 25 строк. **[код]**

### 2.3. Опкод 167: конец звонка **[код]**

```json
{"conversationId": "<uuid>", "reason": "HUNGUP" | "CANCELED" | "REJECTED" | "MISSED",
 "peerId": "<id собеседника в MAX, строкой>", "internalParams": "<как в 78>"}
```
Без `reason` и `internalParams` сервер его молча пропускает, и у собеседника
звонок продолжается. Отклонить входящий можно одним 167 с `REJECTED`, не
открывая сигнальный сокет. **[источник: avenarius]**

После звонка сервер пишет в чат сообщение с вложением `_type: "CALL"`
(`duration` в мс, `conversationId`, `callType` AUDIO|VIDEO, `hangupType`
MISSED|REJECTED|CANCELED|HUNGUP). PyMax его разбирает (`CallAttachment`).
Если звонящий передумал до ответа, отвечающему, по avenarius, не приходит
ничего, кроме этого сообщения. Значит, звонок у нас перестаёт звонить по
сообщению CALL с тем же `conversationId` или через 60 с. **[вывод]**

### 2.4. Опкод 158 и HTTP-путь (запасной)

Опкод 158 с `{}` отвечает `{token, token_lifetime_ts, token_refresh_ts}`
(MAX Desktop называет поля `tokenHost, tokenValue, appKey, sessionInfo`). С ним:

1. `POST https://calls.okcdn.ru/fb.do`, форма: `method=auth.anonymLogin`,
   `format=JSON`, `application_key=CNHIJPLGDIHBABABA`, `session_data=` JSON
   `{"version":3,"device_id":"<uuid>","client_version":1.1,"client_type":"SDK_JS","auth_token":"<токен 158>"}`.
   Ответ: `session_key`, `session_secret_key`, `uid` (id в сигнализации),
   `external_user_id`. Подписи `sig` нет.
2. `method=vchat.startConversation`, `session_key`, `conversationId=<uuid>`,
   `isVideo=false`, `protocolVersion=5`, `externalIds=<id в MAX>`,
   `payload={"is_video":false}`. Ответ: `endpoint` (полный адрес сокета с
   токеном), `token`, `turn_server{urls,username,credential}`,
   `stun_server{urls}`, `client_type`, `device_idx`, `is_concurrent`, `p2p_forbidden`.
3. Конец: `vchat.hangupConversation` (`conversationId`, `reason`).

Так звонит maxcalls. По max-api-docs запись звонка в чате при этом не
появляется. Официальные клиенты так не звонят: MAX Desktop берёт токен 158 только
для своего движка. Нам этот путь нужен лишь на случай, если 78 откажет.

Ошибки API: `{error_code, error_msg}`; 102/103/104 — войти заново,
1102 CALLEE_IS_OFFLINE, 1103 NOT_FRIENDS, 1113 CALLER_IS_REJECTED,
1114 `obsolete_client*`. **[код: SDK]**

## 3. Сигнальный сокет

### 3.1. Адрес **[код]**

- Исходящий: `endpoint` из ответа 78 (в нём уже `userId`, `entityType`,
  `conversationId`, `token`).
- Входящий: `<wse>?userId=<trnu после последнего «:»>&entityType=USER&deviceIdx=0&conversationId=<id>&token=<tkn>`.

К обоим добавляется:
```
&platform=WEB&appVersion=1.1&version=5&device=browser&capabilities=2A03F&clientType=ONE_ME&tgt=start
```
`tgt=start` у звонящего, `tgt=accept` у отвечающего, `tgt=retry` при
переподключении (с `recoverTs=<последний stamp>` и `peerId=<наш peerId>`, а
адрес — `endpoint` из последнего `connection`). Без этих параметров сервер
отвечает «Parameter appVersion is required». Простой WebSocket без
подпротокола. Заголовки `Origin: https://web.max.ru` и браузерный User-Agent,
как у веба **[вывод]**. maxcalls шлёт `capabilities=603F`, SDK по умолчанию
`203F`, web.max.ru — `2A03F` (OpenFlux). Берём `2A03F` **[проверить]**.

### 3.2. Кадры **[код]**

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
- Идентификаторы: `participantId` — id участника в сигнализации (не id
  MAX), с `participantType: "USER"` и `deviceIdx`, если тот не 0.

### 3.3. Команды для звонка 1:1 **[код]**

| Команда | Тело | Когда |
|---|---|---|
| `accept-call` | `{mediaSettings}` | отвечающий принимает; ответ несёт `participantIds`, `participantTypes`, `participantDeviceIdxs` |
| `change-media-settings` | `{mediaSettings}` | сразу после `connection` и после `accept-call`; при выключении микрофона |
| `transmit-data` (SDP) | `{participantId, participantType: "USER", data: {sdp: {type, sdp}, animojiVersion: 1}}` | offer или answer |
| `transmit-data` (ICE) | `{participantId, participantType: "USER", data: {candidate: {candidate, sdpMid: "0", sdpMLineIndex: 0, usernameFragment}}}` | каждый кандидат отдельно |
| `hangup` | `{reason}` | конец (ответа не ждать) |
| `switch-topology` | `{topology: "SERVER", force: false}` | только если P2P не поднялся (§4.4) |

`mediaSettings` для голоса:
```json
{"isAudioEnabled": true, "isVideoEnabled": false, "isScreenSharingEnabled": false,
 "isFastScreenSharingEnabled": false, "isAudioSharingEnabled": false, "isAnimojiEnabled": false}
```
Браузер шлёт ещё `get-rooms`, `custom-data` (отчёт о плохой сети) и
`update-display-layout`. Для звонка они, похоже, не нужны **[вывод]**.

### 3.4. Уведомления **[код]**

| Уведомление | Поля | Смысл |
|---|---|---|
| `connection` | `peerId`, `endpoint`, `conversationParams{turn, stun, serverTime, activityTimeout}`, `conversation{id, state, topology, participants[{id, externalId{type: "ONE_ME", id}, state: "CALLED"\|"ACCEPTED", roles, mediaSettings}]}`, `isConcurrent`, `recoverMessages?` | первый кадр. У звонящего роль `CREATOR`; отвечающий ищет себя в `participants` со `state: "CALLED"` |
| `registered-peer` | `participantId`, `platform`, `clientType` | устройство собеседника подключилось (звонит) |
| `accepted-call` | `participantId`, `mediaSettings` | собеседник ответил. Если `participantId` — наш, ответили на другом нашем устройстве |
| `transmitted-data` | `participantId`, `data{sdp \| candidate}` | SDP и ICE собеседника; в offer бывает `data.capabilities` |
| `media-settings-changed` | `participantId`, `mediaSettings` | собеседник выключил микрофон |
| `topology-changed` | `topology`, `offerTo[]` | сервер сменил топологию |
| `hungup` | `participantId`, `reason` | собеседник ушёл |
| `closed-conversation` | `reason` | звонок окончен |
| `settings-update`, `feature-set-changed`, `features-per-role-changed`, `audio-activity`, `speaker-changed` | | для голоса не нужны |

## 4. Порядок звонка

### 4.1. Исходящий **[код: avenarius, SDK]**

```
сокет MAX:  → 78 {conversationId, calleeIds, internalParams, isVideo:false}
            ← internalCallerParams
ws2 (tgt=start):
            ← connection          (topology "DIRECT")
            → change-media-settings
            ← registered-peer     (у собеседника звонит)
            ← accepted-call       (ответил; hungup/closed-conversation — отказ)
            → transmit-data sdp offer, затем кандидаты
            ← transmitted-data answer и кандидаты
            … разговор …
конец:      → hangup {reason:"HUNGUP"}  (до ответа — "CANCELED")
сокет MAX:  → 167 {conversationId, reason, peerId, internalParams}
```

SDK шлёт offer сразу после `connection`, ещё до ответа, а сервер держит его до
`accept-call`. avenarius шлёт offer после `accepted-call`. Работают оба.
Начинаем с варианта avenarius: он проверен с официальными клиентами **[вывод]**.
На новый offer собеседника (renegotiation) отвечаем answer.

### 4.2. Входящий **[код: avenarius, SDK, HAR из max-api-docs]**

```
сокет MAX:  ← 137 {vcp, conversationId, callerId, type}
            отказ: → 167 {…, reason:"REJECTED"} — и всё
ответ:      распаковать vcp
ws2 (tgt=accept):
            ← connection
            → accept-call {mediaSettings}
            → change-media-settings
            ← transmitted-data offer звонящего, кандидаты
            → transmit-data answer, затем кандидаты
            … разговор …
конец:      → hangup {reason:"HUNGUP"}, → 167
```

Сокет можно открыть сразу по пушу, пока звонит (SDK так и делает), и слать
`accept-call` по кнопке «Ответить». Так ответ быстрее. Если звонков уже два
или идёт другой, SDK отвечает `hangup {reason: "BUSY"}`.

### 4.3. Причины конца

`HUNGUP` (разговор был), `CANCELED` (звонящий до ответа), `REJECTED`
(отклонён), `MISSED`, `BUSY`. Полный список SDK: CANCELED, REJECTED, REMOVED,
HUNGUP, MISSED, BUSY, FAILED, NETWORK_ERROR, KILLED, BANNED, HAS_ACTIVE_CALL,
CALLER_IS_BLOCKED, NOT_FRIENDS, CALLEE_IS_OFFLINE, CALLEE_UNAVAILABLE,
CALLER_IS_REJECTED, SERVICE_UNAVAILABLE, SOCKET_CLOSED, ENDED, ANOTHER_DEVICE,
NOT_FOUND, TIMEOUT, CALL_TIMEOUT, OBSOLETE_CLIENT и другие.

### 4.4. Медиа

- **Топология.** Для 1:1 по умолчанию `DIRECT`: одно WebRTC-соединение с
  собеседником, offer/answer и ICE через `transmit-data`. Кандидаты
  собеседника в записанном звонке — адреса оператора, и в ответах бывает
  `p2p_forbidden`. Значит, голос, скорее всего, идёт через TURN OK, а не
  напрямую. Для нас это одно и то же: ICE выберет путь сам **[вывод]**.
- **ICE.** Серверы приходят из 78 (`turn`, `stun`), из `vcp`
  (`trne/trnu/trnp/stne`) или из `connection.conversationParams`. SDK
  добавляет копию последнего TURN-адреса с `?transport=tcp`. Если
  `p2p_forbidden`, политика `relay`. Кандидаты собеседника, пришедшие до
  remote description, копить и применить после. **[код]**
- **SDP.** Unified plan, `a=group:BUNDLE`, rtcp-mux, DTLS-SRTP (обычные).
  Offer SDK всегда несёт m=audio и m=video. SDK вырезает из своего SDP G722,
  PCMU, PCMA, CN и telephone-event, ставит RED первым и добавляет
  `a=rtcp-fb:111 nack`. fmtp Opus не трогает. У браузера Opus виден с
  `minptime=10;useinbandfec=…;usedtx=1`. Своих RTP-расширений нет. **[код]**
- **Переход на сервер.** Если DIRECT не соединился за 5 с (или ICE restart
  не помог за 20 с), ведущий шлёт `switch-topology SERVER`. Тогда звонок
  идёт через SFU (`allocate-consumer`, `producer-updated`, `accept-producer`,
  каналы данных с двоичным протоколом). Этого режима мы не делаем:
  `switch-topology` не шлём, а на `topology-changed SERVER` кладём трубку
  с понятным сообщением **[вывод]**.

### 4.5. На `webrtcbin` **[вывод]**

- `bundle-policy=max-bundle`; `stun-server`; `add-turn-server` на каждый TURN.
  В имени TURN есть `:`, пароль в base64: в `turn://user:pass@host:port` их
  кодировать процентами.
- Входящий: `set-remote-description(offer)`. На m=video ответить
  `inactive` (или трансивер `recvonly` без вывода). Дальше `create-answer`,
  `set-local-description`, `transmit-data`; кандидаты из `on-ice-candidate` с
  `usernameFragment` из своего SDP.
- Исходящий: аудиотрансивер `sendrecv` (Opus, PT как у браузера, 111) и
  видеотрансивер `inactive`, если сервер требует m=video **[проверить]**;
  `create-offer`, `transmit-data`; ответ — `set-remote-description`.
- Сокет ws2 — задача asyncio в потоке `Backend` (пакет `websockets` уже есть
  у PyMax). Сигналы `webrtcbin` из потоков GStreamer передавать в этот цикл
  через `call_soon_threadsafe`.

## 5. web.max.ru и MAX Desktop

| | web.max.ru | MAX Desktop 26.36 |
|---|---|---|
| Движок | `@vkontakte/calls-sdk` (JS, GPL-3.0), WebRTC браузера | `max-service`: VK Calls SDK на C++ поверх Google libwebrtc (Opus 1.5.2, libvpx, OpenH264, AV1, libsrtp2, OpenSSL 3.5) |
| Связь с MAX | SDK в той же странице, `fastStart` через опкод 78 | Qt-приложение `max` говорит с MAX и с движком по gRPC на локальном порту (`--rpc-port`, `com.vk.calls.sdk.v1.CallAgent`: `NewCall`, `ProcessIncomingCall`, `EndCall`, `SetupDataChannel`…); токен 158 приложение отдаёт движку (`NeedCallToken` → `CallToken`) |
| API звонков | `https://calls.okcdn.ru/fb.do` | `https://calls.okcdn.ru/api/vchat/…`, `/api/auth/anonymLogin` |
| Тип клиента | `platform=WEB`, `clientType=ONE_ME`, `client_type=SDK_JS` | `ok.desktop.apps.video`, `ONE_ME` |
| Сигнализация, команды | те же: `accept-call`, `transmit-data`, `hangup`, `switch-topology`, `allocate-consumer`… | те же (строки `calls::signaling::WebSocketClient`) |

Сервис один, у клиентов разные типы. Наш клиент подражает веб-клиенту:
сессия MAX у него и так веб. Как MAX Desktop запускает исходящий (опкод 78
или REST движка), **[проверить]** захватом. **[код: строки и схема protobuf
из `libcall-service.so`; вывод о совместимости]**

## 6. Проверки клиента

- `appVersion`, `version`, `platform`, `capabilities` в адресе ws2
  обязательны. Устаревший клиент получает `gen.obsoleteClient` или API 1114
  `obsolete_client*`. **[код]**
- Значения берём как у веб-клиента (`WEB`, `browser`, `ONE_ME`, ключ веба)
  и не придумываем своих. **[вывод]**
- Доходит ли пуш 137 до нашей сессии, **[проверить]**. max-api-docs пишет,
  что вторая сессия с новым `deviceId` его не получала, пока не взяла
  `deviceId` браузера, и упоминает подписку `CHAT_SUBSCRIBE` (75). Наша
  сессия — основной вход по QR, у неё свой `deviceId`. avenarius и OpenFlux
  подписок не делают.
- Правило проекта о правилах MAX: звонки — обычная функция человека.
  Никаких звонков без нажатия человека, никаких повторов и обзвонов.
  Большинство открытых проектов вокруг этого протокола — туннели через TURN;
  MAX может замечать странные звонки.

## 7. Открытые вопросы

1. Приходит ли 137 нашей сессии PyMax; что в нём кроме `vcp`.
2. Какие `sdkVersion` и `capabilities` шлёт web.max.ru сегодня.
3. Нужна ли в offer линия m=video; что сервер делает с offer только с голосом.
4. Сколько ждать `registered-peer` и `accepted-call`; приходит ли что-нибудь
   отвечающему, если звонящий передумал.
5. Идёт ли звонок с MAX Desktop и с телефоном в DIRECT; бывает ли сразу SERVER.
6. Какой Opus (fmtp) у телефонов и MAX Desktop.

## 8. План захвата

Нужен человек: **два тестовых аккаунта MAX** (A и B) и телефон с MAX на
одном из них. Аккаунт отца не трогаем. Ни записи, ни их куски с токенами,
номерами, id и адресами в репозиторий не попадают: всё лежит в
`scratchpad` сеанса, в документ идут только формы (ключи и типы).

**1. web.max.ru в Chrome DevTools (MCP), аккаунт A.**
- Вкладка Network, фильтр WS: сокет MAX (кадры 78, 137, 158, 167, 128) и
  сокет `ws2` (все команды и уведомления, SDP целиком).
- `chrome://webrtc-internals`: выбранная пара кандидатов, кодек, fmtp,
  relay ли.
- Сценарии:
  1. A звонит B (B на телефоне), B отвечает, разговор 20 с, A кладёт.
  2. B звонит A, A отвечает.
  3. B звонит A, A отклоняет.
  4. B звонит A и передумывает до ответа.
  5. A звонит B, B не отвечает.
  6. Во время 2 A выключает микрофон.
- Отдельно: `sdkVersion`, `capabilities`, `platform`, `clientType` из
  `internalParams` и из адреса ws2.

**2. MAX Desktop на ПК, аккаунт B.** Без вмешательства в процесс:
- журнал пакетов `~/.local/share/ONEME/logs/log_*.txt` (158, 137, 78, 167 с
  полями; токены он сам маскирует);
- свой журнал движка `~/.local/share/ONEME/calls/calls-settings/oneme/logs/`;
  перед звонком поднять в настройках движка `sdkLogLevel`/`webrtcLogLevel` до
  `debug`. `disableLogFilter` не включать: он снимает маскировку токенов.
- Сценарии 1–5 между web.max.ru (A) и MAX Desktop (B): звонок между двумя
  разными движками показывает, сходятся ли они в DIRECT.
- mitmproxy на `calls.okcdn.ru` и `videowebrtc.okcdn.ru` — только если журналов
  не хватит. Движок проверяет сертификаты по системному хранилищу без
  закрепления; есть ключи `sslVerifyCallsApi`/`sslVerifySignaling`.

**3. Наш клиент без медиа, аккаунт A.** Маленький сценарий на PyMax в
`scratchpad`: войти существующей сессией из Vault, ждать 137, распаковать
`vcp`, открыть ws2 с `tgt=accept`, сделать `accept-call` и записать offer.
Затем отклонить через 167. Так проверяются вопросы 1, 3 и 4 без медиа.

После захвата: убрать **[проверить]** из документа и сверить формы в §2–§4.
Дальше шаг 4 плана — звонок на ПК через `webrtcbin`.

## Источники

- `@vkontakte/calls-sdk` 2.8.12, npm, GPL-3.0: `calls-sdk.esm.js` (REST,
  сигнализация, топологии, правка SDP).
- PyMax 2.4.1 (`pymax/protocol/enums.py`, `types/domain/attachments/call.py`).
- [eizemazal/avenarius](https://github.com/eizemazal/avenarius), Kotlin,
  GPL-3.0: работающие звонки 1:1, опкоды 78 и 167, записи настоящих звонков
  в тестах (`CallSetupParserTest.kt`, `CallSession.kt`, `MaxClient.kt`).
- [icyfalc0n/maxcalls](https://github.com/icyfalc0n/maxcalls), Go,
  GPL-3.0: HTTP-путь, разбор `vcp`. Медиа не делает: это туннель на голом ICE
  со своими сообщениями, с официальным клиентом не говорит.
- [p1neappleXpress/OpenFlux](https://github.com/p1neappleXpress/OpenFlux):
  `internalParams` веб-клиента для 78, адрес отвечающего из `vcp`.
- [pr0bel1230/max-api-docs](https://github.com/pr0bel1230/max-api-docs)
  `protocol/calls.md`: кадры ws2 из HAR. Неверны разделы о `vcp` и о том,
  что 78 не начинает звонок.
- MAX Desktop 26.36, статический разбор `/usr/share/max`: `max-service`,
  `libcall-service.so` (вшитая схема `vk-call-service.proto`), `libcore.so`.
