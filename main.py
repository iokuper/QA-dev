"""Основной модуль для запуска тестов."""

import logging
import signal
import sys
import traceback
import threading
from typing import Dict, Set, TypedDict, List, Any, Optional
from pathlib import Path
from datetime import datetime
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn, TimeRemainingColumn
from rich.prompt import Prompt, Confirm
from rich.panel import Panel
from rich import box
from rich.align import Align
from rich.markdown import Markdown

# Импортируем все тестеры
from base_tester import BaseTester
from network_tester import NetworkTester
from hostname_tester import HostnameTester
from ssh_tester import SSHTester
from redfish_tester import RedfishTester
from ipmi_tester import IPMITester
from ip_version_tester import IPVersionTester
from vlan_tester import VLANTester
from dns_tester import DNSTester
from mac_tester import MACTester
from interface_tester import InterfaceTester
from load_tester import LoadTester
from ip_filter_tester import IPFilterTester
from diagnostic_tester import DiagnosticTester
from power_state_tester import PowerStateTester
from interface_status_tester import InterfaceStatusTester
from ntp_tester import NTPTester
from manual_ntp_tester import ManualNTPTester
from snmp_tester import SNMPTester
from logger import setup_logger

# Инициализация Rich
console = Console()

# Константы для путей
LOG_DIR = Path('logs')
REPORT_DIR = Path('reports')
CONFIG_FILE = Path('config.ini')

# Константы для тестирования
MIN_ITERATIONS = 1
MAX_ITERATIONS = 10
RETRY_DELAY = 1.0

# Создаем необходимые директории
LOG_DIR.mkdir(exist_ok=True)
REPORT_DIR.mkdir(exist_ok=True)

# Цветовые стили
STYLES = {
    'header': 'bold cyan',
    'success': 'bold green',
    'error': 'bold red',
    'warning': 'bold yellow',
    'info': 'bold blue',
    'category': 'bold magenta',
    'key': 'bold white on blue',
    'value': 'bold white',
    'menu_item': 'cyan',
    'selected': 'bold white on blue',
}

# Горячие клавиши (удалены, так как не используются)
# HOTKEYS = {
#     'q': 'Выход',
#     'h': 'Помощь',
#     'r': 'Запуск тестов',
#     'a': 'Выбрать все',
#     'n': 'Снять выбор',
#     's': 'Поиск',
#     'f': 'Фильтр',
#     'v': 'Просмотр выбранных',
#     'c': 'Очистить консоль'
# }

class TestCategory(TypedDict):
    """Структура для категории тестов."""
    name: str
    description: str
    tests: List[str]
    icon: str

class TesterDescription(TypedDict):
    """Структура для описания тестера."""
    name: str
    class_name: str
    description: str
    details: str
    dependencies: List[str]
    estimated_time: int  # в секундах

class TestResult(TypedDict):
    """Структура для результатов тестирования."""
    test_name: str
    success: bool
    message: str
    error_details: str
    duration: float
    timestamp: str
    test_type: str

# Категории тестов
TEST_CATEGORIES: Dict[str, TestCategory] = {
    'network': {
        'name': 'Сетевые тесты',
        'description': 'Базовые сетевые настройки и подключения',
        'tests': [
            'Network',          # Базовые сетевые настройки
            'IPVersion',        # Поддержка IPv4/IPv6
            'IPFilter',         # Фильтрация IP-адресов
            'VLAN',             # Настройка VLAN
            'MAC',              # Настройка MAC-адресов
            'Interface',        # Настройка интерфейсов
            'InterfaceStatus'   # Статус интерфейсов
        ],
        'icon': '🌐'
    },
    'management': {
        'name': 'Интерфейсы управления',
        'description': 'Тесты протоколов и интерфейсов управления',
        'tests': [
            'SSH',             # SSH доступ
            'Redfish',         # Redfish API
            'IPMI',            # IPMI доступ
            'SNMP'             # SNMP мониторинг
        ],
        'icon': '🔧'
    },
    'services': {
        'name': 'Сетевые сервисы',
        'description': 'Тесты сетевых служб и протоколов',
        'tests': [
            'DNS',             # DNS настройки
            'NTP',             # NTP синхронизация
            'ManualNTP',       # Ручная настройка NTP
            'Hostname'         # Настройка имени хоста
        ],
        'icon': '🔌'
    },
    'performance': {
        'name': 'Производительность',
        'description': 'Тесты производительности и нагрузки',
        'tests': [
            'Load',            # Тесты под нагрузкой
            'Diagnostic'       # Диагностические тесты
        ],
        'icon': '📊'
    },
    'power': {
        'name': 'Управление питанием',
        'description': 'Тесты управления питанием',
        'tests': [
            'PowerState'       # Управление питанием
        ],
        'icon': '⚡'
    }
}

# Создаем обратную связь от теста к категории
TEST_TO_CATEGORY: Dict[str, str] = {}
for category_key, category in TEST_CATEGORIES.items():
    for test in category['tests']:
        TEST_TO_CATEGORY[test] = category_key

# Описания тестеров
TESTER_CLASSES: Dict[str, TesterDescription] = {
    'Network': {
        'name': 'Network Tester',
        'class_name': 'NetworkTester',
        'description': 'Тестирование базовых сетевых настроек',
        'details': """
        Проверяет:
        - Настройку статического IP
        - Настройку DHCP
        - Доступность сети
        """,
        'dependencies': [],
        'estimated_time': 120
    },
    'IPVersion': {
        'name': 'IP Version Tester',
        'class_name': 'IPVersionTester',
        'description': 'Тестирование поддержки IPv4 и IPv6',
        'details': """
        Проверяет:
        - Поддержку IPv4 и IPv6
        - Доступность интерфейсов по обоим протоколам
        - Корректность настроек IP версий
        """,
        'dependencies': ['Network'],
        'estimated_time': 90
    },
    'IPFilter': {
        'name': 'IP Filter Tester',
        'class_name': 'IPFilterTester',
        'description': 'Тестирование IP-фильтрации',
        'details': """
        Проверяет:
        - Настройку правил IP-фильтрации
        - Корректность блокировки/разрешения трафика
        - Стабильность работы фильтров под нагрузкой
        """,
        'dependencies': ['Network'],
        'estimated_time': 110
    },
    'VLAN': {
        'name': 'VLAN Tester',
        'class_name': 'VLANTester',
        'description': 'Тестирование настроек VLAN',
        'details': """
        Проверяет:
        - Настройку VLAN ID
        - Корректность маршрутизации VLAN
        - Изоляцию сетевого трафика между VLAN
        """,
        'dependencies': ['Network'],
        'estimated_time': 100
    },
    'MAC': {
        'name': 'MAC Address Tester',
        'class_name': 'MACTester',
        'description': 'Тестирование настройки MAC-адресов',
        'details': """
        Проверяет:
        - Изменение MAC-адресов интерфейсов
        - Корректность отображения MAC-адресов через все интерфейсы
        - Стабильность сети после изменения MAC-адреса
        """,
        'dependencies': ['Network'],
        'estimated_time': 70
    },
    'Interface': {
        'name': 'Interface Tester',
        'class_name': 'InterfaceTester',
        'description': 'Тестирование состояния сетевых интерфейсов',
        'details': """
        Проверяет:
        - Состояние (UP/DOWN) интерфейсов
        - Корректность настроек интерфейсов
        - Доступность интерфейсов через разные методы управления
        """,
        'dependencies': ['Network'],
        'estimated_time': 60
    },
    'InterfaceStatus': {
        'name': 'Interface Status Tester',
        'class_name': 'InterfaceStatusTester',
        'description': 'Тестирование статуса сетевых интерфейсов',
        'details': """
        Проверяет:
        - Текущее состояние (UP/DOWN) всех сетевых интерфейсов
        - Соответствие настроек интерфейсов
        - Обновление статуса интерфейсов при изменении настроек
        """,
        'dependencies': ['Interface'],
        'estimated_time': 50
    },
    'SSH': {
        'name': 'SSH Tester',
        'class_name': 'SSHTester',
        'description': 'Тестирование SSH-соединений',
        'details': """
        Проверяет:
        - Доступность SSH-сервиса
        - Корректность аутентификации
        - Скорость соединения и стабильность
        """,
        'dependencies': ['Network'],
        'estimated_time': 90
    },
    'Redfish': {
        'name': 'Redfish Tester',
        'class_name': 'RedfishTester',
        'description': 'Тестирование Redfish API',
        'details': """
        Проверяет:
        - Доступность Redfish API
        - Корректность получаемых данных
        - Возможность внесения изменений через API
        """,
        'dependencies': ['Network'],
        'estimated_time': 150
    },
    'IPMI': {
        'name': 'IPMI Tester',
        'class_name': 'IPMITester',
        'description': 'Тестирование IPMI интерфейса',
        'details': """
        Проверяет:
        - Доступность IPMI интерфейса
        - Корректность настроек через IPMI
        - Функциональность управления питанием
        """,
        'dependencies': ['Network'],
        'estimated_time': 120
    },
    'Load': {
        'name': 'Load Tester',
        'class_name': 'LoadTester',
        'description': 'Тестирование производительности под нагрузкой',
        'details': """
        Проверяет:
        - Производительность сетевых интерфейсов под нагрузкой
        - Стабильность системы при высокой нагрузке
        - Возможность восстановления после нагрузки
        """,
        'dependencies': ['Network'],
        'estimated_time': 200
    },
    'Diagnostic': {
        'name': 'Diagnostic Tester',
        'class_name': 'DiagnosticTester',
        'description': 'Тестирование диагностических функций',
        'details': """
        Проверяет:
        - Сбор диагностической информации
        - Анализ системных логов
        - Мониторинг состояния системы
        - Проверка работоспособности компонентов
        """,
        'dependencies': ['Network'],
        'estimated_time': 180
    },
    'PowerState': {
        'name': 'Power State Tester',
        'class_name': 'PowerStateTester',
        'description': 'Тестирование состояния питания сервера',
        'details': """
        Проверяет:
        - Включение, выключение и перезагрузку сервера
        - Доступность BMC на всех этапах работы сервера
        - Корректность статуса питания через все интерфейсы
        """,
        'dependencies': ['IPMI'],
        'estimated_time': 130
    },
    'NTP': {
        'name': 'NTP Tester',
        'class_name': 'NTPTester',
        'description': 'Тестирование настроек NTP',
        'details': """
        Проверяет:
        - Корректность настроек NTP-серверов
        - Синхронизацию времени с NTP-серверами
        - Стабильность и точность времени на сервере
        """,
        'dependencies': ['Network'],
        'estimated_time': 90
    },
    'ManualNTP': {
        'name': 'Manual NTP Tester',
        'class_name': 'ManualNTPTester',
        'description': 'Ручная настройка и тестирование NTP',
        'details': """
        Проверяет:
        - Возможность ручной настройки NTP-серверов
        - Корректность применения настроек
        - Синхронизацию времени после ручной настройки
        """,
        'dependencies': ['NTP'],
        'estimated_time': 100
    },
    'SNMP': {
        'name': 'SNMP Tester',
        'class_name': 'SNMPTester',
        'description': 'Тестирование SNMP-сервера BMC',
        'details': """
        Проверяет:
        - Доступность SNMP-сервера
        - Корректность данных, получаемых через SNMP
        - Функциональность чтения и записи OID
        - Получение SNMP-трапов
        """,
        'dependencies': ['Network'],
        'estimated_time': 140
    },
    'DNS': {
        'name': 'DNS Tester',
        'class_name': 'DNSTester',
        'description': 'Тестирование DNS-настроек',
        'details': """
        Проверяет:
        - Корректность настроек DNS-серверов
        - Разрешение доменных имен
        - Стабильность DNS-сервиса
        """,
        'dependencies': ['Network'],
        'estimated_time': 80
    },
    'Hostname': {
        'name': 'Hostname Tester',
        'class_name': 'HostnameTester',
        'description': 'Тестирование настройки имени хоста',
        'details': """
        Проверяет:
        - Изменение имени хоста
        - Корректное отображение имени хоста через все интерфейсы
        """,
        'dependencies': ['Network'],
        'estimated_time': 60
    },
}

class TestManager:
    """Класс для управления тестами и взаимодействием с пользователем."""

    def __init__(self):
        self.logger: Optional[logging.Logger] = None
        self.selected_testers: Set[str] = set()
        self.tester_instances: Dict[str, BaseTester] = {}
        self.running = True

    def show_help(self) -> None:
        """Показывает справку по горячим клавишам."""
        help_table = Table(title="Горячие клавиши", box=box.SIMPLE_HEAVY)
        help_table.add_column("Клавиша", style="yellow", no_wrap=True)
        help_table.add_column("Действие", style="magenta")

        for key, description in {
            'q': 'Выход',
            'h': 'Помощь',
            'r': 'Запуск тестов',
            'a': 'Выбрать все',
            'n': 'Снять выбор',
            's': 'Поиск',
            'f': 'Фильтр',
            'v': 'Просмотр выбранных',
            'c': 'Очистить консоль'
        }.items():
            help_table.add_row(key, description)

        console.print(help_table)

    def display_testers_table(self, tester_configs: Dict[str, Any]) -> None:
        """Отображает таблицу выбранных тестеров."""
        table = Table(title="Выбранные Тесты", box=box.MINIMAL_DOUBLE_HEAD, show_lines=True)
        table.add_column("Тестер", style="cyan", no_wrap=True)
        table.add_column("Описание", style="magenta")
        table.add_column("Время (с)", justify="right", style="green")

        for name in tester_configs.keys():
            config = TESTER_CLASSES.get(name)
            if not config:
                continue
            category_key = TEST_TO_CATEGORY.get(name, "")
            category = TEST_CATEGORIES.get(category_key, {})
            icon = category.get('icon', '')
            tester_name = config['name']
            description = config['description']
            estimated_time = config['estimated_time']

            table.add_row(
                f"{icon} {tester_name}",
                description,
                str(estimated_time)
            )

        console.print(table)

    def display_summary(self) -> None:
        """Отображает сводку перед запуском тестов."""
        total_time = sum(TESTER_CLASSES[test]['estimated_time'] for test in self.selected_testers)
        summary_panel = Panel(
            f"""
            [bold cyan]Выбрано тестов:[/bold cyan] {len(self.selected_testers)}
            [bold cyan]Примерное время выполнения:[/bold cyan] {total_time // 60}м {total_time % 60}с

            [bold yellow]Внимание! Убедитесь, что все необходимые условия соблюдены:
            • Наличие сетевого подключения
            • Корректность учетных данных
            • Доступность BMC[/bold yellow]
            """,
            title="Сводка перед запуском",
            border_style="blue"
        )
        console.print(summary_panel)

    def select_tests_interactive(self) -> Set[str]:
        """Интерактивный выбор тестов с использованием rich."""
        try:
            all_tests = [test for category in TEST_CATEGORIES.values() for test in category['tests']]

            # Отображаем все тесты в таблице
            test_table = Table(title="Доступные тесты", box=box.ROUNDED, show_lines=True)
            test_table.add_column("№", style="yellow", no_wrap=True)
            test_table.add_column("Тестер", style="cyan")
            test_table.add_column("Описание", style="magenta")
            test_table.add_column("Категория", style="green")

            test_list = []
            idx = 1
            for category_key, category in TEST_CATEGORIES.items():
                for test in category['tests']:
                    test_list.append((idx, test, TESTER_CLASSES[test]['description'], category['name']))
                    idx += 1

            for row in test_list:
                test_table.add_row(str(row[0]), row[1], row[2], row[3])

            console.print(test_table)

            # Запрос ввода от пользователя
            console.print("\n[bold cyan]Введите номера тестов через запятую или 'all' для выбора всех тестов.[/bold cyan]")
            choice = Prompt.ask("Ваш выбор", default="all").strip().lower()

            if choice == 'all':
                self.logger.info("Пользователь выбрал все тесты")
                return set(all_tests)

            selected_tests = set()
            invalid_entries = []

            # Обработка ввода с защитой от некорректных символов
            for item in choice.split(","):
                try:
                    item = item.strip().encode('utf-8').decode('utf-8')
                    if item.isdigit():
                        idx = int(item) - 1
                        if 0 <= idx < len(test_list):
                            selected_tests.add(test_list[idx][1])
                            self.logger.info(f"Пользователь выбрал тест {test_list[idx][1]}")
                        else:
                            invalid_entries.append(item)
                            self.logger.warning(f"Некорректный номер теста: {item}")
                    else:
                        matches = [test for test in all_tests if item in test.lower() or item in TESTER_CLASSES[test]['description'].lower()]
                        if matches:
                            selected_tests.update(matches)
                            self.logger.info(f"Пользователь выбрал тесты по названию: {matches}")
                        else:
                            invalid_entries.append(item)
                            self.logger.warning(f"Некорректное название теста: {item}")
                except UnicodeError:
                    invalid_entries.append("некорректный символ")
                    self.logger.warning("Обнаружены некорректные символы во вводе")

            if invalid_entries:
                console.print(f"[red]Некорректные номера или названия тестов: {', '.join(invalid_entries)}[/red]")
                self.logger.warning(f"Некорректные вводы: {', '.join(invalid_entries)}")

            if not selected_tests:
                console.print("[red]Некорректный выбор. Выбрано все тесты по умолчанию.[/red]")
                self.logger.info("Некорректный выбор, выбраны все тесты по умолчанию")
                return set(all_tests)

            return selected_tests
        except Exception as e:
            self.logger.error(f"Ошибка при выборе тестов: {e}")
            return set()

    def validate_test_definitions(self) -> bool:
        """Проверяет, что все тесты в TEST_CATEGORIES имеют определения в TESTER_CLASSES."""
        missing_tests = []
        for category in TEST_CATEGORIES.values():
            for test in category['tests']:
                if test not in TESTER_CLASSES:
                    missing_tests.append(test)

        if missing_tests:
            console.print("[bold red]Ошибка: отсутствуют определения для следующих тестов:[/bold red]")
            for test in missing_tests:
                console.print(f"- {test}")
            return False
        return True

    def initialize_testers(self) -> Dict[str, Any]:
        """Инициализирует выбранные тестеры, включая их зависимости."""
        testers = {}

        try:
            # Проверяем зависимости и добавляем недостающие тестеры
            initial_selected = set(self.selected_testers)
            for name in list(initial_selected):
                config = TESTER_CLASSES[name]
                for dep in config['dependencies']:
                    if dep not in self.selected_testers:
                        console.print(f"[yellow]Добавление зависимого теста: {dep} для {name}[/yellow]")
                        self.logger.info(f"Добавление зависимого теста: {dep} для {name}")
                        self.selected_testers.add(dep)

            # Инициализируем тестеры
            for name in self.selected_testers:
                config = TESTER_CLASSES.get(name)
                if not config:
                    self.logger.error(f"Неизвестный тестер: {name}")
                    continue

                # Получаем класс тестера
                tester_class = globals().get(config['class_name'])
                if not tester_class:
                    self.logger.error(f"Не найден класс {config['class_name']} для тестера {name}")
                    continue

                # Создаем экземпляр тестера
                tester_instance = tester_class(str(CONFIG_FILE), self.logger)
                testers[name] = tester_instance
                self.logger.info(f"Тестер {name} инициализирован")

            self.tester_instances = testers
            return testers

        except Exception as e:
            self.logger.error(f"Ошибка при инициализации тестеров: {e}")
            self.logger.debug(traceback.format_exc())
            return {}

    def run_tests(self, iterations: int) -> Dict[str, List[TestResult]]:
        """Запускает тесты и возвращает результаты."""
        test_results: Dict[str, List[TestResult]] = {name: [] for name in self.tester_instances.keys()}
        total_tests = len(self.tester_instances) * iterations

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
            console=console,
            transient=True
        ) as progress:
            task = progress.add_task("[bold blue]Выполнение тестов...", total=total_tests)
            self.logger.info("Начало выполнения тестов")

            for iteration in range(iterations):
                self.logger.info(f"Итерация {iteration + 1}/{iterations}")
                for name, tester in self.tester_instances.items():
                    try:
                        self.logger.info(f"Запуск теста {name}, итерация {iteration + 1}")
                        start_time = datetime.now()
                        tester.perform_tests()
                        end_time = datetime.now()

                        # Собираем результаты
                        for result in tester.test_results:
                            test_results[name].append(result)

                        self.logger.info(f"Тест {name} успешно завершен за {(end_time - start_time).total_seconds():.2f}с")
                    except Exception as e:
                        self.logger.error(f"Ошибка при выполнении теста {name}: {e}")
                        self.logger.debug(traceback.format_exc())

                    progress.update(task, advance=1)

        self.logger.info("Выполнение тестов завершено")
        return test_results

    def generate_test_report(self, tester_results: Dict[str, List[TestResult]], start_time: datetime) -> None:
        """Генерирует отчет о тестировании."""
        try:
            timestamp = start_time.strftime("%Y%m%d_%H%M%S")
            report_file = REPORT_DIR / f"test_report_{timestamp}.log"

            with open(report_file, 'w', encoding='utf-8') as f:
                f.write("=== Отчет о тестировании ===\n\n")
                f.write(f"Время начала: {start_time}\n")
                f.write(f"Время окончания: {datetime.now()}\n")
                f.write(
                    f"Длительность: {(datetime.now() - start_time).total_seconds():.1f}с\n\n"
                )

                total_tests = 0
                total_success = 0

                for tester_name, results in tester_results.items():
                    f.write(f"\n=== {tester_name} ===\n")
                    success_count = sum(1 for result in results if result['success'])
                    total_tests += len(results)
                    total_success += success_count

                    f.write(f"Успешно: {success_count}/{len(results)}\n")

                    for result in results:
                        status = "✓" if result['success'] else "✗"
                        msg = f" - {result.get('message', '')}" if result.get('message') else ""
                        error = f"\nОшибка: {result.get('error_details', '')}" if result.get('error_details') else ""

                        f.write(
                            f"{status} {result['test_type']}: "
                            f"{msg}{error}\n"
                        )

                # Общая статистика
                success_rate = (total_success / total_tests * 100) if total_tests > 0 else 0
                f.write("\n=== Общая статистика ===\n")
                f.write(f"Всего тестов: {total_tests}\n")
                f.write(f"Успешно: {total_success}\n")
                f.write(f"Неудачно: {total_tests - total_success}\n")
                f.write(f"Успешность: {success_rate:.1f}%\n")

            # Генерация Markdown-отчета с помощью rich
            report_markdown = []
            report_markdown.append("# Отчет о тестировании\n")
            report_markdown.append(f"**Время начала:** {start_time}\n")
            report_markdown.append(f"**Время окончания:** {datetime.now()}\n")
            report_markdown.append(f"**Длительность:** {(datetime.now() - start_time).total_seconds():.1f}с\n")

            total_tests_md = 0
            total_success_md = 0

            for tester_name, results in tester_results.items():
                report_markdown.append(f"## {tester_name}")
                success_count = sum(1 for result in results if result['success'])
                total_tests_md += len(results)
                total_success_md += success_count
                report_markdown.append(f"**Успешно:** {success_count}/{len(results)}\n")

                for result in results:
                    status = "✅" if result['success'] else "❌"
                    message = result.get('message', '')
                    error = f" Ошибка: {result.get('error_details')}" if result.get('error_details') else ""
                    report_markdown.append(f"- {status} **{result['test_type']}**: {message}{error}")

            # Общая статистика
            success_rate_md = (total_success_md / total_tests_md * 100) if total_tests_md > 0 else 0
            report_markdown.append("\n## Общая статистика")
            report_markdown.append(f"- **Всего тестов:** {total_tests_md}")
            report_markdown.append(f"- **Успешно:** {total_success_md}")
            report_markdown.append(f"- **Неудачно:** {total_tests_md - total_success_md}")
            report_markdown.append(f"- **Успешность:** {success_rate_md:.1f}%")

            # Сохранение Markdown-отчета
            markdown_content = "\n".join(report_markdown)
            markdown_file = REPORT_DIR / f"test_report_{timestamp}.md"
            with open(markdown_file, 'w', encoding='utf-8') as f_md:
                f_md.write(markdown_content)

            console.print(
                Panel(
                    f"Отчет сохранен:\n- Лог-файл: {report_file}\n- Markdown: {markdown_file}",
                    title="Отчет сгенерирован",
                    border_style="green"
                )
            )
            self.logger.info(f"Отчет сохранен в {report_file} и {markdown_file}")

        except Exception as e:
            self.logger.error(f"Ошибка при генерации отчета: {e}")
            self.logger.debug(traceback.format_exc())

    def display_test_report(self, tester_results: Dict[str, List[TestResult]]) -> None:
        """Отображает отчет о тестировании в консоли с помощью rich."""
        for tester_name, results in tester_results.items():
            console.print(Panel.fit(f"[bold magenta]{tester_name}[/bold magenta]", style="bold blue"))
            table = Table(show_header=True, header_style="bold yellow", box=box.MINIMAL_DOUBLE_HEAD)
            table.add_column("Тестер", style="cyan", no_wrap=True)
            table.add_column("Статус", style="green")
            table.add_column("Сообщение", style="white")

            for result in results:
                status = "[bold green]✓[/bold green]" if result['success'] else "[bold red]✗[/bold red]"
                message = result.get('message', '')
                table.add_row(result['test_type'], status, message)

            console.print(table)

        # Сводка
        total = sum(len(tests) for tests in tester_results.values())
        success = sum(result['success'] for tests in tester_results.values() for result in tests)
        failure = total - success
        summary = f"[bold green]Успешно: {success}[/bold green] / [bold red]Неудачно: {failure}[/bold red] / [bold blue]Всего: {total}[/bold blue]"
        console.print(Panel(summary, title="Сводка", style="bold cyan"))

    def run(self) -> None:
        """Запускает основную логику тестирования."""
        try:
            # Вывод заголовка
            header_panel = Panel(
                Align.center(
                    "[bold cyan]Система тестирования QA OpenYard[/bold cyan]",
                    vertical="middle"
                ),
                subtitle="[bold yellow]Версия 0.1. Первый релиз[/bold yellow]",
                style="bold blue",
                box=box.ROUNDED
            )
            console.print(header_panel)

            # Настройка логгера
            self.logger = setup_logger(
                name='main',
                log_file=str(LOG_DIR / 'test.log')
            )

            # Настройка обработчиков сигналов
            self.setup_signal_handlers()

            # Валидация тестеров
            if not self.validate_test_definitions():
                self.logger.error(
                    "Некоторые тесты не имеют определений. Завершение программы."
                )
                sys.exit(1)

            # Основной цикл программы
            while self.running:
                # Показываем справку
                self.show_help()

                # Выбор тестов через интерактивное меню
                self.selected_testers = self.select_tests_interactive()
                if not self.selected_testers:
                    console.print("[yellow]Тестирование отменено пользователем.[/yellow]")
                    self.logger.info("Тестирование отменено пользователем")
                    break

                # Показываем выбранные тесты
                self.display_testers_table({name: {} for name in self.selected_testers})

                # Показываем сводку перед запуском
                self.display_summary()

                if not Confirm.ask("Начать выполнение тестов?"):
                    self.logger.info("Пользователь отказался от запуска тестов")
                    continue

                # Запрос на количество итераций
                while True:
                    try:
                        iterations = int(
                            Prompt.ask(f"\n[bold blue]Введите количество повторений [{MIN_ITERATIONS}-{MAX_ITERATIONS}]:[/bold blue]")
                        )
                        if MIN_ITERATIONS <= iterations <= MAX_ITERATIONS:
                            break
                        console.print(f"[red]Значение должно быть между {MIN_ITERATIONS} и {MAX_ITERATIONS}.[/red]")
                    except ValueError:
                        console.print("[red]Введите корректное целое число.[/red]")

                # Запуск тестов
                start_time = datetime.now()
                test_results = self.run_tests(iterations)

                # Генерация отчета
                self.generate_test_report(test_results, start_time)

                # Отображение результатов в консоли
                self.display_test_report(test_results)

                # Спрашиваем о продолжении
                if not Confirm.ask("Хотите запустить другие тесты?"):
                    self.running = False
                    self.logger.info("Пользователь завершил работу с тестами")
                    break

        except KeyboardInterrupt:
            console.print("\n[yellow]Прервано пользователем.[/yellow]")
            self.logger.warning("Прервано пользователем через KeyboardInterrupt")
        except Exception as e:
            if self.logger:
                self.logger.error(f"Критическая ошибка: {e}")
                self.logger.debug(traceback.format_exc())
            console.print(f"[red]Критическая ошибка: {e}[/red]")
        finally:
            if self.logger:
                self.logger.info("Завершение тестирования")

            console.print("\nНажмите Enter для выхода...")
            input()

    def setup_signal_handlers(self) -> None:
        """Настраивает обработчики сигналов."""
        def signal_handler(signum: int, frame: Any) -> None:
            self.logger.warning("Получен сигнал завершения")
            console.print("\n[yellow]Завершение работы...[/yellow]")
            sys.exit(0)

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

def main() -> None:
    """Основная функция программы."""
    manager = TestManager()
    manager.run()

if __name__ == '__main__':
    main()
