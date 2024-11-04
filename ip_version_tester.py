"""Модуль для тестирования поддержки версий IP."""

import logging
import time
from typing import Dict, Any, Optional, List, cast
from base_tester import BaseTester
from network_utils import SSHManager, RedfishManager
import ipaddress


class IPVersionTester(BaseTester):
    """Класс для тестирования поддержки версий IP."""

    def __init__(
        self,
        config_file: str = 'config.ini',
        logger: Optional[logging.Logger] = None
    ) -> None:
        """
        Инициализирует IP Version тестер.

        Args:
            config_file: Путь к файлу конфигурации
            logger: Логгер для вывода сообщений
        """
        super().__init__(config_file, logger)

        # Загрузка конфигурации IP Version
        ipv_config = self.config_manager.get_network_config('IPVersion')
        self.interface = cast(str, ipv_config.get('interface', '1'))

        # Параметры тестирования
        self.test_ipv4 = ipv_config.get(
            'test_ipv4',
            'true'
        ).lower() == 'true'
        self.test_ipv6 = ipv_config.get(
            'test_ipv6',
            'true'
        ).lower() == 'true'
        self.test_dual_stack = ipv_config.get(
            'test_dual_stack',
            'true'
        ).lower() == 'true'

        # Тестовые адреса
        self.test_ipv4_addr = cast(str, ipv_config.get('test_ipv4_addr'))
        self.test_ipv6_addr = cast(str, ipv_config.get('test_ipv6_addr'))
        self.test_ipv4_prefix = int(ipv_config.get('test_ipv4_prefix', '24'))
        self.test_ipv6_prefix = int(ipv_config.get('test_ipv6_prefix', '64'))

        # Таймауты и повторы
        self.setup_timeout = int(ipv_config.get('setup_timeout', '30'))
        self.verify_timeout = int(ipv_config.get('verify_timeout', '60'))
        self.retry_count = int(ipv_config.get('retry_count', '3'))
        self.retry_delay = int(ipv_config.get('retry_delay', '10'))

        # Дополнительные параметры
        self.verify_access = ipv_config.get(
            'verify_access',
            'true'
        ).lower() == 'true'
        self.backup_settings = ipv_config.get(
            'backup_settings',
            'true'
        ).lower() == 'true'
        self.check_all_interfaces = ipv_config.get(
            'check_all_interfaces',
            'true'
        ).lower() == 'true'

        # Инициализация других тестеров
        self.ssh_tester = SSHManager(config_file, logger)
        self.redfish_tester = RedfishManager(config_file, logger)

        # Сохранение исходных настроек
        self.original_settings: Dict[str, Any] = {}

        self.logger.debug("Инициализация IP Version тестера завершена")

    def get_current_settings(self) -> Dict[str, Any]:
        """
        Получает текущие настройки IP через все интерфейсы.

        Returns:
            Dict[str, Any]: Текущие настройки
        """
        settings = {
            'ipmi': self._get_ipmi_ip_settings(),
            'redfish': self._get_redfish_ip_settings(),
            'ssh': self._get_ssh_ip_settings()
        }
        return settings

    def _get_ipmi_ip_settings(self) -> Dict[str, Any]:
        """
        Получает настройки IP через IPMI.

        Returns:
            Dict[str, Any]: Настройки IP
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

            settings = {
                'ipv4_enabled': False,
                'ipv6_enabled': False,
                'ipv4_addr': '',
                'ipv6_addr': ''
            }

            for line in result.stdout.splitlines():
                if 'IPv4 Support' in line:
                    settings['ipv4_enabled'] = 'enabled' in line.lower()
                elif 'IPv6 Support' in line:
                    settings['ipv6_enabled'] = 'enabled' in line.lower()
                elif 'IPv4 Address' in line:
                    settings['ipv4_addr'] = line.split(':')[1].strip()
                elif 'IPv6 Address' in line:
                    settings['ipv6_addr'] = line.split(':')[1].strip()

            return settings

        except Exception as e:
            self.logger.error(f"Ошибка при получении настроек IP через IPMI: {e}")
            return {}

    def _get_redfish_ip_settings(self) -> Dict[str, Any]:
        """
        Получает настройки IP через Redfish API.

        Returns:
            Dict[str, Any]: Настройки IP
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
                'ipv4_enabled': data.get('IPv4Enabled', False),
                'ipv6_enabled': data.get('IPv6Enabled', False),
                'ipv4_addr': '',
                'ipv6_addr': ''
            }

            ipv4_addresses = data.get('IPv4Addresses', [])
            if ipv4_addresses:
                settings['ipv4_addr'] = ipv4_addresses[0].get('Address', '')

            ipv6_addresses = data.get('IPv6Addresses', [])
            if ipv6_addresses:
                settings['ipv6_addr'] = ipv6_addresses[0].get('Address', '')

            return settings

        except Exception as e:
            self.logger.error(
                f"Ошибка при получении настроек IP через Redfish: {e}"
            )
            return {}

    def _get_ssh_ip_settings(self) -> Dict[str, Any]:
        """
        Получает настройки IP через SSH.

        Returns:
            Dict[str, Any]: Настройки IP
        """
        try:
            if not self.ssh_tester.connect():
                raise RuntimeError("Не удалось установить SSH соединение")

            settings = {
                'ipv4_enabled': False,
                'ipv6_enabled': False,
                'ipv4_addr': '',
                'ipv6_addr': ''
            }

            # Проверяем поддержку IPv4
            command = "sysctl -n net.ipv4.ip_forward"
            result = self.ssh_tester.execute_command(command)
            if result['success']:
                settings['ipv4_enabled'] = result['output'].strip() == '1'

            # Проверяем поддержку IPv6
            command = "sysctl -n net.ipv6.conf.all.disable_ipv6"
            result = self.ssh_tester.execute_command(command)
            if result['success']:
                settings['ipv6_enabled'] = result['output'].strip() == '0'

            # Получаем адреса
            command = "ip addr show"
            result = self.ssh_tester.execute_command(command)
            if result['success']:
                for line in result['output'].splitlines():
                    if 'inet ' in line:
                        settings['ipv4_addr'] = line.split()[1].split('/')[0]
                    elif 'inet6' in line:
                        settings['ipv6_addr'] = line.split()[1].split('/')[0]

            return settings

        except Exception as e:
            self.logger.error(f"Ошибка при получении настроек IP через SSH: {e}")
            return {}
        finally:
            self.ssh_tester.disconnect()

    def setup_ipv4(self, enable: bool = True) -> bool:
        """
        Настраивает поддержку IPv4.

        Args:
            enable: True для включения, False для отключения

        Returns:
            bool: True если настройка успешна
        """
        try:
            command = [
                "ipmitool", "-I", "lanplus",
                "-H", cast(str, self.ipmi_host),
                "-U", self.ipmi_username,
                "-P", self.ipmi_password,
                "lan", "set", self.interface,
                "ipv4", "enable" if enable else "disable"
            ]
            self._run_command(command)
            time.sleep(5)

            # Проверяем настройки
            settings = self._get_ipmi_ip_settings()
            if not settings:
                raise RuntimeError("Не удалось получить настройки")

            if settings.get('ipv4_enabled') != enable:
                raise RuntimeError(
                    f"Не удалось {'включить' if enable else 'отключить'} IPv4"
                )

            return True

        except Exception as e:
            self.logger.error(f"Ошибка при настройке IPv4: {e}")
            return False

    def setup_ipv6(self, enable: bool = True) -> bool:
        """
        Настраивает поддержку IPv6.

        Args:
            enable: True для включения, False для отключения

        Returns:
            bool: True если настройка успешна
        """
        try:
            command = [
                "ipmitool", "-I", "lanplus",
                "-H", cast(str, self.ipmi_host),
                "-U", self.ipmi_username,
                "-P", self.ipmi_password,
                "lan", "set", self.interface,
                "ipv6", "enable" if enable else "disable"
            ]
            self._run_command(command)
            time.sleep(5)

            # Проверяем настройки
            settings = self._get_ipmi_ip_settings()
            if not settings:
                raise RuntimeError("Не удалось получить настройки")

            if settings.get('ipv6_enabled') != enable:
                raise RuntimeError(
                    f"Не удалось {'включить' if enable else 'отключить'} IPv6"
                )

            return True

        except Exception as e:
            self.logger.error(f"Ошибка при настройке IPv6: {e}")
            return False

    def setup_dual_stack(self) -> bool:
        """
        Настраивает поддержку обоих протоколов (IPv4 и IPv6).

        Returns:
            bool: True если настройка успешна
        """
        try:
            # Включаем IPv4
            if not self.setup_ipv4(True):
                raise RuntimeError("Не удалось включить IPv4")

            # Включаем IPv6
            if not self.setup_ipv6(True):
                raise RuntimeError("Не удалось включить IPv6")

            # Проверяем настройки
            settings = self._get_ipmi_ip_settings()
            if not settings:
                raise RuntimeError("Не удалось получить настройки")

            if not (
                settings.get('ipv4_enabled') and
                settings.get('ipv6_enabled')
            ):
                raise RuntimeError("Не удалось включить dual stack")

            return True

        except Exception as e:
            self.logger.error(f"Ошибка при настройке dual stack: {e}")
            return False

    def verify_ip_settings(self) -> bool:
        """
        Проверяет настройки IP через все интерфейсы.

        Returns:
            bool: True если проверка успешна
        """
        try:
            settings = self.get_current_settings()
            if not all(settings.values()):
                raise RuntimeError(
                    "Не удалось получить настройки через все интерфейсы"
                )

            # Проверяем состояние IPv4
            ipv4_enabled = {
                source: data.get('ipv4_enabled')
                for source, data in settings.items()
            }
            if len(set(ipv4_enabled.values())) > 1:
                self.logger.error(
                    f"Несоответствие состояния IPv4: {ipv4_enabled}"
                )
                return False

            # Проверяем состояние IPv6
            ipv6_enabled = {
                source: data.get('ipv6_enabled')
                for source, data in settings.items()
            }
            if len(set(ipv6_enabled.values())) > 1:
                self.logger.error(
                    f"Несоответствие состояния IPv6: {ipv6_enabled}"
                )
                return False

            return True

        except Exception as e:
            self.logger.error(f"Ошибка при проверке настроек IP: {e}")
            return False

    def test_ip_connectivity(self) -> bool:
        """
        Тестирует сетевую доступность по IPv4 и IPv6.

        Returns:
            bool: True если тест успешен
        """
        try:
            if not self.ssh_tester.connect():
                raise RuntimeError("Не удалось установить SSH соединение")

            success = True

            # Тестируем IPv4 если включен
            if self.test_ipv4:
                command = f"ping -c 4 -W 2 {self.test_ipv4_addr}"
                result = self.ssh_tester.execute_command(command)
                if not result['success'] or ' 0% packet loss' not in result['output']:
                    self.logger.error(f"Тест IPv4 не прошел: {self.test_ipv4_addr}")
                    success = False

            # Тестируем IPv6 если включен
            if self.test_ipv6:
                command = f"ping6 -c 4 -W 2 {self.test_ipv6_addr}"
                result = self.ssh_tester.execute_command(command)
                if not result['success'] or ' 0% packet loss' not in result['output']:
                    self.logger.error(f"Тест IPv6 не прошел: {self.test_ipv6_addr}")
                    success = False

            return success

        except Exception as e:
            self.logger.error(f"Ошибка при тестировании доступности IP: {e}")
            return False
        finally:
            self.ssh_tester.disconnect()

    def perform_tests(self) -> None:
        """Выполняет тестирование поддержки версий IP."""
        try:
            self.logger.info("Начало тестирования поддержки версий IP")

            # Сохраняем текущие настройки
            if self.backup_settings:
                self.original_settings = self.get_current_settings()

            # Тестируем IPv4 если требуется
            if self.test_ipv4:
                if not self.setup_ipv4(True):
                    raise RuntimeError("Не удалось настроить IPv4")
                if not self.verify_ip_settings():
                    raise RuntimeError("Верификация IPv4 не прошла")

            # Тестируем IPv6 если требуется
            if self.test_ipv6:
                if not self.setup_ipv6(True):
                    raise RuntimeError("Не удалось настроить IPv6")
                if not self.verify_ip_settings():
                    raise RuntimeError("Верификация IPv6 не прошла")

            # Тестируем dual stack если требуется
            if self.test_dual_stack:
                if not self.setup_dual_stack():
                    raise RuntimeError("Не удалось настроить dual stack")
                if not self.verify_ip_settings():
                    raise RuntimeError("Верификация dual stack не прошла")

            # Тестируем сетевую доступность
            if self.verify_access and not self.test_ip_connectivity():
                raise RuntimeError("Тест сетевой доступности не прошел")

            self.add_test_result('IP Version Configuration Test', True)
            self.add_test_result('IP Version Connectivity Test', True)

        except Exception as e:
            self.logger.error(f"Ошибка при выполнении тестов: {e}")
            self.add_test_result('IP Version Tests', False, str(e))
        finally:
            self.safe_restore_settings()

    def restore_settings(self) -> bool:
        """
        Восстанавливает исходные настройки IP.

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
                # Восстанавливаем IPv4
                if not self.setup_ipv4(ipmi_settings.get('ipv4_enabled', True)):
                    raise RuntimeError("Не удалось восстановить IPv4")

                # Восстанавливаем IPv6
                if not self.setup_ipv6(ipmi_settings.get('ipv6_enabled', False)):
                    raise RuntimeError("Не удалось восстановить IPv6")

            return True

        except Exception as e:
            self.logger.error(f"Ошибка при восстановлении настроек: {e}")
            return False
