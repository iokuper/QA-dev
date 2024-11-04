"""Модуль для тестирования сетевых настроек."""

import logging
import time
from typing import Dict, Any, Optional, List, cast
from base_tester import BaseTester
from verification_utils import verify_ip_format, ping_ip, verify_settings
from network_utils import SSHManager, RedfishManager, wait_for_port


class NetworkTester(BaseTester):
    """Класс для тестирования сетевых настроек."""

    def __init__(
        self,
        config_file: str = 'config.ini',
        logger: Optional[logging.Logger] = None
    ) -> None:
        """
        Инициализирует Network тестер.

        Args:
            config_file: Путь к файлу конфигурации
            logger: Логгер для вывода сообщений
        """
        super().__init__(config_file, logger)

        # Загрузка конфигурации Network
        network_config = self.config_manager.get_network_config('Network')
        self.interface = cast(str, network_config.get('interface', '1'))

        # Инициализация SSH и Redfish менеджеров
        self.ssh_tester = SSHManager(config_file, logger)
        self.redfish_tester = RedfishManager(config_file, logger)

        # Таймауты и повторы
        self.setup_timeout = int(network_config.get('setup_timeout', '30'))
        self.verify_timeout = int(network_config.get('verify_timeout', '60'))
        self.retry_count = int(network_config.get('retry_count', '3'))
        self.retry_delay = int(network_config.get('retry_delay', '10'))

        # Параметры тестирования
        self.ping_count = int(network_config.get('ping_count', '4'))
        self.ping_timeout = int(network_config.get('ping_timeout', '2'))
        self.port_timeout = float(network_config.get('port_timeout', '5.0'))
        self.port_retry_interval = float(
            network_config.get('port_retry_interval', '0.1')
        )

        # Дополнительные параметры
        self.verify_access = network_config.get(
            'verify_access',
            'true'
        ).lower() == 'true'
        self.backup_settings = network_config.get(
            'backup_settings',
            'true'
        ).lower() == 'true'
        self.check_all_interfaces = network_config.get(
            'check_all_interfaces',
            'true'
        ).lower() == 'true'

        # Сохранение исходных настроек
        self.original_settings: Dict[str, Any] = {}

        self.logger.debug("Инициализация Network тестера завершена")

    def get_current_settings(self) -> Dict[str, Any]:
        """
        Получает текущие сетевые настройки.

        Returns:
            Dict[str, Any]: Текущие настройки
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
                if ':' in line:
                    key, value = [x.strip() for x in line.split(':', 1)]
                    settings[key] = value
            return settings

        except Exception as e:
            self.logger.error(f"Ошибка при получении настроек: {e}")
            return {}

    def setup_static_ip(self, ip: str, mask: str, gateway: str) -> bool:
        """
        Настравает статический IP.

        Args:
            ip: IP-адрес для настройки
            mask: Маска подсети
            gateway: Шлюз

        Returns:
            bool: True если настройка успешна
        """
        try:
            # Проверяем корректность параметров
            if not all(verify_ip_format(addr) for addr in [ip, gateway]):
                raise ValueError("Некорректный формат IP-адреса")

            # Подключаемся по SSH к Ubuntu
            if not self.ssh_tester.connect():
                raise RuntimeError("Не удалось установить SSH соединение")

            # Отключаем DHCP
            command = [
                "ipmitool", "-I", "lanplus",
                "-H", cast(str, self.ipmi_host),
                "-U", self.ipmi_username,
                "-P", self.ipmi_password,
                "lan", "set", self.interface, "ipsrc", "static"
            ]
            self._run_command(command)

            # Ждем применения настроек и получаем новый IP
            max_attempts = 30
            current_ip = None

            for attempt in range(max_attempts):
                # Проверяем статус настроек через SSH
                result = self.ssh_tester.execute_command("ipmitool lan print 1")
                if not result['success']:
                    raise RuntimeError("Не удалось получить статус настроек")

                settings = {}
                for line in result['output'].splitlines():
                    if 'Set in Progress' in line:
                        settings['set_progress'] = line.split(':')[1].strip()
                    elif 'IP Address Source' in line:
                        settings['ip_source'] = line.split(':')[1].strip()
                    elif 'IP Address' in line:
                        settings['ip_address'] = line.split(':')[1].strip()

                # Проверяем условия
                if (settings.get('set_progress') == 'Set Complete' and
                    settings.get('ip_source') == 'Static Address' and
                    settings.get('ip_address') != '0.0.0.0'):
                    current_ip = settings['ip_address']
                    break

                time.sleep(1)

            if not current_ip:
                raise RuntimeError("Не удалось получить новый IP после отключения DHCP")

            # Обновляем IP в конфигурации
            self.update_bmc_ip(current_ip)

            # Устанавливаем статический IP
            command = [
                "ipmitool", "-I", "lanplus",
                "-H", current_ip,
                "-U", self.ipmi_username,
                "-P", self.ipmi_password,
                "lan", "set", self.interface, "ipaddr", ip
            ]
            self._run_command(command)
            time.sleep(2)

            # Обновляем IP в конфигурации
            self.update_bmc_ip(ip)

            # Устанавливаем маску подсети
            command = [
                "ipmitool", "-I", "lanplus",
                "-H", ip,
                "-U", self.ipmi_username,
                "-P", self.ipmi_password,
                "lan", "set", self.interface, "netmask", mask
            ]
            self._run_command(command)
            time.sleep(2)

            # Устанавливаем шлюз
            command = [
                "ipmitool", "-I", "lanplus",
                "-H", ip,
                "-U", self.ipmi_username,
                "-P", self.ipmi_password,
                "lan", "set", self.interface, "defgw", "ipaddr", gateway
            ]
            self._run_command(command)
            time.sleep(5)

            # Проверяем настройки
            settings = self.get_current_settings()
            if not verify_settings(settings, {
                'IP Address': ip,
                'Subnet Mask': mask,
                'Default Gateway IP': gateway,
                'IP Address Source': 'Static'
            }, self.logger):
                raise RuntimeError("Настройки не применились")

            return True

        except Exception as e:
            self.logger.error(f"Ошибка при настройке статического IP: {e}")
            return False
        finally:
            self.ssh_tester.disconnect()

    def setup_dhcp(self) -> bool:
        """
        Настраивает получение IP через DHCP.

        Returns:
            bool: True если настройка успешна
        """
        try:
            # Подключаемся по SSH к Ubuntu
            if not self.ssh_tester.connect():
                raise RuntimeError("Не удалось установить SSH соединеие")

            # Включаем DHCP
            command = [
                "ipmitool", "-I", "lanplus",
                "-H", cast(str, self.ipmi_host),
                "-U", self.ipmi_username,
                "-P", self.ipmi_password,
                "lan", "set", self.interface,
                "ipsrc", "dhcp"
            ]
            self._run_command(command)

            # Ждем применения настроек и получаем новый IP
            max_attempts = 30
            current_ip = None

            for attempt in range(max_attempts):
                # Проверяем статус настроек через SSH
                result = self.ssh_tester.execute_command("ipmitool lan print 1")
                if not result['success']:
                    raise RuntimeError("Не удалось получить статус настроек")

                settings = {}
                for line in result['output'].splitlines():
                    if 'Set in Progress' in line:
                        settings['set_progress'] = line.split(':')[1].strip()
                    elif 'IP Address Source' in line:
                        settings['ip_source'] = line.split(':')[1].strip()
                    elif 'IP Address' in line:
                        settings['ip_address'] = line.split(':')[1].strip()

                # Проверяем условия
                if (settings.get('set_progress') == 'Set Complete' and
                    settings.get('ip_source') == 'DHCP Address' and
                    settings.get('ip_address') != '0.0.0.0'):
                    current_ip = settings['ip_address']
                    break

                time.sleep(1)

            if not current_ip:
                raise RuntimeError("Не удалось получить новый IP после включения DHCP")

            # Обновляем IP в конфигурации
            self.update_bmc_ip(current_ip)

            # Проверяем настройки
            settings = self.get_current_settings()
            if not settings:
                raise RuntimeError("Не удалось получить настройки")

            if settings.get('IP Address Source') != 'DHCP':
                raise RuntimeError("DHCP не включился")

            # Проверяем доступность если требуется
            if self.verify_access:
                if not self.verify_network_access(current_ip):
                    raise RuntimeError("DHCP включен, но сеть недоступна")

            return True

        except Exception as e:
            self.logger.error(f"Ошибка при настройке DHCP: {e}")
            return False
        finally:
            self.ssh_tester.disconnect()

    def test_invalid_settings(self) -> bool:
        """
        Тестирует установку некорректны�� настроек.

        Returns:
            bool: True если тест прошел успешно
        """
        try:
            # Сохраняем текущие настройки
            original_settings = self.get_current_settings()

            # Тестируем некорректные IP
            invalid_ips = [
                '256.256.256.256',  # Некорректный IP
                '0.0.0.0',  # Нулевой IP
                'invalid.ip',  # Некорректный формат
                '192.168.1',  # Неполный IP
                '300.300.300.300'  # IP вне диапазона
            ]

            for invalid_ip in invalid_ips:
                try:
                    command = [
                        "ipmitool", "-I", "lanplus",
                        "-H", cast(str, self.ipmi_host),
                        "-U", self.ipmi_username,
                        "-P", self.ipmi_password,
                        "lan", "set", self.interface,
                        "ipaddr", invalid_ip
                    ]
                    self._run_command(command)
                    self.logger.error(
                        f"Некорректный IP {invalid_ip} был принят"
                    )
                    return False
                except Exception:
                    self.logger.info(
                        f"Некорректный IP {invalid_ip} был отклонен"
                    )

            # Проверяем, что настройки не изменились
            current_settings = self.get_current_settings()
            if not verify_settings(
                current_settings,
                original_settings,
                self.logger
            ):
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
        """Выполняет тестирование сетевых настроек."""
        try:
            self.logger.info("Начало тестирования сетевых настроек")

            # Сохраняем текущие настройки
            if self.backup_settings:
                self.original_settings = self.get_current_settings()

            # Получаем тестовые настройки
            test_settings = self.config_manager.get_network_params(
                'Network',
                '75'  # Ипользуем сет 75 для тестов
            )

            # Настройка статического IP
            if not self.setup_static_ip(
                test_settings['ips'][0],
                self.default_subnet_mask,
                test_settings['gateway']
            ):
                raise RuntimeError("Не удалось настроить статический IP")

            # Тестирование некорректных настроек
            if not self.test_invalid_settings():
                raise RuntimeError("Тест некорректных настроек не прошел")

            # Переключение на DHCP
            if not self.setup_dhcp():
                raise RuntimeError("Не удалось настроить DHCP")

            self.add_test_result('Network Configuration Test', True)
            self.add_test_result('Network Accessibility Test', True)

        except Exception as e:
            self.logger.error(f"Ошибка при выполнении тестов: {e}")
            self.add_test_result('Network Tests', False, str(e))
        finally:
            self.safe_restore_settings()

    def restore_settings(self) -> bool:
        """
        Восстанавливает исходные настройки.

        Returns:
            bool: True если восстановление успешно
        """
        try:
            if not self.original_settings:
                self.logger.info("Нет сохраненных настроек для восстановления")
                return True

            # Восстанавливаем настройки
            if self.original_settings.get('IP Address Source') == 'DHCP':
                return self.setup_dhcp()
            else:
                return self.setup_static_ip(
                    self.original_settings['IP Address'],
                    self.original_settings['Subnet Mask'],
                    self.original_settings['Default Gateway IP']
                )

        except Exception as e:
            self.logger.error(f"Ошибка при восстановлении настроек: {e}")
            return False

    def verify_network_access(self, ip: str) -> bool:
        """
        Проверяет сетевую доступность.

        Args:
            ip: IP-адрес для проверки

        Returns:
            bool: True если доступно
        """
        try:
            # Проверяем доступность по ICMP
            if not wait_for_port(ip, 22, timeout=self.verify_timeout):
                self.logger.error(f"IP {ip} недоступен")
                return False

            # Проверяем доступность по SSH
            if not wait_for_port(ip, 22, timeout=self.verify_timeout):
                self.logger.error(f"SSH порт недоступен на {ip}")
                return False

            # Проверяем доступность по IPMI
            if not wait_for_port(ip, 623, timeout=self.verify_timeout):
                self.logger.error(f"IPMI порт недоступен на {ip}")
                return False

            return True

        except Exception as e:
            self.logger.error(f"Ошибка при проверке доступности {ip}: {e}")
            return False
