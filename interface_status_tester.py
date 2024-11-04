"""Модуль для тестирования статуса сетевых интерфейсов."""

import logging
import time
from typing import Dict, Any, Optional, List, cast
from base_tester import BaseTester
from network_utils import SSHManager, RedfishManager


class InterfaceStatusTester(BaseTester):
    """Класс для тестирования статуса сетевых интерфейсов."""

    # Константы для состояний интерфейса
    STATE_UP = "up"
    STATE_DOWN = "down"

    def __init__(
        self,
        config_file: str = 'config.ini',
        logger: Optional[logging.Logger] = None
    ) -> None:
        """
        Инициализирует Interface Status тестер.

        Args:
            config_file: Путь к файлу конфигурации
            logger: Логгер для вывода сообщений
        """
        super().__init__(config_file, logger)

        # Загрузка конфигурации Interface Status
        status_config = self.config_manager.get_network_config('InterfaceStatus')
        self.interface = cast(str, status_config.get('interface', '1'))

        # Таймауты и повторы
        self.status_timeout = int(status_config.get('status_timeout', '60'))
        self.verify_timeout = int(status_config.get('verify_timeout', '60'))
        self.retry_count = int(status_config.get('retry_count', '3'))
        self.retry_delay = int(status_config.get('retry_delay', '10'))

        # Дополнительные параметры
        self.verify_access = status_config.get(
            'verify_access',
            'true'
        ).lower() == 'true'
        self.check_all_interfaces = status_config.get(
            'check_all_interfaces',
            'true'
        ).lower() == 'true'
        self.force_status = status_config.get(
            'force_status',
            'false'
        ).lower() == 'true'

        # Инициализация других тестеров
        self.ssh_tester = SSHManager(config_file, logger)
        self.redfish_tester = RedfishManager(config_file, logger)

        # Сохранение исходных настроек
        self.original_state: Optional[str] = None

        self.logger.debug("Инициализация Interface Status тестера завершена")

    def get_interface_status(self) -> Dict[str, str]:
        """
        Получает текущий статус интерфейса через все протоколы.

        Returns:
            Dict[str, str]: Статус через разные интерфейсы
        """
        states = {
            'ipmi': self._get_ipmi_interface_status(),
            'redfish': self._get_redfish_interface_status(),
            'ssh': self._get_ssh_interface_status()
        }
        return states

    def _get_ipmi_interface_status(self) -> str:
        """
        Получает статус интерфейса через IPMI.

        Returns:
            str: Статус интерфейса
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

            for line in result.stdout.splitlines():
                if 'Link Status' in line:
                    return line.split(':')[1].strip().lower()

            return ""

        except Exception as e:
            self.logger.error(
                f"Ошибка при получении статуса через IPMI: {e}"
            )
            return ""

    def _get_redfish_interface_status(self) -> str:
        """
        Получает статус интерфейса через Redfish API.

        Returns:
            str: Статус интерфейса
        """
        try:
            endpoint = (
                f"/redfish/v1/Managers/Self/EthernetInterfaces/{self.interface}"
            )
            response = self.redfish_tester.run_request("GET", endpoint)
            if not response:
                raise RuntimeError("Не удалось получить статус")

            data = response.json()
            return data.get('LinkStatus', '').lower()

        except Exception as e:
            self.logger.error(
                f"Ошибка при получении статуса через Redfish: {e}"
            )
            return ""

    def _get_ssh_interface_status(self) -> str:
        """
        Получает статус интерфейса через SSH.

        Returns:
            str: Статус интерфейса
        """
        try:
            if not self.ssh_tester.connect():
                raise RuntimeError("Не удалось установить SSH соединение")

            command = "ip link show"
            result = self.ssh_tester.execute_command(command)
            if not result['success']:
                raise RuntimeError("Не удалось получить статус")

            for line in result['output'].splitlines():
                if 'state' in line.lower():
                    return line.split('state')[1].split()[0].lower()

            return ""

        except Exception as e:
            self.logger.error(
                f"Ошибка при получении статуса через SSH: {e}"
            )
            return ""
        finally:
            self.ssh_tester.disconnect()

    def set_interface_status(self, status: str) -> bool:
        """
        Устанавливает статус интерфейса.

        Args:
            status: Требуемый статус

        Returns:
            bool: True если изменение успешно
        """
        try:
            if status not in [self.STATE_UP, self.STATE_DOWN]:
                raise ValueError(f"Некорректный статус: {status}")

            command = [
                "ipmitool", "-I", "lanplus",
                "-H", cast(str, self.ipmi_host),
                "-U", self.ipmi_username,
                "-P", self.ipmi_password,
                "lan", "set", self.interface,
                "access", status
            ]
            if self.force_status:
                command.append("-f")

            self._run_command(command)
            time.sleep(5)

            # Ждем изменения статуса
            if not self.wait_for_interface_status(status):
                raise RuntimeError(
                    f"Не удалось дождаться статуса: {status}"
                )

            return True

        except Exception as e:
            self.logger.error(f"Ошибка при установке статуса: {e}")
            return False

    def wait_for_interface_status(self, expected_status: str) -> bool:
        """
        Ожидает установки определенного статуса интерфейса.

        Args:
            expected_status: Ожидаемый статус

        Returns:
            bool: True если статус установлен
        """
        try:
            start_time = time.time()
            while time.time() - start_time < self.status_timeout:
                current_status = self._get_ipmi_interface_status()
                if current_status == expected_status:
                    return True
                time.sleep(self.retry_delay)

            self.logger.error(
                f"Таймаут ожидания статуса: {expected_status}"
            )
            return False

        except Exception as e:
            self.logger.error(f"Ошибка при ожидании статуса: {e}")
            return False

    def verify_interface_status(self) -> bool:
        """
        Проверяет соответствие статусов через все интерфейсы.

        Returns:
            bool: True если статусы совпадают
        """
        try:
            states = self.get_interface_status()
            if not all(states.values()):
                raise RuntimeError(
                    "Не удалось получить статус через все интерфейсы"
                )

            # Проверяем соответствие статусов
            if len(set(states.values())) > 1:
                self.logger.error(
                    f"Несоответствие статусов: {states}"
                )
                return False

            return True

        except Exception as e:
            self.logger.error(f"Ошибка при проверке статусов: {e}")
            return False

    def test_interface_cycle(self) -> bool:
        """
        Тестирует цикл включения/выключения интерфейса.

        Returns:
            bool: True если тест успешен
        """
        try:
            # Включаем интерфейс
            if not self.set_interface_status(self.STATE_UP):
                raise RuntimeError("Не удалось включить интерфейс")

            # Проверяем статус
            if not self.verify_interface_status():
                raise RuntimeError("Несоответствие статусов после включения")

            # Выключаем интерфейс
            if not self.set_interface_status(self.STATE_DOWN):
                raise RuntimeError("Не удалось выключить интерфейс")

            # Проверяем статус
            if not self.verify_interface_status():
                raise RuntimeError("Несоответствие статусов после выключения")

            # Снова включаем интерфейс
            if not self.set_interface_status(self.STATE_UP):
                raise RuntimeError("Не удалось повторно включить интерфейс")

            # Проверяем статус
            if not self.verify_interface_status():
                raise RuntimeError(
                    "Несоответствие статусов после повторного включения"
                )

            return True

        except Exception as e:
            self.logger.error(f"Ошибка при тестировании цикла: {e}")
            return False

    def perform_tests(self) -> None:
        """Выполняет тестирование статуса интерфейса."""
        try:
            self.logger.info("Начало тестирования статуса интерфейса")

            # Сохраняем текущий статус
            self.original_state = self._get_ipmi_interface_status()

            # Тестируем цикл включения/выключения
            if not self.test_interface_cycle():
                raise RuntimeError("Тест цикла не прошел")

            self.add_test_result('Interface Status Cycle Test', True)
            self.add_test_result('Interface Status Verification Test', True)

        except Exception as e:
            self.logger.error(f"Ошибка при выполнении тестов: {e}")
            self.add_test_result('Interface Status Tests', False, str(e))
        finally:
            self.safe_restore_settings()

    def restore_settings(self) -> bool:
        """
        Восстанавливает исходный статус интерфейса.

        Returns:
            bool: True если восстановление успешно
        """
        try:
            if not self.original_state:
                self.logger.info(
                    "Нет сохраненного статуса для восстановления"
                )
                return True

            return self.set_interface_status(self.original_state)

        except Exception as e:
            self.logger.error(f"Ошибка при восстановлении статуса: {e}")
            return False
