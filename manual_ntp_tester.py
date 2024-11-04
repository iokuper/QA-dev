"""Модуль для ручного тестирования NTP."""

import logging
import time
from typing import Dict, Any, Optional, List, cast
from base_tester import BaseTester
from network_utils import SSHManager, RedfishManager
from datetime import datetime


class ManualNTPTester(BaseTester):
    """Класс для ручного тестирования NTP."""

    def __init__(
        self,
        config_file: str = 'config.ini',
        logger: Optional[logging.Logger] = None
    ) -> None:
        """
        Инициализирует Manual NTP тестер.

        Args:
            config_file: Путь к файлу конфигурации
            logger: Логгер для вывода сообщений
        """
        super().__init__(config_file, logger)

        # Загрузка конфигурации Manual NTP
        ntp_config = self.config_manager.get_network_config('ManualNTP')
        self.interface = cast(str, ntp_config.get('interface', '1'))

        # Параметры NTP
        self.ntp_servers = cast(
            List[str],
            ntp_config.get('ntp_servers', '').split(',')
        )
        self.max_offset = float(ntp_config.get('max_offset', '1.0'))
        self.sync_timeout = int(ntp_config.get('sync_timeout', '300'))

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

        # Инициализация других тестеров
        self.ssh_tester = SSHManager(config_file, logger)
        self.redfish_tester = RedfishManager(config_file, logger)

        # Сохранение исходных настроек
        self.original_ntp_settings: Dict[str, Any] = {}

        self.logger.debug("Инициализация Manual NTP тестера завершена")

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

    def setup_ntp_servers(self, servers: List[str]) -> bool:
        """
        Настраивает NTP серверы вручную.

        Args:
            servers: Список NTP серверов

        Returns:
            bool: True если настройка успешна
        """
        try:
            if not self.ssh_tester.connect():
                raise RuntimeError("Не удалось установить SSH соединение")

            # Останавливаем службу NTP
            command = "sudo systemctl stop ntp"
            result = self.ssh_tester.execute_command(command)
            if not result['success']:
                raise RuntimeError("Не удалось остановить службу NTP")

            # Создаем новый конфиг
            ntp_config = "\n".join([f"server {server} iburst" for server in servers])
            command = f"echo '{ntp_config}' | sudo tee /etc/ntp.conf"
            result = self.ssh_tester.execute_command(command)
            if not result['success']:
                raise RuntimeError("Не удалось создать конфиг NTP")

            # Запускаем службу NTP
            command = "sudo systemctl start ntp"
            result = self.ssh_tester.execute_command(command)
            if not result['success']:
                raise RuntimeError("Не удалось запустить службу NTP")

            # Ждем синхронизации
            time.sleep(10)

            # Проверяем настройки
            settings = self._get_ssh_ntp_settings()
            if not settings:
                raise RuntimeError("Не удалось получить настройки NTP")

            return True

        except Exception as e:
            self.logger.error(f"Ошибка при настройке NTP серверов: {e}")
            return False
        finally:
            self.ssh_tester.disconnect()

    def verify_ntp_sync(self) -> bool:
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

            # Получаем смещение времени
            command = "ntpq -c rv"
            result = self.ssh_tester.execute_command(command)
            if not result['success']:
                raise RuntimeError("Не удалось получить смещение времени")

            offset = self._parse_time_offset(result['output'])
            if offset is None or abs(offset) > self.max_offset:
                self.logger.error(
                    f"Превышено максимальное смещение времени: "
                    f"{offset} > {self.max_offset}"
                )
                return False

            return True

        except Exception as e:
            self.logger.error(f"Ошибка при проверке синхронизации NTP: {e}")
            return False
        finally:
            self.ssh_tester.disconnect()

    def _parse_time_offset(self, output: str) -> Optional[float]:
        """
        Разбирает вывод ntpq для получения смещения времени.

        Args:
            output: Вывод команды ntpq

        Returns:
            Optional[float]: Смещение времени или None при ошибке
        """
        try:
            for line in output.splitlines():
                if 'offset=' in line:
                    offset_str = line.split('offset=')[1].split(',')[0]
                    return float(offset_str)
            return None
        except Exception as e:
            self.logger.error(f"Ошибка при разборе смещения времени: {e}")
            return None

    def perform_tests(self) -> None:
        """Выполняет тестирование ручной настройки NTP."""
        try:
            self.logger.info("Начало тестирования ручной настройки NTP")

            # Сохраняем текущие настройки
            if self.backup_settings:
                self.original_ntp_settings = self.get_current_settings()

            # Настраиваем NTP серверы
            if not self.setup_ntp_servers(self.ntp_servers):
                raise RuntimeError("Не удалось настроить NTP серверы")

            # Ждем синхронизации
            start_time = time.time()
            while time.time() - start_time < self.sync_timeout:
                if self.verify_ntp_sync():
                    break
                time.sleep(self.retry_delay)
            else:
                raise RuntimeError("Таймаут синхронизации NTP")

            # Проверяем синхронизацию
            if not self.verify_ntp_sync():
                raise RuntimeError("Проверка синхронизации NTP не прошла")

            self.add_test_result('Manual NTP Configuration Test', True)
            self.add_test_result('NTP Synchronization Test', True)

        except Exception as e:
            self.logger.error(f"Ошибка при выполнении тестов: {e}")
            self.add_test_result('Manual NTP Tests', False, str(e))
        finally:
            self.safe_restore_settings()

    def restore_settings(self) -> bool:
        """
        Восстанавливает исходные настройки NTP.

        Returns:
            bool: True если восстановление успешно
        """
        try:
            if not self.original_ntp_settings:
                self.logger.info("Нет сохраненных настроек для восстан��вления")
                return True

            # Восстанавливаем через IPMI
            original_servers = self.original_ntp_settings.get('ipmi', {}).get('servers', [])
            if original_servers:
                if not self.setup_ntp_servers(original_servers):
                    raise RuntimeError(
                        "Не удалось восстановить исходные NTP серверы"
                    )

            return True

        except Exception as e:
            self.logger.error(f"Ошибка при восстановлении настроек: {e}")
            return False
