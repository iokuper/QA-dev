"""Модуль для работы с сетевыми интерфейсами управления."""

import socket
import time
import logging
import requests
import paramiko
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, cast, List
from typing_extensions import TypedDict, Protocol
from datetime import datetime
from paramiko import SSHClient
from urllib3.exceptions import InsecureRequestWarning

# Константы для допустимых символов
ALLOWED_HOSTNAME_CHARS = (
    'abcdefghijklmnopqrstuvwxyz'
    'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
    '0123456789-_'
)

# Константы для таймаутов
DEFAULT_TIMEOUT = 30.0
DEFAULT_RETRY_COUNT = 3
DEFAULT_RETRY_DELAY = 5.0

# Константы для портов
DEFAULT_SSH_PORT = 22
DEFAULT_IPMI_PORT = 623
DEFAULT_REDFISH_PORT = 443


class NetworkError(Exception):
    """Базовый класс для сетевых ошибок."""
    pass


class ConnectionError(NetworkError):
    """Ошибка подключения."""
    pass


class CommandError(NetworkError):
    """Ошибка выполнения команды."""
    pass


class ConfigError(NetworkError):
    """Ошибка конфигурации."""
    pass


class AuthenticationError(NetworkError):
    """Ошибка аутентификации."""
    pass


class NetworkResult(TypedDict):
    """Структура для результатов сетевых операций."""
    success: bool
    output: Optional[str]
    error: Optional[str]
    duration: float
    timestamp: str


class NetworkInterface(Protocol):
    """Протокол для сетевых интерфейсов."""

    def connect(self) -> bool:
        """
        Устанавливает соединение.

        Returns:
            bool: True если соединение установлено

        Raises:
            ConnectionError: При ошибке подключения
        """
        ...

    def disconnect(self) -> None:
        """
        Закрывает соединение.

        Raises:
            NetworkError: При ошибке закрытия соединения
        """
        ...

    def execute_command(
        self,
        command: str,
        timeout: Optional[float] = None
    ) -> NetworkResult:
        """
        Выполняет команду.

        Args:
            command: Команда для выполнения
            timeout: Таймаут выполнения

        Returns:
            NetworkResult: Результат выполнения

        Raises:
            CommandError: При ошибке выполнения команды
            TimeoutError: При превышении таймаута
        """
        ...

    def verify_connection(self) -> bool:
        """
        Проверяет соединение.

        Returns:
            bool: True если соединение активно

        Raises:
            NetworkError: При ошибке проверки соединения
        """
        ...


class NetworkManager(ABC):
    """Абстрактный базовый класс для менеджеров сетевых интерфейсов."""

    def __init__(
        self,
        config_file: str,
        logger: Optional[logging.Logger] = None
    ) -> None:
        """
        Инициализирует сетевой менеджер.

        Args:
            config_file: Путь к файлу конфигурации
            logger: Логгер для вывода сообщений
        """
        from config_manager import ConfigManager
        self.config_manager = ConfigManager(config_file)
        self.logger = logger or logging.getLogger(__name__)

    @abstractmethod
    def connect(self) -> bool:
        """
        Устанавливает соединение.

        Returns:
            bool: True если соединение установлено

        Raises:
            ConnectionError: При ошибке подключения
        """
        pass

    @abstractmethod
    def disconnect(self) -> None:
        """
        Закрывает соединение.

        Raises:
            NetworkError: При ошибке закрытия соединения
        """
        pass

    @abstractmethod
    def execute_command(
        self,
        command: str,
        timeout: Optional[float] = None
    ) -> NetworkResult:
        """
        Выполняет команду.

        Args:
            command: Команда для выполнения
            timeout: Таймаут выполнения

        Returns:
            NetworkResult: Результат выполнения

        Raises:
            CommandError: При ошибке выполнения команды
            TimeoutError: При превышении таймаута
        """
        pass

    @abstractmethod
    def verify_connection(self) -> bool:
        """
        Проверяет соединение.

        Returns:
            bool: True если соединение активно

        Raises:
            NetworkError: При ошибке проверки соединения
        """
        pass


class SSHManager(NetworkManager):
    """Менеджер для работы через SSH."""

    def __init__(
        self,
        config_file: str,
        logger: Optional[logging.Logger] = None
    ) -> None:
        """
        Инициализирует SSH менеджер.

        Args:
            config_file: Путь к файлу конфигурации
            logger: Логгер для вывода сообщений
        """
        super().__init__(config_file, logger)

        # Загружаем конфигурацию SSH
        ssh_config = self.config_manager.get_network_config('SSH')
        self.ssh_host = cast(str, ssh_config.get('ssh_host'))
        self.ssh_port = int(ssh_config.get('ssh_port', DEFAULT_SSH_PORT))

        # Получаем учетные данные
        credentials = self.config_manager.get_credentials('SSH')
        self.ssh_username = cast(str, credentials['username'])
        self.ssh_password = cast(str, credentials['password'])

        # Параметры подключения
        self.timeout = float(ssh_config.get('timeout', DEFAULT_TIMEOUT))
        self.retry_count = int(ssh_config.get('retry_count', DEFAULT_RETRY_COUNT))
        self.retry_delay = float(
            ssh_config.get('retry_delay', DEFAULT_RETRY_DELAY)
        )

        self.client: Optional[SSHClient] = None

    def connect(self) -> bool:
        """
        Устанавливает SSH соединение.

        Returns:
            bool: True если соединение установлено

        Raises:
            ConnectionError: При ошибке подключения
            AuthenticationError: При ошибке аутентификации
        """
        try:
            if self.client:
                self.disconnect()

            self.client = paramiko.SSHClient()
            self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            start_time = time.time()
            self.client.connect(
                hostname=self.ssh_host,
                port=self.ssh_port,
                username=self.ssh_username,
                password=self.ssh_password,
                timeout=self.timeout
            )
            duration = time.time() - start_time

            self.logger.debug(
                f"SSH соединение установлено за {duration:.2f}с"
            )
            return True

        except paramiko.AuthenticationException as e:
            msg = f"Ошибка аутентификации SSH: {e}"
            self.logger.error(msg)
            raise AuthenticationError(msg)
        except Exception as e:
            msg = f"Ошибка SSH подключения: {e}"
            self.logger.error(msg)
            raise ConnectionError(msg)

    def disconnect(self) -> None:
        """
        Закрывает SSH соединение.

        Raises:
            NetworkError: При ошибке закрытия соединения
        """
        try:
            if self.client:
                self.client.close()
                self.client = None
                self.logger.debug("SSH соединение закрыто")
        except Exception as e:
            msg = f"Ошибка закрытия SSH соединения: {e}"
            self.logger.error(msg)
            raise NetworkError(msg)

    def execute_command(
        self,
        command: str,
        timeout: Optional[float] = None
    ) -> NetworkResult:
        """
        Выполняет команду через SSH.

        Args:
            command: Команда для выполнения
            timeout: Таймаут выполнения

        Returns:
            NetworkResult: Результат выполнения

        Raises:
            CommandError: При ошибке выполнения команды
            TimeoutError: При превышении таймаута
        """
        if not self.client:
            raise ConnectionError("SSH соединение не установлено")

        try:
            start_time = time.time()
            stdin, stdout, stderr = self.client.exec_command(
                command,
                timeout=timeout or self.timeout
            )
            output = stdout.read().decode().strip()
            error = stderr.read().decode().strip()
            duration = time.time() - start_time

            result: NetworkResult = {
                'success': stdout.channel.recv_exit_status() == 0,
                'output': output,
                'error': error if error else None,
                'duration': duration,
                'timestamp': datetime.now().isoformat()
            }

            if error:
                self.logger.warning(f"SSH stderr: {error}")

            return result

        except socket.timeout:
            msg = (
                f"Таймаут выполнения команды SSH "
                f"(timeout={timeout or self.timeout}с): {command}"
            )
            self.logger.error(msg)
            raise TimeoutError(msg)
        except Exception as e:
            msg = f"Ошибка выполнения команды SSH: {e}"
            self.logger.error(msg)
            raise CommandError(msg)

    def verify_connection(self) -> bool:
        """
        Проверяет SSH соединение.

        Returns:
            bool: True если соединение активно

        Raises:
            NetworkError: При ошибке проверки соединения
        """
        try:
            if not self.client:
                return False

            result = self.execute_command("echo test")
            return result['success'] and result['output'] == "test"

        except Exception as e:
            msg = f"Ошибка проверки SSH соединения: {e}"
            self.logger.error(msg)
            raise NetworkError(msg)


class RedfishManager:
    """Менеджер для работы через Redfish API."""

    def __init__(
        self,
        base_tester: 'BaseTester',  # Предполагаем, что BaseTester определён
        logger: Optional[logging.Logger] = None
    ) -> None:
        """
        Инициализирует Redfish менеджер.

        Args:
            base_tester: Экземпляр BaseTester с конфигурацией и текущим IP-адресом BMC
            logger: Логгер для вывода сообщений
        """
        self.base_tester = base_tester
        self.logger = logger or logging.getLogger(__name__)

        # Инициализируем сессию requests
        self.session = requests.Session()
        self.session.verify = False  # Отключаем проверку SSL-сертификата
        requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

        # Загрузка настроек из конфигурации
        redfish_config = self.base_tester.config_manager.get_network_config('Redfish')
        self.verify_ssl = redfish_config.get('verify_ssl', 'false').lower() == 'true'
        self.timeout = float(redfish_config.get('timeout', DEFAULT_TIMEOUT))
        self.retry_count = int(redfish_config.get('retry_count', DEFAULT_RETRY_COUNT))
        self.retry_delay = float(redfish_config.get('retry_delay', DEFAULT_RETRY_DELAY))

        # Параметры подключения (инициализируем, будут обновлены при подключении)
        self.redfish_port = DEFAULT_REDFISH_PORT
        self.auth = None
        self.base_url = ''

    def connect(self) -> None:
        """
        Устанавливает соединение с Redfish API.

        Raises:
            ConnectionError: При ошибке подключения
        """
        try:
            # Обновляем параметры подключения с текущими данными
            self.redfish_port = DEFAULT_REDFISH_PORT
            self.auth = (self.base_tester.ipmi_username, self.base_tester.ipmi_password)
            self.base_url = f"https://{self.base_tester.ipmi_host}:{self.redfish_port}"

            self.logger.debug(f"Подключение к Redfish API по адресу {self.base_url}")

            # Проверяем соединение
            response = self.session.get(
                f"{self.base_url}/redfish/v1",
                auth=self.auth,
                timeout=self.timeout,
                verify=self.verify_ssl
            )
            response.raise_for_status()
            self.logger.debug("Redfish соединение установлено")

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401:
                msg = f"Ошибка аутентификации Redfish: {e}"
                self.logger.error(msg)
                raise AuthenticationError(msg)
            else:
                msg = f"Ошибка HTTP при подключении к Redfish: {e}"
                self.logger.error(msg)
                raise ConnectionError(msg)
        except Exception as e:
            msg = f"Ошибка подключения к Redfish API: {e}"
            self.logger.error(msg)
            raise ConnectionError(msg)

    def disconnect(self) -> None:
        """
        Закрывает соединение с Redfish API.
        """
        try:
            self.session.close()
            self.logger.debug("Redfish соединение закрыто")
        except Exception as e:
            msg = f"Ошибка при закрытии Redfish соединения: {e}"
            self.logger.error(msg)
            raise NetworkError(msg)

    def run_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None
    ) -> Optional[requests.Response]:
        """
        Выполняет HTTP-запрос к Redfish API.

        Args:
            method: HTTP метод ('GET', 'POST', 'PATCH', 'DELETE')
            endpoint: URI ресурса Redfish API
            data: Тело запроса (для методов 'POST' и 'PATCH')
            headers: Заголовки запроса

        Returns:
            Response: Объект ответа requests или None в случае ошибки

        Raises:
            NetworkError: При ошибке выполнения запроса
        """
        url = f"https://{self.base_tester.ipmi_host}:{self.redfish_port}{endpoint}"
        self.logger.debug(f"Отправка {method} запроса к {url} с данными {data} и заголовками {headers}")
        response = None
        try:
            response = self.session.request(
                method=method,
                url=url,
                json=data,
                headers=headers,
                auth=self.auth,
                verify=self.verify_ssl,
                timeout=self.timeout
            )
            self.logger.debug(f"Получен ответ: статус {response.status_code}, тело {response.text}")
            response.raise_for_status()
            return response
        except requests.exceptions.HTTPError as e:
            self.logger.error(f"Ошибка HTTP при выполнении запроса: {e}")
            if response is not None:
                self.logger.error(f"Тело ответа: {response.text}")
            return response  # Возвращаем response даже при ошибке для обработки в вызывающем коде
        except Exception as e:
            self.logger.error(f"Неожиданная ошибка при выполнении запроса: {e}", exc_info=True)
            raise NetworkError(f"Неожиданная ошибка при выполнении запроса: {e}")

    def verify_connection(self) -> bool:
        """
        Проверяет соединение с Redfish API.

        Returns:
            bool: True, если соединение успешно, иначе False
        """
        try:
            self.connect()
            self.logger.debug("Проверка соединения с Redfish API прошла успешно")
            return True
        except Exception as e:
            self.logger.error(f"Ошибка проверки Redfish соединения: {e}")
            return False
        finally:
            self.disconnect()

def wait_for_port(
    host: str,
    port: int,
    timeout: float = DEFAULT_TIMEOUT,
    retry_interval: float = DEFAULT_RETRY_DELAY
) -> bool:
    """
    Ожидает доступности порта.

    Args:
        host: Хост для проверки
        port: Порт для проверки
        timeout: Таймаут ожидания
        retry_interval: Интервал между попытками

    Returns:
        bool: True если порт стал доступен
    """
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            with socket.create_connection((host, port), timeout=retry_interval):
                return True
        except (socket.timeout, socket.error):
            time.sleep(retry_interval)
    return False


def verify_network_access(
    ip: str,
    ports: Optional[List[int]] = None,
    logger: Optional[logging.Logger] = None
) -> bool:
    """
    Проверяет сетевую доступность.

    Args:
        ip: IP-адрес для проверки
        ports: Список портов для проверки (по умолчанию [623, 443])
        logger: Логгер для вывода сообщений

    Returns:
        bool: True если доступен хотя бы один порт
    """
    log = logger or logging.getLogger(__name__)
    try:
        if ports is None:
            ports = [623, 443]  # IPMI и Redfish порты по умолчанию

        # Проверяем каждый порт
        for port in ports:
            if wait_for_port(ip, port, timeout=30):
                log.info(f"Порт {port} доступен на {ip}")
                return True
            else:
                log.warning(f"Порт {port} недоступен на {ip}")

        log.error(f"Все порты {ports} недоступны на {ip}")
        return False

    except Exception as e:
        log.error(f"Ошибка при проверке доступности {ip}: {e}")
        return False
