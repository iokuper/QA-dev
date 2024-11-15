"""Модуль с утилитами для верификации настроек."""

import subprocess
import logging
import platform
import socket
import time
from typing import Optional, Dict, Any, List, cast, TYPE_CHECKING
from ipaddress import ip_address, IPv4Address
from network_utils import wait_for_port

if TYPE_CHECKING:
    from network_utils import SSHManager


def verify_ip_format(ip: str, logger: Optional[logging.Logger] = None) -> bool:
    """
    Проверяет формат IP-адреса.

    Args:
        ip: IP-адрес для проверки
        logger: Логгер для вывода сообщений

    Returns:
        bool: True если формат корректен
    """
    log = logger or logging.getLogger(__name__)
    try:
        ip_obj = ip_address(ip)
        if not isinstance(ip_obj, IPv4Address):
            log.error(f"Адрес {ip} не является IPv4")
            return False
        return True
    except ValueError:
        log.error(f"Некорректный формат IP адреса: {ip}")
        return False


def verify_settings(ssh_manager: 'SSHManager', interface: str) -> Dict[str, str]:
    """Проверяет текущие сетевые настройки через SSH."""
    try:
        max_retries = 3
        for attempt in range(max_retries):
            try:
                if not ssh_manager.connect():
                    raise RuntimeError("SSH соединение не установлено")

                command = f"ipmitool lan print {interface}"
                result = ssh_manager.execute_command(command)
                if not result or not result['success']:
                    raise RuntimeError(
                        f"Ошибка выполнения команды: {result.get('error') if result else None}"
                    )

                # Парсим вывод ipmitool
                settings = {}
                if result['output']:
                    for line in result['output'].splitlines():
                        if ':' not in line:
                            continue
                        key, value = [x.strip() for x in line.split(':', 1)]
                        settings[key] = value

                # Логируем текущие настройки
                ssh_manager.logger.debug(
                    f"Текущие настройки: "
                    f"Progress={settings.get('Set in Progress')}, "
                    f"Source={settings.get('IP Address Source')}, "
                    f"IP={settings.get('IP Address')}, "
                    f"Mask={settings.get('Subnet Mask')}, "
                    f"Gateway={settings.get('Default Gateway IP')}"
                )

                return settings

            except Exception as e:
                if attempt < max_retries - 1:
                    ssh_manager.logger.debug(
                        f"Попытка {attempt + 1} не удалась: {e}, повторяем..."
                    )
                    time.sleep(5)
                    continue
                raise

    except Exception as e:
        raise RuntimeError(f"Ошибка проверки настроек: {e}")
    finally:
        ssh_manager.disconnect()


def verify_port_open(
    host: str,
    port: int,
    timeout: float = 5.0,
    logger: Optional[logging.Logger] = None
) -> bool:
    """
    Проверяет доступность порта.

    Args:
        host: Хост для проверки
        port: Порт для проверки
        timeout: Таймаут подключения
        logger: Логгер для вывода сообщений

    Returns:
        bool: True если порт доступен
    """
    log = logger or logging.getLogger(__name__)
    try:
        with socket.create_connection((host, port), timeout=timeout):
            log.debug(f"Порт {port} доступен на {host}")
            return True
    except (socket.timeout, socket.error) as e:
        log.error(f"Порт {port} не доступен на {host}: {e}")
        return False


def wait_for_port_open(
    host: str,
    port: int,
    timeout: float = 60.0,
    interval: float = 1.0,
    logger: Optional[logging.Logger] = None
) -> bool:
    """
    Ожидает открытия порта.

    Args:
        host: Хост для проверки
        port: Порт для проверки
        timeout: Общий таймаут ожидания
        interval: Интервал между проверками
        logger: Логгер для вывода сообщений

    Returns:
        bool: True если порт стал доступен
    """
    log = logger or logging.getLogger(__name__)
    end_time = time.time() + timeout
    attempt = 1

    while time.time() < end_time:
        log.debug(
            f"Попытка {attempt}/∞ проверки доступности {host}:{port}"
        )
        if verify_port_open(
            host,
            port,
            timeout=min(interval, 1.0),
            logger=log
        ):
            return True
        time.sleep(interval)
        attempt += 1

    log.error(
        f"Порт {port} не стал доступен на {host} "
        f"после {timeout} секунд ожидания"
    )
    return False


def ping_ip(
    ip: str,
    count: int = 4,
    timeout: int = 2,
    logger: Optional[logging.Logger] = None
) -> bool:
    """
    Отправляет ping-запросы на указанный IP-адрес.

    Args:
        ip: IP-адрес для проверки
        count: Количество пакетов
        timeout: Таймаут ожидания ответа
        logger: Логгер для вывода сообщений

    Returns:
        bool: True если ping успешен
    """
    log = logger or logging.getLogger(__name__)
    try:
        # Проверяем корректность IP
        ip_obj = ip_address(ip)
        if not isinstance(ip_obj, IPv4Address):
            log.error(f"Некорректный IPv4 адрес: {ip}")
            return False

        # Определяем параметры для разных ОС
        if platform.system().lower() == 'windows':
            param_count = '-n'
            param_timeout = '-w'
            timeout_ms = timeout * 1000  # Windows использует миллисекунды
        else:
            param_count = '-c'
            param_timeout = '-W'
            timeout_ms = timeout

        command = [
            'ping',
            param_count, str(count),
            param_timeout, str(timeout_ms),
            ip
        ]

        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        success = result.returncode == 0
        if success:
            log.debug(f"Ping на {ip} успешен")
        else:
            log.debug(f"Ping на {ip} не удался")
        return success

    except Exception as e:
        log.error(f"Ошибка при отправке ping на {ip}: {e}")
        return False


def parse_lan_print(
    output: str,
    logger: Optional[logging.Logger] = None
) -> Optional[Dict[str, str]]:
    """
    Разбирает вывод команды 'ipmitool lan print'.

    Args:
        output: Вывод команды для разбора
        logger: Логгер для вывода сообщений

    Returns:
        Optional[Dict[str, str]]: Словарь с настройками или None
    """
    log = logger or logging.getLogger(__name__)
    try:
        if not output:
            log.error("Пустой вывод команды")
            return None

        settings: Dict[str, str] = {}
        lines = output.strip().split('\n')

        for line in lines:
            line = line.strip()
            if ':' in line:
                key, value = [part.strip() for part in line.split(':', 1)]
                settings[key] = value

        required_keys = [
            'IP Address Source',
            'IP Address',
            'Subnet Mask',
            'Default Gateway IP'
        ]

        # Проверяем наличие всех необходимых параметров
        missing_keys = [key for key in required_keys if key not in settings]
        if missing_keys:
            log.error(f"Отсутствуют параметры: {', '.join(missing_keys)}")
            return None

        # Проверяем корректность IP адресов
        for key in ['IP Address', 'Default Gateway IP']:
            try:
                if settings[key] != '0.0.0.0':
                    ip_address(settings[key])
            except ValueError:
                log.error(
                    f"Некорректный IP адрес в поле {key}: {settings[key]}"
                )
                return None

        return settings

    except Exception as e:
        log.error(f"Ошибка при разборе вывода lan print: {e}")
        return None


def verify_network_access(
    ip: str,
    ports: Optional[List[int]] = None,
    logger: Optional[logging.Logger] = None
) -> bool:
    """
    Проверяет сетевую доступность.

    Args:
        ip: IP-адрес для проверки
        ports: Список портов ля проверки
        logger: Логгер для вывода сообщений

    Returns:
        bool: True если доступно
    """
    log = logger or logging.getLogger(__name__)
    try:
        if not verify_ip_format(ip, log):
            return False

        if ports is None:
            ports = [623, 443]

        # Проверяем ping
        if not ping_ip(ip, logger=log):
            log.error(f"Ping на {ip} не прошел")
            return False

        # Проверяем порты
        for port in ports:
            if not wait_for_port_open(ip, port, logger=log):
                log.error(f"Порт {port} не доступен на {ip}")
                return False

        return True

    except Exception as e:
        log.error(f"Ошибка при проверке сетевой доступности {ip}: {e}")
        return False
