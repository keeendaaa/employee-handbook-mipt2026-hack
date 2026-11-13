"""Public HTTP downloads with DNS validation at the actual TCP connection."""

from email.message import Message
import ipaddress
from pathlib import Path
import re
import socket
import time
import unicodedata
from urllib.parse import unquote, urljoin, urlsplit
import zipfile

import httpcore
import httpx

MAX_BYTES = 25 * 1024 * 1024
FORMATS = {'.pdf', '.docx', '.xlsx'}


class ImportFailure(ValueError):
    pass


def filename(value: str) -> str:
    name = unicodedata.normalize('NFC', value.replace('\\', '/').rsplit('/', 1)[-1].strip())
    if not name or len(name) > 200 or any(ord(c) < 32 for c in name) or Path(name).suffix.lower() not in FORMATS:
        raise ImportFailure('Поддерживаются файлы PDF, DOCX и XLSX с именем до 200 символов.')
    return name


def public_url(value: str) -> str:
    value = value.strip()
    if len(value) > 4096 or any(ord(c) < 32 for c in value):
        raise ImportFailure('Некорректная ссылка на файл.')
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username is not None or parsed.password is not None:
            raise ValueError()
        if parsed.port not in (None, 80 if parsed.scheme == 'http' else 443):
            raise ValueError()
        url = httpx.URL(value)
        if url.host.lower().rstrip('.') in ('localhost', 'localhost.localdomain'):
            raise ValueError()
        try:
            address = ipaddress.ip_address(url.host)
        except ValueError:
            address = None
        if address is not None and not _global(address):
            raise ValueError()
        return str(url.copy_with(fragment=None))
    except (ValueError, httpx.InvalidURL):
        raise ImportFailure('Нужна HTTP/HTTPS-ссылка на публичный файл без логина, пароля и нестандартного порта.') from None


def _global(address):
    mapped = getattr(address, 'ipv4_mapped', None)
    return (mapped or address).is_global and not address.is_multicast


def direct_link(value: str) -> str:
    url = public_url(value)
    parsed = urlsplit(url)
    if parsed.hostname == 'drive.google.com':
        match = re.fullmatch(r'/file/d/([A-Za-z0-9_-]+)/?(?:view|preview)?/?', parsed.path)
        if match:
            return 'https://drive.google.com/uc?export=download&id=' + match.group(1)
    if parsed.hostname == 'docs.google.com':
        match = re.match(r'^/(document|spreadsheets)/d/([A-Za-z0-9_-]+)(?:/|$)', parsed.path)
        if match:
            kind, identifier = match.groups()
            return f'https://docs.google.com/{kind}/d/{identifier}/export?format=' + ('docx' if kind == 'document' else 'xlsx')
    return url


class PublicBackend(httpcore.SyncBackend):
    def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        try:
            addresses = list(dict.fromkeys(row[4][0] for row in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)))
        except OSError:
            raise ImportFailure('Не удалось определить адрес сервера файла.') from None
        if not addresses or any(not _global(ipaddress.ip_address(ip)) for ip in addresses):
            raise ImportFailure('Ссылки на локальные и внутренние адреса запрещены.')
        # Connect to a checked numeric address; TLS still uses the original URL's SNI.
        error = None
        for address in addresses:
            try:
                return super().connect_tcp(address, port, timeout=timeout, local_address=local_address, socket_options=socket_options)
            except (OSError, httpcore.NetworkError, httpcore.TimeoutException) as exc:
                error = exc
        raise ImportFailure('Не удалось подключиться к серверу файла.') from error


def download(url: str, directory: Path, *, pool_factory=None) -> Path:
    current = direct_link(url)
    directory.mkdir(parents=True, exist_ok=True)
    temporary = directory / '.download.part'
    deadline = time.monotonic() + 90
    factory = pool_factory or (lambda: httpcore.ConnectionPool(network_backend=PublicBackend(), max_connections=1))
    try:
        for redirect in range(6):
            current = public_url(current)
            with factory() as pool:
                with pool.stream('GET', current, headers={'User-Agent': 'MIPT-Navigator/0.1', 'Accept-Encoding': 'identity'},
                                 extensions={'timeout': {'connect': 10, 'read': 15, 'write': 10, 'pool': 10}}) as response:
                    headers = {k.decode('ascii').lower(): v.decode('latin-1') for k, v in response.headers}
                    if response.status in (301, 302, 303, 307, 308):
                        if redirect == 5 or 'location' not in headers:
                            raise ImportFailure('Слишком много перенаправлений у ссылки.')
                        current = public_url(urljoin(current, headers['location']))
                        continue
                    if response.status != 200:
                        raise ImportFailure(f'Сервер файла вернул HTTP {response.status}. Проверьте доступ по ссылке.')
                    if headers.get('content-encoding', 'identity').lower() not in ('', 'identity'):
                        raise ImportFailure('Сервер передал файл в неподдерживаемом HTTP-сжатии. Загрузите файл вручную.')
                    if 'text/html' in headers.get('content-type', '').lower():
                        raise ImportFailure('Ссылка открывает веб-страницу, а не файл. Нужна прямая ссылка или открытый доступ к документу.')
                    try:
                        if int(headers.get('content-length', '0')) > MAX_BYTES:
                            raise ImportFailure('Файл превышает лимит 25 МБ.')
                    except ValueError as exc:
                        if isinstance(exc, ImportFailure):
                            raise
                    size = 0
                    with temporary.open('wb') as output:
                        for chunk in response.iter_stream():
                            size += len(chunk)
                            if size > MAX_BYTES or time.monotonic() > deadline:
                                raise ImportFailure('Превышен лимит размера 25 МБ или времени скачивания.')
                            output.write(chunk)
                    if not size:
                        raise ImportFailure('По ссылке получен пустой файл.')
                    message = Message()
                    message['Content-Disposition'] = headers.get('content-disposition', '')
                    suggested = message.get_filename() or unquote(urlsplit(current).path.rsplit('/', 1)[-1])
                    try:
                        name = filename(suggested)
                    except ImportFailure:
                        with temporary.open('rb') as source:
                            magic = source.read(512)
                        if magic.startswith(b'%PDF-'):
                            extension = '.pdf'
                        elif magic.startswith(b'PK'):
                            with zipfile.ZipFile(temporary) as archive:
                                names = set(archive.namelist())
                            extension = '.docx' if 'word/document.xml' in names else '.xlsx' if 'xl/workbook.xml' in names else ''
                        else:
                            extension = ''
                        if not extension:
                            raise ImportFailure('По ссылке не получен PDF, DOCX или XLSX. Возможно, требуется вход в аккаунт.')
                        name = 'Документ' + extension
                    destination = directory / name
                    if destination.exists():
                        raise ImportFailure('Оригинал уже сохранён; повторите импорт новой задачей.')
                    temporary.rename(destination)
                    destination.chmod(0o600)
                    return destination
        raise ImportFailure('Не удалось скачать файл.')
    except ImportFailure:
        raise
    except (httpcore.NetworkError, httpcore.TimeoutException, httpcore.ProtocolError, OSError, ValueError, zipfile.BadZipFile):
        raise ImportFailure('Не удалось скачать или прочитать файл. Проверьте ссылку и открытый доступ.') from None
    finally:
        temporary.unlink(missing_ok=True)
