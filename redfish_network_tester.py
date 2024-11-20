"""Модуль для тестирования сетевых настроек через Redfish API."""

import logging
import time
from typing import Dict, Any, Optional, List, cast
from base_tester import BaseTester
from verification_utils import verify_settings, verify_port_open
from network_utils import SSHManager, RedfishManager


class RedfishNetworkTester(BaseTester):
    """Класс для тестирования сетевых настроек через Redfish API."""

    def __init__(
        self,
        config_file: str = 'config.ini',
        logger: Optional[logging.Logger] = None
    ) -> None:
        """
        Инициализирует Redfish Network тестер.

        Args:
            config_file: Путь к файлу конфигурации
            logger: Логгер для вывода сообщений
        """
        super().__init__(config_file, logger)

        # Загрузка конфигурации Redfish
        redfish_config = self.config_manager.get_network_config('Redfish')

        # Инициализация менеджеров с правильной пердачей config_file
        self.redfish_manager = RedfishManager(str(config_file), logger)
        self.ssh_tester = SSHManager(str(config_file), logger)

        # Параметры тестирования
        self.interface = cast(str, redfish_config.get('interface', '1'))
        self.verify_access = redfish_config.get('verify_access', 'true').lower() == 'true'
        self.backup_settings = redfish_config.get('backup_settings', 'true').lower() == 'true'
        self.check_all_interfaces = redfish_config.get('check_all_interfaces', 'true').lower() == 'true'

        # Загрузка параметров тестирования некорректных настроек
        self.invalid_ips = [ip.strip() for ip in redfish_config.get('invalid_ips', '').split(',') if ip.strip()]
        self.invalid_masks = [mask.strip() for mask in redfish_config.get('invalid_masks', '').split(',') if mask.strip()]
        self.invalid_gateways = [gw.strip() for gw in redfish_config.get('invalid_gateways', '').split(',') if gw.strip()]

        self.logger.debug("Инициализация RedfishNetworkTester завершена")

    def get_current_settings_via_ssh(self) -> Dict[str, Any]:
        """Получает текущие сетевые настойки через SSH к ОС с использованием ipmitool."""
        try:
            if not self.ssh_tester.connect():
                raise RuntimeError("Не удалось подключиться к ОС через SSH")

            command = f"ipmitool lan print {self.interface}"
            stdout, stderr = self.ssh_tester.execute_command(command)

            if stderr:
                raise RuntimeError(f"Ошибка выполнения команды: {stderr}")

            settings = {}
            if stdout:
                for line in stdout.splitlines():
                    line = line.strip()
                    if ':' in line:
                        parts = [x.strip() for x in line.split(':', 1)]
                        if len(parts) == 2:
                            key, value = parts
                            settings[key] = value
                        else:
                            self.logger.debug(f"Строка имеет неожиданный формат: {line}")
                    else:
                        self.logger.debug(f"Строка без двоеточия: {line}")
            return settings

        except Exception as e:
            self.logger.error(f"Ошибка получения настроек через SSH: {e}", exc_info=True)
            return {}
        finally:
            self.ssh_tester.disconnect()

    def get_current_settings_via_ipmi(self) -> Dict[str, Any]:
        """Получает текущие сетевые настройки через IPMI (ipmitool с локальной машины)."""
        try:
            command = [
                "ipmitool", "-I", "lanplus",
                "-H", self.ipmi_host,
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
            self.logger.error(f"Ошибка получения настроек через IPMI: {e}", exc_info=True)
            return {}

    def get_current_settings_via_redfish(self, interface_id: str) -> Dict[str, Any]:
        """Получает текущие сетевые настройки через Redfish API для указанного интерфейса."""
        try:
            self.redfish_manager.connect()
            manager_id = self.get_manager_id()
            if manager_id is None:
                raise RuntimeError("Не удалось получить ManagerId")

            endpoint = f"/redfish/v1/Managers/{manager_id}/EthernetInterfaces/{interface_id}"
            response = self.redfish_manager.run_request("GET", endpoint)
            if response is None or not response.ok:
                raise RuntimeError(f"Не удалось получить данные интерфейса через Redfish: {response}")

            data = response.json()
            return data
        except Exception as e:
            self.logger.error(f"Ошибка получения настроек через Redfish: {e}", exc_info=True)
            return {}
        finally:
            self.redfish_manager.disconnect()

    def get_manager_id(self) -> Optional[str]:
        """Получает ManagerId из Redfish API."""
        try:
            # Добавляем вызов connect
            self.redfish_manager.connect()

            endpoint = "/redfish/v1/Managers/"
            response = self.redfish_manager.run_request("GET", endpoint)
            if response is None or not response.ok:
                raise RuntimeError(f"Не удалось получить список Managers через Redfish API: {response}")
            data = response.json()
            managers = data.get('Members', [])
            if not managers:
                self.logger.error("Список Managers пуст")
                return None
            # Возьмём первый менеджер
            manager_uri = managers[0]['@odata.id']
            manager_id = manager_uri.strip('/').split('/')[-1]
            return manager_id
        except Exception as e:
            self.logger.error(f"Ошибка при получении ManagerId: {e}", exc_info=True)
            return None
        finally:
            self.redfish_manager.disconnect()

    def get_active_interface_ids(self, manager_id: str) -> List[str]:
        """Возвращает список идентифкаторов активных Ethernet-интерфейсов."""
        interface_ids = []
        try:
            endpoint = f"/redfish/v1/Managers/{manager_id}/EthernetInterfaces/"
            response = self.redfish_manager.run_request("GET", endpoint)
            if response is None or not response.ok:
                raise RuntimeError(f"Не далось получить список EthernetInterfaces через Redfish API: {response}")
            data = response.json()
            interfaces = data.get('Members', [])
            if not interfaces:
                self.logger.error("Список EthernetInterfaces пуст")
                return []

            self.logger.debug(f"Найдено {len(interfaces)} интерфейсов")

            for interface in interfaces:
                interface_uri = interface['@odata.id']
                response = self.redfish_manager.run_request("GET", interface_uri)
                if response is None or not response.ok:
                    self.logger.error(f"Не удалось получить данные для интерфейса {interface_uri}")
                    continue
                interface_data = response.json()
                self.logger.debug(f"Данные интерфейса {interface_uri}: {interface_data}")

                # Проверяем наличие IPv4 адресов
                ipv4_addresses = interface_data.get('IPv4Addresses', [])
                if ipv4_addresses:
                    interface_id = interface_uri.strip('/').split('/')[-1]
                    self.logger.info(f"Найден интерфейс с IP-адресом: {interface_id}")
                    interface_ids.append(interface_id)

            if not interface_ids:
                self.logger.error("Не удалось найти интерфейсы с IP-адресами")
            return interface_ids
        except Exception as e:
            self.logger.error(f"Ошибка при получении InterfaceIds: {e}", exc_info=True)
            return []

    def get_initial_modes(self) -> Dict[str, bool]:
        """Определяет начальный режим получения IP-адреса для каждого интерфейса."""
        initial_modes = {}
        try:
            for interface_id in self.original_settings.keys():
                settings = self.original_settings[interface_id]
                dhcp_enabled = settings.get('DHCPv4', {}).get('DHCPEnabled', False)
                initial_modes[interface_id] = dhcp_enabled
                mode_str = 'DHCP' if dhcp_enabled else 'Static'
                self.logger.info(f"Начальный режим работы интерфейса {interface_id}: {mode_str}")
            return initial_modes
        except Exception as e:
            self.logger.error(f"Ошибка определения начальных режимов: {e}", exc_info=True)
            return {}

    def update_bmc_ip(self, new_ip: str) -> None:
        """
        Обновляет IP адрес BMC во всех компонентах.

        Args:
            new_ip: Новый IP адрес
        """
        try:
            old_ip = self.ipmi_host
            self.logger.info(f"Обновление IP BMC: {old_ip} -> {new_ip}")

            # Обновляем IP в текущем экземпляре
            self.ipmi_host = new_ip


            time.sleep(20)
            if not verify_port_open(old_ip, 443):
                self.logger.info(f"Старый IP {old_ip} больше не доступен")
                time.sleep(5)

            # Ждем доступности нового IP
            self.logger.info(f"Ожидание доступности нового IP {new_ip}")
            if verify_port_open(new_ip, 443):
                self.logger.info(f"Новый IP {new_ip} стал доступен")
                time.sleep(5)
            else:
                raise RuntimeError(f"Таймаут ожидания доступности нового IP {new_ip}")

            # Пересоздаем Redfish менеджер с новым IP
            self.redfish_manager.disconnect()

            # Создаем новую конфигурацию с обновленным IP
            redfish_config = self.config_manager.get_network_config('Redfish')
            redfish_config['redfish_host'] = new_ip

            # Создаем новый экземпляр RedfishManager с обновленно конфигурацией
            self.redfish_manager = RedfishManager(
                self.config_file,
                self.logger
            )

            # Обновляем host в redfish_manager напрямую
            self.redfish_manager.host = new_ip
            self.redfish_manager.base_url = f"https://{new_ip}:{self.redfish_manager.port}"

            # Пробуем подключиться несколько раз
            max_attempts = 3
            for attempt in range(max_attempts):
                try:
                    if self.redfish_manager.connect():
                        self.logger.info(f"Успешное подключение к BMC по новому IP {new_ip}")
                        return
                    time.sleep(10)
                except Exception as e:
                    if attempt == max_attempts - 1:
                        raise
                    self.logger.warning(f"Попытка {attempt + 1} подключения не удалась: {e}")

            raise RuntimeError(f"Не удалось подключиться к BMC по новому IP {new_ip} после {max_attempts} попыток")

        except Exception as e:
            self.logger.error(f"Ошибка при обновлении IP BMC: {e}")
            raise

    def setup_static_ip_via_redfish(
        self,
        interface_id: str,
        ip: str,
        mask: str,
        gateway: str
    ) -> bool:
        """Устанавливает статический IP через Redfish API."""
        try:
            self.logger.info(
                f"Установка статического IP на интерфейсе {interface_id}: "
                f"IP: {ip}, Маска: {mask}, Шлюз: {gateway}"
            )

            # Получаем текущие настройки
            response = self.redfish_manager.run_request(
                "GET",
                f"/redfish/v1/Managers/Self/EthernetInterfaces/{interface_id}"
            )
            if not response or not response.ok:
                raise RuntimeError("Не удалось получить текущие настройки")

            current_settings = response.json()
            current_ip = current_settings.get('IPv4Addresses', [{}])[0].get('Address')

            # Проверяем, не пытаемся ли мы установить те же настройки
            if current_ip == ip:
                self.logger.info(f"IP {ip} уже установлен, пропускаем настройку")
                return True

            # Формируем и отправляем запрос
            etag = response.headers.get('ETag')
            headers = {
                'Content-Type': 'application/json',
                'If-Match': etag if etag else ''
            }

            payload = {
                'DHCPv4': {'DHCPEnabled': False},
                'IPv4StaticAddresses': [{
                    'Address': ip,
                    'SubnetMask': mask,
                    'Gateway': gateway
                }]
            }

            response = self.redfish_manager.run_request(
                "PATCH",
                f"/redfish/v1/Managers/Self/EthernetInterfaces/{interface_id}",
                data=payload,
                headers=headers
            )

            if not response.ok:
                error_message = (
                    f"Не удалось установить статический IP: "
                    f"{response.status_code} {response.reason}"
                )
                if response.text:
                    error_message += f", Ответ: {response.text}"
                raise RuntimeError(error_message)

            # Обновляем IP во всех компонентах
            self.update_bmc_ip(ip)
            return True

        except Exception as e:
            self.logger.error(f"Ошибка установки статического IP: {e}")
            return False

    def enable_dhcp_via_redfish(self, interface_id: str) -> bool:
        """Включат DHCP через Redfish API."""
        try:
            self.logger.info(f"Включение DHCP на интерфейсе {interface_id}")

            # Получаем текущие настройки
            settings = self.get_current_settings_via_redfish(interface_id)
            if not settings:
                raise RuntimeError("Не удалось получить текущие настройки")

            # Проверяем, не включен ли уже DHCP
            if settings.get('DHCPv4', {}).get('DHCPEnabled', False):
                self.logger.info(f"DHCP уже включен на интерфейсе {interface_id}")
                return True

            # Получаем текущий ETag и отправляем запрос на включение DHCP
            endpoint = f"/redfish/v1/Managers/Self/EthernetInterfaces/{interface_id}"
            response = self.redfish_manager.run_request("GET", endpoint)
            if not response or not response.ok:
                raise RuntimeError("Не удалось получить текущие настройки")

            etag = response.headers.get('ETag', '')
            headers = {'Content-Type': 'application/json'}
            if etag:
                headers['If-Match'] = etag

            # Включаем DHCP
            payload = {
                "DHCPv4": {
                    "DHCPEnabled": True
                }
            }

            response = self.redfish_manager.run_request(
                "PATCH",
                endpoint,
                data=payload,
                headers=headers
            )

            if not response or not response.ok:
                error_message = f"Не удалось включить DHCP через Redfish API: {response.status_code} {response.reason}"
                if response.text:
                    error_message += f", Тело ответа: {response.text}"
                raise RuntimeError(error_message)

            self.logger.info(f"Запрос на включение DHCP отправлен через Redfish API для интерфейса {interface_id}")

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

            raise RuntimeError("Не удалось подтвердить применение DHCP настроек")

        except Exception as e:
            self.logger.error(f"Ошибка при включении DHCP через Redfish: {e}")
            return False

    def test_invalid_settings(self, interface_id: str) -> bool:
        """Тестирует установку некорректных настроек на указанном интерфейсе."""
        try:
            self.logger.info(f"Тестирование некорректных настроек на интерфейсе {interface_id}")
            self.redfish_manager.connect()

            manager_id = self.get_manager_id()
            if manager_id is None:
                raise RuntimeError("Не удалось получить ManagerId")

            # Плучаем текущий ETag
            endpoint = f"/redfish/v1/Managers/{manager_id}/EthernetInterfaces/{interface_id}"
            get_response = self.redfish_manager.run_request("GET", endpoint)
            if get_response is None or not get_response.ok:
                raise RuntimeError(f"Не удалось получить данные интерфейса: {get_response}")
            etag = get_response.headers.get('ETag', '')
            headers = {'Content-Type': 'application/json'}
            if etag:
                headers['If-Match'] = etag

            # Сохраняем исходные настройки
            original_settings = get_response.json()

            # Тестрование некорректных IP-адресов
            for invalid_ip in self.invalid_ips:
                self.logger.debug(f"Тестирование некорректного IP: {invalid_ip}")
                payload = {
                    "IPv4StaticAddresses": [
                        {
                            "Address": invalid_ip,
                            "SubnetMask": "255.255.255.0",
                            "Gateway": "192.168.1.1"
                        }
                    ],
                    "DHCPv4": {
                        "DHCPEnabled": False
                    }
                }
                response = self.redfish_manager.run_request("PATCH", endpoint, data=payload, headers=headers)
                if response and response.ok:
                    self.logger.error(f"Некорректный IP {invalid_ip} был принят системой!")
                    return False
                else:
                    self.logger.info(f"Некорректный IP {invalid_ip} был отклонен")

            # Тестирование некорректных масок подсети
            for invalid_mask in self.invalid_masks:
                self.logger.debug(f"Тестирование некорректной маски подсети: {invalid_mask}")
                payload = {
                    "IPv4StaticAddresses": [
                        {
                            "Address": "192.168.1.100",
                            "SubnetMask": invalid_mask,
                            "Gateway": "192.168.1.1"
                        }
                    ],
                    "DHCPv4": {
                        "DHCPEnabled": False
                    }
                }
                response = self.redfish_manager.run_request("PATCH", endpoint, data=payload, headers=headers)
                if response and response.ok:
                    self.logger.error(f"Некорректная маска подсети {invalid_mask} была принята системой!")
                    return False
                else:
                    self.logger.info(f"Некорректная маска подсети {invalid_mask} была отклонена")

            # Тестирование некорректных шлюзов
            for invalid_gateway in self.invalid_gateways:
                self.logger.debug(f"Тестирование некорректного шлюза: {invalid_gateway}")
                payload = {
                    "IPv4StaticAddresses": [
                        {
                            "Address": "192.168.1.100",
                            "SubnetMask": "255.255.255.0",
                            "Gateway": invalid_gateway
                        }
                    ],
                    "DHCPv4": {
                        "DHCPEnabled": False
                    }
                }
                response = self.redfish_manager.run_request("PATCH", endpoint, data=payload, headers=headers)
                if response and response.ok:
                    self.logger.error(f"Некоректный шлюз {invalid_gateway} был принят системой!")
                    return False
                else:
                    self.logger.info(f"Некорректный шлюз {invalid_gateway} был отклонен")

            return True

        except Exception as e:
            self.logger.error(f"Ошибка при тестировании некорректных настроек: {e}", exc_info=True)
            return False
        finally:
            self.redfish_manager.disconnect()

    def perform_tests(self) -> None:
        """Выпоняет тестирование сетевых настроек."""
        try:
            self.logger.info("Начало тестирования сетевых настроек через Redfish API")

            # Получаем тестовые параметры из конфигурации
            test_params = self.config_manager.get_test_params('Network')
            test_ip = test_params['ips']
            test_mask = test_params.get('subnet_mask', '255.255.255.0')
            test_gateway = test_params['gateway']

            # Получаем ManagerId
            manager_id = self.get_manager_id()
            if manager_id is None:
                raise RuntimeError("Не удалось получить ManagerId")

            # Получаем список активных интерфейсов
            interface_ids = self.get_active_interface_ids(manager_id)
            if not interface_ids:
                raise RuntimeError("Не удалось получить список активных интерфейсов")

            # Сохраняем текущие настройки
            if self.backup_settings:
                for interface_id in interface_ids:
                    settings = self.get_current_settings_via_redfish(interface_id)
                    if settings:
                        self.original_settings[interface_id] = settings
                        self.logger.debug(
                            f"Сохранены исходные настройки {interface_id}: {settings}"
                        )

            # Определяем начальные режимы
            initial_modes = self.get_initial_modes()

            # Тестируем каждый интерфейс
            for interface_id in interface_ids:
                dhcp_enabled = initial_modes.get(interface_id, False)
                mode_str = 'DHCP' if dhcp_enabled else 'Static'
                self.logger.info(f"Тестирование интерфейса {interface_id} (режим: {mode_str})")

                # Пропускаем тестирование USB интерфейса
                if 'usb' in interface_id.lower():
                    self.logger.info(f"Пропуск тестирования USB интерфейса {interface_id}")
                    continue

                try:
                    if dhcp_enabled:
                        # Начальный режим DHCP
                        self.logger.info(f"Переключение {interface_id} в статический режим")
                        if not self.setup_static_ip_via_redfish(
                            interface_id, test_ip, test_mask, test_gateway
                        ):
                            raise RuntimeError(
                                "Не удалось переклюиться на статический IP"
                            )

                        self.logger.info(f"Тестирование некорректных настроек на {interface_id}")
                        if not self.test_invalid_settings(interface_id):
                            raise RuntimeError("Тест некорректных настроек не прошел")

                        self.logger.info(f"Возврат {interface_id} в режим DHCP")
                        if not self.enable_dhcp_via_redfish(interface_id):
                            raise RuntimeError("Не удалось вернуться на DHCP")

                    else:
                        # Начальный режим Static
                        self.logger.info(f"Тестирование некорректных настроек на {interface_id}")
                        if not self.test_invalid_settings(interface_id):
                            raise RuntimeError("Тест некорректных настроек не прошел")

                        self.logger.info(f"Применение тестовых настроек на {interface_id}")
                        if not self.setup_static_ip_via_redfish(
                            interface_id, test_ip, test_mask, test_gateway
                        ):
                            raise RuntimeError(
                                "Не удалось применить тестовые настройки"
                            )

                        self.logger.info(f"Переключение {interface_id} в режим DHCP")
                        if not self.enable_dhcp_via_redfish(interface_id):
                            raise RuntimeError("Не удалось переключиться на DHCP")

                        self.logger.info(f"Восстановление исходных настроек {interface_id}")
                        if not self.restore_settings():
                            raise RuntimeError(
                                "Не удалось восстановить исходные настройки"
                            )

                    self.logger.info(f"Тестирование интерфейса {interface_id} завершено успешно")

                except Exception as e:
                    self.logger.error(f"Ошибка при тестировании {interface_id}: {str(e)}")
                    if self.backup_settings:
                        self.safe_restore_settings()
                    raise

                self.add_test_result('Network Configuration Test via Redfish', True)
                self.logger.info("Тестирование сетевых настроек успешно завершено")

        except Exception as e:
            self.logger.error(f"Ошибка при тестировании: {str(e)}")
            self.add_test_result('Network Configuration Test via Redfish', False, str(e))
            if self.backup_settings:
                self.safe_restore_settings()
            raise

    def restore_settings(self) -> bool:
        """Восстанавливает исходные настройки."""
        try:
            if not self.original_settings:
                self.logger.info("Нет исходных настроек для восстановления")
                return True

            for interface_id, settings in self.original_settings.items():
                # Пропускаем USB интерфейс
                if 'usb' in interface_id.lower():
                    self.logger.info(f"Пропуск восстановления настроек USB интерфейса {interface_id}")
                    continue

                dhcp_enabled = settings.get('DHCPv4', {}).get('DHCPEnabled', False)
                self.logger.info(
                    f"Восстановление исходных настроек для интерфейса {interface_id}"
                )

                # Сначала отключаем DHCP если он был включен
                if dhcp_enabled:
                    # Ждем получения IP через DHCP
                    time.sleep(30)  # Даем время на получение IP

                    # Пытаемся найти новый IP через IPMI
                    try:
                        new_ip = self._get_current_ip_via_ipmi()
                        if new_ip:
                            self.ipmi_host = new_ip
                            self.redfish_manager.host = new_ip
                            self.redfish_manager.base_url = f"https://{new_ip}:{self.redfish_manager.port}"
                    except Exception as e:
                        self.logger.error(f"Не удалось получить новый IP через IPMI: {e}")
                        return False

                # Восстанавливаем статические настройки
                ipv4_addresses = settings.get('IPv4StaticAddresses', [])
                if not ipv4_addresses:
                    self.logger.error(
                        f"Исходные статические настройки неполные для интерфейса {interface_id}"
                    )
                    return False

                original_ip = ipv4_addresses[0].get('Address')
                original_mask = ipv4_addresses[0].get('SubnetMask')
                original_gateway = ipv4_addresses[0].get('Gateway')

                if not original_ip or not original_mask or not original_gateway:
                    self.logger.error(
                        f"Исходные статические настройки неполные для интерфейса {interface_id}"
                    )
                    return False

                # Восстанавливаем статические настройки
                if not self.setup_static_ip_via_redfish(
                    interface_id,
                    original_ip,
                    original_mask,
                    original_gateway
                ):
                    self.logger.error(
                        f"Не удалось восстановить статические настройки на интерфйсе {interface_id}"
                    )
                    return False

            return True

        except Exception as e:
            self.logger.error(f"Ошибка при восстановлении настроек: {e}")
            return False

    def safe_restore_settings(self) -> None:
        """Безопасно восстанавливает исходные настройки."""
        self.logger.info("Попытка безопасного восстановления исходных настроек")
        success = self.restore_settings()
        if success:
            self.logger.info("Исходные настройки успешно восстановлены")
        else:
            self.logger.error("Не удалось восстановить исходные настройки")

    def log_settings(self, settings: Dict[str, Any], message: str) -> None:
        """Логирует сетевые настройки в читаемом формате."""
        self.logger.info(f"{message}:")
        self.logger.info(f"  IP Source: {settings.get('IP Address Source')}")
        self.logger.info(f"  IP: {settings.get('IP Address')}")
        self.logger.info(f"  Mask: {settings.get('Subnet Mask')}")
        self.logger.info(f"  Gateway: {settings.get('Default Gateway IP')}")

    def verify_current_settings(self, expected_settings: Dict[str, str]) -> bool:
        """Проверяет текуие настройки через SSH."""
        try:
            current = verify_settings(self.ssh_tester, self.interface)
            if not current:
                return False

            for key in ['IP Address', 'Subnet Mask', 'Default Gateway IP']:
                if current.get(key) != expected_settings.get(key):
                    self.logger.error(
                        f"Несоответствие {key}: "
                        f"ожидалось {expected_settings.get(key)}, "
                        f"получено {current.get(key)}"
                    )
                    return False
            return True
        except Exception as e:
            self.logger.error(f"Ошибка проверки настроек: {e}")
            return False

    def _get_current_ip_via_ipmi(self) -> Optional[str]:
        """Получает текущий IP через IPMI."""
        try:
            command = [
                "ipmitool", "-I", "lanplus",
                "-H", self.ipmi_host,
                "-U", self.ipmi_username,
                "-P", self.ipmi_password,
                "lan", "print", self.interface
            ]
            result = self._run_command(command)
            for line in result.stdout.splitlines():
                if "IP Address" in line:
                    return line.split(":", 1)[1].strip()
            return None
        except Exception as e:
            self.logger.error(f"Ошибка получения IP через IPMI: {e}")
            return None
