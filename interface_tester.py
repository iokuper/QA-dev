"""Модуль для тестирования сетевых интерфейсов."""

import logging
import time
from typing import Dict, Any, Optional, List, cast
from base_tester import BaseTester
from verification_utils import verify_ip_format, verify_port_open
from network_utils import SSHManager, RedfishManager


class InterfaceTester(BaseTester):
    """Класс для тестирования сетевых интерфейсов."""

    def __init__(
        self,
        config_file: str = 'config.ini',
        logger: Optional[logging.Logger] = None
    ) -> None:
        """
        Инициализирует Interface тестер.

        Args:
            config_file: Путь к файлу конфигурации
            logger: Логгер для вывода сообщений
        """
        super().__init__(config_file, logger)

        # Загрузка конфигурации Interface
        interface_config = self.config_manager.get_network_config('Interface')
        self.interface = cast(str, interface_config.get('interface', '1'))

        # Параметры тестирования
        self.test_interfaces = cast(
            List[str],
            interface_config.get('test_interfaces', '').split(',')
        )
        self.required_ports = [
            int(x) for x in interface_config.get(
                'required_ports',
                '22,623,443'
            ).split(',')
        ]

        # Таймауты и повторы
        self.setup_timeout = int(interface_config.get('setup_timeout', '30'))
        self.verify_timeout = int(interface_config.get('verify_timeout', '60'))
        self.retry_count = int(interface_config.get('retry_count', '3'))
        self.retry_delay = int(interface_config.get('retry_delay', '10'))

        # Дополнительные параметры
        self.verify_access = interface_config.get(
            'verify_access',
            'true'
        ).lower() == 'true'
        self.backup_settings = interface_config.get(
            'backup_settings',
            'true'
        ).lower() == 'true'
        self.check_all_interfaces = interface_config.get(
            'check_all_interfaces',
            'true'
        ).lower() == 'true'

        # Инициализация других тестеров
        self.ssh_tester = SSHManager(config_file, logger)
        self.redfish_tester = RedfishManager(config_file, logger)

        # Сохранение исходных настроек
        self.original_settings: Dict[str, Any] = {}

        self.logger.debug("Инициализация Interface тестера завершена")

    def get_current_settings(self) -> Dict[str, Any]:
        """
        Получает текущие настройки интерфейсов через все протоколы.

        Returns:
            Dict[str, Any]: Текущие настройки
        """
        settings = {
            'ipmi': self._get_ipmi_interface_settings(),
            'redfish': self._get_redfish_interface_settings(),
            'ssh': self._get_ssh_interface_settings()
        }
        return settings

    def _get_ipmi_interface_settings(self) -> Dict[str, Any]:
        """
        Получает настройки интерфейсов через IPMI.

        Returns:
            Dict[str, Any]: Настройки интерфейсов
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
                    settings['mac'] = line.split(':')[1].strip()
                elif 'IP Address Source' in line:
                    settings['ip_source'] = line.split(':')[1].strip()
                elif 'IP Address' in line:
                    settings['ip'] = line.split(':')[1].strip()

            return settings

        except Exception as e:
            self.logger.error(
                f"Ошибка при получении настроек интерфейсов через IPMI: {e}"
            )
            return {}

    def _get_redfish_interface_settings(self) -> Dict[str, Any]:
        """
        Получает настройки интерфейсов через Redfish API.

        Returns:
            Dict[str, Any]: Настройки интерфейсов
        """
        try:
            endpoint = (
                f"/redfish/v1/Managers/Self/EthernetInterfaces/{self.interface}"
            )
            response = self.redfish_tester.run_request("GET", endpoint)
            if not response:
                raise RuntimeError("Не удалось получить настройки")

            data = response.json()
            settings = {
                'mac': data.get('MACAddress', ''),
                'ip_source': (
                    'DHCP' if data.get('DHCPv4', {}).get('DHCPEnabled')
                    else 'Static'
                ),
                'ip': data.get('IPv4Addresses', [{}])[0].get('Address', '')
            }

            return settings

        except Exception as e:
            self.logger.error(
                f"Ошибка при получении настроек интерфейсов через Redfish: {e}"
            )
            return {}

    def _get_ssh_interface_settings(self) -> Dict[str, Any]:
        """
        Получает настройки интерфейсов через SSH.

        Returns:
            Dict[str, Any]: Настройки интерфейсов
        """
        try:
            if not self.ssh_tester.connect():
                raise RuntimeError("Не удалось установить SSH соединение")

            settings = {}

            # Получаем MAC и IP
            command = "ip addr show"
            result = self.ssh_tester.execute_command(command)
            if not result['success']:
                raise RuntimeError("Не удалось получить настройки интерфейсов")

            for line in result['output'].splitlines():
                if 'link/ether' in line:
                    settings['mac'] = line.split()[1]
                elif 'inet ' in line:
                    settings['ip'] = line.split()[1].split('/')[0]

            # Определяем источник IP
            command = "nmcli -t -f IP4.METHOD connection show"
            result = self.ssh_tester.execute_command(command)
            if result['success'] and result['output']:
                settings['ip_source'] = (
                    'DHCP' if 'auto' in result['output']
                    else 'Static'
                )

            return settings

        except Exception as e:
            self.logger.error(
                f"Ошибка при получении настроек интерфейсов через SSH: {e}"
            )
            return {}
        finally:
            self.ssh_tester.disconnect()

    def verify_interface_settings(self) -> bool:
        """
        Проверяет настройки интерфейсов через все протоколы.

        Returns:
            bool: True если проверка успешна
        """
        try:
            settings = self.get_current_settings()
            if not all(settings.values()):
                raise RuntimeError(
                    "Не удалось получить настройки через все протоколы"
                )

            # Проверяем MAC-адреса
            macs = {
                source: data.get('mac')
                for source, data in settings.items()
            }
            if len(set(macs.values())) > 1:
                self.logger.error(
                    f"Несоответствие MAC-адресов между протоколами: {macs}"
                )
                return False

            # Проверяем IP-адреса
            ips = {
                source: data.get('ip')
                for source, data in settings.items()
            }
            if len(set(ips.values())) > 1:
                self.logger.error(
                    f"Несоответствие IP-адресов между протоколами: {ips}"
                )
                return False

            # Проверяем источники IP
            sources = {
                source: data.get('ip_source')
                for source, data in settings.items()
            }
            if len(set(sources.values())) > 1:
                self.logger.error(
                    f"Несоответствие источников IP между протоколами: {sources}"
                )
                return False

            # Проверяем доступность портов
            if self.verify_access:
                ip = next(iter(ips.values()))
                for port in self.required_ports:
                    if not verify_port_open(ip, port):
                        self.logger.error(
                            f"Порт {port} недоступен на {ip}"
                        )
                        return False

            return True

        except Exception as e:
            self.logger.error(
                f"Ошибка при проверке настроек интерфейсов: {e}"
            )
            return False

    def test_interface_switching(self) -> bool:
        """
        Тестирует переключение между интерфейсами.

        Returns:
            bool: True если тест прошел успешно
        """
        try:
            # Сохраняем текущие настройки
            original_settings = self.get_current_settings()

            for test_interface in self.test_interfaces:
                self.logger.info(
                    f"Тестирование интерфейса {test_interface}"
                )

                # Переключаем интерфейс через IPMI
                command = [
                    "ipmitool", "-I", "lanplus",
                    "-H", cast(str, self.ipmi_host),
                    "-U", self.ipmi_username,
                    "-P", self.ipmi_password,
                    "lan", "set", self.interface,
                    "access", test_interface
                ]
                self._run_command(command)
                time.sleep(5)

                # Проверяем настройки
                if not self.verify_interface_settings():
                    self.logger.error(
                        f"Проверка настроек не прошла "
                        f"для интерфейса {test_interface}"
                    )
                    return False

            # Восстанавливаем исходный интерфейс
            command = [
                "ipmitool", "-I", "lanplus",
                "-H", cast(str, self.ipmi_host),
                "-U", self.ipmi_username,
                "-P", self.ipmi_password,
                "lan", "set", self.interface,
                "access", self.interface
            ]
            self._run_command(command)
            time.sleep(5)

            # Проверяем, что настройки вернулись к исходным
            current_settings = self.get_current_settings()
            if current_settings != original_settings:
                self.logger.error(
                    "Настройки не вернулись к исходным после тестирования"
                )
                return False

            return True

        except Exception as e:
            self.logger.error(
                f"Ошибка при тестировании переключения интерфейсов: {e}"
            )
            return False

    def perform_tests(self) -> None:
        """Выполняет тестирование интерфейсов."""
        try:
            self.logger.info("Начало тестирования интерфейсов")

            # Сохраняем текущие настройки
            if self.backup_settings:
                self.original_settings = self.get_current_settings()

            # Проверяем текущие настройки
            if not self.verify_interface_settings():
                raise RuntimeError(
                    "Начальная проверка настроек интерфейсов не прошла"
                )

            # Тестируем переключение интерфейсов
            if not self.test_interface_switching():
                raise RuntimeError(
                    "Тест переключения интерфейсов не прошел"
                )

            self.add_test_result('Interface Configuration Test', True)
            self.add_test_result('Interface Switching Test', True)

        except Exception as e:
            self.logger.error(f"Ошибка при выполнении тестов: {e}")
            self.add_test_result('Interface Tests', False, str(e))
        finally:
            self.safe_restore_settings()

    def restore_settings(self) -> bool:
        """
        Восстанавливает исходные настройки интерфейсов.

        Returns:
            bool: True если восстановление успешно
        """
        try:
            if not self.original_settings:
                self.logger.info("Нет сохраненных настроек для восстановления")
                return True

            # Восстанавливаем интерфейс через IPMI
            command = [
                "ipmitool", "-I", "lanplus",
                "-H", cast(str, self.ipmi_host),
                "-U", self.ipmi_username,
                "-P", self.ipmi_password,
                "lan", "set", self.interface,
                "access", self.interface
            ]
            self._run_command(command)
            time.sleep(5)

            # Проверяем настройки
            current_settings = self.get_current_settings()
            if current_settings != self.original_settings:
                raise RuntimeError("Не удалось восстановить настройки")

            return True

        except Exception as e:
            self.logger.error(f"Ошибка при восстановлении настроек: {e}")
            return False
