"""Модуль для тестирования настройки VLAN."""

import logging
import time
from typing import Dict, Any, Optional, List, cast
from base_tester import BaseTester
from verification_utils import verify_ip_format
from network_utils import SSHManager, RedfishManager


class VLANTester(BaseTester):
    """Класс для тестирования настройки VLAN."""

    def __init__(
        self,
        config_file: str = 'config.ini',
        logger: Optional[logging.Logger] = None
    ) -> None:
        """
        Инициализирует VLAN тестер.

        Args:
            config_file: Путь к файлу конфигурации
            logger: Логгер для вывода сообщений
        """
        super().__init__(config_file, logger)

        # Загрузка конфигурации VLAN
        vlan_config = self.config_manager.get_network_config('VLAN')
        self.interface = cast(str, vlan_config.get('interface', '1'))

        # Параметры VLAN
        self.test_vlan_id = int(vlan_config.get('test_vlan_id', '100'))
        self.test_vlan_priority = int(vlan_config.get('test_vlan_priority', '0'))
        self.invalid_vlan_ids = [
            int(x) for x in vlan_config.get(
                'invalid_vlan_ids',
                '0,4095,4096'
            ).split(',')
        ]

        # Таймауты и повторы
        self.setup_timeout = int(vlan_config.get('setup_timeout', '30'))
        self.verify_timeout = int(vlan_config.get('verify_timeout', '60'))
        self.retry_count = int(vlan_config.get('retry_count', '3'))
        self.retry_delay = int(vlan_config.get('retry_delay', '10'))

        # Дополнительные параметры
        self.verify_access = vlan_config.get(
            'verify_access',
            'true'
        ).lower() == 'true'
        self.backup_settings = vlan_config.get(
            'backup_settings',
            'true'
        ).lower() == 'true'
        self.check_all_interfaces = vlan_config.get(
            'check_all_interfaces',
            'true'
        ).lower() == 'true'

        # Инициализация других тестеров
        self.ssh_tester = SSHManager(config_file, logger)
        self.redfish_tester = RedfishManager(config_file, logger)

        # Сохранение исходных настроек
        self.original_settings: Dict[str, Any] = {}

        self.logger.debug("Инициализация VLAN тестера завершена")

    def get_current_settings(self) -> Dict[str, Any]:
        """
        Получает текущие настройки VLAN через все интерфейсы.

        Returns:
            Dict[str, Any]: Текущие настройки
        """
        settings = {
            'ipmi': self._get_ipmi_vlan_settings(),
            'redfish': self._get_redfish_vlan_settings(),
            'ssh': self._get_ssh_vlan_settings()
        }
        return settings

    def _get_ipmi_vlan_settings(self) -> Dict[str, Any]:
        """
        Получает настройки VLAN через IPMI.

        Returns:
            Dict[str, Any]: Настройки VLAN
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
                if 'VLAN ID' in line:
                    settings['vlan_id'] = int(line.split(':')[1].strip())
                elif 'VLAN Priority' in line:
                    settings['vlan_priority'] = int(line.split(':')[1].strip())

            return settings

        except Exception as e:
            self.logger.error(f"Ошибка при получении настроек VLAN через IPMI: {e}")
            return {}

    def _get_redfish_vlan_settings(self) -> Dict[str, Any]:
        """
        Получает настройки VLAN через Redfish API.

        Returns:
            Dict[str, Any]: Настройки VLAN
        """
        try:
            endpoint = (
                f"/redfish/v1/Managers/Self/EthernetInterfaces/{self.interface}"
            )
            response = self.redfish_tester.run_request("GET", endpoint)
            if not response:
                raise RuntimeError("Не удалось получить настройки")

            data = response.json()
            vlan_data = data.get('VLAN', {})

            settings = {
                'vlan_id': vlan_data.get('VLANId', 0),
                'vlan_priority': vlan_data.get('VLANPriority', 0),
                'vlan_enabled': vlan_data.get('VLANEnable', False)
            }

            return settings

        except Exception as e:
            self.logger.error(
                f"Ошибка при получении настроек VLAN через Redfish: {e}"
            )
            return {}

    def _get_ssh_vlan_settings(self) -> Dict[str, Any]:
        """
        Получает настройки VLAN через SSH.

        Returns:
            Dict[str, Any]: Настройки VLAN
        """
        try:
            if not self.ssh_tester.connect():
                raise RuntimeError("Не удалось установить SSH соединение")

            command = "ip -d link show"
            result = self.ssh_tester.execute_command(command)
            if not result['success']:
                raise RuntimeError("Не удалось получить настройки VLAN")

            settings = {}
            for line in result['output'].splitlines():
                if 'vlan id' in line.lower():
                    settings['vlan_id'] = int(
                        line.split('vlan id')[1].split()[0]
                    )
                    break

            return settings

        except Exception as e:
            self.logger.error(f"Ошибка при получении настроек VLAN через SSH: {e}")
            return {}
        finally:
            self.ssh_tester.disconnect()

    def setup_vlan_via_ipmi(self, vlan_id: int, priority: int = 0) -> bool:
        """
        Настраивает VLAN через IPMI.

        Args:
            vlan_id: ID VLAN
            priority: Приоритет VLAN

        Returns:
            bool: True если настройка успешна
        """
        try:
            if not self._validate_vlan_id(vlan_id):
                raise ValueError(f"Некорректный VLAN ID: {vlan_id}")

            if not 0 <= priority <= 7:
                raise ValueError(f"Некорректный приоритет VLAN: {priority}")

            # Устанавливаем VLAN ID
            command = [
                "ipmitool", "-I", "lanplus",
                "-H", cast(str, self.ipmi_host),
                "-U", self.ipmi_username,
                "-P", self.ipmi_password,
                "lan", "set", self.interface,
                "vlan", "id", str(vlan_id)
            ]
            self._run_command(command)
            time.sleep(2)

            # Устанавливаем приоритет
            command = [
                "ipmitool", "-I", "lanplus",
                "-H", cast(str, self.ipmi_host),
                "-U", self.ipmi_username,
                "-P", self.ipmi_password,
                "lan", "set", self.interface,
                "vlan", "priority", str(priority)
            ]
            self._run_command(command)
            time.sleep(5)

            # Проверяем настройки
            settings = self._get_ipmi_vlan_settings()
            if not settings:
                raise RuntimeError("Не удалось получить настройки")

            if (
                settings.get('vlan_id') != vlan_id or
                settings.get('vlan_priority') != priority
            ):
                raise RuntimeError("Настройки VLAN не применились")

            return True

        except Exception as e:
            self.logger.error(f"Ошибка при настройке VLAN через IPMI: {e}")
            return False

    def setup_vlan_via_redfish(self, vlan_id: int, priority: int = 0) -> bool:
        """
        Настраивает VLAN через Redfish API.

        Args:
            vlan_id: ID VLAN
            priority: Приоритет VLAN

        Returns:
            bool: True если настройка успешна
        """
        try:
            if not self._validate_vlan_id(vlan_id):
                raise ValueError(f"Некорректный VLAN ID: {vlan_id}")

            if not 0 <= priority <= 7:
                raise ValueError(f"Некорректный приоритет VLAN: {priority}")

            endpoint = (
                f"/redfish/v1/Managers/Self/EthernetInterfaces/{self.interface}"
            )
            data = {
                "VLAN": {
                    "VLANEnable": True,
                    "VLANId": vlan_id,
                    "VLANPriority": priority
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
            settings = self._get_redfish_vlan_settings()
            if not settings:
                raise RuntimeError("Не удалось получить настройки")

            if (
                settings.get('vlan_id') != vlan_id or
                settings.get('vlan_priority') != priority or
                not settings.get('vlan_enabled')
            ):
                raise RuntimeError("Настройки VLAN не применились")

            return True

        except Exception as e:
            self.logger.error(f"Ошибка при настройке VLAN через Redfish: {e}")
            return False

    def setup_vlan_via_ssh(self, vlan_id: int) -> bool:
        """
        Настраивает VLAN через SSH.

        Args:
            vlan_id: ID VLAN

        Returns:
            bool: True если настройка успешна
        """
        try:
            if not self._validate_vlan_id(vlan_id):
                raise ValueError(f"Некорректный VLAN ID: {vlan_id}")

            if not self.ssh_tester.connect():
                raise RuntimeError("Не удалось установить SSH соединение")

            # Получаем имя интерфейса
            command = "ip link show"
            result = self.ssh_tester.execute_command(command)
            if not result['success']:
                raise RuntimeError("Не удалось получить список интерфейсов")

            interface_name = None
            for line in result['output'].splitlines():
                if 'state UP' in line:
                    interface_name = line.split(':')[1].strip()
                    break

            if not interface_name:
                raise RuntimeError("Не удалось определить имя интерфейса")

            # Создаем VLAN интерфейс
            commands = [
                f"sudo ip link add link {interface_name} name {interface_name}.{vlan_id} type vlan id {vlan_id}",
                f"sudo ip link set dev {interface_name}.{vlan_id} up"
            ]

            for cmd in commands:
                result = self.ssh_tester.execute_command(cmd)
                if not result['success']:
                    raise RuntimeError(f"Не удалось выполнить команду: {cmd}")
                time.sleep(2)

            # Проверяем настройки
            settings = self._get_ssh_vlan_settings()
            if not settings:
                raise RuntimeError("Не удалось получить настройки")

            if settings.get('vlan_id') != vlan_id:
                raise RuntimeError("Настройки VLAN не применились")

            return True

        except Exception as e:
            self.logger.error(f"Ошибка при настройке VLAN через SSH: {e}")
            return False
        finally:
            self.ssh_tester.disconnect()

    def _validate_vlan_id(self, vlan_id: int) -> bool:
        """
        Проверяет корректность VLAN ID.

        Args:
            vlan_id: ID VLAN для проверки

        Returns:
            bool: True если ID корректен
        """
        return 1 <= vlan_id <= 4094

    def test_invalid_settings(self) -> bool:
        """
        Тестирует установку некорректных VLAN ID.

        Returns:
            bool: True если тест прошел успешно
        """
        try:
            # Сохраняем текущие настройки
            original_settings = self._get_ipmi_vlan_settings()

            # Тестируем некорректные VLAN ID
            for invalid_id in self.invalid_vlan_ids:
                try:
                    if self.setup_vlan_via_ipmi(invalid_id):
                        self.logger.error(
                            f"Некорректный VLAN ID {invalid_id} был принят"
                        )
                        return False
                except Exception:
                    self.logger.info(
                        f"Некорректный VLAN ID {invalid_id} был отклонен"
                    )

            # Проверяем, что настройки не изменились
            current_settings = self._get_ipmi_vlan_settings()
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

    def verify_vlan_settings(self) -> bool:
        """
        Проверяет настройки VLAN через все интерфейсы.

        Returns:
            bool: True если проверка успешна
        """
        try:
            settings = self.get_current_settings()
            if not all(settings.values()):
                raise RuntimeError(
                    "Не удалось получить настройки через все интерфейсы"
                )

            # Проверяем VLAN ID
            vlan_ids = {
                source: data.get('vlan_id')
                for source, data in settings.items()
            }
            if len(set(vlan_ids.values())) > 1:
                self.logger.error(
                    f"Несоответствие VLAN ID между интерфейсами: {vlan_ids}"
                )
                return False

            # Проверяем приоритет (только для IPMI и Redfish)
            priorities = {
                source: data.get('vlan_priority')
                for source, data in settings.items()
                if source in ['ipmi', 'redfish']
            }
            if len(set(priorities.values())) > 1:
                self.logger.error(
                    f"Несоответствие приоритетов VLAN: {priorities}"
                )
                return False

            return True

        except Exception as e:
            self.logger.error(f"Ошибка при проверке настроек VLAN: {e}")
            return False

    def perform_tests(self) -> None:
        """Выполняет тестирование настройки VLAN."""
        try:
            self.logger.info("Начало тестирования настройки VLAN")

            # Сохраняем текущие настройки
            if self.backup_settings:
                self.original_settings = self.get_current_settings()

            # Настройка через IPMI
            if not self.setup_vlan_via_ipmi(
                self.test_vlan_id,
                self.test_vlan_priority
            ):
                raise RuntimeError("Не удалось настроить VLAN через IPMI")

            # Проверка настроек
            if not self.verify_vlan_settings():
                raise RuntimeError("Верификация настроек VLAN не прошла")

            # Настройка через Redfish
            if not self.setup_vlan_via_redfish(
                self.test_vlan_id,
                self.test_vlan_priority
            ):
                raise RuntimeError("Не удалось настроить VLAN через Redfish")

            # Проверка настроек
            if not self.verify_vlan_settings():
                raise RuntimeError("Верификация настроек VLAN не прошла")

            # Настройка через SSH
            if not self.setup_vlan_via_ssh(self.test_vlan_id):
                raise RuntimeError("Не удалось настроить VLAN через SSH")

            # Проверка настроек
            if not self.verify_vlan_settings():
                raise RuntimeError("Верификация настроек VLAN не прошла")

            # Тестирование некорректных настроек
            if not self.test_invalid_settings():
                raise RuntimeError("Тест некорректных настроек не прошел")

            self.add_test_result('VLAN Configuration Test', True)
            self.add_test_result('VLAN Verification Test', True)

        except Exception as e:
            self.logger.error(f"Ошибка при выполнении тестов: {e}")
            self.add_test_result('VLAN Tests', False, str(e))
        finally:
            self.safe_restore_settings()

    def restore_settings(self) -> bool:
        """
        Восстанавливает исходные настройки VLAN.

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
                return self.setup_vlan_via_ipmi(
                    ipmi_settings.get('vlan_id', 0),
                    ipmi_settings.get('vlan_priority', 0)
                )

            return True

        except Exception as e:
            self.logger.error(f"Ошибка при восстановлении настроек: {e}")
            return False
