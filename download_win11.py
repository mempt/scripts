#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Официальный загрузчик оригинального ISO-образа Windows 11 с сайта Microsoft.
Скрипт решает проблему ошибки 715-123130 и блокировки в РФ:
1. Парсит официальную страницу Microsoft Windows 11 для определения актуальной редакции.
2. Имитирует браузерное подтверждение сессии и токены валидации (vlscppe, ov-df).
3. Получает SKU для русского языка ("Russian" / "Русский").
4. Генерирует официальную прямую 24-часовую ссылку на Microsoft CDN (software.download.prss.microsoft.com).
5. Скачивает образ на максимальной скорости с интерактивным прогресс-баром, расчетом скорости/ETA и поддержкой докачки (Resume).
"""

import sys
import os
import re
import time
import uuid
import json
import shutil
import argparse
import urllib.request
import urllib.error

# Настройка UTF-8 для корректного вывода в терминале Windows
try:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

# Базовые константы
DEFAULT_PAGE_URL = "https://www.microsoft.com/en-us/software-download/windows11"
DEFAULT_ORG_ID = "y6jn8c31"
DEFAULT_PROFILE_ID = "606624d44113"
DEFAULT_INSTANCE_ID = "560dc9f3-1aa5-4a2f-b63c-9e18f8d0e175"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0.0.0 Safari/537.36"
)

def format_size(bytes_num):
    """Преобразование количества байт в удобочитаемую строку (Б, КБ, МБ, ГБ)."""
    if bytes_num is None:
        return "неизвестно"
    for unit in ['Б', 'КБ', 'МБ', 'ГБ', 'ТБ']:
        if bytes_num < 1024.0:
            return f"{bytes_num:.2f} {unit}"
        bytes_num /= 1024.0
    return f"{bytes_num:.2f} ПБ"

def format_time(seconds):
    """Преобразование секунд в формат ЧЧ:ММ:СС или ММ:СС."""
    if seconds is None or seconds < 0 or seconds > 86400 * 30:
        return "--:--"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"

class Win11Downloader:
    def __init__(self, page_url=DEFAULT_PAGE_URL, target_language="Russian"):
        self.page_url = page_url
        self.target_language = target_language.lower()
        self.session_id = str(uuid.uuid4())
        self.profile_id = DEFAULT_PROFILE_ID
        self.instance_id = DEFAULT_INSTANCE_ID
        self.org_id = DEFAULT_ORG_ID
        self.api_endpoint = "https://www.microsoft.com/software-download-connector/api/"
        self.edition_id = None
        self.headers = {
            "User-Agent": USER_AGENT,
            "Referer": self.page_url,
            "Accept": "*/*",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        }

    def _request(self, url, headers=None, data=None, timeout=30):
        req_headers = dict(self.headers)
        if headers:
            req_headers.update(headers)
        req = urllib.request.Request(url, headers=req_headers, data=data)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            err_body = ""
            try:
                err_body = e.read().decode('utf-8', errors='ignore')
            except Exception:
                pass
            raise RuntimeError(f"HTTP {e.code} ({e.reason}) при запросе к {url}\n{err_body}")

    def parse_page(self):
        """Шаг 1: Парсинг официальной страницы Microsoft Windows 11."""
        print(f"[*] [1/5] Парсинг официальной страницы Microsoft...")
        html = self._request(self.page_url).decode('utf-8', errors='ignore')

        # Извлечение адреса API коннектора
        m_endpoint = re.search(r'id=["\']endpoint-svc["\'][^>]*value=["\']([^"\']+)["\']', html)
        if m_endpoint:
            self.api_endpoint = m_endpoint.group(1).rstrip('/') + '/'

        # Поиск актуального ID редакции Windows 11 multi-edition x64
        m_edition = re.search(r'<select[^>]*id=["\']product-edition["\'][^>]*>(.*?)</select>', html, re.DOTALL)
        if m_edition:
            options = re.findall(r'<option[^>]*value=["\'](\d+)["\'][^>]*>(.*?)</option>', m_edition.group(1))
            for val, title in options:
                if val != "null":
                    self.edition_id = val
                    print(f"    -> Найдена актуальная редакция: {title.strip()} (ID: {val})")
                    break

        if not self.edition_id:
            self.edition_id = "3321"
            print(f"    -> Используется стандартный ID редакции: {self.edition_id}")

    def authenticate_session(self):
        """Шаг 2: Прохождение авторизации сессии Microsoft (anti-bot / ov-df)."""
        print(f"[*] [2/5] Прохождение проверки подлинности сессии...")

        # 1. Запрос к vlscppe tags
        url_tags = f"https://vlscppe.microsoft.com/tags?org_id={self.org_id}&session_id={self.session_id}"
        try:
            self._request(url_tags, timeout=15)
        except Exception:
            pass

        # 2. Получение параметров токена из ov-df
        url_mdt = (
            f"https://ov-df.microsoft.com/mdt.js"
            f"?instanceId={self.instance_id}&PageId=si&session_id={self.session_id}"
        )
        body_mdt = self._request(url_mdt, timeout=15).decode('utf-8', errors='ignore')

        m_w = re.search(r'[?&]w=([A-F0-9]+)', body_mdt)
        m_rticks = re.search(r'rticks\=\"\+?(\d+)', body_mdt)
        if not m_w or not m_rticks:
            raise RuntimeError("Не удалось получить токен проверки безопасности ov-df от Microsoft.")

        w_val = m_w.group(1)
        rticks_val = m_rticks.group(1)
        now_ms = int(time.time() * 1000)

        # 3. Отправка ответа проверки
        url_reply = (
            f"https://ov-df.microsoft.com/"
            f"?session_id={self.session_id}&CustomerId={self.instance_id}"
            f"&PageId=si&w={w_val}&mdt={now_ms}&rticks={rticks_val}"
        )
        try:
            self._request(url_reply, timeout=15)
        except Exception:
            pass

        print(f"    -> Сессия успешно подтверждена (Session ID: {self.session_id})")

    def get_sku_for_language(self):
        """Шаг 3: Получение доступных языков и выбор русского SKU."""
        print(f"[*] [3/5] Получение языковых пакетов...")
        url_sku = (
            f"{self.api_endpoint}getskuinformationbyproductedition"
            f"?profile={self.profile_id}&productEditionId={self.edition_id}"
            f"&SKU=undefined&friendlyFileName=undefined&Locale=ru-ru&sessionID={self.session_id}"
        )

        resp = self._request(url_sku)
        data = json.loads(resp.decode('utf-8'))

        if data.get("Errors"):
            err = data["Errors"][0]
            if err.get("Type") == 9:
                raise RuntimeError(
                    "Ошибка 715-123130: Microsoft заблокировал этот IP-адрес.\n"
                    "РЕШЕНИЕ: Переключите в вашем VPN другую локацию/страну (например, Германию, Нидерланды или США) и запустите скрипт снова."
                )
            raise RuntimeError(f"Ошибка получения языков: {err.get('Value')}")

        skus = data.get("Skus", [])
        if not skus:
            raise RuntimeError("Сервер Microsoft не вернул доступные языки.")

        selected_sku = None
        for sku in skus:
            lang = sku.get("Language", "").lower()
            localized = sku.get("LocalizedLanguage", "").lower()
            if self.target_language in lang or self.target_language in localized or "рус" in localized:
                selected_sku = sku
                break

        if not selected_sku:
            avail = [s.get("Language") for s in skus]
            raise RuntimeError(
                f"Язык '{self.target_language}' не найден. Доступно: {', '.join(avail)}"
            )

        sku_id = selected_sku["Id"]
        display_name = selected_sku.get("ProductDisplayName", "Windows 11 Russian")
        print(f"    -> Выбран язык: Русский (SKU ID: {sku_id})")
        print(f"    -> Дистрибутив: {display_name}")
        return sku_id, display_name

    def generate_download_link(self, sku_id):
        """Шаг 4: Генерация прямой ссылки Microsoft CDN на загрузку ISO."""
        print(f"[*] [4/5] Запрос официальной прямой ссылки...")
        url_dl = (
            f"{self.api_endpoint}GetProductDownloadLinksBySku"
            f"?profile={self.profile_id}&productEditionId=undefined"
            f"&SKU={sku_id}&friendlyFileName=undefined&Locale=ru-ru&sessionID={self.session_id}"
        )

        resp = self._request(url_dl)
        data = json.loads(resp.decode('utf-8'))

        if data.get("Errors"):
            for err in data["Errors"]:
                if err.get("Type") == 9 or "Sentinel" in str(err):
                    raise RuntimeError(
                        "Защита Microsoft отклонила запрос (SentinelReject / Код 715-123130):\n"
                        "  Microsoft временно ограничил генерацию ссылок для данного IP/VPN-сервера.\n"
                        "  РЕШЕНИЕ:\n"
                        "  1) Смените в вашем VPN сервер или страну (например, Германия, Нидерланды, Швеция, США) и перезапустите скрипт.\n"
                        "  2) Либо, если у вас уже есть прямая ссылка, запустите сразу скачивание:\n"
                        "     python download_win11.py --url \"<ССЫЛКА>\""
                    )
            raise RuntimeError(f"Ошибка генерации ссылки: {data['Errors']}")

        options = data.get("ProductDownloadOptions", [])
        if not options:
            raise RuntimeError("Сервер Microsoft не вернул ссылку для скачивания.")

        download_info = options[0]
        iso_url = download_info.get("Uri")
        expires = data.get("DownloadExpirationDatetime", "24 часа")

        m_name = re.search(r'/([^/?]+?\.iso)', iso_url, re.IGNORECASE)
        filename = m_name.group(1) if m_name else "Win11_Russian_x64.iso"

        print(f"    -> Ссылка успешно сгенерирована!")
        print(f"    -> Файл: {filename}")
        print(f"    -> Ссылка действует до: {expires}")
        return iso_url, filename

    def download_file(self, url, destination_path, chunk_size=1024 * 1024):
        """Шаг 5: Загрузка ISO с поддержкой докачки и динамическим прогресс-баром."""
        print(f"[*] [5/5] Запуск загрузки...")

        temp_path = destination_path + ".part"
        downloaded_bytes = 0

        if os.path.exists(temp_path):
            downloaded_bytes = os.path.getsize(temp_path)
            print(f"    -> Найден неполный файл ({format_size(downloaded_bytes)}). Продолжаем скачивание с места обрыва...")

        req_headers = dict(self.headers)
        if downloaded_bytes > 0:
            req_headers["Range"] = f"bytes={downloaded_bytes}-"

        req = urllib.request.Request(url, headers=req_headers)

        retries = 5
        while retries > 0:
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    status = resp.status
                    content_range = resp.headers.get("Content-Range")
                    total_bytes = None

                    if status == 206 and content_range:
                        m = re.search(r'/(\d+)', content_range)
                        if m:
                            total_bytes = int(m.group(1))
                    elif status == 200:
                        downloaded_bytes = 0
                        cl = resp.headers.get("Content-Length")
                        if cl:
                            total_bytes = int(cl)
                    else:
                        cl = resp.headers.get("Content-Length")
                        if cl:
                            total_bytes = downloaded_bytes + int(cl)

                    total_str = format_size(total_bytes)
                    print(f"    -> Полный размер ISO: {total_str}")
                    print(f"    -> Нажмите Ctrl+C для паузы в любой момент (прогресс сохранится)\n")

                    file_mode = "ab" if downloaded_bytes > 0 else "wb"
                    start_time = time.time()
                    last_time = start_time
                    bytes_since_last = 0
                    current_speed = 0

                    with open(temp_path, file_mode) as out_file:
                        while True:
                            chunk = resp.read(chunk_size)
                            if not chunk:
                                break
                            out_file.write(chunk)
                            downloaded_bytes += len(chunk)
                            bytes_since_last += len(chunk)

                            now = time.time()
                            dt = now - last_time
                            if dt >= 0.4:
                                current_speed = bytes_since_last / dt
                                last_time = now
                                bytes_since_last = 0

                            # Расчет ширины терминала для красивого отображения
                            term_width = shutil.get_terminal_size((80, 20)).columns
                            bar_width = max(15, min(30, term_width - 55))

                            speed_str = f"{format_size(current_speed)}/с"

                            if total_bytes and total_bytes > 0:
                                percent = (downloaded_bytes / total_bytes) * 100
                                filled = int(bar_width * downloaded_bytes // total_bytes)
                                bar = "■" * filled + " " * (bar_width - filled)
                                eta = (total_bytes - downloaded_bytes) / current_speed if current_speed > 0 else 0
                                eta_str = format_time(eta)

                                line = (
                                    f"\r  [{bar}] {percent:5.1f}% | "
                                    f"{format_size(downloaded_bytes)}/{total_str} | "
                                    f"{speed_str:>10} | Ост: {eta_str} "
                                )
                            else:
                                line = f"\r  Скачано: {format_size(downloaded_bytes)} | {speed_str:>10} "

                            sys.stdout.write(line)
                            sys.stdout.flush()

                    sys.stdout.write("\n\n")
                    sys.stdout.flush()
                    break

            except KeyboardInterrupt:
                print("\n\n[!] Загрузка приостановлена пользователем (Ctrl+C).")
                print(f"    Сохранено: {format_size(os.path.getsize(temp_path))}")
                print("    Чтобы продолжить, просто запустите скрипт заново — он продолжит с этого же места.")
                sys.exit(0)

            except Exception as e:
                retries -= 1
                if retries > 0:
                    print(f"\n[!] Сбой соединения: {e}. Повторная попытка через 3 сек (осталось попыток: {retries})...")
                    time.sleep(3)
                    if os.path.exists(temp_path):
                        downloaded_bytes = os.path.getsize(temp_path)
                        req_headers["Range"] = f"bytes={downloaded_bytes}-"
                        req = urllib.request.Request(url, headers=req_headers)
                else:
                    print(f"\n[-] Ошибка сети: {e}")
                    print("    Файл частично сохранен (.part). Запустите скрипт снова для продолжения.")
                    sys.exit(1)

        # Переименование .part в .iso после успешной загрузки
        if os.path.exists(destination_path):
            try:
                os.remove(destination_path)
            except Exception:
                pass
        os.rename(temp_path, destination_path)
        print(f"[✓] УСПЕХ! Официальный ISO-образ успешно загружен:")
        print(f"    Путь: {os.path.abspath(destination_path)}")
        print(f"    Размер: {format_size(os.path.getsize(destination_path))}")

def main():
    parser = argparse.ArgumentParser(
        description="Официальный загрузчик ISO Windows 11 с серверов Microsoft."
    )
    parser.add_argument(
        "--lang", default="Russian",
        help="Язык дистрибутива (по умолчанию: Russian)"
    )
    parser.add_argument(
        "--output-dir", default=".",
        help="Папка для сохранения файла (по умолчанию текущая)"
    )
    parser.add_argument(
        "--url", default=None,
        help="Прямая ссылка Microsoft CDN для прямого скачивания (пропуская парсинг и генерацию)"
    )
    parser.add_argument(
        "--url-only", action="store_true",
        help="Только получить и вывести официальную прямую ссылку, не запуская скачивание"
    )

    args = parser.parse_args()

    print("=" * 75)
    print("      Официальный загрузчик Windows 11 ISO (Microsoft CDN)")
    print("=" * 75)

    downloader = Win11Downloader(target_language=args.lang)

    try:
        dest_dir = os.path.abspath(args.output_dir)
        os.makedirs(dest_dir, exist_ok=True)

        if args.url:
            direct_url = args.url
            m_name = re.search(r'/([^/?]+?\.iso)', direct_url, re.IGNORECASE)
            filename = m_name.group(1) if m_name else "Win11_Russian_x64.iso"
            print(f"[*] Используется переданная прямая ссылка Microsoft CDN:")
            print(f"    Файл: {filename}")
        else:
            downloader.parse_page()
            downloader.authenticate_session()
            sku_id, prod_name = downloader.get_sku_for_language()
            direct_url, filename = downloader.generate_download_link(sku_id)

            print("-" * 75)
            print("Прямая официальная ссылка Microsoft CDN:")
            print(direct_url)
            print("-" * 75)

            if args.url_only:
                print("[*] Режим '--url-only': прямая ссылка получена, скачивание пропущено.")
                return

        dest_path = os.path.join(dest_dir, filename)
        downloader.download_file(direct_url, dest_path)

    except Exception as err:
        print(f"\n[-] ОШИБКА: {err}")
        sys.exit(1)

if __name__ == "__main__":
    main()
