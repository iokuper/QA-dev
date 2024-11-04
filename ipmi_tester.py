"""Модуль для тестирования через IPMI."""

import logging
import time
from typing import Dict, Any, Optional, cast
from base_tester import BaseTester
from verification_utils import verify_ip_format
from network_utils import wait_for_port


class IPMITester(BaseTester):
    """Класс для тестирования через IPMI."""

    def __init__(
        self,
        config_file: str = 'config.ini',
        logger: Optional[logging.Logger] = None
    ) -> None:
        """
        Инициализирует IPMI тестер.

        Args:
            config_file: Путь к файлу конфигурации
            logger: Логгер для вывода сообщений
        """
        super().__init__(config_file, logger)

        # Загрузка конфигурации IPMI
        ipmi_config = self.config_manager.get_network_config('IPMI')
        self.interface = cast(str, ipmi_config.get('interface', '1'))

        # Таймауты и повторы
        self.setup_timeout = int(ipmi_config.get('setup_timeout', '30'))
        self.verify_timeout = int(ipmi_config.get('verify_timeout', '60'))
        self.retry_count = int(ipmi_config.get('retry_count', '3'))
        self.retry_delay = int(ipmi_config.get('retry_delay', '10'))

        # Дополнительные параметры
        self.verify_access = ipmi_config.get(
            'verify_access',
            'true'
        ).lower() == 'true'
        self.check_privileges = ipmi_config.get(
            'check_privileges',
            'true'
        ).lower() == 'true'

        # Сохранение исходных настроек
        self.original_settings: Dict[str, Any] = {}

        self.logger.debug("Инициализация IPMI тестера завершена")

    def get_current_settings(self) -> Dict[str, Any]:
        """
        Получает текущие настройки IPMI.

        Returns:
            Dict[str, Any]: Текущие настройки
        """
        try:
            command = [
                "ipmitool", "-I", "lanplus",
                "-H", cast(str, self.ipmi_host),
                "-U", self.ipmi_username,
                "-P", self.ipmi_password,
                "lan", "print", self.interface
            ]
            result = self._run_command(command)

            settings: Dict[str, Any] = {}
            for line in result.stdout.splitlines():
                if ':' in line:
                    key, value = [x.strip() for x in line.split(':', 1)]
                    settings[key] = value

            return settings

        except Exception as e:
            self.logger.error(f"Ошибка при получении настроек IPMI: {e}")
            return {}

    def verify_ipmi_access(self) -> bool:
        """
        Проверяет доступность IPMI.

        Returns:
            bool: True если IPMI доступен
        """
        try:
            # Проверяем доступность порта IPMI
            if not wait_for_port(
                cast(str, self.ipmi_host),
                623,
                timeout=self.verify_timeout
            ):
                self.logger.error(f"IPMI порт недоступен на {self.ipmi_host}")
                return False

            # Проверяем базовую команду
            command = [
                "ipmitool", "-I", "lanplus",
                "-H", cast(str, self.ipmi_host),
                "-U", self.ipmi_username,
                "-P", self.ipmi_password,
                "mc", "info"
            ]
            result = self._run_command(command)
            if not result.stdout:
                self.logger.error("Не удалось получить информацию о BMC")
                return False

            return True

        except Exception as e:
            self.logger.error(f"Ошибка при проверке доступности IPMI: {e}")
            return False

    def check_ipmi_privileges(self) -> bool:
        """
        Проверяет привилегии IPMI пользователя.

        Returns:
            bool: True если проверка успешна
        """
        try:
            command = [
                "ipmitool", "-I", "lanplus",
                "-H", cast(str, self.ipmi_host),
                "-U", self.ipmi_username,
                "-P", self.ipmi_password,
                "channel", "getaccess", self.interface,
                "1"  # ID пользователя
            ]
            result = self._run_command(command)

            # Проверяем необходимые привилегии
            required_privileges = [
                'IPMI Messaging',
                'User Level Authentication',
                'Administrator'
            ]

            for privilege in required_privileges:
                if privilege not in result.stdout:
                    self.logger.error(
                        f"Отсутствует привилегия: {privilege}"
                    )
                    return False

            return True

        except Exception as e:
            self.logger.error(f"Ошибка при проверке привилегий: {e}")
            return False

    def test_ipmi_commands(self) -> bool:
        """
        Тестирует основные команды IPMI.

        Returns:
            bool: True если тест успешен
        """
        try:
            test_commands = [
                ["mc", "info"],
                ["sdr", "list"],
                ["sensor", "list"],
                ["sel", "info"],
                ["chassis", "status"]
            ]

            for cmd in test_commands:
                command = [
                    "ipmitool", "-I", "lanplus",
                    "-H", cast(str, self.ipmi_host),
                    "-U", self.ipmi_username,
                    "-P", self.ipmi_password
                ] + cmd

                try:
                    result = self._run_command(command)
                    if not result.stdout:
                        self.logger.error(
                            f"Команда {' '.join(cmd)} не вернула данных"
                        )
                        return False
                    self.logger.info(
                        f"Команда {' '.join(cmd)} выполнена успешно"
                    )
                except Exception as e:
                    self.logger.error(
                        f"Ошибка при выполнении команды {' '.join(cmd)}: {e}"
                    )
                    return False

            return True

        except Exception as e:
            self.logger.error(f"Ошибка при тестировании команд IPMI: {e}")
            return False

    def test_ipmi_sensors(self) -> bool:
        """
        Тестирует доступ к сенсорам IPMI.

        Returns:
            bool: True если тест успешен
        """
        try:
            command = [
                "ipmitool", "-I", "lanplus",
                "-H", cast(str, self.ipmi_host),
                "-U", self.ipmi_username,
                "-P", self.ipmi_password,
                "sdr", "type", "list"
            ]
            result = self._run_command(command)

            if not result.stdout:
                self.logger.error("Не удалось получить список сенсоров")
                return False

            # Проверяем наличие основных типов сенсоров
            required_sensors = [
                'Temperature',
                'Voltage',
                'Fan',
                'Power Supply'
            ]

            for sensor in required_sensors:
                if sensor not in result.stdout:
                    self.logger.warning(
                        f"Не найден тип сенсора: {sensor}"
                    )

            return True

        except Exception as e:
            self.logger.error(f"Ошибка при тестировании сенсоров: {e}")
            return False

    def test_ipmi_sel(self) -> bool:
        """
        Тестирует работу с системным журналом событий (SEL).

        Returns:
            bool: True если тест успешен
        """
        try:
            # Проверяем информацию о SEL
            command = [
                "ipmitool", "-I", "lanplus",
                "-H", cast(str, self.ipmi_host),
                "-U", self.ipmi_username,
                "-P", self.ipmi_password,
                "sel", "info"
            ]
            result = self._run_command(command)
            if not result.stdout:
                self.logger.error("Не удалось получить информацию о SEL")
                return False

            # Пробуем добавить тестовое событие
            command = [
                "ipmitool", "-I", "lanplus",
                "-H", cast(str, self.ipmi_host),
                "-U", self.ipmi_username,
                "-P", self.ipmi_password,
                "sel", "add", "0x0a", "0x00", "0x02"
            ]
            result = self._run_command(command)
            if not result.stdout:
                self.logger.error("Не удалось добавить тестовое событие")
                return False

            return True

        except Exception as e:
            self.logger.error(f"Ошибка при тестировании SEL: {e}")
            return False

    def perform_tests(self) -> None:
        """Выполняет тестирование через IPMI."""
        try:
            self.logger.info("Начало тестирования через IPMI")

            # Проверяем доступность IPMI
            if not self.verify_ipmi_access():
                raise RuntimeError("IPMI недоступен")

            # Проверяем привилегии если требуется
            if self.check_privileges and not self.check_ipmi_privileges():
                raise RuntimeError("Недостаточно привилегий")

            # Тестируем основные команды
            if not self.test_ipmi_commands():
                raise RuntimeError("Тест команд IPMI не прошел")

            # Тестируем сенсоры
            if not self.test_ipmi_sensors():
                raise RuntimeError("Тест сенсоров не прошел")

            # Тестируем SEL
            if not self.test_ipmi_sel():
                raise RuntimeError("Тест SEL не прошел")

            self.add_test_result('IPMI Access Test', True)
            self.add_test_result('IPMI Commands Test', True)
            self.add_test_result('IPMI Sensors Test', True)
            self.add_test_result('IPMI SEL Test', True)

        except Exception as e:
            self.logger.error(f"Ошибка при выполнении тестов: {e}")
            self.add_test_result('IPMI Tests', False, str(e))

    def restore_settings(self) -> bool:
        """
        Восстанавливает исходные настройки.

        Returns:
            bool: True если восстановление успешно
        """
        # В данном случае нам не нужно восстанавливать настройки,
        # так как мы только тестируем функциональность
        return True
