"""Модуль для тестирования настройки NTP."""

import logging
import time
from typing import Dict, Any, Optional, List, cast
from base_tester import BaseTester
from network_utils import SSHManager, RedfishManager


class NTPTester(BaseTester):
    """Класс для тестирования настройки NTP."""

    def __init__(
        self,
        config_file: str = 'config.ini',
        logger: Optional[logging.Logger] = None
    ) -> None:
        """
        Инициализирует NTP тестер.

        Args:
            config_file: Путь к файлу конфигурации
            logger: Логгер для вывода сообщений
        """
        super().__init__(config_file, logger)

        # Загрузка конфигурации NTP
        ntp_config = self.config_manager.get_network_config('NTP')
        self.interface = cast(str, ntp_config.get('interface', '1'))

        # Параметры NTP
        self.primary_ntp = cast(str, ntp_config.get('primary_ntp'))
        self.secondary_ntp = cast(str, ntp_config.get('secondary_ntp'))
        self.max_time_diff = float(ntp_config.get('max_time_diff', '1.0'))

        # Таймауты и повторы
        self.setup_timeout = int(ntp_config.get('setup_timeout', '30'))
        self.verify_timeout = int(ntp_config.get('verify_timeout', '60'))
        self.retry_count = int(ntp_config.get('retry_count', '3'))
        self.retry_delay = int(ntp_config.get('retry_delay', '10'))

        # Дополнительные параметры
        self.verify_sync = ntp_config.get(
            'verify_sync',
            'true'
        ).lower() == 'true'
        self.backup_settings = ntp_config.get(
            'backup_settings',
            'true'
        ).lower() == 'true'
        self.check_both_servers = ntp_config.get(
            'check_both_servers',
            'true'
        ).lower() == 'true'

        # Инициализация других тестеров
        self.ssh_tester = SSHManager(config_file, logger)
        self.redfish_tester = RedfishManager(config_file, logger)

        # Сохранение исходных настроек
        self.original_settings: Dict[str, Any] = {}

        self.logger.debug("Инициализация NTP тестера завершена")

    def get_current_settings(self) -> Dict[str, Any]:
        """
        Получает текущие настройки NTP через все интерфейсы.

        Returns:
            Dict[str, Any]: Текущие настройки
        """
        settings = {
            'ipmi': self._get_ipmi_ntp_settings(),
            'redfish': self._get_redfish_ntp_settings(),
            'ssh': self._get_ssh_ntp_settings()
        }
        return settings

    def _get_ipmi_ntp_settings(self) -> Dict[str, str]:
        """
        Получает настройки NTP через IPMI.

        Returns:
            Dict[str, str]: Настройки NTP
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

            settings = {}
            for line in result.stdout.splitlines():
                if 'NTP Server 1' in line:
                    settings['primary_ntp'] = line.split(':')[1].strip()
                elif 'NTP Server 2' in line:
                    settings['secondary_ntp'] = line.split(':')[1].strip()

            return settings

        except Exception as e:
            self.logger.error(f"Ошибка при получении NTP через IPMI: {e}")
            return {}

    def _get_redfish_ntp_settings(self) -> Dict[str, str]:
        """
        Получает настройки NTP через Redfish API.

        Returns:
            Dict[str, str]: Настройки NTP
        """
        try:
            endpoint = "/redfish/v1/Managers/Self/NetworkProtocol"
            response = self.redfish_tester.run_request("GET", endpoint)
            if not response:
                raise RuntimeError("Не удалось получить настройки")

            data = response.json()
            ntp_data = data.get('NTP', {})
            servers = ntp_data.get('NTPServers', [])

            settings = {
                'primary_ntp': servers[0] if len(servers) > 0 else '',
                'secondary_ntp': servers[1] if len(servers) > 1 else ''
            }

            return settings

        except Exception as e:
            self.logger.error(f"Ошибка при получении NTP через Redfish: {e}")
            return {}

    def _get_ssh_ntp_settings(self) -> Dict[str, str]:
        """
        Получает настройки NTP через SSH.

        Returns:
            Dict[str, str]: Настройки NTP
        """
        try:
            if not self.ssh_tester.connect():
                raise RuntimeError("Не удалось установить SSH соединение")

            command = "cat /etc/ntp.conf"
            result = self.ssh_tester.execute_command(command)
            if not result['success']:
                raise RuntimeError("Не удалось получить настройки NTP")

            settings = {'primary_ntp': '', 'secondary_ntp': ''}
            servers = []
            for line in result['output'].splitlines():
                if line.startswith('server'):
                    servers.append(line.split()[1])

            if len(servers) > 0:
                settings['primary_ntp'] = servers[0]
            if len(servers) > 1:
                settings['secondary_ntp'] = servers[1]

            return settings

        except Exception as e:
            self.logger.error(f"Ошибка при получении NTP через SSH: {e}")
            return {}
        finally:
            self.ssh_tester.disconnect()

    def setup_ntp_via_ipmi(self) -> bool:
        """
        Настраивает NTP через IPMI.

        Returns:
            bool: True если настройка успешна
        """
        try:
            # Устанавливаем первичный NTP
            command = [
                "ipmitool", "-I", "lanplus",
                "-H", cast(str, self.ipmi_host),
                "-U", self.ipmi_username,
                "-P", self.ipmi_password,
                "lan", "set", self.interface,
                "ntp1", self.primary_ntp
            ]
            self._run_command(command)
            time.sleep(2)

            # Устанавливаем вторичный NTP
            command = [
                "ipmitool", "-I", "lanplus",
                "-H", cast(str, self.ipmi_host),
                "-U", self.ipmi_username,
                "-P", self.ipmi_password,
                "lan", "set", self.interface,
                "ntp2", self.secondary_ntp
            ]
            self._run_command(command)
            time.sleep(5)

            # Проверяем настройки
            settings = self._get_ipmi_ntp_settings()
            if not settings:
                raise RuntimeError("Не удалось получить настройки")

            if (
                settings.get('primary_ntp') != self.primary_ntp or
                settings.get('secondary_ntp') != self.secondary_ntp
            ):
                raise RuntimeError("Настройки NTP не применились")

            return True

        except Exception as e:
            self.logger.error(f"Ошибка при настройке NTP через IPMI: {e}")
            return False

    def setup_ntp_via_redfish(self) -> bool:
        """
        Настраивает NTP через Redfish API.

        Returns:
            bool: True если настройка успешна
        """
        try:
            endpoint = "/redfish/v1/Managers/Self/NetworkProtocol"
            data = {
                "NTP": {
                    "NTPServers": [
                        self.primary_ntp,
                        self.secondary_ntp
                    ]
                }
            }

            response = self.redfish_tester.run_request(
                "PATCH",
                endpoint,
                data=data
            )
            if not response:
                raise RuntimeError("Не удалось применить настройки")

            time.sleep(5)

            # Проверяем настройки
            settings = self._get_redfish_ntp_settings()
            if not settings:
                raise RuntimeError("Не удалось получить настройки")

            if (
                settings.get('primary_ntp') != self.primary_ntp or
                settings.get('secondary_ntp') != self.secondary_ntp
            ):
                raise RuntimeError("Настройки NTP не применились")

            return True

        except Exception as e:
            self.logger.error(f"Ошибка при настройке NTP через Redfish: {e}")
            return False

    def setup_ntp_via_ssh(self) -> bool:
        """
        Настраивает NTP через SSH.

        Returns:
            bool: True если настройка успешна
        """
        try:
            if not self.ssh_tester.connect():
                raise RuntimeError("Не удалось установить SSH соединение")

            # Создаем конфигурацию NTP
            ntp_config = (
                "server {primary}\n"
                "server {secondary}\n"
            ).format(
                primary=self.primary_ntp,
                secondary=self.secondary_ntp
            )

            # Записываем конфигурацию
            command = f"echo '{ntp_config}' | sudo tee /etc/ntp.conf"
            result = self.ssh_tester.execute_command(command)
            if not result['success']:
                raise RuntimeError("Не удалось записать конфигурацию NTP")

            # Перезапускаем службу NTP
            command = "sudo systemctl restart ntp"
            result = self.ssh_tester.execute_command(command)
            if not result['success']:
                raise RuntimeError("Не удалось перезапустить службу NTP")

            time.sleep(5)

            # Проверяем настройки
            settings = self._get_ssh_ntp_settings()
            if not settings:
                raise RuntimeError("Не удалось получить настройки")

            if (
                settings.get('primary_ntp') != self.primary_ntp or
                settings.get('secondary_ntp') != self.secondary_ntp
            ):
                raise RuntimeError("Настройки NTP не применились")

            return True

        except Exception as e:
            self.logger.error(f"Ошибка при настройке NTP через SSH: {e}")
            return False
        finally:
            self.ssh_tester.disconnect()

    def verify_ntp_settings(self) -> bool:
        """
        Проверяет настройки NTP через все интерфейсы.

        Returns:
            bool: True если проверка успешна
        """
        try:
            settings = self.get_current_settings()
            if not all(settings.values()):
                raise RuntimeError(
                    "Не удалось получить настройки через все интерфейсы"
                )

            # Проверяем первичный NTP
            primary_ntp = {
                source: settings['primary_ntp']
                for source, settings in settings.items()
            }
            if len(set(primary_ntp.values())) > 1:
                self.logger.error(
                    f"Несоответствие первичного NTP: {primary_ntp}"
                )
                return False

            # Проверяем вторичный NTP
            secondary_ntp = {
                source: settings['secondary_ntp']
                for source, settings in settings.items()
            }
            if len(set(secondary_ntp.values())) > 1:
                self.logger.error(
                    f"Несоответствие вторичного NTP: {secondary_ntp}"
                )
                return False

            # Проверяем синхронизацию если требуется
            if self.verify_sync:
                if not self._verify_ntp_sync():
                    return False

            return True

        except Exception as e:
            self.logger.error(f"Ошибка при проверке настроек NTP: {e}")
            return False

    def _verify_ntp_sync(self) -> bool:
        """
        Проверяет синхронизацию с NTP серверами.

        Returns:
            bool: True если синхронизация успешна
        """
        try:
            if not self.ssh_tester.connect():
                raise RuntimeError("Не удалось установить SSH соединение")

            # Проверяем статус синхронизации
            command = "ntpq -p"
            result = self.ssh_tester.execute_command(command)
            if not result['success']:
                raise RuntimeError("Не удалось получить статус NTP")

            # Проверяем наличие активных серверов
            active_servers = []
            for line in result['output'].splitlines():
                if '*' in line:  # Активный сервер
                    active_servers.append(line)

            if not active_servers:
                self.logger.error("Нет активных NTP серверов")
                return False

            # Проверяем смещение времени
            command = "ntpq -c rv"
            result = self.ssh_tester.execute_command(command)
            if result['success'] and 'offset=' in result['output']:
                offset = float(
                    result['output'].split('offset=')[1].split(',')[0]
                )
                if abs(offset) > self.max_time_diff:
                    self.logger.error(
                        f"Смещение времени {offset} превышает "
                        f"допустимое {self.max_time_diff}"
                    )
                    return False

            return True

        except Exception as e:
            self.logger.error(f"Ошибка при проверке синхронизации NTP: {e}")
            return False
        finally:
            self.ssh_tester.disconnect()

    def test_invalid_settings(self) -> bool:
        """
        Тестирует установку некорректных NTP серверов.

        Returns:
            bool: True если тест прошел успешно
        """
        try:
            # Получаем некорректные настройки
            invalid_servers = [
                '256.256.256.256',  # Некорректный IP
                '0.0.0.0',  # Нулевой IP
                'invalid.ntp',  # Некорректное имя
                '192.168.1',  # Неполный IP
                '300.300.300.300'  # IP вне диапазона
            ]

            # Сохраняем текущие настройки
            original_settings = self._get_ipmi_ntp_settings()

            # Тестируем некорректные NTP серверы
            for invalid_server in invalid_servers:
                command = [
                    "ipmitool", "-I", "lanplus",
                    "-H", cast(str, self.ipmi_host),
                    "-U", self.ipmi_username,
                    "-P", self.ipmi_password,
                    "lan", "set", self.interface,
                    "ntp1", invalid_server
                ]
                try:
                    self._run_command(command)
                    self.logger.error(
                        f"Некорректный NTP сервер {invalid_server} был принят"
                    )
                    return False
                except Exception:
                    self.logger.info(
                        f"Некорректный NTP сервер {invalid_server} был отклонен"
                    )

            # Проверяем, что настройки не изменились
            current_settings = self._get_ipmi_ntp_settings()
            if current_settings != original_settings:
                self.logger.error(
                    "Настройки изменились после тестов некорректных значений"
                )
                return False

            return True

        except Exception as e:
            self.logger.error(
                f"Ошибка при тестировании некорректных настроек: {e}"
            )
            return False

    def perform_tests(self) -> None:
        """Выполняет тестирование настройки NTP."""
        try:
            self.logger.info("Начало тестирования настройки NTP")

            # Сохраняем текущие настройки
            if self.backup_settings:
                self.original_settings = self.get_current_settings()

            # Настройка через IPMI
            if not self.setup_ntp_via_ipmi():
                raise RuntimeError("Не удалось настроить NTP через IPMI")

            # Проверка настроек
            if not self.verify_ntp_settings():
                raise RuntimeError("Верификация настроек NTP не прошла")

            # Настройка через Redfish
            if not self.setup_ntp_via_redfish():
                raise RuntimeError("Не удалось настроить NTP через Redfish")

            # Проверка настроек
            if not self.verify_ntp_settings():
                raise RuntimeError("Верификация настроек NTP не прошла")

            # Настройка через SSH
            if not self.setup_ntp_via_ssh():
                raise RuntimeError("Не удалось настроить NTP через SSH")

            # Проверка настроек
            if not self.verify_ntp_settings():
                raise RuntimeError("Верификация настроек NTP не прошла")

            # Тестирование некорректных настроек
            if not self.test_invalid_settings():
                raise RuntimeError("Тест некорректных настроек не прошел")

            self.add_test_result('NTP Configuration Test', True)
            self.add_test_result('NTP Synchronization Test', True)

        except Exception as e:
            self.logger.error(f"Ошибка при выполнении тестов: {e}")
            self.add_test_result('NTP Tests', False, str(e))
        finally:
            self.safe_restore_settings()

    def restore_settings(self) -> bool:
        """
        Восстанавливает исходные настройки NTP.

        Returns:
            bool: True если восстановление успешно
        """
        try:
            if not self.original_settings:
                self.logger.info("Нет сохраненных настроек для восстановления")
                return True

            # Восстанавливаем через IPMI
            ipmi_settings = self.original_settings.get('ipmi', {})
            if ipmi_settings:
                self.primary_ntp = ipmi_settings.get('primary_ntp', '')
                self.secondary_ntp = ipmi_settings.get('secondary_ntp', '')
                return self.setup_ntp_via_ipmi()

            return True

        except Exception as e:
            self.logger.error(f"Ошибка при восстановлении настроек: {e}")
            return False
