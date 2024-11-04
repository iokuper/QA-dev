"""Модуль для тестирования настройки DNS."""

import logging
import time
from typing import Dict, Any, Optional, List, cast
from base_tester import BaseTester
from verification_utils import verify_ip_format
from network_utils import SSHManager, RedfishManager


class DNSTester(BaseTester):
    """Класс для тестирования настройки DNS."""

    def __init__(
        self,
        config_file: str = 'config.ini',
        logger: Optional[logging.Logger] = None
    ) -> None:
        """
        Инициализирует DNS тестер.

        Args:
            config_file: Путь к файлу конфигурации
            logger: Логгер для вывода сообщений
        """
        super().__init__(config_file, logger)

        # Загрузка конфигурации DNS
        dns_config = self.config_manager.get_network_config('DNS')
        self.interface = cast(str, dns_config.get('interface', '1'))
        self.primary_dns = cast(str, dns_config.get('primary_dns'))
        self.secondary_dns = cast(str, dns_config.get('secondary_dns'))
        self.test_domains = cast(
            List[str],
            dns_config.get('test_domains', '').split(',')
        )

        # Таймауты и повторы
        self.setup_timeout = int(dns_config.get('setup_timeout', '30'))
        self.verify_timeout = int(dns_config.get('verify_timeout', '60'))
        self.retry_count = int(dns_config.get('retry_count', '3'))
        self.retry_delay = int(dns_config.get('retry_delay', '10'))

        # Дополнительные параметры
        self.verify_resolution = dns_config.get(
            'verify_resolution',
            'true'
        ).lower() == 'true'
        self.backup_settings = dns_config.get(
            'backup_settings',
            'true'
        ).lower() == 'true'
        self.check_both_servers = dns_config.get(
            'check_both_servers',
            'true'
        ).lower() == 'true'

        # Инициализация других тестеров
        self.ssh_tester = SSHManager(config_file, logger)
        self.redfish_tester = RedfishManager(config_file, logger)

        # Сохранение исходных настроек
        self.original_dns_settings: Dict[str, Dict[str, str]] = {}

        self.logger.debug("Инициализация DNS тестера завершена")

    def get_current_settings(self) -> Dict[str, Any]:
        """
        Получает текущие настройки DNS через все интерфейсы.

        Returns:
            Dict[str, Any]: Текущие настройки
        """
        settings = {
            'ipmi': self._get_ipmi_dns_settings(),
            'redfish': self._get_redfish_dns_settings(),
            'ssh': self._get_ssh_dns_settings()
        }
        return settings

    def _get_ipmi_dns_settings(self) -> Dict[str, str]:
        """
        Получает настройки DNS через IPMI.

        Returns:
            Dict[str, str]: Настройки DNS
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
                if 'DNS Server 1' in line:
                    settings['primary_dns'] = line.split(':')[1].strip()
                elif 'DNS Server 2' in line:
                    settings['secondary_dns'] = line.split(':')[1].strip()
            return settings

        except Exception as e:
            self.logger.error(f"Ошибка при получении DNS через IPMI: {e}")
            return {}

    def _get_redfish_dns_settings(self) -> Dict[str, str]:
        """
        Получает настройки DNS через Redfish API.

        Returns:
            Dict[str, str]: Настройки DNS
        """
        try:
            endpoint = (
                f"/redfish/v1/Managers/Self/EthernetInterfaces/{self.interface}"
            )
            response = self.redfish_tester.run_request("GET", endpoint)
            if not response:
                raise RuntimeError("Не удалось получить настройки")

            data = response.json()
            dns_servers = data.get('NameServers', [])
            settings = {
                'primary_dns': dns_servers[0] if len(dns_servers) > 0 else '',
                'secondary_dns': dns_servers[1] if len(dns_servers) > 1 else ''
            }
            return settings

        except Exception as e:
            self.logger.error(f"Ошибка при получении DNS через Redfish: {e}")
            return {}

    def _get_ssh_dns_settings(self) -> Dict[str, str]:
        """
        Получает настройки DNS через SSH.

        Returns:
            Dict[str, str]: Настройки DNS
        """
        try:
            if not self.ssh_tester.connect():
                raise RuntimeError("Не удалось установить SSH соединение")

            command = "cat /etc/resolv.conf"
            result = self.ssh_tester.execute_command(command)
            if not result['success']:
                raise RuntimeError("Не удалось получить настройки DNS")

            settings = {'primary_dns': '', 'secondary_dns': ''}
            nameservers = []
            for line in result['output'].splitlines():
                if line.startswith('nameserver'):
                    nameservers.append(line.split()[1])

            if len(nameservers) > 0:
                settings['primary_dns'] = nameservers[0]
            if len(nameservers) > 1:
                settings['secondary_dns'] = nameservers[1]

            return settings

        except Exception as e:
            self.logger.error(f"Ошибка при получении DNS через SSH: {e}")
            return {}
        finally:
            self.ssh_tester.disconnect()

    def setup_dns_via_ipmi(self) -> bool:
        """
        Настраивает DNS через IPMI.

        Returns:
            bool: True если настройка успешна
        """
        try:
            # Проверяем корректность DNS серверов
            if not all(verify_ip_format(dns) for dns in [
                self.primary_dns,
                self.secondary_dns
            ]):
                raise ValueError("Некорректный формат IP-адреса DNS сервера")

            # Устанавливаем первичный DNS
            command = [
                "ipmitool", "-I", "lanplus",
                "-H", cast(str, self.ipmi_host),
                "-U", self.ipmi_username,
                "-P", self.ipmi_password,
                "lan", "set", self.interface,
                "dns1", self.primary_dns
            ]
            self._run_command(command)
            time.sleep(2)

            # Устанавливаем вторичный DNS
            command = [
                "ipmitool", "-I", "lanplus",
                "-H", cast(str, self.ipmi_host),
                "-U", self.ipmi_username,
                "-P", self.ipmi_password,
                "lan", "set", self.interface,
                "dns2", self.secondary_dns
            ]
            self._run_command(command)
            time.sleep(5)

            # Проверяем настройки
            settings = self._get_ipmi_dns_settings()
            if not settings:
                raise RuntimeError("Не удалось получить настройки")

            if (
                settings.get('primary_dns') != self.primary_dns or
                settings.get('secondary_dns') != self.secondary_dns
            ):
                raise RuntimeError("Настройки DNS не применились")

            return True

        except Exception as e:
            self.logger.error(f"Ошибка при настройке DNS через IPMI: {e}")
            return False

    def setup_dns_via_redfish(self) -> bool:
        """
        Настраивает DNS через Redfish API.

        Returns:
            bool: True если настройка успешна
        """
        try:
            # Проверяем корректность DNS серверов
            if not all(verify_ip_format(dns) for dns in [
                self.primary_dns,
                self.secondary_dns
            ]):
                raise ValueError("Некорректный формат IP-адреса DNS сервера")

            endpoint = (
                f"/redfish/v1/Managers/Self/EthernetInterfaces/{self.interface}"
            )
            data = {
                "NameServers": [
                    self.primary_dns,
                    self.secondary_dns
                ]
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
            settings = self._get_redfish_dns_settings()
            if not settings:
                raise RuntimeError("Не удалось получить настройки")

            if (
                settings.get('primary_dns') != self.primary_dns or
                settings.get('secondary_dns') != self.secondary_dns
            ):
                raise RuntimeError("Настройки DNS не применились")

            return True

        except Exception as e:
            self.logger.error(f"Ошибка при настройке DNS через Redfish: {e}")
            return False

    def setup_dns_via_ssh(self) -> bool:
        """
        Настраивает DNS через SSH.

        Returns:
            bool: True если настройка успешна
        """
        try:
            # Проверяем корректность DNS серверов
            if not all(verify_ip_format(dns) for dns in [
                self.primary_dns,
                self.secondary_dns
            ]):
                raise ValueError("Некорректный формат IP-адреса DNS сервера")

            if not self.ssh_tester.connect():
                raise RuntimeError("Не удалось установить SSH соединение")

            # Создаем новый resolv.conf
            resolv_conf = (
                f"nameserver {self.primary_dns}\n"
                f"nameserver {self.secondary_dns}\n"
            )

            # Записываем настройки
            command = f"echo '{resolv_conf}' | sudo tee /etc/resolv.conf"
            result = self.ssh_tester.execute_command(command)
            if not result['success']:
                raise RuntimeError("Не удалось применить настройки DNS")

            time.sleep(2)

            # Проверяем настройки
            settings = self._get_ssh_dns_settings()
            if not settings:
                raise RuntimeError("Не удалось получить настройки")

            if (
                settings.get('primary_dns') != self.primary_dns or
                settings.get('secondary_dns') != self.secondary_dns
            ):
                raise RuntimeError("Настройки DNS не применились")

            return True

        except Exception as e:
            self.logger.error(f"Ошибка при настройке DNS через SSH: {e}")
            return False
        finally:
            self.ssh_tester.disconnect()

    def verify_dns_settings(self) -> bool:
        """
        Проверяет настройки DNS через все интерфейсы.

        Returns:
            bool: True если проверка успешна
        """
        try:
            settings = self.get_current_settings()
            if not all(settings.values()):
                raise RuntimeError(
                    "Не удалось получить настройки через все интерфейсы"
                )

            # Проверяем первичный DNS
            primary_dns = {
                interface: settings['primary_dns']
                for interface, settings in settings.items()
            }
            if len(set(primary_dns.values())) > 1:
                self.logger.error(
                    f"Несоответствие первичного DNS: {primary_dns}"
                )
                return False

            # Проверяем вторичный DNS
            secondary_dns = {
                interface: settings['secondary_dns']
                for interface, settings in settings.items()
            }
            if len(set(secondary_dns.values())) > 1:
                self.logger.error(
                    f"Несоответствие вторичного DNS: {secondary_dns}"
                )
                return False

            # Проверяем разрешение имен если требуется
            if self.verify_resolution:
                if not self._verify_dns_resolution():
                    return False

            return True

        except Exception as e:
            self.logger.error(f"Ошибка при проверке настроек DNS: {e}")
            return False

    def _verify_dns_resolution(self) -> bool:
        """
        Проверяет разрешение имен через настроенные DNS серверы.

        Returns:
            bool: True если проверка успешна
        """
        try:
            if not self.ssh_tester.connect():
                raise RuntimeError("Не удалось установить SSH соединение")

            # Проверяем разрешение через каждый DNS сервер
            dns_servers = [self.primary_dns]
            if self.check_both_servers:
                dns_servers.append(self.secondary_dns)

            for dns_server in dns_servers:
                for domain in self.test_domains:
                    command = f"dig @{dns_server} {domain} +short"
                    result = self.ssh_tester.execute_command(command)
                    if not result['success'] or not result['output']:
                        self.logger.error(
                            f"Не удалось разрешить {domain} через DNS {dns_server}"
                        )
                        return False
                    self.logger.info(
                        f"Домен {domain} успешно разрешен через {dns_server}"
                    )

            return True

        except Exception as e:
            self.logger.error(f"Ошибка при проверке разрешения имен: {e}")
            return False
        finally:
            self.ssh_tester.disconnect()

    def test_invalid_settings(self) -> bool:
        """
        Тестирует установку некорректных DNS серверов.

        Returns:
            bool: True если тест прошел успешно
        """
        try:
            # Получаем некорректные настройки
            invalid_servers = [
                '256.256.256.256',  # Некорректный IP
                '0.0.0.0',  # Нулевой IP
                'invalid.dns',  # Некорректное имя
                '192.168.1',  # Неполный IP
                '300.300.300.300'  # IP вне диапазона
            ]

            # Сохраняем текущие настройки
            original_settings = self._get_ipmi_dns_settings()

            # Тестируем некорректные DNS серверы
            for invalid_server in invalid_servers:
                command = [
                    "ipmitool", "-I", "lanplus",
                    "-H", cast(str, self.ipmi_host),
                    "-U", self.ipmi_username,
                    "-P", self.ipmi_password,
                    "lan", "set", self.interface,
                    "dns1", invalid_server
                ]
                try:
                    self._run_command(command)
                    self.logger.error(
                        f"Некорректный DNS сервер {invalid_server} был принят"
                    )
                    return False
                except Exception:
                    self.logger.info(
                        f"Некорректный DNS сервер {invalid_server} был отклонен"
                    )

            # Проверяем, что настройки не изменились
            current_settings = self._get_ipmi_dns_settings()
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
        """Выполняет тестирование настройки DNS."""
        try:
            self.logger.info("Начало тестирования настройки DNS")

            # Сохраняем текущие настройки
            self.original_dns_settings = self.get_current_settings()

            # Настройка через IPMI
            if not self.setup_dns_via_ipmi():
                raise RuntimeError("Не удалось настроить DNS через IPMI")

            # Проверка настроек
            if not self.verify_dns_settings():
                raise RuntimeError("Верификация настроек DNS не прошла")

            # Настройка через Redfish
            if not self.setup_dns_via_redfish():
                raise RuntimeError("Не удалось настроить DNS через Redfish")

            # Проверка настроек
            if not self.verify_dns_settings():
                raise RuntimeError("Верификация настроек DNS не прошла")

            # Настройка через SSH
            if not self.setup_dns_via_ssh():
                raise RuntimeError("Не удалось настроить DNS через SSH")

            # Проверка настроек
            if not self.verify_dns_settings():
                raise RuntimeError("Верификация настроек DNS не прошла")

            # Тестирование некорректных настроек
            if not self.test_invalid_settings():
                raise RuntimeError("Тест некорректных настроек не прошел")

            self.add_test_result('DNS Configuration Test', True)
            self.add_test_result('DNS Servers Status Test', True)

        except Exception as e:
            self.logger.error(f"Ошибка при выполнении тестов: {e}")
            self.add_test_result('DNS Tests', False, str(e))
        finally:
            self.safe_restore_settings()

    def restore_settings(self) -> bool:
        """
        Восстанавливает исходные настройки DNS.

        Returns:
            bool: True если восстановление успешно
        """
        try:
            if not self.original_dns_settings:
                self.logger.info("Нет сохраненных настроек для восстановления")
                return True

            # Восстанавливаем через IPMI
            ipmi_settings = self.original_dns_settings.get('ipmi', {})
            if ipmi_settings:
                self.primary_dns = ipmi_settings.get('primary_dns', '')
                self.secondary_dns = ipmi_settings.get('secondary_dns', '')
                return self.setup_dns_via_ipmi()

            return True

        except Exception as e:
            self.logger.error(f"Ошибка при восстановлении настроек: {e}")
            return False

    def _run_command(
        self,
        command: List[str],
        timeout: Optional[int] = None
    ) -> Any:
        """
        Выполняет команду с проверкой вывода.

        Args:
            command: Команда для выполнения
            timeout: Таймаут выполнения

        Returns:
            Any: Результат выполнения команды

        Raises:
            RuntimeError: При ошибке выполнения команды
        """
        try:
            result = super()._run_command(command, timeout)
            combined_output = (
                f"{result.stdout}\n{result.stderr}".strip()
            )
            self.logger.error(f"Ошибка выполнения команды: {combined_output}")
            raise RuntimeError(f"Ошибка выполнения команды: {combined_output}")

            self.logger.debug("Команда успешно выполнена")
            return result

        except Exception:
            raise

    def verify_network_access(self, ip: str, ports: Optional[List[int]] = None) -> bool:
        """
        Проверяет сетевую доступность.

        Args:
            ip: IP-адрес для проверки
            ports: Список портов для проверки

        Returns:
            bool: True если доступно
        """
        if ports is None:
            ports = [22, 53]  # По умолчанию проверяем SSH и DNS

        for port in ports:
            if not wait_for_port(ip, port):
                self.logger.error(f"Порт {port} недоступен на {ip}")
                return False
        return True

    def safe_restore_settings(self) -> bool:
        """
        Безопасно восстанавливает настройки.

        Returns:
            bool: True если восстановление успешно
        """
        try:
            for attempt in range(self.retry_count):
                try:
                    if self.restore_settings():
                        if self.wait_for_dns_settings(
                            {
                                "Primary DNS Server": self.original_dns_settings.get(
                                    'ipmi', {}
                                ).get('primary_dns', ''),
                                "Secondary DNS Server": self.original_dns_settings.get(
                                    'ipmi', {}
                                ).get('secondary_dns', '')
                            },
                            timeout=self.verify_timeout
                        ):
                            self.logger.info("Настройки успешно восстановлены")
                            return True
                    self.logger.warning(
                        f"Попытка восстановления {attempt + 1} не удалась"
                    )
                except Exception as e:
                    self.logger.error(
                        f"Ошибка при попытке восстановления {attempt + 1}: {e}"
                    )
                if attempt < self.retry_count - 1:
                    time.sleep(self.retry_delay)
            return False

        except Exception as e:
            self.logger.error(f"Критическая ошибка при восстановлении: {e}")
            return False

    def wait_for_dns_settings(
        self,
        expected_settings: Dict[str, str],
        timeout: int = 60
    ) -> bool:
        """
        Ожидает применения настроек DNS.

        Args:
            expected_settings: Ожидаемые настройки
            timeout: Таймаут ожидания в секундах

        Returns:
            bool: True если настройки применились
        """
        start_time = time.time()
        while time.time() - start_time < timeout:
            settings = self._get_ipmi_dns_settings()
            if all(
                settings.get(key) == value
                for key, value in expected_settings.items()
            ):
                return True
            time.sleep(1)

        self.logger.error(
            f"Превышен таймаут ожидания применения настроек DNS ({timeout} сек)"
        )
        return False

    def verify_dns_server_status(self) -> Dict[str, bool]:
        """
        Проверяет доступность DNS серверов.

        Returns:
            Dict[str, bool]: Статус каждого DNS сервера
        """
        try:
            if not self.ssh_tester.connect_ssh():
                raise RuntimeError("Не удалось установить SSH соединение")

            status = {
                'primary': False,
                'secondary': False
            }

            # Проверяем каждый DNS сервер
            for dns_type, dns_server in [
                ('primary', self.primary_dns),
                ('secondary', self.secondary_dns)
            ]:
                command = f"nc -zv -w5 {dns_server} 53"
                output = self.ssh_tester.execute_ssh_command(command)
                status[dns_type] = output is not None and "succeeded" in output.lower()

                if status[dns_type]:
                    self.logger.info(f"{dns_type.title()} DNS сервер {dns_server} доступен")
                else:
                    self.logger.error(f"{dns_type.title()} DNS сервер {dns_server} недоступен")

            return status

        except Exception as e:
            self.logger.error(f"Ошибка при проверке статуса DNS серверов: {e}")
            return {'primary': False, 'secondary': False}
        finally:
            self.ssh_tester.close_ssh()
