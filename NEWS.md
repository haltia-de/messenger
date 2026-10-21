# Что нового · What's new

## 2.7.0 (2026-10-21)

### Русский

Теперь можно звонить контактам MAX. Входящий звонок звучит и будит экран планшета; ответить можно одной большой кнопкой. Перед исходящим звонком программа спрашивает «Позвонить …?».

Во время разговора голос собеседника слышен через динамик, а эхо на планшете подавляется. Планшет не засыпает до конца звонка.

Второй звонок во время разговора получает ответ «занято». При выходе из программы звонок завершается правильно.

Звонки доступны только там, где установлены нужные компоненты GStreamer.

### English

You can now make voice calls to MAX contacts. An incoming call rings and wakes the tablet’s screen; one big button answers it. Before calling a contact, the program asks «Позвонить …?» (Call …?).

During a call, the other person’s voice comes through the speaker and echo is suppressed on the tablet. The tablet stays awake until the call ends.

A second call during a conversation gets a busy answer. Quitting the program ends the call properly.

Calls are available only where the needed GStreamer components are installed.

The licence is now GPL-3.0-or-later.

## 2.6.1 (2026-10-20)

### Русский

- При входе в чат или канал экранная клавиатура больше не выскакивает сама: она появляется, когда вы касаетесь поля ввода.

### English

- Opening a chat or a channel no longer brings up the on-screen keyboard by itself: it comes when you tap the entry.

## 2.6.0 (2026-10-20)

### Русский

- Фото и голосовые снова уходят в MAX: MAX изменил способ загрузки, и программа теперь загружает их так же, как его собственное приложение.
- Поиск находит каналы и группы по названию, как поиск в самом MAX. Найденные показаны под вашими чатами, на них можно подписаться.
- Голосовые сообщения можно выключить в настройках, тогда кнопки микрофона не будет.
- Если файл с таким именем уже есть, программа так и говорит и предлагает заменить его, сохранить рядом копию или выбрать другое имя.

### English

- Photos and voice messages reach MAX again: MAX changed how uploads work, and the program now uploads them the way MAX's own app does.
- The search finds channels and groups by name, as MAX's own search does. They are shown under your chats, ready to subscribe.
- Voice messages can be switched off in the settings, which removes the microphone button.
- When a file of the same name already exists, the program says so and offers to replace it, save a copy beside it or choose another name.

## 2.5.0 (2026-10-20)

### Русский

- Фото и файлы отправляются скрепкой слева от поля ввода: выбранные ждут над полем, у каждого свой ✕. Голосовое сообщение записывается, пока держите кнопку микрофона.
- Вход в MAX хранится в связке ключей рабочего стола. Входить заново не нужно: прежний вход переносится туда сам.
- Мессенджеры в настройках показаны карточками: у каждого переключатель, вход по QR-коду и «Выйти».
- Экспериментально: Telegram. Он выключен, пока его не включить в настройках. Чаты обоих мессенджеров идут одним списком, поиск по номеру телефона ищет в обоих.
- При отправке фото окно выбора сразу показывает фотографии.

### English

- Photos and files are sent with the paperclip left of the entry: the chosen ones wait above it, each with its ✕. A voice message records while you hold the microphone button.
- The MAX login is kept in the desktop's keyring. No need to sign in again: the old login moves there by itself.
- The settings show each messenger as a card with a switch, a QR-code sign-in and «Выйти» (sign out).
- Experimental: Telegram. It stays off until switched on in the settings. The chats of both messengers share one list, and a phone number is looked up in both.
- When attaching, the file chooser starts with the photos.

## 2.4.0 (2026-10-20)

### Русский

Быстрее и надёжнее, особенно на планшете:

- Новые сообщения и прокрутка больше не подтормаживают окно.
- Когда нет связи, это видно по жёлтой полосе; программа сама переподключается, а вы остаётесь там, где были. Неотправленное сообщение остаётся в поле ввода.
- Кнопки больше не остаются серыми навсегда после обрыва связи.
- Фото загружаются по два, сначала те, что на экране.

### English

Faster and steadier, above all on a tablet:

- New messages and scrolling no longer make the window stall.
- Without a connection a yellow bar says so; the program reconnects by itself and you stay where you were. A message that could not go out stays in the entry.
- Buttons no longer stay grey for good after a lost connection.
- Photos load a couple at a time, the ones on screen first.

## 2.3.3 (2026-10-20)

### Русский

Сообщения самого сервиса, например приветствие в Избранном, показываются словами, а не служебным ключом.

### English

Messages from the service itself, such as the welcome in Saved Messages, are shown in words instead of a technical key.

## 2.3.2 (2026-10-19)

### Русский

На обычном рабочем столе у окна снова есть кнопки окна, его можно закрыть; сообщения продолжают приходить в фоне.

### English

On an ordinary desktop the window has its window buttons again, so it can be closed; it keeps receiving messages in the background.

## 2.3.1 (2026-10-19)

### Русский

Пакеты для Debian 13 и Ubuntu 24.04 теперь есть в выпуске.

### English

Packages for Debian 13 and Ubuntu 24.04 are now part of the release.

## 2.3.0 (2026-10-19)

### Русский

- Программу можно поставить во Flatpak и пакетом для Debian 13 и Ubuntu 24.04 из репозиториев Haltia.
- QR-код для входа показывается и там, где нет библиотеки Pillow.

### English

- The program can be installed as a Flatpak and as a package for Debian 13 and Ubuntu 24.04 from Haltia's repositories.
- The login QR code is shown where the Pillow library is missing too.

## 2.2.1 (2026-10-19)

### Русский

- Пока играет голосовое сообщение, компьютер не засыпает и на обычных рабочих столах, не только на планшете.
- Во Flatpak сеанс, настройки и кэш хранятся в папке программы.

### English

- While a voice message plays, the computer does not fall asleep on ordinary desktops either, not only on the tablet.
- In Flatpak the session, settings and cache are kept in the program's own folder.

## 2.2.0 (2026-10-19)

### Русский

- Окна «Сохранить как» и «Папка для файлов» — системные: в KDE и во Flatpak открывается выбор файлов рабочего стола.
- Во Flatpak программа сама просит разрешения запускаться с сеансом и работать в фоне.

### English

- The «Save as» and «Folder for files» windows are the system's: in KDE and in Flatpak the desktop's file chooser opens.
- In Flatpak the program asks by itself for permission to start with the session and run in the background.

## 2.1.1 (2026-10-19)

## 2.1.0 (2026-10-19)

## 2.0.0 (2026-10-19)

## 1.19.1 (2026-10-19)

## 1.19.0 (2026-10-19)

## 1.18.3 (2026-10-18)

## 1.18.2 (2026-10-18)

## 1.18.1 (2026-10-18)

## 1.18 (2026-10-18)

## 1.17 (2026-10-18)

## 1.16.1 (2026-10-18)

## 1.16 (2026-10-18)
