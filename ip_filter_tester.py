"""Модуль для тестирования фильтрации IP-адресов."""

import logging
import time
from typing import Dict, Any, Optional, List, cast
from base_tester import BaseTester
from network_utils import SSHManager, RedfishManager
import ipaddress


class IPFilterTester(BaseTester):
    """Класс для тестирования фильтрации IP-адресов."""

    def __init__(
        self,
        config_file: str = 'config.ini',
        logger: Optional[logging.Logger] = None
    ) -> None:
        """
        Инициализирует IP Filter тестер.

        Args:
            config_file: Путь к файлу конфигурации
            logger: Логгер для вывода сообщений
        """
        super().__init__(config_file, logger)

        # Загрузка конфигурации IP Filter
        filter_config = self.config_manager.get_network_config('IPFilter')
        self.interface = cast(str, filter_config.get('interface', '1'))

        # Параметры фильтрации
        self.allowed_ips = cast(
            List[str],
            filter_config.get('allowed_ips', '').split(',')
        )
        self.blocked_ips = cast(
            List[str],
            filter_config.get('blocked_ips', '').split(',')
        )
        self.test_ports = [
            int(x) for x in filter_config.get(
                'test_ports',
                '22,623,443'
            ).split(',')
        ]

        # Таймауты и повторы
        self.setup_timeout = int(filter_config.get('setup_timeout', '30'))
        self.verify_timeout = int(filter_config.get('verify_timeout', '60'))
        self.retry_count = int(filter_config.get('retry_count', '3'))
        self.retry_delay = int(filter_config.get('retry_delay', '10'))

        # Дополнительные параметры
        self.verify_access = filter_config.get(
            'verify_access',
            'true'
        ).lower() == 'true'
        self.backup_settings = filter_config.get(
            'backup_settings',
            'true'
        ).lower() == 'true'
        self.strict_mode = filter_config.get(
            'strict_mode',
            'false'
        ).lower() == 'true'

        # Инициализация других тестеров
        self.ssh_tester = SSHManager(config_file, logger)
        self.redfish_tester = RedfishManager(config_file, logger)

        # Сохранение исходных настроек
        self.original_settings: Dict[str, Any] = {}

        self.logger.debug("Инициализация IP Filter тестера завершена")

    def get_current_settings(self) -> Dict[str, Any]:
        """
        Получает текущие настройки фильтрации через все интерфейсы.

        Returns:
            Dict[str, Any]: Текущие настройки
        """
        settings = {
            'ipmi': self._get_ipmi_filter_settings(),
            'redfish': self._get_redfish_filter_settings(),
            'ssh': self._get_ssh_filter_settings()
        }
        return settings

    def _get_ipmi_filter_settings(self) -> Dict[str, Any]:
        """
        Получает настройки фильтрации через IPMI.

        Returns:
            Dict[str, Any]: Настройки фильтрации
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
                'allowed_ips': [],
                'blocked_ips': []
            }

            for line in result.stdout.splitlines():
                if 'IP Filter' in line:
                    if 'Allow' in line:
                        settings['allowed_ips'].append(
                            line.split(':')[1].strip()
                        )
                    elif 'Block' in line:
                        settings['blocked_ips'].append(
                            line.split(':')[1].strip()
                        )

            return settings

        except Exception as e:
            self.logger.error(
                f"Ошибка при получении настроек фильтрации через IPMI: {e}"
            )
            return {}

    def _get_redfish_filter_settings(self) -> Dict[str, Any]:
        """
        Получает настройки фильтрации через Redfish API.

        Returns:
            Dict[str, Any]: Настройки фильтрации
        """
        try:
            endpoint = (
                f"/redfish/v1/Managers/Self/NetworkProtocol/IPFilter"
            )
            response = self.redfish_tester.run_request("GET", endpoint)
            if not response:
                raise RuntimeError("Не удалось получить настройки")

            data = response.json()
            settings = {
                'allowed_ips': data.get('AllowedAddresses', []),
                'blocked_ips': data.get('BlockedAddresses', []),
                'enabled': data.get('FilterEnabled', False)
            }

            return settings

        except Exception as e:
            self.logger.error(
                f"Ошибка при получении настроек фильтрации через Redfish: {e}"
            )
            return {}

    def _get_ssh_filter_settings(self) -> Dict[str, Any]:
        """
        Получает настройки фильтрации через SSH.

        Returns:
            Dict[str, Any]: Настройки фильтрации
        """
        try:
            if not self.ssh_tester.connect():
                raise RuntimeError("Не удалось установить SSH соединение")

            settings = {
                'allowed_ips': [],
                'blocked_ips': []
            }

            # Получаем правила iptables
            command = "sudo iptables -L INPUT -n"
            result = self.ssh_tester.execute_command(command)
            if not result['success']:
                raise RuntimeError("Не удалось получить правила iptables")

            for line in result['output'].splitlines():
                if 'ACCEPT' in line and 'source' in line:
                    ip = line.split('source')[1].strip()
                    settings['allowed_ips'].append(ip)
                elif 'DROP' in line and 'source' in line:
                    ip = line.split('source')[1].strip()
                    settings['blocked_ips'].append(ip)

            return settings

        except Exception as e:
            self.logger.error(
                f"Ошибка при получении настроек фильтрации через SSH: {e}"
            )
            return {}
        finally:
            self.ssh_tester.disconnect()

    def setup_ip_filter(
        self,
        allowed_ips: List[str],
        blocked_ips: List[str]
    ) -> bool:
        """
        Настраивает фильтрацию IP-адресов.

        Args:
            allowed_ips: Список разрешенных IP
            blocked_ips: Список заблокированных IP

        Returns:
            bool: True если настройка успешна
        """
        try:
            # Проверяем корректность IP-адресов
            for ip in allowed_ips + blocked_ips:
                try:
                    ipaddress.ip_address(ip)
                except ValueError:
                    raise ValueError(f"Некорректный IP-адрес: {ip}")

            # Настраиваем через IPMI
            if not self.setup_filter_via_ipmi(allowed_ips, blocked_ips):
                raise RuntimeError("Не удалось настроить фильтрацию через IPMI")

            # Настраиваем через Redfish
            if not self.setup_filter_via_redfish(allowed_ips, blocked_ips):
                raise RuntimeError(
                    "Не удалось настроить фильтрацию через Redfish"
                )

            # Настраиваем через SSH
            if not self.setup_filter_via_ssh(allowed_ips, blocked_ips):
                raise RuntimeError("Не удалось настроить фильтрацию через SSH")

            # Проверяем настройки
            if not self.verify_filter_settings():
                raise RuntimeError("Верификация настроек фильтрации не прошла")

            return True

        except Exception as e:
            self.logger.error(f"Ошибка при настройке фильтрации IP: {e}")
            return False

    def setup_filter_via_ipmi(
        self,
        allowed_ips: List[str],
        blocked_ips: List[str]
    ) -> bool:
        """
        Настраивает фильтрацию через IPMI.

        Args:
            allowed_ips: Список разрешенных IP
            blocked_ips: Список заблокированных IP

        Returns:
            bool: True если настройка успешна
        """
        try:
            # Очищаем текущие правила
            command = [
                "ipmitool", "-I", "lanplus",
                "-H", cast(str, self.ipmi_host),
                "-U", self.ipmi_username,
                "-P", self.ipmi_password,
                "lan", "set", self.interface,
                "ipfilter", "clear"
            ]
            self._run_command(command)
            time.sleep(2)

            # Добавляем разрешенные IP
            for ip in allowed_ips:
                command = [
                    "ipmitool", "-I", "lanplus",
                    "-H", cast(str, self.ipmi_host),
                    "-U", self.ipmi_username,
                    "-P", self.ipmi_password,
                    "lan", "set", self.interface,
                    "ipfilter", "allow", ip
                ]
                self._run_command(command)
                time.sleep(1)

            # Добавляем заблокированные IP
            for ip in blocked_ips:
                command = [
                    "ipmitool", "-I", "lanplus",
                    "-H", cast(str, self.ipmi_host),
                    "-U", self.ipmi_username,
                    "-P", self.ipmi_password,
                    "lan", "set", self.interface,
                    "ipfilter", "block", ip
                ]
                self._run_command(command)
                time.sleep(1)

            # Проверяем настройки
            settings = self._get_ipmi_filter_settings()
            if not settings:
                raise RuntimeError("Не удалось получить настройки")

            if (
                set(settings['allowed_ips']) != set(allowed_ips) or
                set(settings['blocked_ips']) != set(blocked_ips)
            ):
                raise RuntimeError("Настройки фильтрации не применились")

            return True

        except Exception as e:
            self.logger.error(f"Ошибка при настройке фильтрации через IPMI: {e}")
            return False

    def setup_filter_via_redfish(
        self,
        allowed_ips: List[str],
        blocked_ips: List[str]
    ) -> bool:
        """
        Настраивает фильтрацию через Redfish API.

        Args:
            allowed_ips: Список разрешенных IP
            blocked_ips: Список заблокированных IP

        Returns:
            bool: True если настройка успешна
        """
        try:
            endpoint = "/redfish/v1/Managers/Self/NetworkProtocol/IPFilter"
            data = {
                "FilterEnabled": True,
                "AllowedAddresses": allowed_ips,
                "BlockedAddresses": blocked_ips
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
            settings = self._get_redfish_filter_settings()
            if not settings:
                raise RuntimeError("Не удалось получить настройки")

            if (
                not settings['enabled'] or
                set(settings['allowed_ips']) != set(allowed_ips) or
                set(settings['blocked_ips']) != set(blocked_ips)
            ):
                raise RuntimeError("Настройки фильтрации не применились")

            return True

        except Exception as e:
            self.logger.error(
                f"Ошибка при настройке фильтрации через Redfish: {e}"
            )
            return False

    def setup_filter_via_ssh(
        self,
        allowed_ips: List[str],
        blocked_ips: List[str]
    ) -> bool:
        """
        Настраивает фильтрацию через SSH.

        Args:
            allowed_ips: Список разрешенных IP
            blocked_ips: Список заблокированных IP

        Returns:
            bool: True если настройка успешна
        """
        try:
            if not self.ssh_tester.connect():
                raise RuntimeError("Не удалось установить SSH соединение")

            # Очищаем текущие правила
            command = "sudo iptables -F INPUT"
            result = self.ssh_tester.execute_command(command)
            if not result['success']:
                raise RuntimeError("Не удалось очистить правила iptables")

            # Добавляем разрешенные IP
            for ip in allowed_ips:
                command = (
                    f"sudo iptables -A INPUT -s {ip} -j ACCEPT"
                )
                result = self.ssh_tester.execute_command(command)
                if not result['success']:
                    raise RuntimeError(
                        f"Не удалось добавить разрешенный IP: {ip}"
                    )

            # Добавляем заблокированные IP
            for ip in blocked_ips:
                command = (
                    f"sudo iptables -A INPUT -s {ip} -j DROP"
                )
                result = self.ssh_tester.execute_command(command)
                if not result['success']:
                    raise RuntimeError(
                        f"Не удалось добавить заблокированный IP: {ip}"
                    )

            # Проверяем настройки
            settings = self._get_ssh_filter_settings()
            if not settings:
                raise RuntimeError("Не удалось получить настройки")

            if (
                set(settings['allowed_ips']) != set(allowed_ips) or
                set(settings['blocked_ips']) != set(blocked_ips)
            ):
                raise RuntimeError("Настройки фильтрации не применились")

            return True

        except Exception as e:
            self.logger.error(f"Ошибка при настройке фильтрации через SSH: {e}")
            return False
        finally:
            self.ssh_tester.disconnect()

    def verify_filter_settings(self) -> bool:
        """
        Проверяет настройки фильтрации через все интерфейсы.

        Returns:
            bool: True если проверка успешна
        """
        try:
            settings = self.get_current_settings()
            if not all(settings.values()):
                raise RuntimeError(
                    "Не удалось получить настройки через все интерфейсы"
                )

            # Проверяем разрешенные IP
            allowed_ips = {
                source: set(data['allowed_ips'])
                for source, data in settings.items()
            }
            if len(set(map(frozenset, allowed_ips.values()))) > 1:
                self.logger.error(
                    f"Несоответствие разрешенных IP: {allowed_ips}"
                )
                return False

            # Проверяем заблокированные IP
            blocked_ips = {
                source: set(data['blocked_ips'])
                for source, data in settings.items()
            }
            if len(set(map(frozenset, blocked_ips.values()))) > 1:
                self.logger.error(
                    f"Несоответствие заблокированных IP: {blocked_ips}"
                )
                return False

            return True

        except Exception as e:
            self.logger.error(f"Ошибка при проверке настроек фильтрации: {e}")
            return False

    def test_filter_access(self) -> bool:
        """
        Тестирует доступность портов с разных IP-адресов.

        Returns:
            bool: True если тест успешен
        """
        try:
            success = True

            # Проверяем доступ с разрешенных IP
            for ip in self.allowed_ips:
                for port in self.test_ports:
                    if not self.verify_port_access(ip, port, True):
                        self.logger.error(
                            f"Порт {port} недоступен с разрешенного IP {ip}"
                        )
                        success = False

            # Проверяем блокировку с запрещенных IP
            for ip in self.blocked_ips:
                for port in self.test_ports:
                    if not self.verify_port_access(ip, port, False):
                        self.logger.error(
                            f"Порт {port} доступен с заблокированного IP {ip}"
                        )
                        success = False

            return success

        except Exception as e:
            self.logger.error(f"Ошибка при тестировании доступа: {e}")
            return False

    def verify_port_access(
        self,
        ip: str,
        port: int,
        should_be_accessible: bool
    ) -> bool:
        """
        Проверяет доступность порта с указанного IP.

        Args:
            ip: IP-адрес для проверки
            port: Порт для проверки
            should_be_accessible: Ожидаемая доступность

        Returns:
            bool: True если доступность соответствует ожидаемой
        """
        try:
            if not self.ssh_tester.connect():
                raise RuntimeError("Не удалось установить SSH соединение")

            command = f"nc -zv -w5 {ip} {port}"
            result = self.ssh_tester.execute_command(command)

            is_accessible = result['success'] and "succeeded" in result['output']
            return is_accessible == should_be_accessible

        except Exception as e:
            self.logger.error(f"Ошибка при проверке доступа: {e}")
            return False
        finally:
            self.ssh_tester.disconnect()

    def perform_tests(self) -> None:
        """Выполняет тестирование фильтрации IP."""
        try:
            self.logger.info("Начало тестирования фильтрации IP")

            # Сохраняем текущие настройки
            if self.backup_settings:
                self.original_settings = self.get_current_settings()

            # Настраиваем фильтрацию
            if not self.setup_ip_filter(self.allowed_ips, self.blocked_ips):
                raise RuntimeError("Не удалось настроить фильтрацию IP")

            # Проверяем настройки
            if not self.verify_filter_settings():
                raise RuntimeError("Верификация настроек фильтрации не прошла")

            # Тестируем доступность
            if self.verify_access and not self.test_filter_access():
                raise RuntimeError("Тест доступности не прошел")

            self.add_test_result('IP Filter Configuration Test', True)
            self.add_test_result('IP Filter Access Test', True)

        except Exception as e:
            self.logger.error(f"Ошибка при выполнении тестов: {e}")
            self.add_test_result('IP Filter Tests', False, str(e))
        finally:
            self.safe_restore_settings()

    def restore_settings(self) -> bool:
        """
        Восстанавливает исходные настройки фильтрации.

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
                return self.setup_filter_via_ipmi(
                    ipmi_settings.get('allowed_ips', []),
                    ipmi_settings.get('blocked_ips', [])
                )

            return True

        except Exception as e:
            self.logger.error(f"Ошибка при восстановлении настроек: {e}")
            return False
