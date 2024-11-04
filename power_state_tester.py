"""Модуль для тестирования управления питанием."""

import logging
import time
from typing import Dict, Any, Optional, List, cast
from base_tester import BaseTester
from network_utils import SSHManager, RedfishManager


class PowerStateTester(BaseTester):
    """Класс для тестирования управления питанием."""

    # Константы для состояний питания
    POWER_ON = "on"
    POWER_OFF = "off"
    POWER_RESET = "reset"
    POWER_CYCLE = "cycle"

    def __init__(
        self,
        config_file: str = 'config.ini',
        logger: Optional[logging.Logger] = None
    ) -> None:
        """
        Инициализирует Power State тестер.

        Args:
            config_file: Путь к файлу конфигурации
            logger: Логгер для вывода сообщений
        """
        super().__init__(config_file, logger)

        # Загрузка конфигурации Power State
        power_config = self.config_manager.get_network_config('PowerState')
        self.interface = cast(str, power_config.get('interface', '1'))

        # Таймауты и повторы
        self.power_timeout = int(power_config.get('power_timeout', '300'))
        self.verify_timeout = int(power_config.get('verify_timeout', '60'))
        self.retry_count = int(power_config.get('retry_count', '3'))
        self.retry_delay = int(power_config.get('retry_delay', '10'))

        # Дополнительные параметры
        self.verify_access = power_config.get(
            'verify_access',
            'true'
        ).lower() == 'true'
        self.check_all_interfaces = power_config.get(
            'check_all_interfaces',
            'true'
        ).lower() == 'true'
        self.force_power = power_config.get(
            'force_power',
            'false'
        ).lower() == 'true'

        # Инициализация других тестеров
        self.ssh_tester = SSHManager(config_file, logger)
        self.redfish_tester = RedfishManager(config_file, logger)

        # Сохранение исходных настроек
        self.original_state: Optional[str] = None

        self.logger.debug("Инициализация Power State тестера завершена")

    def get_power_state(self) -> Dict[str, str]:
        """
        Получает текущее состояние питания через все интерфейсы.

        Returns:
            Dict[str, str]: Состояние питания через разные интерфейсы
        """
        states = {
            'ipmi': self._get_ipmi_power_state(),
            'redfish': self._get_redfish_power_state(),
            'ssh': self._get_ssh_power_state()
        }
        return states

    def _get_ipmi_power_state(self) -> str:
        """
        Получает состояние питания через IPMI.

        Returns:
            str: Состояние питания
        """
        try:
            command = [
                "ipmitool", "-I", "lanplus",
                "-H", cast(str, self.ipmi_host),
                "-U", self.ipmi_username,
                "-P", self.ipmi_password,
                "power", "status"
            ]
            result = self._run_command(command)
            return result.stdout.strip().lower()

        except Exception as e:
            self.logger.error(
                f"Ошибка при получении состояния питания через IPMI: {e}"
            )
            return ""

    def _get_redfish_power_state(self) -> str:
        """
        Получает состояние питания через Redfish API.

        Returns:
            str: Состояние питания
        """
        try:
            endpoint = "/redfish/v1/Systems/Self"
            response = self.redfish_tester.run_request("GET", endpoint)
            if not response:
                raise RuntimeError("Не удалось получить состояние питания")

            data = response.json()
            return data.get('PowerState', '').lower()

        except Exception as e:
            self.logger.error(
                f"Ошибка при получении состояния питания через Redfish: {e}"
            )
            return ""

    def _get_ssh_power_state(self) -> str:
        """
        Получает состояние питания через SSH.

        Returns:
            str: Состояние питания
        """
        try:
            if not self.ssh_tester.connect():
                raise RuntimeError("Не удалось установить SSH соединение")

            command = "cat /sys/class/power_supply/*/online"
            result = self.ssh_tester.execute_command(command)
            if not result['success']:
                raise RuntimeError("Не удалось получить состояние питания")

            return "on" if "1" in result['output'] else "off"

        except Exception as e:
            self.logger.error(
                f"Ошибка при получении состояния питания через SSH: {e}"
            )
            return ""
        finally:
            self.ssh_tester.disconnect()

    def set_power_state(self, state: str) -> bool:
        """
        Устанавливает состояние питания.

        Args:
            state: Требуемое состояние питания

        Returns:
            bool: True если изменение успешно
        """
        try:
            if state not in [
                self.POWER_ON,
                self.POWER_OFF,
                self.POWER_RESET,
                self.POWER_CYCLE
            ]:
                raise ValueError(f"Некорректное состояние питания: {state}")

            command = [
                "ipmitool", "-I", "lanplus",
                "-H", cast(str, self.ipmi_host),
                "-U", self.ipmi_username,
                "-P", self.ipmi_password,
                "power", state
            ]
            if self.force_power:
                command.append("-f")

            self._run_command(command)
            time.sleep(5)

            # Ждем изменения состояния
            if not self.wait_for_power_state(state):
                raise RuntimeError(
                    f"Не удалось дождаться состояния питания: {state}"
                )

            return True

        except Exception as e:
            self.logger.error(f"Ошибка при установке состояния питания: {e}")
            return False

    def wait_for_power_state(self, expected_state: str) -> bool:
        """
        Ожидает установки определенного состояния питания.

        Args:
            expected_state: Ожидаемое состояние

        Returns:
            bool: True если состояние установлено
        """
        try:
            start_time = time.time()
            while time.time() - start_time < self.power_timeout:
                current_state = self._get_ipmi_power_state()
                if current_state == expected_state:
                    return True
                time.sleep(self.retry_delay)

            self.logger.error(
                f"Таймаут ожидания состояния питания: {expected_state}"
            )
            return False

        except Exception as e:
            self.logger.error(f"Ошибка при ожидании состояния питания: {e}")
            return False

    def verify_power_states(self) -> bool:
        """
        Проверяет соответствие состояний питания через все интерфейсы.

        Returns:
            bool: True если состояния совпадают
        """
        try:
            states = self.get_power_state()
            if not all(states.values()):
                raise RuntimeError(
                    "Не удалось получить состояние через все интерфейсы"
                )

            # Проверяем соответствие состояний
            if len(set(states.values())) > 1:
                self.logger.error(
                    f"Несоответствие состояний питания: {states}"
                )
                return False

            return True

        except Exception as e:
            self.logger.error(f"Ошибка при проверке состояний питания: {e}")
            return False

    def test_power_cycle(self) -> bool:
        """
        Тестирует цикл питания.

        Returns:
            bool: True если тест успешен
        """
        try:
            # Включаем питание
            if not self.set_power_state(self.POWER_ON):
                raise RuntimeError("Не удалось включить питание")

            # Проверяем состояние
            if not self.verify_power_states():
                raise RuntimeError("Несоответствие состояний после включения")

            # Выключаем питание
            if not self.set_power_state(self.POWER_OFF):
                raise RuntimeError("Не удалось выключить питание")

            # Проверяем состояние
            if not self.verify_power_states():
                raise RuntimeError("Несоответствие состояний после выключения")

            # Снова включаем питание
            if not self.set_power_state(self.POWER_ON):
                raise RuntimeError("Не удалось повторно включить питание")

            # Проверяем состояние
            if not self.verify_power_states():
                raise RuntimeError(
                    "Несоответствие состояний после повторного включения"
                )

            return True

        except Exception as e:
            self.logger.error(f"Ошибка при тестировании цикла питания: {e}")
            return False

    def test_power_reset(self) -> bool:
        """
        Тестирует сброс питания.

        Returns:
            bool: True если тест успешен
        """
        try:
            # Включаем питание
            if not self.set_power_state(self.POWER_ON):
                raise RuntimeError("Не удалось включить питание")

            # Проверяем состояние
            if not self.verify_power_states():
                raise RuntimeError("Несоответствие состояний после включения")

            # Выполняем сброс
            if not self.set_power_state(self.POWER_RESET):
                raise RuntimeError("Не удалось выполнить сброс питания")

            # Проверяем состояние
            if not self.verify_power_states():
                raise RuntimeError("Несоответствие состояний после сброса")

            return True

        except Exception as e:
            self.logger.error(f"Ошибка при тестировании сброса питания: {e}")
            return False

    def perform_tests(self) -> None:
        """Выполняет тестирование управления питанием."""
        try:
            self.logger.info("Начало тестирования управления питанием")

            # Сохраняем текущее состояние
            self.original_state = self._get_ipmi_power_state()

            # Тестируем цикл питания
            if not self.test_power_cycle():
                raise RuntimeError("Тест цикла питания не прошел")

            # Тестируем сброс питания
            if not self.test_power_reset():
                raise RuntimeError("Тест сброса питания не прошел")

            self.add_test_result('Power Cycle Test', True)
            self.add_test_result('Power Reset Test', True)

        except Exception as e:
            self.logger.error(f"Ошибка при выполнении тестов: {e}")
            self.add_test_result('Power State Tests', False, str(e))
        finally:
            self.safe_restore_settings()

    def restore_settings(self) -> bool:
        """
        Восстанавливает исходное состояние питания.

        Returns:
            bool: True если восстановление успешно
        """
        try:
            if not self.original_state:
                self.logger.info(
                    "Нет сохраненного состояния для восстановления"
                )
                return True

            return self.set_power_state(self.original_state)

        except Exception as e:
            self.logger.error(f"Ошибка при восстановлении состояния: {e}")
            return False
