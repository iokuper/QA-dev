"""Модуль для тестирования через SSH."""

import logging
import time
from typing import Dict, Any, Optional, cast
from base_tester import BaseTester
from verification_utils import verify_ip_format
from network_utils import SSHManager


class SSHTester(BaseTester):
    """Класс для тестирования через SSH."""

    def __init__(
        self,
        config_file: str = 'config.ini',
        logger: Optional[logging.Logger] = None
    ) -> None:
        """
        Инициализирует SSH тестер.

        Args:
            config_file: Путь к файлу конфигурации
            logger: Логгер для вывода сообщений
        """
        super().__init__(config_file, logger)

        # Загрузка конфигурации SSH
        ssh_config = self.config_manager.get_network_config('SSH')
        self.interface = cast(str, ssh_config.get('interface', '1'))

        # Получаем SSH настройки
        credentials = self.config_manager.get_credentials('SSH')
        self.ssh_username = cast(str, credentials['username'])
        self.ssh_password = cast(str, credentials['password'])
        self.ssh_port = int(ssh_config.get('ssh_port', '22'))

        # Таймауты и повторы
        self.setup_timeout = int(ssh_config.get('setup_timeout', '30'))
        self.verify_timeout = int(ssh_config.get('verify_timeout', '60'))
        self.retry_count = int(ssh_config.get('retry_count', '3'))
        self.retry_delay = int(ssh_config.get('retry_delay', '10'))

        # Дополнительные параметры
        self.verify_access = ssh_config.get(
            'verify_access',
            'true'
        ).lower() == 'true'
        self.backup_settings = ssh_config.get(
            'backup_settings',
            'true'
        ).lower() == 'true'
        self.check_sudo = ssh_config.get(
            'check_sudo',
            'true'
        ).lower() == 'true'

        # Инициализация SSH менеджера
        self.ssh_manager = SSHManager(config_file, logger)

        # Сохранение исходных настроек
        self.original_settings: Dict[str, Any] = {}

        self.logger.debug("Инициализация SSH тестера завершена")

    def get_current_settings(self) -> Dict[str, Any]:
        """
        Получает текущие сетевые настройки через SSH.

        Returns:
            Dict[str, Any]: Текущие настройки
        """
        try:
            if not self.ssh_manager.connect():
                raise RuntimeError("Не удалось установить SSH соединение")

            # Получаем IP адрес
            command = "ip addr show"
            result = self.ssh_manager.execute_command(command)
            if not result['success']:
                raise RuntimeError("Не удалось получить IP адрес")

            settings: Dict[str, Any] = {}
            if result['output']:
                for line in result['output'].splitlines():
                    if 'inet ' in line:
                        parts = line.strip().split()
                        ip = parts[1].split('/')[0]
                        settings['IP Address'] = ip
                        break

            # Получаем маску подсети
            command = "ip route show"
            result = self.ssh_manager.execute_command(command)
            if not result['success']:
                raise RuntimeError("Не удалось получить маску подсети")

            if result['output']:
                for line in result['output'].splitlines():
                    if 'dev' in line and settings.get('IP Address') in line:
                        mask = line.split()[1].split('/')[1]
                        settings['Subnet Mask'] = self._cidr_to_netmask(int(mask))
                        break

            # Получаем шлюз по умолчанию
            command = "ip route show default"
            result = self.ssh_manager.execute_command(command)
            if not result['success']:
                raise RuntimeError("Не удалось получить шлюз")

            if result['output']:
                gateway = result['output'].split()[2]
                settings['Default Gateway IP'] = gateway

            # Определяем источник IP
            command = "nmcli -t -f IP4.METHOD connection show"
            result = self.ssh_manager.execute_command(command)
            if result['success'] and result['output']:
                method = result['output'].strip()
                settings['IP Address Source'] = (
                    'DHCP' if 'auto' in method else 'Static'
                )

            return settings

        except Exception as e:
            self.logger.error(f"Ошибка при получении настроек через SSH: {e}")
            return {}
        finally:
            self.ssh_manager.disconnect()

    def setup_static_ip(
        self,
        ip: str,
        mask: str,
        gateway: str
    ) -> bool:
        """
        Настраивает статический IP через SSH.

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

            if not self.ssh_manager.connect():
                raise RuntimeError("Не удалось установить SSH соединение")

            # Получаем имя интерфейса
            command = "ip link show"
            result = self.ssh_manager.execute_command(command)
            if not result['success']:
                raise RuntimeError("Не удалось получить список интерфейсов")

            interface_name = None
            if result['output']:
                for line in result['output'].splitlines():
                    if 'state UP' in line:
                        interface_name = line.split(':')[1].strip()
                        break

            if not interface_name:
                raise RuntimeError("Не удалось определить имя интерфейса")

            # Настраиваем статический IP
            cidr = self._netmask_to_cidr(mask)
            commands = [
                f"sudo nmcli con mod {interface_name} ipv4.method manual",
                (f"sudo nmcli con mod {interface_name} "
                 f"ipv4.addresses {ip}/{cidr}"),
                f"sudo nmcli con mod {interface_name} ipv4.gateway {gateway}",
                f"sudo nmcli con down {interface_name}",
                f"sudo nmcli con up {interface_name}"
            ]

            for cmd in commands:
                result = self.ssh_manager.execute_command(cmd)
                if not result['success']:
                    raise RuntimeError(f"Не удалось выполнить команду: {cmd}")
                time.sleep(2)

            # Проверяем настройки
            settings = self.get_current_settings()
            if not settings:
                raise RuntimeError("Не удалось получить настройки")

            if (
                settings.get('IP Address') != ip or
                settings.get('Subnet Mask') != mask or
                settings.get('Default Gateway IP') != gateway or
                settings.get('IP Address Source') != 'Static'
            ):
                raise RuntimeError("Настройки не применились")

            return True

        except Exception as e:
            self.logger.error(f"Ошибка при настройке статического IP: {e}")
            return False
        finally:
            self.ssh_manager.disconnect()

    def setup_dhcp(self) -> bool:
        """
        Настраивает получение IP через DHCP.

        Returns:
            bool: True если настройка успешна
        """
        try:
            if not self.ssh_manager.connect():
                raise RuntimeError("Не удалось установить SSH соединение")

            # Получаем имя интерфейса
            command = "ip link show"
            result = self.ssh_manager.execute_command(command)
            if not result['success']:
                raise RuntimeError("Не удалось получить список интерфейсов")

            interface_name = None
            if result['output']:
                for line in result['output'].splitlines():
                    if 'state UP' in line:
                        interface_name = line.split(':')[1].strip()
                        break

            if not interface_name:
                raise RuntimeError("Не удалось определить имя интерфейса")

            # Настраиваем DHCP
            commands = [
                f"sudo nmcli con mod {interface_name} ipv4.method auto",
                f"sudo nmcli con down {interface_name}",
                f"sudo nmcli con up {interface_name}"
            ]

            for cmd in commands:
                result = self.ssh_manager.execute_command(cmd)
                if not result['success']:
                    raise RuntimeError(f"Не удалось выполнить команду: {cmd}")
                time.sleep(2)

            # Проверяем настройки
            settings = self.get_current_settings()
            if not settings:
                raise RuntimeError("Не удалось получить настройки")

            if settings.get('IP Address Source') != 'DHCP':
                raise RuntimeError("DHCP не включился")

            return True

        except Exception as e:
            self.logger.error(f"Ошибка при настройке DHCP: {e}")
            return False
        finally:
            self.ssh_manager.disconnect()

    def check_sudo_privileges(self) -> bool:
        """
        Проверяет наличие sudo привилегий.

        Returns:
            bool: True если есть sudo привилегии
        """
        try:
            if not self.ssh_manager.connect():
                raise RuntimeError("Не удалось установить SSH соединение")

            command = "sudo -n true"
            result = self.ssh_manager.execute_command(command)
            return result['success']

        except Exception as e:
            self.logger.error(f"Ошибка при проверке sudo привилегий: {e}")
            return False
        finally:
            self.ssh_manager.disconnect()

    def _cidr_to_netmask(self, cidr: int) -> str:
        """
        Конвертирует CIDR в маску подсети.

        Args:
            cidr: CIDR нотация (например, 24)

        Returns:
            str: Маска подсети (например, 255.255.255.0)
        """
        mask = (0xffffffff >> (32 - cidr)) << (32 - cidr)
        return '.'.join(
            [str((mask >> (8 * i)) & 0xff) for i in range(3, -1, -1)]
        )

    def _netmask_to_cidr(self, netmask: str) -> int:
        """
        Конвертирует маску подсети в CIDR.

        Args:
            netmask: Маска подсети (например, 255.255.255.0)

        Returns:
            int: CIDR нотация (например, 24)
        """
        return sum(bin(int(x)).count('1') for x in netmask.split('.'))

    def perform_tests(self) -> None:
        """Выполняет тестирование через SSH."""
        try:
            self.logger.info("Начало тестирования через SSH")

            # Проверяем sudo привилегии если требуется
            if self.check_sudo and not self.check_sudo_privileges():
                raise RuntimeError("Недостаточно sudo привилегий")

            # Сохраняем текущие настройки
            if self.backup_settings:
                self.original_settings = self.get_current_settings()

            # Получаем тестовые настройки
            test_settings = self.config_manager.get_test_params('SSH')

            # Настройка статического IP
            if not self.setup_static_ip(
                test_settings['ips'][0],
                self.default_subnet_mask,
                test_settings['gateway']
            ):
                raise RuntimeError("Не удалось настроить статический IP")

            # Переключение на DHCP
            if not self.setup_dhcp():
                raise RuntimeError("Не удалось настроить DHCP")

            self.add_test_result('SSH Configuration Test', True)
            self.add_test_result('SSH Accessibility Test', True)

        except Exception as e:
            self.logger.error(f"Ошибка при выполнении тестов: {e}")
            self.add_test_result('SSH Tests', False, str(e))
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
