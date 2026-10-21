# Звонки в Alpine 3.24

Проверено 2026-10-21 по официальным `APKINDEX.tar.gz` и содержимому APK
для **armv7**, ветка **v3.24**. Одного успешного импорта GstWebRTC недостаточно:
`calls_supported()` проверяет также наличие элементов и запоминает результат
до следующего запуска программы.

| Пакет | Репозиторий, версия | Содержимое для звонков |
| --- | --- | --- |
| `gstreamer` | main, 1.28.3-r0 | `Gst-1.0.typelib` |
| `gst-plugins-base` | main, 1.28.3-r0 | `GstSdp-1.0.typelib`, `libgstopus.so` (Opus), преобразование звука |
| `gst-plugins-good` | community, 1.28.3-r0 | `libgstpulseaudio.so` (pulsesrc, pulsesink), RTP |
| `gst-plugins-bad` | community, 1.28.3-r0 | `GstWebRTC-1.0.typelib`, `libgstwebrtc-1.0.so.0`, DTLS, SRTP; **без webrtcbin** |
| `libnice-gstreamer` | community, 0.1.22-r0 | `libgstnice.so` (nicesrc); подтягивает `libnice` |

Официальные источники:
[main/armv7](https://dl-cdn.alpinelinux.org/alpine/v3.24/main/armv7/),
[community/armv7](https://dl-cdn.alpinelinux.org/alpine/v3.24/community/armv7/),
[APKBUILD gst-plugins-bad](https://github.com/alpinelinux/aports/blob/3.24-stable/community/gst-plugins-bad/APKBUILD).

## Препятствие для проверки на планшете

В `gst-plugins-bad-1.28.3-r0.apk` отсутствуют
`usr/lib/gstreamer-1.0/libgstwebrtc.so` и `libgstwebrtcnice-1.0.so.0`.
Исходники GStreamer 1.28.3 в
`gst-libs/gst/webrtc/nice/meson.build` требуют **libnice >= 0.1.23**;
Alpine 3.24 содержит 0.1.22. Без этой зависимости автоматически пропускается
сборка библиотеки ICE, а за ней — плагина `ext/webrtc`.
[Исходный архив GStreamer 1.28.3](https://gstreamer.freedesktop.org/src/gst-plugins-bad/gst-plugins-bad-1.28.3.tar.xz).

Добавленные зависимости APKBUILD устанавливают остальные части стека,
но сами по себе ещё не включают звонки. Нужен исправленный пакет плагина
с подходящей libnice, согласованный с сеансом устройства/архитектором.
Не следует подменять этим фактом проверку на планшете: она ещё не выполнена.

## Экран и оболочка

Фото приходит как необязательная ссылка `Person.photo`; загружается обычным
`Media.photo` с теми же ограничениями хостов и перенаправлений. Без фото
показан силуэт. Поздний ответ загрузчика не заменяет фото нового звонящего.
Кнопки закреплены под областью фото и имени: в низком окне прокручивается
только эта область, «Завершить» остаётся видимой.

Входящий удерживает `Awake` ещё до ответа. `Gio.Notification` отправляет
URGENT (freedesktop urgency=2), `category=call.incoming` и действие
`app.show-call`, которое только показывает окно. GIO добавляет hint
`desktop-entry=io.github.haltia_de.Messenger`. Это контракт
[shell PR #17](https://github.com/haltia-de/shell/pull/17); команды оболочки
из приложения не вызываются. Уведомление снимается при выходе из ringing.

Мелодия — синтетический тон 660 Гц: 0,7 с звука, 2,3 с паузы, без микрофона.
Громкость собственного потока из настройки `ring_volume` (0…1, по умолчанию
0,65); системная громкость и mute сохраняют силу. Вывод идёт в системный
выход PulseAudio, на планшете это должны быть динамики. Поток разговора
имеет `media.role=phone`, мелодии — `media.role=ringtone`. Аппаратные устройства
и ALSA-маршруты в программе не зашиты.

Для приёмки нужны входящий и исходящий разговоры по пять минут на тестовых
аккаунтах, проверка пробуждения, мелодии, слышимости в обе стороны,
завершения с обеих сторон и запись CPU/RSS. Устройство меняет только его
сеанс, владеющий блокировкой планшета; звонки совершает человек.
