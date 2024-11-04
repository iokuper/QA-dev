"""Модуль для диагностического тестирования."""

import logging
from typing import Optional, List, cast
from base_tester import BaseTester
from network_utils import SSHManager, RedfishManager, wait_for_port


class DiagnosticTester(BaseTester):
    """Класс для диагностического тестирования."""

    def __init__(
        self,
        config_file: str = 'config.ini',
        logger: Optional[logging.Logger] = None
    ) -> None:
        """
        Инициализирует Diagnostic тестер.

        Args:
            config_file: Путь к файлу конфигурации
            logger: Логгер для вывода сообщений
        """
        super().__init__(config_file, logger)

        # Загрузка конфигурации Diagnostic
        diag_config = self.config_manager.get_network_config('Diagnostic')
        self.interface = cast(str, diag_config.get('interface', '1'))

        # Параметры тестирования
        self.test_ports = [
            int(x) for x in diag_config.get(
                'test_ports',
                '22,623,443'
            ).split(',')
        ]
        self.redfish_endpoints = cast(
            List[str],
            diag_config.get('redfish_endpoints', '').split(',')
        )
        self.ssh_commands = cast(
            List[str],
            diag_config.get('ssh_commands', '').split(',')
        )

        # Инициализация других тестеров
        self.ssh_tester = SSHManager(config_file, logger)
        self.redfish_tester = RedfishManager(config_file, logger)

        # Добавляем параметр collect_logs
        self.collect_logs = diag_config.get('collect_logs', 'true').lower() == 'true'

        self.logger.debug("Инициализация Diagnostic тестера завершена")

    def test_network_connectivity(self) -> bool:
        """
        Тестирует сетевую доступность.

        Returns:
            bool: True если тест успешен
        """
        try:
            self.logger.info("Тестирование сетевой доступности")

            # Проверяем доступность портов
            for port in self.test_ports:
                if not wait_for_port(
                    cast(str, self.ipmi_host),
                    port,
                    timeout=self.verify_timeout
                ):
                    self.logger.error(
                        f"Порт {port} недоступен на {self.ipmi_host}"
                    )
                    return False
                self.logger.info(f"Порт {port} доступен")

            return True

        except Exception as e:
            self.logger.error(f"Ошибка при тестировании доступности: {e}")
            return False

    def test_redfish_api(self) -> bool:
        """
        Тестирует Redfish API.

        Returns:
            bool: True если тест успешен
        """
        try:
            self.logger.info("Тестирование Redfish API")

            # Проверяем каждый эндпоинт
            for endpoint in self.redfish_endpoints:
                try:
                    response = self.redfish_tester.run_request("GET", endpoint)
                    if not response or response.status_code != 200:
                        self.logger.error(
                            f"Эндпоинт {endpoint} недоступен: "
                            f"{response.status_code if response else 'No response'}"
                        )
                        return False
                    self.logger.info(f"Эндпоинт {endpoint} доступен")
                except Exception as e:
                    self.logger.error(
                        f"Ошибка при проверке эндпоинта {endpoint}: {e}"
                    )
                    return False

            return True

        except Exception as e:
            self.logger.error(f"Ошибка при тестировании Redfish API: {e}")
            return False

    def test_ssh_connectivity(self) -> bool:
        """
        Тестирует SSH подключение.

        Returns:
            bool: True если тест успешен
        """
        try:
            self.logger.info("Тестирование SSH подключения")

            # Проверяем подключение
            if not self.ssh_tester.connect():
                self.logger.error("Не удалось установить SSH соединение")
                return False

            # Выполняем тестовые команды
            for command in self.ssh_commands:
                try:
                    result = self.ssh_tester.execute_command(command)
                    if not result['success']:
                        self.logger.error(
                            f"Команда {command} завершилась с ошибкой: "
                            f"{result.get('error', 'Unknown error')}"
                        )
                        return False
                    self.logger.info(f"Команда {command} выполнена успешно")
                except Exception as e:
                    self.logger.error(
                        f"Ошибка при выполнении команды {command}: {e}"
                    )
                    return False

            return True

        except Exception as e:
            self.logger.error(f"Ошибка при тестировании SSH: {e}")
            return False
        finally:
            self.ssh_tester.disconnect()

    def collect_diagnostic_logs(self) -> bool:
        """
        Собирает диагностические логи.

        Returns:
            bool: True если сбор успешен
        """
        try:
            self.logger.info("Сбор диагностических логов")

            if not self.ssh_tester.connect():
                raise RuntimeError("Не удалось установить SSH соединение")

            # Собираем системные логи
            commands = [
                "dmesg",
                "journalctl -n 1000",
                "cat /var/log/syslog",
                "ip addr show",
                "ip route show",
                "netstat -tuln"
            ]

            for command in commands:
                try:
                    result = self.ssh_tester.execute_command(command)
                    if result['success']:
                        self.logger.info(
                            f"=== Вывод команды {command} ===\n"
                            f"{result['output']}\n"
                            "=== Конец вывода ==="
                        )
                    else:
                        self.logger.warning(
                            f"Не удалось выполнить команду {command}: "
                            f"{result.get('error', 'Unknown error')}"
                        )
                except Exception as e:
                    self.logger.warning(
                        f"Ошибка при выполнении команды {command}: {e}"
                    )

            return True

        except Exception as e:
            self.logger.error(f"Ошибка при сборе диагн��стических логов: {e}")
            return False
        finally:
            self.ssh_tester.disconnect()

    def perform_tests(self) -> None:
        """Выполняет диагностическое тестирование."""
        try:
            self.logger.info("Начало диагностического тестирования")

            # Тестируем сетевую доступность
            if not self.test_network_connectivity():
                self.add_test_result('Network Connectivity Test', False,
                                   "Тест сетевой доступности не прошел")
            else:
                self.add_test_result('Network Connectivity Test', True)

            # Тестируем Redfish API
            if not self.test_redfish_api():
                self.add_test_result('Redfish API Test', False,
                                   "Тест Redfish API не прошел")
            else:
                self.add_test_result('Redfish API Test', True)

            # Тестируем SSH подключение
            if not self.test_ssh_connectivity():
                self.add_test_result('SSH Connectivity Test', False,
                                   "Тест SSH подключения не прошел")
            else:
                self.add_test_result('SSH Connectivity Test', True)

            # Собираем диагностические логи если требуется
            if self.collect_logs:
                if not self.collect_diagnostic_logs():
                    self.add_test_result('Diagnostic Logs Collection', False,
                                       "Не удалось собрать диагностические логи")
                else:
                    self.add_test_result('Diagnostic Logs Collection', True)

        except Exception as e:
            self.logger.error(f"Ошибка при выполнении тестов: {e}")
            self.add_test_result('Diagnostic Tests', False, str(e))

    def restore_settings(self) -> bool:
        """
        Восстанавливает исходные настройки.

        Returns:
            bool: True если восстановление успешно
        """
        # В данном случае нам не нужно восстанавливать настройки,
        # так как мы только проводим диагностику
        return True
