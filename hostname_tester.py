"""Модуль для тестирования настройки имени хоста."""

import logging
import time
import re
from typing import Optional, List, Dict, Any, cast
from base_tester import BaseTester
from network_utils import SSHManager, RedfishManager, ALLOWED_HOSTNAME_CHARS


class HostnameTester(BaseTester):
    """Класс для тестирования настройки имени хоста."""

    def __init__(
        self,
        config_file: str = 'config.ini',
        logger: Optional[logging.Logger] = None
    ) -> None:
        """
        Инициализирует Hostname тестер.

        Args:
            config_file: Путь к файлу конфигурации
            logger: Логгер для вывода сообщений
        """
        super().__init__(config_file, logger)

        # Загрузка конфигурации Hostname
        hostname_config = self.config_manager.get_network_config('Hostname')
        self.max_length = int(hostname_config.get('max_length', '64'))
        self.min_length = int(hostname_config.get('min_length', '1'))
        self.test_hostname = cast(
            str,
            hostname_config.get('test_hostname', 'test-bmc')
        )

        # Таймауты и повторы
        self.setup_timeout = int(hostname_config.get('setup_timeout', '30'))
        self.verify_timeout = int(hostname_config.get('verify_timeout', '60'))
        self.retry_count = int(hostname_config.get('retry_count', '3'))
        self.retry_delay = int(hostname_config.get('retry_delay', '10'))

        # Дополнительные параметры
        self.verify_dns = hostname_config.get(
            'verify_dns',
            'true'
        ).lower() == 'true'
        self.backup_settings = hostname_config.get(
            'backup_settings',
            'true'
        ).lower() == 'true'
        self.check_all_interfaces = hostname_config.get(
            'check_all_interfaces',
            'true'
        ).lower() == 'true'

        # Инициализация других тестеров
        self.ssh_tester = SSHManager(config_file, logger)
        self.redfish_tester = RedfishManager(config_file, logger)

        # Сохранение исходных настроек
        self.original_hostname: Optional[str] = None

        self.logger.debug("Инициализация Hostname тестера завершена")

    def get_current_settings(self) -> Dict[str, Any]:
        """
        Получает текущие настройки имени хоста через все интерфейсы.

        Returns:
            Dict[str, Any]: Текущие настройки
        """
        try:
            settings = {
                'ipmi': self._get_ipmi_hostname(),
                'redfish': self._get_redfish_hostname(),
                'ssh': self._get_ssh_hostname()
            }
            return settings

        except Exception as e:
            self.logger.error(f"Ошибка при получении настроек: {e}")
            return {}

    def _get_ipmi_hostname(self) -> Dict[str, str]:
        """
        Получает имя хоста через IPMI.

        Returns:
            Dict[str, str]: Настройки имени хоста
        """
        try:
            command = [
                "ipmitool", "-I", "lanplus",
                "-H", cast(str, self.ipmi_host),
                "-U", self.ipmi_username,
                "-P", self.ipmi_password,
                "mc", "getsysinfo", "hostname"
            ]
            result = self._run_command(command)
            return {'hostname': result.stdout.strip()}

        except Exception as e:
            self.logger.error(f"Ошибка при получении имени хоста через IPMI: {e}")
            return {}

    def _get_redfish_hostname(self) -> Dict[str, str]:
        """
        Получает имя хоста через Redfish API.

        Returns:
            Dict[str, str]: Настройки имени хоста
        """
        try:
            endpoint = "/redfish/v1/Managers/Self"
            response = self.redfish_tester.run_request("GET", endpoint)
            if not response:
                raise RuntimeError("Не удалось получить данные через Redfish")

            data = response.json()
            return {'hostname': data.get('HostName', '')}

        except Exception as e:
            self.logger.error(
                f"Ошибка при получении имени хоста через Redfish: {e}"
            )
            return {}

    def _get_ssh_hostname(self) -> Dict[str, str]:
        """
        Получает имя хоста через SSH.

        Returns:
            Dict[str, str]: Настройки имени хоста
        """
        try:
            if not self.ssh_tester.connect():
                raise RuntimeError("Не удалось установить SSH соединение")

            command = "hostname"
            result = self.ssh_tester.execute_command(command)
            if not result['success']:
                raise RuntimeError("Не удалось получить имя хоста")

            return {'hostname': result['output'].strip()}

        except Exception as e:
            self.logger.error(f"Ошибка при получении имени хоста через SSH: {e}")
            return {}
        finally:
            self.ssh_tester.disconnect()

    def setup_hostname_via_ipmi(self, hostname: str) -> bool:
        """
        Устанавливает имя хоста через IPMI.

        Args:
            hostname: Новое имя хоста

        Returns:
            bool: True если установка успешна
        """
        try:
            if not self._validate_hostname(hostname):
                raise ValueError(f"Некорректное имя хоста: {hostname}")

            command = [
                "ipmitool", "-I", "lanplus",
                "-H", cast(str, self.ipmi_host),
                "-U", self.ipmi_username,
                "-P", self.ipmi_password,
                "mc", "setsysinfo", "hostname", hostname
            ]
            self._run_command(command)
            time.sleep(5)

            # Проверяем настройки
            settings = self._get_ipmi_hostname()
            if not settings:
                raise RuntimeError("Не удалось получить настройки")

            if settings.get('hostname') != hostname:
                raise RuntimeError("Имя хоста не применилось")

            return True

        except Exception as e:
            self.logger.error(f"Ошибка при установке имени хоста через IPMI: {e}")
            return False

    def setup_hostname_via_redfish(self, hostname: str) -> bool:
        """
        Устанавливает имя хоста через Redfish API.

        Args:
            hostname: Новое имя хоста

        Returns:
            bool: True если установка успешна
        """
        try:
            if not self._validate_hostname(hostname):
                raise ValueError(f"Некорректное имя хоста: {hostname}")

            endpoint = "/redfish/v1/Managers/Self"
            data = {"HostName": hostname}

            response = self.redfish_tester.run_request(
                "PATCH",
                endpoint,
                data=data
            )
            if not response:
                raise RuntimeError("Не удалось применить настройки")

            time.sleep(5)

            # Проверяем настройки
            settings = self._get_redfish_hostname()
            if not settings:
                raise RuntimeError("Не удалось получить настройки")

            if settings.get('hostname') != hostname:
                raise RuntimeError("Имя хоста не применилось")

            return True

        except Exception as e:
            self.logger.error(
                f"Ошибка при установке имени хоста через Redfish: {e}"
            )
            return False

    def setup_hostname_via_ssh(self, hostname: str) -> bool:
        """
        Устанавливает имя хоста через SSH.

        Args:
            hostname: Новое имя хоста

        Returns:
            bool: True если установка успешна
        """
        try:
            if not self._validate_hostname(hostname):
                raise ValueError(f"Некорректное имя хоста: {hostname}")

            if not self.ssh_tester.connect():
                raise RuntimeError("Не удалось установить SSH соединение")

            # Устанавливаем имя хоста
            commands = [
                f"sudo hostnamectl set-hostname {hostname}",
                f"echo '{hostname}' | sudo tee /etc/hostname",
                "sudo systemctl restart systemd-hostnamed"
            ]

            for cmd in commands:
                result = self.ssh_tester.execute_command(cmd)
                if not result['success']:
                    raise RuntimeError(f"Не удалось выполнить команду: {cmd}")

            time.sleep(5)

            # Проверяем настройки
            settings = self._get_ssh_hostname()
            if not settings:
                raise RuntimeError("Не удалось получить настройки")

            if settings.get('hostname') != hostname:
                raise RuntimeError("Имя хоста не применилось")

            return True

        except Exception as e:
            self.logger.error(f"Ошибка при установке имени хоста через SSH: {e}")
            return False
        finally:
            self.ssh_tester.disconnect()

    def _validate_hostname(self, hostname: str) -> bool:
        """
        Проверяет корректность имени хоста.

        Args:
            hostname: Имя хоста для проверки

        Returns:
            bool: True если имя хоста корректно
        """
        try:
            # Проверяем длину
            if not self.min_length <= len(hostname) <= self.max_length:
                self.logger.error(
                    f"Длина имени хоста должна быть от {self.min_length} "
                    f"до {self.max_length} символов"
                )
                return False

            # Проверяем допустимые символы
            if not all(c in ALLOWED_HOSTNAME_CHARS for c in hostname):
                self.logger.error("Имя хоста содержит недопустимые символы")
                return False

            # Проверяем начало и конец
            if hostname[0] == '-' or hostname[-1] == '-':
                self.logger.error(
                    "Имя хоста не может начинаться или заканчиваться дефисом"
                )
                return False

            # Проверяем формат RFC 1123
            if not re.match(r'^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?$', hostname):
                self.logger.error("Имя хоста не соответствует формату RFC 1123")
                return False

            return True

        except Exception as e:
            self.logger.error(f"Ошибка при валидации имени хоста: {e}")
            return False

    def test_invalid_settings(self) -> bool:
        """
        Тестирует установку некорректных имен хоста.

        Returns:
            bool: True если тест прошел успешно
        """
        try:
            invalid_hostnames = [
                "",  # Пустое имя
                "a" * (self.max_length + 1),  # Слишком длинное
                "host@name",  # Недопустимые символы
                "-hostname",  # Начинается с дефиса
                "hostname-",  # Заканчивается дефисом
                "host name",  # Пробелы
                "host.name",  # Точки
                "host_name",  # Подчеркивания
                "1234",  # Только цифры
                "host#name",  # Специальные символы
                "HOSTNAME",  # Только заглавные
                "h" * 64  # Максимальная длина + 1
            ]

            for hostname in invalid_hostnames:
                if self.setup_hostname_via_ipmi(hostname):
                    self.logger.error(
                        f"Некорректное имя хоста {hostname} было принято"
                    )
                    return False
                self.logger.info(
                    f"Некорректное имя хоста {hostname} было отклонено"
                )

            return True

        except Exception as e:
            self.logger.error(
                f"Ошибка при тестировании некорректных имен хоста: {e}"
            )
            return False

    def verify_hostname_settings(self) -> bool:
        """
        Проверяет настройки имени хоста через все интерфейсы.

        Returns:
            bool: True если проверка успешна
        """
        try:
            settings = self.get_current_settings()
            if not all(settings.values()):
                raise RuntimeError(
                    "Не удалось получить настройки через все интерфейсы"
                )

            # Сравниваем имена хостов
            hostnames = {
                source: data.get('hostname')
                for source, data in settings.items()
            }

            if len(set(hostnames.values())) > 1:
                self.logger.error(
                    f"Несоответствие имен хоста между интерфейсами: {hostnames}"
                )
                return False

            # Проверяем соответствие тестовому имени хоста
            current_hostname = next(iter(hostnames.values()))
            if current_hostname != self.test_hostname:
                self.logger.error(
                    f"Имя хоста не соответствует тестовому: "
                    f"{current_hostname} != {self.test_hostname}"
                )
                return False

            # Проверяем разрешение DNS если требуется
            if self.verify_dns:
                if not self._verify_dns_resolution():
                    return False

            return True

        except Exception as e:
            self.logger.error(f"Ошибка при проверке настроек имени хоста: {e}")
            return False

    def _verify_dns_resolution(self) -> bool:
        """
        Проверяет разрешение имени хоста через DNS.

        Returns:
            bool: True если проверка успешна
        """
        try:
            if not self.ssh_tester.connect():
                raise RuntimeError("Не удалось установить SSH соединение")

            # Проверяем прямое разрешение
            command = f"dig +short {self.test_hostname}"
            result = self.ssh_tester.execute_command(command)
            if not result['success'] or not result['output']:
                self.logger.error(
                    f"Не удалось разрешить имя хоста {self.test_hostname}"
                )
                return False

            # Проверяем обратное разрешение
            ip = result['output'].strip()
            command = f"dig +short -x {ip}"
            result = self.ssh_tester.execute_command(command)
            if not result['success'] or not result['output']:
                self.logger.error(f"Не удалось выполнить обратное разрешение {ip}")
                return False

            return True

        except Exception as e:
            self.logger.error(f"Ошибка при проверке DNS разрешения: {e}")
            return False
        finally:
            self.ssh_tester.disconnect()

    def perform_tests(self) -> None:
        """Выполняет тестирование настройки имени хоста."""
        try:
            self.logger.info("Начало тестирования настройки имени хоста")

            # Сохраняем текущие настройки
            if self.backup_settings:
                settings = self._get_ipmi_hostname()
                self.original_hostname = settings.get('hostname')

            # Настройка через IPMI
            if not self.setup_hostname_via_ipmi(self.test_hostname):
                raise RuntimeError("Не удалось настроить имя хоста через IPMI")

            # Проверка настроек
            if not self.verify_hostname_settings():
                raise RuntimeError("Верификация настроек имени хоста не прошла")

            # Настройка через Redfish
            if not self.setup_hostname_via_redfish(self.test_hostname):
                raise RuntimeError("Не удалось настроить имя хоста через Redfish")

            # Проверка настроек
            if not self.verify_hostname_settings():
                raise RuntimeError("Верификация настроек имени хоста не прошла")

            # Настройка через SSH
            if not self.setup_hostname_via_ssh(self.test_hostname):
                raise RuntimeError("Не удалось настроить имя хоста через SSH")

            # Проверка настроек
            if not self.verify_hostname_settings():
                raise RuntimeError("Верификация настроек имени хоста не прошла")

            # Тестирование некорректных настроек
            if not self.test_invalid_settings():
                raise RuntimeError("Тест некорректных настроек не прошел")

            self.add_test_result('Hostname Configuration Test', True)
            self.add_test_result('Hostname Verification Test', True)

        except Exception as e:
            self.logger.error(f"Ошибка при выполнении тестов: {e}")
            self.add_test_result('Hostname Tests', False, str(e))
        finally:
            self.safe_restore_settings()

    def restore_settings(self) -> bool:
        """
        Восстанавливает исходные настройки имени хоста.

        Returns:
            bool: True если восстановление успешно
        """
        try:
            if not self.original_hostname:
                self.logger.info("Нет сохраненного имени хоста")
                return True

            return self.setup_hostname_via_ipmi(self.original_hostname)

        except Exception as e:
            self.logger.error(f"Ошибка при восстановлении настроек: {e}")
            return False
