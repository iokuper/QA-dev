"""Модуль для тестирования настройки MAC-адреса."""

import logging
import time
import re
from typing import Dict, Any, Optional, List, cast
from base_tester import BaseTester
from network_utils import SSHManager, RedfishManager


class MACTester(BaseTester):
    """Класс для тестирования настройки MAC-адреса."""

    def __init__(
        self,
        config_file: str = 'config.ini',
        logger: Optional[logging.Logger] = None
    ) -> None:
        """
        Инициализирует MAC тестер.

        Args:
            config_file: Путь к файлу конфигурации
            logger: Логгер для вывода сообщений
        """
        super().__init__(config_file, logger)

        # Загрузка конфигурации MAC
        mac_config = self.config_manager.get_network_config('MAC')
        self.interface = cast(str, mac_config.get('interface', '1'))
        self.test_mac = cast(str, mac_config.get('test_mac'))
        self.default_mac = cast(str, mac_config.get('default_mac'))

        # Таймауты и повторы
        self.setup_timeout = int(mac_config.get('setup_timeout', '30'))
        self.verify_timeout = int(mac_config.get('verify_timeout', '60'))
        self.retry_count = int(mac_config.get('retry_count', '3'))
        self.retry_delay = int(mac_config.get('retry_delay', '10'))

        # Дополнительные параметры
        self.verify_network = mac_config.get(
            'verify_network',
            'true'
        ).lower() == 'true'
        self.backup_settings = mac_config.get(
            'backup_settings',
            'true'
        ).lower() == 'true'
        self.allow_multicast = mac_config.get(
            'allow_multicast',
            'false'
        ).lower() == 'true'
        self.allow_broadcast = mac_config.get(
            'allow_broadcast',
            'false'
        ).lower() == 'true'

        # Инициализация других тестеров
        self.ssh_tester = SSHManager(config_file, logger)
        self.redfish_tester = RedfishManager(config_file, logger)

        # Сохранение исходных настроек
        self.original_mac: Optional[str] = None

        self.logger.debug("Инициализация MAC тестера завершена")

    def get_current_settings(self) -> Dict[str, Any]:
        """
        Получает текущие настройки MAC через все интерфейсы.

        Returns:
            Dict[str, Any]: Текущие настройки
        """
        settings = {
            'ipmi': self._get_ipmi_mac(),
            'redfish': self._get_redfish_mac(),
            'ssh': self._get_ssh_mac()
        }
        return settings

    def _get_ipmi_mac(self) -> Dict[str, str]:
        """
        Получает MAC-адрес через IPMI.

        Returns:
            Dict[str, str]: Настройки MAC
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
                if 'MAC Address' in line:
                    settings['mac_address'] = line.split(':')[1].strip()
                    break

            return settings

        except Exception as e:
            self.logger.error(f"Ошибка при получении MAC через IPMI: {e}")
            return {}

    def _get_redfish_mac(self) -> Dict[str, str]:
        """
        Получает MAC-адрес через Redfish API.

        Returns:
            Dict[str, str]: Настройки MAC
        """
        try:
            endpoint = (
                f"/redfish/v1/Managers/Self/EthernetInterfaces/{self.interface}"
            )
            response = self.redfish_tester.run_request("GET", endpoint)
            if not response:
                raise RuntimeError("Не удалось получить настройки")

            data = response.json()
            return {'mac_address': data.get('MACAddress', '')}

        except Exception as e:
            self.logger.error(f"Ошибка при получении MAC через Redfish: {e}")
            return {}

    def _get_ssh_mac(self) -> Dict[str, str]:
        """
        Получает MAC-адрес через SSH.

        Returns:
            Dict[str, str]: Настройки MAC
        """
        try:
            if not self.ssh_tester.connect():
                raise RuntimeError("Не удалось установить SSH соединение")

            command = "ip link show"
            result = self.ssh_tester.execute_command(command)
            if not result['success']:
                raise RuntimeError("Не удалось получить MAC")

            settings = {}
            for line in result['output'].splitlines():
                if 'link/ether' in line:
                    mac = line.split('link/ether')[1].split()[0].strip()
                    settings['mac_address'] = mac
                    break

            return settings

        except Exception as e:
            self.logger.error(f"Ошибка при получении MAC через SSH: {e}")
            return {}
        finally:
            self.ssh_tester.disconnect()

    def setup_mac_via_ipmi(self, mac: str) -> bool:
        """
        Настраивает MAC-адрес через IPMI.

        Args:
            mac: Новый MAC-адрес

        Returns:
            bool: True если настройка успешна
        """
        try:
            if not self.validate_mac_address(mac):
                raise ValueError(f"Некорректный MAC-адрес: {mac}")

            command = [
                "ipmitool", "-I", "lanplus",
                "-H", cast(str, self.ipmi_host),
                "-U", self.ipmi_username,
                "-P", self.ipmi_password,
                "lan", "set", self.interface,
                "mac", mac
            ]
            self._run_command(command)
            time.sleep(5)

            # Проверяем настройки
            settings = self._get_ipmi_mac()
            if not settings:
                raise RuntimeError("Не удалось получить настройки")

            if settings.get('mac_address') != mac:
                raise RuntimeError("MAC-адрес не применился")

            return True

        except Exception as e:
            self.logger.error(f"Ошибка при настройке MAC через IPMI: {e}")
            return False

    def setup_mac_via_redfish(self, mac: str) -> bool:
        """
        Настраивает MAC-адрес через Redfish API.

        Args:
            mac: Новый MAC-адрес

        Returns:
            bool: True если настройка успешна
        """
        try:
            if not self.validate_mac_address(mac):
                raise ValueError(f"Некорректный MAC-адрес: {mac}")

            endpoint = (
                f"/redfish/v1/Managers/Self/EthernetInterfaces/{self.interface}"
            )
            data = {"MACAddress": mac}

            response = self.redfish_tester.run_request(
                "PATCH",
                endpoint,
                data=data
            )
            if not response:
                raise RuntimeError("Не удалось применить настройки")

            time.sleep(5)

            # Проверяем настройки
            settings = self._get_redfish_mac()
            if not settings:
                raise RuntimeError("Не удалось получить настройки")

            if settings.get('mac_address') != mac:
                raise RuntimeError("MAC-адрес не применился")

            return True

        except Exception as e:
            self.logger.error(f"Ошибка при настройке MAC через Redfish: {e}")
            return False

    def setup_mac_via_ssh(self, mac: str) -> bool:
        """
        Настраивает MAC-адрес через SSH.

        Args:
            mac: Новый MAC-адрес

        Returns:
            bool: True если настройка успешна
        """
        try:
            if not self.validate_mac_address(mac):
                raise ValueError(f"Некорректный MAC-адрес: {mac}")

            if not self.ssh_tester.connect():
                raise RuntimeError("Не удалось установить SSH соединение")

            # Получаем имя интерфейса
            command = "ip link show"
            result = self.ssh_tester.execute_command(command)
            if not result['success']:
                raise RuntimeError("Не удалось получить список интерфейсов")

            interface_name = None
            for line in result['output'].splitlines():
                if 'link/ether' in line:
                    interface_name = line.split(':')[1].strip()
                    break

            if not interface_name:
                raise RuntimeError("Не удалось определить имя интерфейса")

            # Устанавливаем новый MAC
            commands = [
                f"sudo ip link set dev {interface_name} address {mac}",
                f"sudo ip link set dev {interface_name} down",
                f"sudo ip link set dev {interface_name} up"
            ]

            for cmd in commands:
                result = self.ssh_tester.execute_command(cmd)
                if not result['success']:
                    raise RuntimeError(f"Не удалось выполнить команду: {cmd}")
                time.sleep(2)

            # Проверяем настройки
            settings = self._get_ssh_mac()
            if not settings:
                raise RuntimeError("Не удалось получить настройки MAC")

            if settings.get('mac_address') != mac:
                raise RuntimeError("MAC-адрес не применился")

            return True

        except Exception as e:
            self.logger.error(f"Ошибка при настройке MAC через SSH: {e}")
            return False
        finally:
            self.ssh_tester.disconnect()

    def validate_mac_address(self, mac: str) -> bool:
        """
        Проверяет корректность MAC-адреса.

        Args:
            mac: MAC-адрес для проверки

        Returns:
            bool: True если MAC-адрес корректен
        """
        try:
            # Проверяем формат MAC-адреса
            if not re.match(
                r'^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$',
                mac
            ):
                self.logger.error(f"Некорректный формат MAC-адреса: {mac}")
                return False

            # Проверяем broadcast/multicast биты
            first_byte = int(mac.split(':')[0], 16)
            if not self.allow_broadcast and (first_byte & 0x01):
                self.logger.error("Broadcast MAC-адреса запрещены")
                return False

            if not self.allow_multicast and (first_byte & 0x01):
                self.logger.error("Multicast MAC-адреса запрещены")
                return False

            return True

        except Exception as e:
            self.logger.error(f"Ошибка при валидации MAC-адреса: {e}")
            return False

    def test_invalid_settings(self) -> bool:
        """
        Тестирует установку некорректных MAC-адресов.

        Returns:
            bool: True если тест прошел успешно
        """
        try:
            invalid_macs = [
                "00:00:00:00:00:00",  # Нулевой MAC
                "FF:FF:FF:FF:FF:FF",  # Broadcast MAC
                "01:00:00:00:00:00",  # Multicast MAC
                "invalid_mac",        # Некорректный формат
                "00:11:22:33:44",    # Неполный MAC
                "00:11:22:33:44:ZZ"  # Некорректные символы
            ]

            # Сохраняем текущие настройки
            original_settings = self._get_ipmi_mac()

            for invalid_mac in invalid_macs:
                try:
                    if self.setup_mac_via_ipmi(invalid_mac):
                        self.logger.error(
                            f"Некорректный MAC {invalid_mac} был принят"
                        )
                        return False
                except Exception:
                    self.logger.info(
                        f"Некорректный MAC {invalid_mac} был отклонен"
                    )

            # Проверяем, что настройки не изменились
            current_settings = self._get_ipmi_mac()
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

    def verify_mac_settings(self) -> bool:
        """
        Проверяет настройки MAC через все интерфейсы.

        Returns:
            bool: True если проверка успешна
        """
        try:
            settings = self.get_current_settings()
            if not all(settings.values()):
                raise RuntimeError(
                    "Не удалось получить настройки через все интерфейсы"
                )

            # Сравниваем MAC-адреса
            mac_addresses = {
                source: data.get('mac_address')
                for source, data in settings.items()
            }

            if len(set(mac_addresses.values())) > 1:
                self.logger.error(
                    f"Несоответствие MAC-адресов между интерфейсами: "
                    f"{mac_addresses}"
                )
                return False

            # Проверяем соответствие тестовому MAC
            current_mac = next(iter(mac_addresses.values()))
            if current_mac != self.test_mac:
                self.logger.error(
                    f"MAC-адрес не соответствует тестовому: "
                    f"{current_mac} != {self.test_mac}"
                )
                return False

            return True

        except Exception as e:
            self.logger.error(f"Ошибка при проверке настроек MAC: {e}")
            return False

    def perform_tests(self) -> None:
        """Выполняет тестирование настройки MAC-адреса."""
        try:
            self.logger.info("Начало тестирования настройки MAC-адреса")

            # Сохраняем текущие настройки
            if self.backup_settings:
                settings = self._get_ipmi_mac()
                self.original_mac = settings.get('mac_address')

            # Настройка через IPMI
            if not self.setup_mac_via_ipmi(self.test_mac):
                raise RuntimeError("Не удалось настроить MAC через IPMI")

            # Проверка настроек
            if not self.verify_mac_settings():
                raise RuntimeError("Верификация настроек MAC не прошла")

            # Настройка через Redfish
            if not self.setup_mac_via_redfish(self.test_mac):
                raise RuntimeError("Не удалось настроить MAC через Redfish")

            # Проверка настроек
            if not self.verify_mac_settings():
                raise RuntimeError("Верификация настроек MAC не прошла")

            # Настройка через SSH
            if not self.setup_mac_via_ssh(self.test_mac):
                raise RuntimeError("Не удалось настроить MAC через SSH")

            # Проверка настроек
            if not self.verify_mac_settings():
                raise RuntimeError("Верификация настроек MAC не прошла")

            # Тестирование некорректных настроек
            if not self.test_invalid_settings():
                raise RuntimeError("Тест некорректных настроек не прошел")

            self.add_test_result('MAC Configuration Test', True)
            self.add_test_result('MAC Verification Test', True)

        except Exception as e:
            self.logger.error(f"Ошибка при выполнении тестов: {e}")
            self.add_test_result('MAC Tests', False, str(e))
        finally:
            self.safe_restore_settings()

    def restore_settings(self) -> bool:
        """
        Восстанавливает исходные настройки MAC-адреса.

        Returns:
            bool: True если восстановление успешно
        """
        try:
            if not self.original_mac:
                self.logger.info("Нет сохраненных настроек для восстановления")
                return True

            return self.setup_mac_via_ipmi(self.original_mac)

        except Exception as e:
            self.logger.error(f"Ошибка при вос��тановлении на��троек: {e}")
            return False
