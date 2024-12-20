"""Базовый модуль для всех тестеров."""

import logging
import time
import subprocess
from typing import Dict, Any, Optional, List, cast
from typing_extensions import TypedDict
from datetime import datetime
from logger import setup_test_logger
from network_utils import (
    wait_for_port,
    DEFAULT_IPMI_PORT,
    DEFAULT_REDFISH_PORT,
    NetworkError
)


class TestResult(TypedDict):
    """Структура для хранения результатов тестов."""
    test_name: str
    success: bool
    message: Optional[str]
    timestamp: str
    duration: float
    error_details: Optional[str]
    test_type: str


class BaseTester:
    """Базовый класс для всех тестеров."""

    def __init__(
        self,
        config_file: str = 'config.ini',
        logger: Optional[logging.Logger] = None
    ) -> None:
        """
        Инициализирует базовый тестер.

        Args:
            config_file: Путь к файлу конфигурации
            logger: Логгер для вывода сообщений

        Raises:
            ConfigError: Пи ошибке инициализации конфигурации
            NetworkError: При ошибке инициализации сетевых компонентов
        """
        self.config_file = config_file
        self.logger = logger or setup_test_logger(
            f"{self.__class__.__name__}",
            log_file="logs/tester.log"
        )

        try:
            # Импортируем здесь для избежания циклических импортов
            from config_manager import ConfigManager, ConfigError
            self.config_manager = ConfigManager(config_file)

            # Получаем учетные данные
            credentials = self.config_manager.get_credentials('IPMI')
            self.ipmi_username = cast(str, credentials['username'])
            self.ipmi_password = cast(str, credentials['password'])

            # Получаем сетевые настройки
            network_config = self.config_manager.get_network_config('Network')
            self.interface = cast(str, network_config.get('interface', '1'))
            self.ipmi_host = cast(str, network_config.get('ipmi_host'))
            self.default_subnet_mask = cast(
                str,
                network_config.get('default_subnet_mask', '255.255.255.0')
            )

            # Таймауты и повторы
            self.command_timeout = int(
                network_config.get('command_timeout', '30')
            )
            self.verify_timeout = int(
                network_config.get('verify_timeout', '60')
            )
            self.retry_count = int(network_config.get('retry_count', '3'))
            self.retry_delay = int(network_config.get('retry_delay', '10'))

            # Структура для хранения результатов тестов
            self.test_results: List[TestResult] = []

            # Сохранение исходных настроек
            self.original_settings: Dict[str, Any] = {}

            # Проверяем доступность хоста
            if not self._verify_host_access(self.ipmi_host):
                raise NetworkError(f"Хост {self.ipmi_host} недоступен")

        except ConfigError as e:
            self.logger.error(f"Ошибка инициализации конфигурации: {e}")
            raise
        except NetworkError as e:
            self.logger.error(f"Ошибка инициализации сети: {e}")
            raise
        except Exception as e:
            self.logger.error(f"Неожиданная ошибка инициализации: {e}")
            raise

    def add_test_result(
        self,
        test_name: str,
        success: bool,
        message: Optional[str] = None,
        error_details: Optional[str] = None
    ) -> None:
        """
        Добавляет результат теста.

        Args:
            test_name: Название теста
            success: Результат теста
            message: Дополнительное сообщение
            error_details: Детали ошибки
        """
        start_time = time.time()
        result: TestResult = {
            'test_name': test_name,
            'success': success,
            'message': message,
            'timestamp': datetime.now().isoformat(),
            'duration': time.time() - start_time,
            'error_details': error_details,
            'test_type': self.__class__.__name__
        }
        self.test_results.append(result)
        self.logger.info(
            f"Тест {test_name}: "
            f"{'успешно' if success else 'неуспешно'}"
            f"{f' - {message}' if message else ''}"
        )

    def _run_command(
        self,
        command: List[str],
        timeout: Optional[int] = None
    ) -> subprocess.CompletedProcess:
        """Выполняет команду с обработкой ошибок."""
        try:
            result = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout or self.command_timeout
            )

            if result.returncode != 0:
                error_msg = (
                    f"Command failed with code {result.returncode}: "
                    f"{result.stderr}"
                )
                raise RuntimeError(error_msg)

            return result

        except subprocess.TimeoutExpired as e:
            raise RuntimeError(f"Command timed out after {e.timeout}s")
        except Exception as e:
            raise RuntimeError(f"Error executing command: {e}")

    def _verify_host_access(self, host: str) -> bool:
        """Проверяет доступность хоста."""
        try:
            # Проверяем доступность по IPMI
            if not wait_for_port(
                host,
                DEFAULT_IPMI_PORT,
                self.verify_timeout
            ):
                self.logger.error(f"IPMI порт недоступен на {host}")
                return False

            # Проверяем доступность по Redfish
            if not wait_for_port(
                host,
                DEFAULT_REDFISH_PORT,
                self.verify_timeout
            ):
                self.logger.error(f"Redfish порт недоступен на {host}")
                return False

            self.logger.debug(f"IPMI и Redfish порты доступны на {host}")
            return True

        except Exception as e:
            self.logger.error(f"Ошибка при проверке доступности {host}: {e}")
            return False

    def update_bmc_ip(self, new_ip: str) -> None:
        """Обновляет IP-адрес BMC в переменной self.ipmi_host."""
        self.logger.info(f"Обновление IP BMC: {self.ipmi_host} -> {new_ip}")
        self.ipmi_host = new_ip

    def safe_restore_settings(self) -> bool:
        """
        Безопасно восстанавливает настройки.

        Returns:
            bool: True если восстановление успешно
        """
        try:
            for attempt in range(self.retry_count):
                try:
                    if self.restore_settings():
                        self.logger.info("Настройки успешно восстановлены")
                        return True
                    self.logger.warning(
                        f"Попытка восстановления {attempt + 1} не удалась"
                    )
                except Exception as e:
                    self.logger.error(
                        f"Ошибка восстановления (попытка {attempt + 1}): {e}",
                        exc_info=True
                    )
                if attempt < self.retry_count - 1:
                    time.sleep(self.retry_delay)
            return False
        except Exception as e:
            self.logger.error(
                f"Критическая ошибка при восстановлении: {e}",
                exc_info=True
            )
            return False

    def restore_settings(self) -> bool:
        """
        Восстанавливает исходные настройки.

        Returns:
            bool: True если восстановление успешно

        Raises:
            NotImplementedError: Если метод не реализован в подклассе
        """
        raise NotImplementedError(
            "Метод restore_settings должен быть реализован в подклассе"
        )

    def perform_tests(self) -> None:
        """
        Выполняет тестирование.

        Raises:
            NotImplementedError: Если метод не реализоан в подклассе
        """
        raise NotImplementedError(
            "Метод perform_tests должен быть реализован в подклассе"
        )
