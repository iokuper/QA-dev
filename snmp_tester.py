"""Модуль для тестирования настройки SNMP."""

import logging
import time
from typing import Dict, Any, Optional, List, cast
from base_tester import BaseTester
from network_utils import SSHManager, RedfishManager


class SNMPTester(BaseTester):
    """Класс для тестирования настройки SNMP."""

    def __init__(
        self,
        config_file: str = 'config.ini',
        logger: Optional[logging.Logger] = None
    ) -> None:
        """
        Инициализирует SNMP тестер.

        Args:
            config_file: Путь к файлу конфигурации
            logger: Логгер для вывода сообщений
        """
        super().__init__(config_file, logger)

        # Загрузка конфигурации SNMP
        snmp_config = self.config_manager.get_network_config('SNMP')
        self.interface = cast(str, snmp_config.get('interface', '1'))

        # Параметры SNMP
        self.community = cast(str, snmp_config.get('community', 'public'))
        self.version = cast(str, snmp_config.get('version', '2c'))
        self.port = int(snmp_config.get('port', '161'))
        self.trap_port = int(snmp_config.get('trap_port', '162'))
        self.auth_protocol = cast(
            str,
            snmp_config.get('auth_protocol', 'SHA')
        )
        self.priv_protocol = cast(
            str,
            snmp_config.get('priv_protocol', 'AES')
        )

        # Таймауты и повторы
        self.setup_timeout = int(snmp_config.get('setup_timeout', '30'))
        self.verify_timeout = int(snmp_config.get('verify_timeout', '60'))
        self.retry_count = int(snmp_config.get('retry_count', '3'))
        self.retry_delay = int(snmp_config.get('retry_delay', '10'))

        # Дополнительные параметры
        self.verify_access = snmp_config.get(
            'verify_access',
            'true'
        ).lower() == 'true'
        self.backup_settings = snmp_config.get(
            'backup_settings',
            'true'
        ).lower() == 'true'
        self.test_traps = snmp_config.get(
            'test_traps',
            'true'
        ).lower() == 'true'

        # Инициализация других тестеров
        self.ssh_tester = SSHManager(config_file, logger)
        self.redfish_tester = RedfishManager(config_file, logger)

        # Сохранение исходных настроек
        self.original_settings: Dict[str, Any] = {}

        self.logger.debug("Инициализация SNMP тестера завершена")

    def get_current_settings(self) -> Dict[str, Any]:
        """
        Получает текущие настройки SNMP через все интерфейсы.

        Returns:
            Dict[str, Any]: Текущие настройки
        """
        settings = {
            'ipmi': self._get_ipmi_snmp_settings(),
            'redfish': self._get_redfish_snmp_settings(),
            'ssh': self._get_ssh_snmp_settings()
        }
        return settings

    def _get_ipmi_snmp_settings(self) -> Dict[str, Any]:
        """
        Получает настройки SNMP через IPMI.

        Returns:
            Dict[str, Any]: Настройки SNMP
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
                if 'SNMP Community String' in line:
                    settings['community'] = line.split(':')[1].strip()
                elif 'SNMP Port' in line:
                    settings['port'] = int(line.split(':')[1].strip())

            return settings

        except Exception as e:
            self.logger.error(f"Ошибка при получении SNMP через IPMI: {e}")
            return {}

    def _get_redfish_snmp_settings(self) -> Dict[str, Any]:
        """
        Получает настройки SNMP через Redfish API.

        Returns:
            Dict[str, Any]: Настройки SNMP
        """
        try:
            endpoint = "/redfish/v1/Managers/Self/NetworkProtocol"
            response = self.redfish_tester.run_request("GET", endpoint)
            if not response:
                raise RuntimeError("Не удалось получить настройки")

            data = response.json()
            snmp_data = data.get('SNMP', {})

            settings = {
                'enabled': snmp_data.get('ProtocolEnabled', False),
                'port': snmp_data.get('Port', 161),
                'auth_protocol': snmp_data.get('AuthenticationProtocol', ''),
                'priv_protocol': snmp_data.get('PrivacyProtocol', '')
            }

            return settings

        except Exception as e:
            self.logger.error(f"Ошибка при получении SNMP через Redfish: {e}")
            return {}

    def _get_ssh_snmp_settings(self) -> Dict[str, Any]:
        """
        Получает настройки SNMP через SSH.

        Returns:
            Dict[str, Any]: Настройки SNMP
        """
        try:
            if not self.ssh_tester.connect():
                raise RuntimeError("Не удалось установить SSH соединение")

            command = "cat /etc/snmp/snmpd.conf"
            result = self.ssh_tester.execute_command(command)
            if not result['success']:
                raise RuntimeError("Не удалось получить настройки SNMP")

            settings = {
                'version': '',
                'community': '',
                'port': 161
            }

            for line in result['output'].splitlines():
                if line.startswith('com2sec'):
                    settings['community'] = line.split()[-1]
                elif line.startswith('agentaddress'):
                    settings['port'] = int(line.split(':')[-1])
                elif 'v3' in line:
                    settings['version'] = '3'
                elif 'v2c' in line:
                    settings['version'] = '2c'

            return settings

        except Exception as e:
            self.logger.error(f"Ошибка при получении SNMP через SSH: {e}")
            return {}
        finally:
            self.ssh_tester.disconnect()

    def setup_snmp_via_ipmi(self) -> bool:
        """
        Настраивает SNMP через IPMI.

        Returns:
            bool: True если настройка успешна
        """
        try:
            # Устанавливаем community string
            command = [
                "ipmitool", "-I", "lanplus",
                "-H", cast(str, self.ipmi_host),
                "-U", self.ipmi_username,
                "-P", self.ipmi_password,
                "lan", "set", self.interface,
                "snmp", self.community
            ]
            self._run_command(command)
            time.sleep(2)

            # Устанавливаем порт
            command = [
                "ipmitool", "-I", "lanplus",
                "-H", cast(str, self.ipmi_host),
                "-U", self.ipmi_username,
                "-P", self.ipmi_password,
                "lan", "set", self.interface,
                "snmp_port", str(self.port)
            ]
            self._run_command(command)
            time.sleep(5)

            # Проверяем настройки
            settings = self._get_ipmi_snmp_settings()
            if not settings:
                raise RuntimeError("Не удалось получить настройки")

            if (
                settings.get('community') != self.community or
                settings.get('port') != self.port
            ):
                raise RuntimeError("Настройки SNMP не применились")

            return True

        except Exception as e:
            self.logger.error(f"Ошибка при настройке SNMP через IPMI: {e}")
            return False

    def setup_snmp_via_redfish(self) -> bool:
        """
        Настраивает SNMP через Redfish API.

        Returns:
            bool: True если настройка успешна
        """
        try:
            endpoint = "/redfish/v1/Managers/Self/NetworkProtocol"
            data = {
                "SNMP": {
                    "ProtocolEnabled": True,
                    "Port": self.port,
                    "AuthenticationProtocol": self.auth_protocol,
                    "PrivacyProtocol": self.priv_protocol
                }
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
            settings = self._get_redfish_snmp_settings()
            if not settings:
                raise RuntimeError("Не удалось получить настройки")

            if (
                not settings.get('enabled') or
                settings.get('port') != self.port or
                settings.get('auth_protocol') != self.auth_protocol or
                settings.get('priv_protocol') != self.priv_protocol
            ):
                raise RuntimeError("Настройки SNMP не применились")

            return True

        except Exception as e:
            self.logger.error(f"Ошибка при настройке SNMP через Redfish: {e}")
            return False

    def setup_snmp_via_ssh(self) -> bool:
        """
        Настраивает SNMP через SSH.

        Returns:
            bool: True если настройка успешна
        """
        try:
            if not self.ssh_tester.connect():
                raise RuntimeError("Не удалось установить SSH соединение")

            # Создаем конфигурацию SNMP
            snmp_config = (
                f"agentaddress udp:{self.port}\n"
                f"com2sec readonly default {self.community}\n"
                "group MyROGroup v2c readonly\n"
                "view all included .1 80\n"
                "access MyROGroup \"\" any noauth exact all none none\n"
            )

            # Записываем конфигурацию
            command = f"echo '{snmp_config}' | sudo tee /etc/snmp/snmpd.conf"
            result = self.ssh_tester.execute_command(command)
            if not result['success']:
                raise RuntimeError("Не удалось записать конфигурацию SNMP")

            # Перезапускаем службу SNMP
            command = "sudo systemctl restart snmpd"
            result = self.ssh_tester.execute_command(command)
            if not result['success']:
                raise RuntimeError("Не удалось перезапустить службу SNMP")

            time.sleep(5)

            # Проверяем настройки
            settings = self._get_ssh_snmp_settings()
            if not settings:
                raise RuntimeError("Не удалось получить настройки")

            if (
                settings.get('community') != self.community or
                settings.get('port') != self.port or
                settings.get('version') != self.version
            ):
                raise RuntimeError("Настройки SNMP не применились")

            return True

        except Exception as e:
            self.logger.error(f"Ошибка при настройке SNMP через SSH: {e}")
            return False
        finally:
            self.ssh_tester.disconnect()

    def verify_snmp_settings(self) -> bool:
        """
        Проверяет настройки SNMP через все интерфейсы.

        Returns:
            bool: True если проверка успешна
        """
        try:
            settings = self.get_current_settings()
            if not all(settings.values()):
                raise RuntimeError(
                    "Не удалось получить настройки через все интерфейсы"
                )

            # Проверяем порты
            ports = {
                source: data.get('port')
                for source, data in settings.items()
            }
            if len(set(ports.values())) > 1:
                self.logger.error(
                    f"Несоответствие портов SNMP: {ports}"
                )
                return False

            # Проверяем community string (только для IPMI и SSH)
            communities = {
                source: data.get('community')
                for source, data in settings.items()
                if source in ['ipmi', 'ssh']
            }
            if len(set(communities.values())) > 1:
                self.logger.error(
                    f"Несоответствие community string: {communities}"
                )
                return False

            return True

        except Exception as e:
            self.logger.error(f"Ошибка при проверке настроек SNMP: {e}")
            return False

    def test_snmp_traps(self) -> bool:
        """
        Тестирует отправку и получение SNMP трапов.

        Returns:
            bool: True если тест успешен
        """
        try:
            if not self.ssh_tester.connect():
                raise RuntimeError("Не удалось установить SSH соединение")

            # Запускаем snmptrapd
            command = f"sudo snmptrapd -f -Lo -c /etc/snmp/snmptrapd.conf {self.trap_port}"
            result = self.ssh_tester.execute_command(command)
            if not result['success']:
                raise RuntimeError("Не удалось запустить snmptrapd")

            time.sleep(2)

            # Отправляем тестовый трап
            command = (
                f"snmptrap -v {self.version} -c {self.community} "
                f"localhost:{self.trap_port} '' "
                f"SNMPv2-MIB::coldStart.0"
            )
            result = self.ssh_tester.execute_command(command)
            if not result['success']:
                raise RuntimeError("Не удалось отправить тестовый трап")

            # Проверяем получение трапа
            command = "grep -i trap /var/log/snmptrapd.log"
            result = self.ssh_tester.execute_command(command)
            if not result['success'] or 'coldStart' not in result['output']:
                raise RuntimeError("Тестовый трап не получен")

            return True

        except Exception as e:
            self.logger.error(f"Ошибка при тестировании SNMP трапов: {e}")
            return False
        finally:
            # Останавливаем snmptrapd
            command = "sudo pkill snmptrapd"
            self.ssh_tester.execute_command(command)
            self.ssh_tester.disconnect()

    def perform_tests(self) -> None:
        """Выполняет тестирование настройки SNMP."""
        try:
            self.logger.info("Начало тестирования настройки SNMP")

            # Сохраняем текущие настройки
            if self.backup_settings:
                self.original_settings = self.get_current_settings()

            # Настройка через IPMI
            if not self.setup_snmp_via_ipmi():
                raise RuntimeError("Не удалось настроить SNMP через IPMI")

            # Проверка настроек
            if not self.verify_snmp_settings():
                raise RuntimeError("Верификация настроек SNMP не прошла")

            # Настройка через Redfish
            if not self.setup_snmp_via_redfish():
                raise RuntimeError("Не удалось настроить SNMP через Redfish")

            # Проверка настроек
            if not self.verify_snmp_settings():
                raise RuntimeError("Верификация настроек SNMP не прошла")

            # Настройка через SSH
            if not self.setup_snmp_via_ssh():
                raise RuntimeError("Не удалось настроить SNMP через SSH")

            # Проверка настроек
            if not self.verify_snmp_settings():
                raise RuntimeError("Верификация настроек SNMP не прошла")

            # Тестирование трапов если требуется
            if self.test_traps and not self.test_snmp_traps():
                raise RuntimeError("Тест SNMP трапов не прошел")

            self.add_test_result('SNMP Configuration Test', True)
            self.add_test_result('SNMP Trap Test', True)

        except Exception as e:
            self.logger.error(f"Ошибка при выполнении тестов: {e}")
            self.add_test_result('SNMP Tests', False, str(e))
        finally:
            self.safe_restore_settings()

    def restore_settings(self) -> bool:
        """
        Восстанавливает исходные настройки SNMP.

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
                self.community = ipmi_settings.get('community', 'public')
                self.port = ipmi_settings.get('port', 161)
                return self.setup_snmp_via_ipmi()

            return True

        except Exception as e:
            self.logger.error(f"Ошибка при восстановлении настроек: {e}")
            return False
