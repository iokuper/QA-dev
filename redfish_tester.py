"""Модуль для тестирования через Redfish API."""

import logging
import time
from typing import Dict, Any, Optional, cast
from base_tester import BaseTester
from verification_utils import verify_ip_format
import requests
from requests.exceptions import RequestException


class RedfishTester(BaseTester):
    """Класс для тестирования через Redfish API."""

    def __init__(
        self,
        config_file: str = 'config.ini',
        logger: Optional[logging.Logger] = None
    ) -> None:
        """
        Инициализирует Redfish тестер.

        Args:
            config_file: Путь к файлу конфигурации
            logger: Логгер для вывода сообщений
        """
        super().__init__(config_file, logger)

        # Загрузка конфигурации Redfish
        redfish_config = self.config_manager.get_network_config('Redfish')
        self.interface = cast(str, redfish_config.get('interface', '1'))

        # Параметры подключения
        self.verify_ssl = redfish_config.get(
            'verify_ssl',
            'false'
        ).lower() == 'true'
        self.base_url = f"https://{self.ipmi_host}"
        self.session = requests.Session()
        self.session.verify = self.verify_ssl
        self.session.auth = (self.ipmi_username, self.ipmi_password)

        # Таймауты и повторы
        self.setup_timeout = int(redfish_config.get('setup_timeout', '30'))
        self.verify_timeout = int(redfish_config.get('verify_timeout', '60'))
        self.retry_count = int(redfish_config.get('retry_count', '3'))
        self.retry_delay = int(redfish_config.get('retry_delay', '10'))

        # Дополнительные параметры
        self.verify_access = redfish_config.get(
            'verify_access',
            'true'
        ).lower() == 'true'
        self.backup_settings = redfish_config.get(
            'backup_settings',
            'true'
        ).lower() == 'true'
        self.check_schema = redfish_config.get(
            'check_schema',
            'true'
        ).lower() == 'true'

        # Сохранение исходных настроек
        self.original_settings: Dict[str, Any] = {}

        self.logger.debug("Инициализация Redfish тестера завершена")

    def get_current_settings(self) -> Dict[str, Any]:
        """
        Получает текущие сетевые настройки через Redfish API.

        Returns:
            Dict[str, Any]: Текущие настройки
        """
        try:
            endpoint = (
                f"/redfish/v1/Managers/Self/EthernetInterfaces/{self.interface}"
            )
            response = self.run_request("GET", endpoint)
            if not response:
                raise RuntimeError("Не удалось получить текущие настройки")

            data = response.json()
            ipv4_data = data.get('IPv4Addresses', [{}])[0]

            settings = {
                'IP Address': ipv4_data.get('Address', ''),
                'Subnet Mask': ipv4_data.get('SubnetMask', ''),
                'Default Gateway IP': ipv4_data.get('Gateway', ''),
                'IP Address Source': (
                    'DHCP' if data.get('DHCPv4', {}).get('DHCPEnabled', False)
                    else 'Static'
                )
            }

            return settings

        except Exception as e:
            self.logger.error(f"Ошибка при получении текущих настроек: {e}")
            return {}

    def run_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None
    ) -> Optional[requests.Response]:
        """
        Выполняет HTTP запрос к Redfish API.

        Args:
            method: HTTP метод
            endpoint: Endpoint API
            data: Данные для отправки
            headers: Заголовки запроса

        Returns:
            Optional[requests.Response]: Ответ сервера или None при ошибке
        """
        try:
            url = f"{self.base_url}{endpoint}"
            response = self.session.request(
                method=method,
                url=url,
                json=data,
                headers=headers,
                timeout=self.timeout
            )
            response.raise_for_status()
            return response
        except Exception as e:
            self.logger.error(f"Ошибка при выполнении запроса: {e}")
            return None

    def setup_static_ip(
        self,
        ip: str,
        mask: str,
        gateway: str
    ) -> bool:
        """
        Настраивает статический IP через Redfish API.

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

            endpoint = (
                f"/redfish/v1/Managers/Self/EthernetInterfaces/{self.interface}"
            )
            data = {
                "DHCPv4": {
                    "DHCPEnabled": False
                },
                "IPv4Addresses": [{
                    "Address": ip,
                    "SubnetMask": mask,
                    "Gateway": gateway
                }]
            }

            # Получаем текущий ETag
            response = self.run_request("GET", endpoint)
            if not response:
                raise RuntimeError("Не удалось получить ETag")

            etag = response.headers.get('ETag')
            headers = {'If-Match': etag} if etag else None

            # Отправляем запрос на обновление
            response = self.run_request(
                "PATCH",
                endpoint,
                data=data,
                headers=headers
            )
            if not response:
                raise RuntimeError("Не удалось применить настройки")

            time.sleep(5)

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

            # Проверяем доступность если требуется
            if self.verify_access and not self.verify_network_access(ip):
                raise RuntimeError("Настройки применились, но сеть недоступна")

            return True

        except Exception as e:
            self.logger.error(f"Ошибка при настройке статического IP: {e}")
            return False

    def setup_dhcp(self) -> bool:
        """
        Настраивает получение IP через DHCP.

        Returns:
            bool: True если настройка успешна
        """
        try:
            endpoint = (
                f"/redfish/v1/Managers/Self/EthernetInterfaces/{self.interface}"
            )
            data = {
                "DHCPv4": {
                    "DHCPEnabled": True
                }
            }

            # Получаем текущий ETag
            response = self.run_request("GET", endpoint)
            if not response:
                raise RuntimeError("Не удалось получить ETag")

            etag = response.headers.get('ETag')
            headers = {'If-Match': etag} if etag else None

            # Отправляем запрос на обновление
            response = self.run_request(
                "PATCH",
                endpoint,
                data=data,
                headers=headers
            )
            if not response:
                raise RuntimeError("Не удалось применить настройки")

            time.sleep(10)  # Ждем получения адреса

            # Проверяем настройки
            settings = self.get_current_settings()
            if not settings:
                raise RuntimeError("Не удалось получить настройки")

            if settings.get('IP Address Source') != 'DHCP':
                raise RuntimeError("DHCP не включился")

            # Проверяем доступность если требуется
            if self.verify_access:
                ip = settings.get('IP Address')
                if not ip or not self.verify_network_access(ip):
                    raise RuntimeError("DHCP включен, но сеть недоступна")

            return True

        except Exception as e:
            self.logger.error(f"Ошибка при настройке DHCP: {e}")
            return False

    def test_invalid_settings(self) -> bool:
        """
        Тестирует установку некорректных настроек.

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

            endpoint = (
                f"/redfish/v1/Managers/Self/EthernetInterfaces/{self.interface}"
            )

            for invalid_ip in invalid_ips:
                data = {
                    "IPv4Addresses": [{
                        "Address": invalid_ip
                    }]
                }

                try:
                    response = self.run_request("PATCH", endpoint, data=data)
                    if response:
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
        """Выполняет тестирование через Redfish API."""
        try:
            self.logger.info("Начало тестирования через Redfish API")

            # Сохраняем текущие настройки
            if self.backup_settings:
                self.original_settings = self.get_current_settings()

            # Получаем тестовые настройки
            test_settings = self.config_manager.get_test_params('Redfish')

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

            self.add_test_result('Redfish Configuration Test', True)
            self.add_test_result('Redfish Accessibility Test', True)

        except Exception as e:
            self.logger.error(f"Ошибка при выполнении тестов: {e}")
            self.add_test_result('Redfish Tests', False, str(e))
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

            # Восстанавливаем настройки через Redfish
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
