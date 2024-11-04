"""Модуль для тестирования под нагрузкой."""

import logging
import time
import subprocess
from typing import Dict, Any, Optional, List, cast
from base_tester import BaseTester
from network_utils import SSHManager, RedfishManager


class LoadTester(BaseTester):
    """Класс для тестирования под нагрузкой."""

    def __init__(
        self,
        config_file: str = 'config.ini',
        logger: Optional[logging.Logger] = None
    ) -> None:
        """
        Инициализирует Load тестер.

        Args:
            config_file: Путь к файлу конфигурации
            logger: Логгер для вывода сообщений
        """
        super().__init__(config_file, logger)

        # Загрузка конфигурации Load
        load_config = self.config_manager.get_network_config('Load')
        self.interface = cast(str, load_config.get('interface', '1'))

        # Параметры нагрузки
        self.test_duration = int(load_config.get('test_duration', '300'))
        self.bandwidth = cast(str, load_config.get('bandwidth', '100M'))
        self.parallel_streams = int(load_config.get('parallel_streams', '4'))
        self.packet_size = int(load_config.get('packet_size', '1400'))

        # Таймауты и повторы
        self.setup_timeout = int(load_config.get('setup_timeout', '30'))
        self.verify_timeout = int(load_config.get('verify_timeout', '60'))
        self.retry_count = int(load_config.get('retry_count', '3'))
        self.retry_delay = int(load_config.get('retry_delay', '10'))

        # Пороговые значения
        self.min_bandwidth = float(load_config.get('min_bandwidth', '50.0'))
        self.max_latency = float(load_config.get('max_latency', '100.0'))
        self.max_packet_loss = float(load_config.get('max_packet_loss', '1.0'))

        # Дополнительные параметры
        self.verify_access = load_config.get(
            'verify_access',
            'true'
        ).lower() == 'true'
        self.monitor_resources = load_config.get(
            'monitor_resources',
            'true'
        ).lower() == 'true'
        self.collect_metrics = load_config.get(
            'collect_metrics',
            'true'
        ).lower() == 'true'

        # Инициализация других тестеров
        self.ssh_tester = SSHManager(config_file, logger)
        self.redfish_tester = RedfishManager(config_file, logger)

        # Сохранение исходных настроек
        self.original_settings: Dict[str, Any] = {}

        self.logger.debug("Инициализация Load тестера завершена")

    def start_iperf_server(self) -> bool:
        """
        Запускает iperf сервер.

        Returns:
            bool: True если сервер запущен успешно
        """
        try:
            if not self.ssh_tester.connect():
                raise RuntimeError("Не удалось установить SSH соединение")

            # Проверяем наличие iperf3
            check_cmd = "which iperf3"
            result = self.ssh_tester.execute_command(check_cmd)
            if not result['success']:
                raise RuntimeError("iperf3 не установлен на сервере")

            # Останавливаем существующий сервер если есть
            stop_cmd = "sudo pkill iperf3"
            self.ssh_tester.execute_command(stop_cmd)
            time.sleep(2)

            # Запускаем сервер
            server_cmd = "iperf3 -s -D"
            result = self.ssh_tester.execute_command(server_cmd)
            if not result['success']:
                raise RuntimeError("Не удалось запустить iperf сервер")

            # Проверяем что сервер запущен
            check_cmd = "pgrep iperf3"
            result = self.ssh_tester.execute_command(check_cmd)
            if not result['success']:
                raise RuntimeError("iperf сервер не запущен")

            return True

        except Exception as e:
            self.logger.error(f"Ошибка при запуске iperf сервера: {e}")
            return False
        finally:
            self.ssh_tester.disconnect()

    def stop_iperf_server(self) -> bool:
        """
        Останавливает iperf сервер.

        Returns:
            bool: True если сервер остановлен успешно
        """
        try:
            if not self.ssh_tester.connect():
                raise RuntimeError("Не удалось установить SSH соединение")

            command = "sudo pkill iperf3"
            result = self.ssh_tester.execute_command(command)
            if not result['success']:
                raise RuntimeError("Не удалось остановить iperf сервер")

            return True

        except Exception as e:
            self.logger.error(f"Ошибка при остановке iperf сервера: {e}")
            return False
        finally:
            self.ssh_tester.disconnect()

    def run_iperf_test(self) -> Dict[str, Any]:
        """
        Запускает тест производительности с помощью iperf.

        Returns:
            Dict[str, Any]: Результаты теста
        """
        try:
            command = [
                "iperf3",
                "-c", cast(str, self.ipmi_host),
                "-t", str(self.test_duration),
                "-b", self.bandwidth,
                "-P", str(self.parallel_streams),
                "-l", str(self.packet_size),
                "-J"  # JSON output
            ]

            result = self._run_command(command)
            if not result:
                raise RuntimeError("Не удалось выполнить iperf тест")

            # Парсим JSON вывод
            import json
            data = json.loads(result.stdout)

            # Извлекаем метрики
            metrics = {
                'bandwidth': float(data['end']['sum_received']['bits_per_second']),
                'latency': float(data['end']['sum_received']['jitter_ms']),
                'packet_loss': float(data['end']['sum_received']['lost_percent'])
            }

            return metrics

        except Exception as e:
            self.logger.error(f"Ошибка при выполнении iperf теста: {e}")
            return {}

    def monitor_system_resources(self) -> Dict[str, Any]:
        """
        Мониторит системные ресурсы во время теста.

        Returns:
            Dict[str, Any]: Метрики использования ресурсов
        """
        try:
            if not self.ssh_tester.connect():
                raise RuntimeError("Не удалось установить SSH соединение")

            metrics = {
                'cpu_usage': [],
                'memory_usage': [],
                'network_usage': []
            }

            # Мониторим ресурсы каждые 5 секунд
            for _ in range(self.test_duration // 5):
                # CPU
                cpu_cmd = "top -bn1 | grep 'Cpu(s)' | awk '{print $2}'"
                result = self.ssh_tester.execute_command(cpu_cmd)
                if result['success'] and result['output']:
                    metrics['cpu_usage'].append(float(result['output']))

                # Memory
                mem_cmd = "free -m | grep Mem | awk '{print $3/$2 * 100}'"
                result = self.ssh_tester.execute_command(mem_cmd)
                if result['success'] and result['output']:
                    metrics['memory_usage'].append(float(result['output']))

                # Network
                net_cmd = f"cat /proc/net/dev | grep {self.interface}"
                result = self.ssh_tester.execute_command(net_cmd)
                if result['success'] and result['output']:
                    bytes_rx = int(result['output'].split()[1])
                    metrics['network_usage'].append(bytes_rx)

                time.sleep(5)

            return {
                'cpu_avg': sum(metrics['cpu_usage']) / len(metrics['cpu_usage']),
                'memory_avg': sum(metrics['memory_usage']) / len(metrics['memory_usage']),
                'network_throughput': (
                    metrics['network_usage'][-1] - metrics['network_usage'][0]
                ) / self.test_duration
            }

        except Exception as e:
            self.logger.error(f"Ошибка при мониторинге ресурсов: {e}")
            return {}
        finally:
            self.ssh_tester.disconnect()

    def verify_test_results(
        self,
        metrics: Dict[str, Any]
    ) -> bool:
        """
        Проверяет результаты тестирования.

        Args:
            metrics: Метрики для проверки

        Returns:
            bool: True если все метрики в норме
        """
        try:
            if not metrics:
                raise ValueError("Отсутствуют метрики для проверки")

            # Проверяем пропускную способность
            bandwidth_mbps = metrics['bandwidth'] / 1_000_000
            if bandwidth_mbps < self.min_bandwidth:
                self.logger.error(
                    f"Пропускная способность {bandwidth_mbps:.1f} Mbps "
                    f"ниже минимальной {self.min_bandwidth} Mbps"
                )
                return False

            # Проверяем задержку
            if metrics['latency'] > self.max_latency:
                self.logger.error(
                    f"Задержка {metrics['latency']:.1f} мс "
                    f"превышает максимальную {self.max_latency} мс"
                )
                return False

            # Проверяем потери пакетов
            if metrics['packet_loss'] > self.max_packet_loss:
                self.logger.error(
                    f"Потери пакетов {metrics['packet_loss']:.1f}% "
                    f"превышают максимальные {self.max_packet_loss}%"
                )
                return False

            return True

        except Exception as e:
            self.logger.error(f"Ошибка при проверке результатов теста: {e}")
            return False

    def perform_tests(self) -> None:
        """Выполняет тестирование под нагрузкой."""
        try:
            self.logger.info("Начало тестирования под нагрузкой")

            # Запускаем iperf сервер
            if not self.start_iperf_server():
                raise RuntimeError("Не удалось запустить iperf сервер")

            # Запускаем мониторинг ресурсов если требуется
            if self.monitor_resources:
                resource_metrics = self.monitor_system_resources()
                if resource_metrics:
                    self.logger.info(
                        f"Средняя загрузка CPU: {resource_metrics['cpu_avg']:.1f}%"
                    )
                    self.logger.info(
                        f"Среднее использование памяти: "
                        f"{resource_metrics['memory_avg']:.1f}%"
                    )
                    self.logger.info(
                        f"Пропускная способность сети: "
                        f"{resource_metrics['network_throughput'] / 1024:.1f} KB/s"
                    )

            # Выполняем тест производительности
            metrics = self.run_iperf_test()
            if not metrics:
                raise RuntimeError("Не удалось получить метрики теста")

            # Проверяем результаты
            if not self.verify_test_results(metrics):
                raise RuntimeError("Тест производительности не прошел")

            self.add_test_result('Load Test', True)
            self.add_test_result('Performance Metrics', True)

        except Exception as e:
            self.logger.error(f"Ошибка при выполнении тестов: {e}")
            self.add_test_result('Load Tests', False, str(e))
        finally:
            self.stop_iperf_server()
            self.safe_restore_settings()

    def restore_settings(self) -> bool:
        """
        Восстанавливает исходные настройки.

        Returns:
            bool: True если восстановление успешно
        """
        # В данном случае нам не нужно восстанавливать настройки,
        # так как мы только тестируем производительность
        return True
