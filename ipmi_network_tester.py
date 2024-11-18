"""Модуль для тестирования сетевых настроек IPMI."""

import logging
import time
from typing import Dict, Any, Optional, cast
from base_tester import BaseTester
from verification_utils import verify_settings
from network_utils import SSHManager, verify_network_access


class IPMINetworkTester(BaseTester):
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

        # Провеяем доступность хоста
        if not verify_network_access(
            ip=self.ipmi_host,
            ports=[623, 443],
            logger=self.logger
        ):
            raise RuntimeError(f"Хост {self.ipmi_host} недоступен")

        # Инициализация SSH менеджера
        self.ssh_tester = SSHManager(config_file, logger)

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
        """Получает текущие сетевые настройки."""
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
            self.logger.error(f"Ошибка пи получении настроек: {e}")
            return {}

    def setup_static_ip(self, ip: str, mask: str, gateway: str) -> bool:
        """Устанавливает статический IP-адрес."""
        try:
            self.logger.info(
                f"Применение статических параметров: IP-адрес: {ip}, "
                f"Маска: {mask}, Шлюз: {gateway}"
            )
            current_ip = None

            # Подключаемся к Ubuntu для мониторинга изменений
            if not self.ssh_tester.connect():
                raise RuntimeError("Не удалось подключиться к Ubuntu по SSH")

            try:
                # Получаем текущие настройки через SSH
                settings = verify_settings(self.ssh_tester, self.interface)
                current_ip = settings.get('IP Address')

                if not current_ip:
                    raise RuntimeError("Не удалось получить текущий IP")

                if current_ip == ip:
                    self.logger.warning(
                        f"Попытка установить текущий IP {ip}. "
                        "Пропускаем изменение IP"
                    )
                    return True

                # Отключаем DHCP через IPMI
                command = [
                    "ipmitool", "-I", "lanplus",
                    "-H", cast(str, self.ipmi_host),
                    "-U", self.ipmi_username,
                    "-P", self.ipmi_password,
                    "lan", "set", self.interface, "ipsrc", "static"
                ]
                self._run_command(command)

                # Ждем и проверяем через SSH, что DHCP отключился
                self.logger.debug(
                    "Ожидание применения настроек после отключения DHCP"
                )

                time.sleep(10)
                for attempt in range(10):
                    settings = verify_settings(self.ssh_tester, self.interface)
                    if (settings['Set in Progress'] == 'Set Complete' and
                            settings['IP Address Source'] == 'Static Address'):
                        current_ip = settings['IP Address']
                        self.logger.info(
                            f"DHCP отключен, текущий IP: {current_ip}"
                        )
                        break
                    time.sleep(self.retry_delay)
                else:
                    raise RuntimeError("Не удалось отключить DHCP")

                # Обновляем IP в конфигурации
                self.update_bmc_ip(current_ip)

                # Устанавливаем IP адрес
                self.logger.debug(f"Установка IP адреса: {ip}")
                command = [
                    "ipmitool", "-I", "lanplus",
                    "-H", current_ip,
                    "-U", self.ipmi_username,
                    "-P", self.ipmi_password,
                    "lan", "set", self.interface, "ipaddr", ip
                ]
                self._run_command(command)

                # Ждем применения IP
                time.sleep(10)
                self.logger.debug("Ожидание применения IP адреса...")
                for attempt in range(10):
                    settings = verify_settings(self.ssh_tester, self.interface)
                    if (settings['Set in Progress'] == 'Set Complete' and
                            settings['IP Address'] == ip):
                        self.logger.info(f"IP адрес {ip} успешно применен")
                        current_ip = ip
                        self.update_bmc_ip(current_ip)
                        break
                    time.sleep(self.retry_delay)
                else:
                    raise RuntimeError("Не удало применить IP адрес")

                # Устанавливаем маску подсети
                self.logger.info(f"Установка маски подсети: {mask}")
                command = [
                    "ipmitool", "-I", "lanplus",
                    "-H", ip,
                    "-U", self.ipmi_username,
                    "-P", self.ipmi_password,
                    "lan", "set", self.interface, "netmask", mask
                ]
                self._run_command(command)

                time.sleep(10)
                self.logger.debug("Ожидание применения маски...")
                for attempt in range(10):
                    settings = verify_settings(self.ssh_tester, self.interface)
                    if (settings['Set in Progress'] == 'Set Complete' and
                            settings['Subnet Mask'] == mask):
                        self.logger.info(f"Маска {mask} успешно применена")
                        break
                    time.sleep(self.retry_delay)
                else:
                    raise RuntimeError("Не удало применить маску")

                # Устанавливаем шлюз
                self.logger.info(f"Установка шлюза: {gateway}")
                command = [
                    "ipmitool", "-I", "lanplus",
                    "-H", ip,
                    "-U", self.ipmi_username,
                    "-P", self.ipmi_password,
                    "lan", "set", self.interface, "defgw", "ipaddr", gateway
                ]
                self._run_command(command)

                time.sleep(10)
                self.logger.debug("Ожидание применения шлюза...")
                for attempt in range(10):
                    settings = verify_settings(self.ssh_tester, self.interface)
                    if (settings['Set in Progress'] == 'Set Complete' and
                            settings['Default Gateway IP'] == gateway):
                        self.logger.info(f"Шлюз {gateway} успешно применен")
                        break
                    time.sleep(self.retry_delay)
                else:
                    raise RuntimeError("Не удало применить шлюз")

                # Проверяем финальное применение настроек
                self.logger.debug("Проверка применения настроек...")
                for attempt in range(10):  # Увеличиваем количество попыток
                    settings = verify_settings(self.ssh_tester, self.interface)
                    self.logger.debug(
                        f"Попытка {attempt + 1}: "
                        f"IP={settings.get('IP Address')}, "
                        f"Source={settings.get('IP Address Source')}, "
                        f"Mask={settings.get('Subnet Mask')}, "
                        f"Gateway={settings.get('Default Gateway IP')}, "
                        f"Progress={settings.get('Set in Progress')}"
                    )
                    if (settings['Set in Progress'] == 'Set Complete' and
                            settings['IP Address'] == ip and
                            settings['IP Address Source'] == 'Static Address' and
                            settings['Subnet Mask'] == mask and
                            settings['Default Gateway IP'] == gateway):
                        self.logger.info(f"Новый IP {ip} успешно установлен")
                        self.update_bmc_ip(ip)
                        return True
                    time.sleep(5)

                # Если настройки не применились, логируем текущие знчения
                self.logger.error(
                    "Не удалось применить новые настройки. "
                    f"Текущие значения: {settings}"
                )
                return False

            finally:
                self.ssh_tester.disconnect()

        except Exception as e:
            self.logger.error(f"Ошибка при настройке статического IP: {e}")
            return False

    def _wait_for_static_ip(self, max_attempts: int = 10) -> Optional[str]:
        """
        Ожидает олучения статического IP после отключения DHCP.

        Args:
            max_attempts: Максимальное количество попыток

        Returns:
            Optional[str]: Полученный IP или None при ошибке
        """
        # Подключаемся к Ubuntu по SSH
        if not self.ssh_tester.connect():
            self.logger.error("Не удалось подключиться к Ubuntu по SSH")
            return None

        try:
            for attempt in range(max_attempts):
                try:
                    # Получаем настройки через SSH на Ubuntu
                    settings = verify_settings(self.ssh_tester, self.interface)

                    if (settings['Set in Progress'] == 'Set Complete' and
                        settings['IP Address Source'] == 'Static Address'):
                        current_ip = settings['IP Address']
                        self.logger.info(
                            "Получен текущий IP после отключения DHCP: "
                            f"{current_ip}"
                        )
                        return current_ip

                except Exception as e:
                    self.logger.debug(f"Попытка {attempt + 1}: {e}")

                time.sleep(self.retry_delay)

            return None

        finally:
            self.ssh_tester.disconnect()

    def _verify_static_ip_settings(
        self,
        expected_ip: str,
        max_attempts: int = 10
    ) -> bool:
        """Проверяет применение настроек статического IP."""
        try:
            for attempt in range(max_attempts):
                settings = verify_settings(self.ssh_tester, self.interface)
                if (settings['Set in Progress'] == 'Set Complete' and
                        settings['IP Address'] == expected_ip):
                    self.logger.info(
                        f"Верификация успешна: текущий IP {expected_ip}"
                    )
                    return True
                time.sleep(self.retry_delay)
            return False

        except Exception as e:
            self.logger.debug(
                f"Попытка верификации {attempt + 1}: {e}"
            )
            return False

    def setup_dhcp(self) -> bool:
        """Включает DHCP."""
        try:
            self.logger.debug("Включение DHCP...")
            # Включаем DHCP через IPMI
            command = [
                "ipmitool", "-I", "lanplus",
                "-H", cast(str, self.ipmi_host),
                "-U", self.ipmi_username,
                "-P", self.ipmi_password,
                "lan", "set", self.interface, "ipsrc", "dhcp"
            ]
            self._run_command(command)

            # Ждем применения настроек DHCP
            time.sleep(10)
            self.logger.debug("Проверка применения настроек...")

            for attempt in range(10):
                try:
                    settings = verify_settings(self.ssh_tester, self.interface)
                    self.logger.debug(
                        f"Попытка {attempt + 1}: "
                        f"Source={settings.get('IP Address Source')}, "
                        f"IP={settings.get('IP Address')}, "
                        f"Progress={settings.get('Set in Progress')}"
                    )

                    if settings['Set in Progress'] == 'Set Complete':
                        if settings['IP Address Source'] == 'DHCP Address':
                            # Ждем получения IP и шлюза
                            if (settings['IP Address'] != '0.0.0.0' and
                                    settings['Default Gateway IP'] != '0.0.0.0'):
                                new_ip = settings['IP Address']
                                self.logger.info(
                                    f"DHCP включен, получен IP: {new_ip}"
                                )
                                self.update_bmc_ip(new_ip)
                                return True
                except Exception as e:
                    self.logger.debug(
                        f"Ошибка проверки (попытка {attempt + 1}): {e}"
                    )

                time.sleep(5)  # Уменьшаем задержку между попытками

            self.logger.error("Не удалось включить DHCP")
            return False

        except Exception as e:
            self.logger.error(f"Ошибка при настройке DHCP: {e}")
            return False

    def test_invalid_settings(self) -> bool:
        """Тестирует установку некорректных настроек."""
        try:
            # Подключаемся к Ubuntu для мониторинга
            if not self.ssh_tester.connect():
                raise RuntimeError("SSH соединение не установлено")

            try:
                # Сохраняем текущие настройки
                original_settings = self.get_current_settings()
                if not original_settings:
                    raise RuntimeError("Не удалось получить текущие настройки")

                # Получаем параметры для тестирования
                test_params = self.config_manager.get_network_params(
                    'Network',
                    self.ipmi_host
                )

                # Проверяем некорректные IP
                for invalid_ip in test_params.get('invalid_ips', []):
                    if not invalid_ip:  # Пропускаем путые значения
                        continue
                    try:
                        command = [
                            "ipmitool", "-I", "lanplus",
                            "-H", cast(str, self.ipmi_host),
                            "-U", self.ipmi_username,
                            "-P", self.ipmi_password,
                            "lan", "set", self.interface,
                            "ipaddr", invalid_ip.strip()
                        ]
                        self._run_command(command)

                        # Проверяем через SSH что IP не изменился
                        settings = verify_settings(
                            self.ssh_tester,
                            self.interface
                        )
                        if (settings['IP Address'] !=
                                original_settings['IP Address']):
                            self.logger.error(
                                f"Некорректный IP {invalid_ip} был применен!"
                            )
                            return False
                        self.logger.info(
                            f"Некорректный IP {invalid_ip} был отклонен"
                        )
                    except Exception:
                        self.logger.info(
                            f"Некорректный IP {invalid_ip} был отклонен"
                        )

                # Проверяем некорректные маски
                for invalid_mask in test_params.get('invalid_masks', []):
                    if not invalid_mask:
                        continue
                    try:
                        command = [
                            "ipmitool", "-I", "lanplus",
                            "-H", cast(str, self.ipmi_host),
                            "-U", self.ipmi_username,
                            "-P", self.ipmi_password,
                            "lan", "set", self.interface,
                            "netmask", invalid_mask
                        ]
                        self._run_command(command)

                        # Проверяем через SSH что маска не изменилась
                        settings = verify_settings(
                            self.ssh_tester,
                            self.interface
                        )
                        if (settings['Subnet Mask'] !=
                                original_settings['Subnet Mask']):
                            self.logger.error(
                                f"Некорректная маска {invalid_mask} была применена!"
                            )
                            return False
                        self.logger.info(
                            f"Некорректная маска {invalid_mask} была отклонена"
                        )
                    except Exception:
                        self.logger.info(
                            f"Некорректная маска {invalid_mask} была отклонена"
                        )

                # Проверяем некорректные шлюзы
                for invalid_gateway in test_params.get('invalid_gateways', []):
                    if not invalid_gateway:
                        continue
                    try:
                        command = [
                            "ipmitool", "-I", "lanplus",
                            "-H", cast(str, self.ipmi_host),
                            "-U", self.ipmi_username,
                            "-P", self.ipmi_password,
                            "lan", "set", self.interface,
                            "defgw", "ipaddr", invalid_gateway
                        ]
                        self._run_command(command)

                        # Проверяем через SSH что шлюз не изменился
                        settings = verify_settings(
                            self.ssh_tester,
                            self.interface
                        )
                        if (settings['Default Gateway IP'] !=
                                original_settings['Default Gateway IP']):
                            self.logger.error(
                                f"Некорректный шлюз {invalid_gateway} был применен!"
                            )
                            return False
                        self.logger.info(
                            f"Некорректный шлюз {invalid_gateway} был отклонен"
                        )
                    except Exception:
                        self.logger.info(
                            f"Некорректный шлюз {invalid_gateway} был отклонен"
                        )

                return True

            finally:
                self.ssh_tester.disconnect()

        except Exception as e:
            self.logger.error(
                f"Ошибка при тестировании некорректных настроек: {e}"
            )
            return False

    def perform_tests(self) -> None:
        """Выполняет тестирование сетевых настроек."""
        try:
            self.logger.info("Начало тестирования сетевых настроек")

            # 1. Сохраняем текущие настройки
            if self.backup_settings:
                self.original_settings = self.get_current_settings()
                if not self.original_settings:
                    raise RuntimeError("Не удалось получить текущие настройки")
                self.logger.debug(
                    f"Сохранены текущие настройки: {self.original_settings}"
                )

            # Определяем начальный режим работы
            initial_mode = self.original_settings.get('IP Address Source', '')
            self.logger.info(f"Начальный режим работы: {initial_mode}")

            # Получаем тестовые насройки
            test_settings = self.config_manager.get_network_params(
                'Network',
                self.ipmi_host
            )
            self.logger.debug(f"Получены тестовые настройки: {test_settings}")

            # 2. Тестируем некоррекные настройки если режим Static
            if initial_mode == 'Static Address':
                self.logger.info("Тестирование некорректных настроек")
                if not self.test_invalid_settings():
                    raise RuntimeError("Тест некорректных настроек не прошел")

            # 3. Тестируем переключение режимов
            if initial_mode == 'DHCP Address':
                # DHCP -> Static
                if not self.setup_static_ip(
                    test_settings['ips'][0],
                    str(test_settings['subnet_mask']),
                    str(test_settings['gateway'])
                ):
                    raise RuntimeError("Не удалось переключиться на статический IP")

                # Тестируем некорректные настройки в статическом режиме
                self.logger.info("Тестирование некорректных настроек")
                if not self.test_invalid_settings():
                    raise RuntimeError("Тест некорректных настроек не прошел")

                # Static -> DHCP
                if not self.setup_dhcp():
                    raise RuntimeError("Не удалось вернуться на DHCP")

            else:  # Static Address
                # Static -> DHCP
                if not self.setup_dhcp():
                    raise RuntimeError("Не удалось переключиться на DHCP")

                # DHCP -> Static с тестовыми настройками
                if not self.setup_static_ip(
                    test_settings['ips'][0],
                    str(test_settings['subnet_mask']),
                    str(test_settings['gateway'])
                ):
                    raise RuntimeError("Не удалось применить тестовые настройки")

            # 4. Восстанавливаем исходные настройки
            if initial_mode == 'DHCP Address':
                if not self.setup_dhcp():
                    raise RuntimeError("Не удалось восстановить DHCP")
            else:  # Static Address
                if not self.setup_static_ip(
                    self.original_settings['IP Address'],
                    self.original_settings['Subnet Mask'],
                    self.original_settings['Default Gateway IP']
                ):
                    raise RuntimeError("Не удалось восстановить статические настройки")

            self.add_test_result('Network Configuration Test', True)
            self.add_test_result('Network Accessibility Test', True)

        except Exception as e:
            self.logger.error(f"Ошибка при выполнеии тесто: {e}")
            self.add_test_result('Network Tests', False, str(e))
            if self.backup_settings:
                self.safe_restore_settings()

    def restore_settings(self) -> bool:
        """
        Восстанавливает исходные настройки.

        Returns:
            bool: True если восстановление успешно
        """
        try:
            if not self.original_settings:
                self.logger.info("Нет сохраненых настроек для восстановления")
                return True

            initial_mode = self.original_settings.get('IP Address Source', '')
            self.logger.info(f"Восстановление настроек режима: {initial_mode}")

            if initial_mode == 'DHCP Address':
                return self.setup_dhcp()
            else:
                return self.setup_static_ip(
                    self.original_settings['IP Address'],
                    self.original_settings['Subnet Mask'],
                    self.original_settings['Default Gateway IP']
                )

        except Exception as e:
            self.logger.error(f"Ошибка при воссановлении настроек: {e}")
            return False
