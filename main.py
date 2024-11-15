# main_module.py

"""Основной модуль для запуска тестов."""

import logging
import signal
import sys
import traceback
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
import urllib3
import os

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

# Отключаем предупреждения urllib3 о небезопасных соединениях
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

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

class TestCategory(TypedDict):
    """Структура для категории тестов."""
    name: str
    description: str
    tests: List[str]
    icon: str

class TesterDescription(TypedDict):
    """Структура для описания тестера."""
    name: str
    class_obj: Any  # Изменено с class_name на class_obj
    description: str
    details: str
    dependencies: List[str]
    estimated_time: int  # в секундах

class TestResult(TypedDict):
    """Структура для результатов тестирования."""
    test_name: str
    success: bool
    message: str
    error_details: Optional[str]
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
        'class_obj': NetworkTester,
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
        'class_obj': IPVersionTester,
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
        'class_obj': IPFilterTester,
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
        'class_obj': VLANTester,
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
        'class_obj': MACTester,
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
        'class_obj': InterfaceTester,
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
        'class_obj': InterfaceStatusTester,
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
        'class_obj': SSHTester,
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
        'class_obj': RedfishTester,
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
        'class_obj': IPMITester,
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
        'class_obj': LoadTester,
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
        'class_obj': DiagnosticTester,
        'description': 'Тестирование диагностических функций',
        'details': """
        Проверяет:
        - Сбор диагностической информации
        - Анализ системных ло��ов
        - Мониторинг состояния системы
        - Проверка работоспособности компонентов
        """,
        'dependencies': ['Network'],
        'estimated_time': 180
    },
    'PowerState': {
        'name': 'Power State Tester',
        'class_obj': PowerStateTester,
        'description': 'Тестирование состояния питания сервера',
        'details': """
        Проверяет:
        - Включение, выключение и перезагрузку сервера
        - Доступность BMC на всех этапах рабоы сервера
        - Корректность статуса питания через все интерфейсы
        """,
        'dependencies': ['IPMI'],
        'estimated_time': 130
    },
    'NTP': {
        'name': 'NTP Tester',
        'class_obj': NTPTester,
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
        'class_obj': ManualNTPTester,
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
        'class_obj': SNMPTester,
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
        'class_obj': DNSTester,
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
        'class_obj': HostnameTester,
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
    """Класс для управления тестами и взаимодействием с ползователем."""

    def __init__(self):
        """
        Инициализирует TestManager.

        Настраивает логирование и инициализирует необходимые атрибуты.
        """
        self.logger: logging.Logger = setup_logger(
            name='main',
            log_file=str(LOG_DIR / 'test.log')
        )
        self.selected_testers: Set[str] = set()
        self.tester_instances: Dict[str, BaseTester] = {}
        self.running = True

    def show_help(self) -> None:
        """
        Показывает справку по горячим клавишам.

        Выводит таблицу с доступными горячими клавишами и их действиями.
        """
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
            'c': 'Очистить консоль',
            'b': 'Назад'
        }.items():
            help_table.add_row(key, description)

        console.print(help_table)

    def display_testers_table(self, tester_configs: Dict[str, Any]) -> None:
        """
        Отображает таблицу выбранных тестеров.

        Args:
            tester_configs (Dict[str, Any]): Конфигурации выбранных тестеров.
        """
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
        """
        Отображает сводку перед запуском тестов.

        Выводит панель с информацией о количестве выбранных тестов и примерном времени выполнения.
        """
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
        """
        Интерактивный выбор тестов с использованием rich.

        Returns:
            Set[str]: Набор выбранных тестов.
        """
        try:
            selected_tests = set()

            while True:
                # Отображаем категории тестов
                category_table = Table(title="Категории Тестов", box=box.ROUNDED, show_lines=True)
                category_table.add_column("№", style="yellow", no_wrap=True)
                category_table.add_column("Категория", style="cyan")
                category_table.add_column("Описание", style="magenta")
                category_table.add_column("Иконка", style="green")

                category_list = list(TEST_CATEGORIES.keys())
                for idx, category_key in enumerate(category_list, start=1):
                    category = TEST_CATEGORIES[category_key]
                    category_table.add_row(
                        str(idx),
                        category['name'],
                        category['description'],
                        category['icon']
                    )

                console.print(category_table)

                # Запрос выбора категорий
                console.print("\n[bold cyan]Выберите категории тестов (например, 1,3), 'all' для всех категорий, 'h' для помощи, 'r' для запуска тестов, 'c' для очистки консоли или 'q' для выхода:[/bold cyan]")
                choice = Prompt.ask("Ваш выбор").strip().lower()

                # Обработка Горячих Клавиш
                if choice == 'h':
                    self.show_help()
                    continue
                elif choice == 'q':
                    self.quit_program()
                elif choice == 'a':
                    selected_categories = set(category_list)
                    self.logger.info("Пользователь выбрал все категории тестов")
                elif choice == 'n':
                    selected_categories = set()
                    selected_tests.clear()
                    console.print("[yellow]Все категории сняты с выбора.[/yellow]")
                    self.logger.info("Пользователь снял выбор со всех категорий тестов")
                    continue
                elif choice == 'r':
                    # Запуск тестов прямо из выбора категорий, если есть выбранные тестеры
                    if self.selected_testers:
                        self.run_tests_directly()
                        continue
                    else:
                        console.print("[yellow]Нет выбранных тестов для запуска. Пожалуйста, выберите тесты сначала.[/yellow]")
                        self.logger.info("Пользователь попытался запустить тесты без выбранных тестеров")
                        continue
                elif choice == 'c':
                    self.clear_console()
                    continue
                elif choice == 'v':
                    self.view_selected_tests()
                    continue
                elif choice == 's':
                    keyword = Prompt.ask("Введите ключевое слово для поиска категорий").strip()
                    found_categories = self.search_categories(keyword)
                    if found_categories:
                        selected_categories = set(found_categories)
                        console.print(f"[green]Найдено категорий: {len(found_categories)}[/green]")
                        self.logger.info(f"Найдено категорий по ключевому слову '{keyword}': {found_categories}")
                    else:
                        console.print(f"[red]Категории по ключевому слову '{keyword}' не найдены.[/red]")
                        self.logger.info(f"Категории по ключевому слову '{keyword}' не найдены.")
                        continue
                elif choice == 'f':
                    # Фильтрация по времени выполнения
                    try:
                        min_time = int(Prompt.ask("Введите минимальное время выполнения (с)").strip())
                        max_time = int(Prompt.ask("Введите максимальное время выполнения (с)").strip())
                        filtered_categories = [key for key in category_list
                                               if any(TESTER_CLASSES[test]['estimated_time'] >= min_time and TESTER_CLASSES[test]['estimated_time'] <= max_time
                                                      for test in TEST_CATEGORIES[key]['tests'])]
                        if filtered_categories:
                            selected_categories = set(filtered_categories)
                            console.print(f"[green]Категории отфильтрованы: {len(filtered_categories)}[/green]")
                            self.logger.info(f"Категории отфильтрованы по времени выполнения: {filtered_categories}")
                        else:
                            console.print(f"[red]Категории по заданным критериям не найдены.[/red]")
                            self.logger.info("Категории по заданным критериям не найдены.")
                            continue
                    except ValueError:
                        console.print("[red]Некорректный ввод для фильтрации. Попробуйте снова.[/red]")
                        self.logger.warning("Некорректный ввод для фильтрации.")
                        continue
                else:
                    selected_categories = set()
                    invalid_entries = []

                    for item in choice.split(","):
                        item = item.strip()
                        if item.isdigit():
                            idx = int(item) - 1
                            if 0 <= idx < len(category_list):
                                selected_categories.add(category_list[idx])
                                self.logger.info(f"Пользователь выбрал категорию {category_list[idx]}")
                            else:
                                invalid_entries.append(item)
                                self.logger.warning(f"Некорректный номер категории: {item}")
                        else:
                            invalid_entries.append(item)
                            self.logger.warning(f"Некорректный ввод для категории: {item}")

                    if invalid_entries:
                        # Санитизация сообщений для логирования
                        sanitized_invalid = [self.sanitize_input(entry) for entry in invalid_entries]
                        console.print(f"[red]Некорректные номера категорий: {', '.join(sanitized_invalid)}[/red]")
                        self.logger.warning(f"Некорректные вводы категорий: {', '.join(sanitized_invalid)}")

                    if not selected_categories:
                        console.print("[red]Некорректный выбор категорий. Попробуйте снова.[/red]")
                        continue

                # Добавляем тесты из выбранных категорий
                for category_key in selected_categories:
                    tests = TEST_CATEGORIES[category_key]['tests']
                    selected_tests.update(tests)

                # Переходим к выбору конкретных тестеров из выбранных категорий
                final_selected_tests = self.select_specific_testers(selected_tests)

                return final_selected_tests

        except Exception as e:
            self.logger.error(f"Ошибка при выборе тестов: {e}")
            return set()

    def select_specific_testers(self, available_tests: Set[str]) -> Set[str]:
        """
        Позволяет пользователю выбрать конкретные тестеры из доступных.

        Args:
            available_tests (Set[str]): Набор доступных тестов для выбора.

        Returns:
            Set[str]: Набор выбранных тестов.
        """
        selected_tests = set()
        available_tests = sorted(available_tests)
        test_list = list(available_tests)
        total_tests = len(test_list)

        while True:
            try:
                # Отображаем доступные тестеры
                tester_table = Table(title="Доступные Тестеры", box=box.ROUNDED, show_lines=True)
                tester_table.add_column("№", style="yellow", no_wrap=True)
                tester_table.add_column("Тестер", style="cyan")
                tester_table.add_column("Описание", style="magenta")
                tester_table.add_column("Время (с)", justify="right", style="green")

                for idx, test in enumerate(test_list, start=1):
                    config = TESTER_CLASSES[test]
                    tester_table.add_row(
                        str(idx),
                        config['name'],
                        config['description'],
                        str(config['estimated_time'])
                    )

                console.print(tester_table)

                # Запрос выбора тестеров
                console.print("\n[bold cyan]Выберите тестеры для выполнения (например, 1,3,5), 'all' для всех тестеров, 'b' для возврата, 'h' для помощи, 'c' для очистки консоли, 'v' для просмотра выбранных или 'q' для выхода:[/bold cyan]")
                choice = Prompt.ask("Ваш выбор").strip().lower()

                # Обработка Горячих Клавиш
                if choice == 'h':
                    self.show_help()
                    continue
                elif choice == 'q':
                    self.quit_program()
                elif choice == 'a':
                    selected_tests.update(available_tests)
                    self.logger.info("Пользователь выбрал всех доступных тестеров")
                elif choice == 'n':
                    selected_tests.clear()
                    console.print("[yellow]Все тестеры сняты с выбора.[/yellow]")
                    self.logger.info("Пользователь снял выбор со всех тестеров")
                    continue
                elif choice == 'b':
                    # Возвращаемся к выбору категорий
                    return self.select_tests_interactive()
                elif choice == 'c':
                    self.clear_console()
                    continue
                elif choice == 'v':
                    self.view_selected_tests()
                    continue
                elif choice == 'r':
                    # Запуск тестов прямо из выбора тестеров, если есть выбранные тестеры
                    if self.selected_testers:
                        self.run_tests_directly()
                        continue
                    else:
                        console.print("[yellow]Нет выбранных тестов для запуска. Пожалуйста, выберите тесты сначала.[/yellow]")
                        self.logger.info("Пользователь попытался запустить тесты без выбранных тестеров")
                        continue
                elif choice == 's':
                    keyword = Prompt.ask("Введите ключевое слово для поиска тестеров").strip()
                    found_testers = self.search_testers(keyword)
                    if found_testers:
                        selected_tests.update(found_testers)
                        console.print(f"[green]Найдено тестеров: {len(found_testers)}[/green]")
                        self.logger.info(f"Найдено тестеров по ключевому слову '{keyword}': {found_testers}")
                    else:
                        console.print(f"[red]Тестеры по ключевому слову '{keyword}' не найдены.[/red]")
                        self.logger.info(f"Тестеры по ключевому слову '{keyword}' не найдены.")
                        continue
                elif choice == 'f':
                    # Фильтрация по времени выполнения
                    try:
                        min_time = int(Prompt.ask("Введите минимальное время выполнения (с)").strip())
                        max_time = int(Prompt.ask("Введите максимальное время выполнения (с)").strip())
                        filtered_testers = [test for test in test_list
                                            if TESTER_CLASSES[test]['estimated_time'] >= min_time and TESTER_CLASSES[test]['estimated_time'] <= max_time]
                        if filtered_testers:
                            selected_tests.update(filtered_testers)
                            console.print(f"[green]Тестеры отфильтрованы: {len(filtered_testers)}[/green]")
                            self.logger.info(f"Тестеры отфильтрованы по времени выполнения: {filtered_testers}")
                        else:
                            console.print(f"[red]Тестеры по заданным критериям не найдены.[/red]")
                            self.logger.info("Тестеры по заданным критериям не найдены.")
                            continue
                    except ValueError:
                        console.print("[red]Некорректный ввод для фильтрации. Попробуйте снова.[/red]")
                        self.logger.warning("Некорректный ввод для фильтрации.")
                        continue
                else:
                    invalid_entries = []
                    for item in choice.split(","):
                        item = item.strip()
                        if item.isdigit():
                            idx = int(item) - 1
                            if 0 <= idx < total_tests:
                                selected_tests.add(test_list[idx])
                                self.logger.info(f"Пользователь выбрал тестер {test_list[idx]}")
                            else:
                                invalid_entries.append(item)
                                self.logger.warning(f"Некорректный номер тестера: {item}")
                        else:
                            invalid_entries.append(item)
                            self.logger.warning(f"Некорректный ввод для тестера: {item}")

                    if invalid_entries:
                        # Санитизация сообщений для логирования
                        sanitized_invalid = [self.sanitize_input(entry) for entry in invalid_entries]
                        console.print(f"[red]Некорректные номера тестеров: {', '.join(sanitized_invalid)}[/red]")
                        self.logger.warning(f"Некорректные вводы тестеров: {', '.join(sanitized_invalid)}")

                if not selected_tests:
                    console.print("[red]Некорректный выбор тестеров. Попробуйте снова.[/red]")
                    self.logger.info("Некорректный выбор тестеров, пробуем снова")
                    continue

                # Подтверждение выбора
                self.display_selected_testers(selected_tests)
                if Confirm.ask("Вы подтверждаете выбор тестеров?"):
                    break
                else:
                    console.print("[yellow]Давайте выберем тестеры заново.[/yellow]")
                    selected_tests.clear()
            except Exception as e:
                self.logger.error(f"Ошибка при выборе тестеров: {e}")
                return set()

        return selected_tests

    def search_categories(self, keyword: str) -> List[str]:
        """
        Ищет категории по ключевому слову.

        Args:
            keyword (str): Ключевое слово для поиска.

        Returns:
            List[str]: Список найденных категорий.
        """
        return [key for key, category in TEST_CATEGORIES.items() if keyword.lower() in category['name'].lower() or keyword.lower() in category['description'].lower()]

    def search_testers(self, keyword: str) -> List[str]:
        """
        Ищет тестеров по ключевому слову.

        Args:
            keyword (str): Ключевое слово для поиска.

        Returns:
            List[str]: Список найденных тестеров.
        """
        return [test for test, config in TESTER_CLASSES.items() if keyword.lower() in config['name'].lower() or keyword.lower() in config['description'].lower()]

    def clear_console(self) -> None:
        """Очищает консоль."""
        os.system('cls' if os.name == 'nt' else 'clear')
        self.logger.info("Консоль очищена")

    def view_selected_tests(self) -> None:
        """Отображает текущий список выбранных тестеров."""
        if not self.selected_testers:
            console.print("[yellow]Нет выбранных тестов.[/yellow]")
            return

        table = Table(title="Текущие Выбранные Тестеры", box=box.MINIMAL_DOUBLE_HEAD, show_lines=True)
        table.add_column("Тестер", style="cyan", no_wrap=True)
        table.add_column("Описание", style="magenta")
        table.add_column("Время (с)", justify="right", style="green")

        for test in sorted(self.selected_testers):
            config = TESTER_CLASSES[test]
            category_key = TEST_TO_CATEGORY.get(test, "")
            category = TEST_CATEGORIES.get(category_key, {})
            icon = category.get('icon', '')
            table.add_row(
                f"{icon} {config['name']}",
                config['description'],
                str(config['estimated_time'])
            )

        console.print(table)

    def display_selected_testers(self, selected_tests: Set[str]) -> None:
        """
        Отображает текущий выбор тестеров для подтверждения.

        Args:
            selected_tests (Set[str]): Набор выбранных тестеров.
        """
        if not selected_tests:
            console.print("[yellow]Нет выбранных тестеров.[/yellow]")
            return

        table = Table(title="Выбранные Тест��ры для Подтверждения", box=box.MINIMAL_DOUBLE_HEAD, show_lines=True)
        table.add_column("Тестер", style="cyan", no_wrap=True)
        table.add_column("Описание", style="magenta")
        table.add_column("Время (с)", justify="right", style="green")

        for test in sorted(selected_tests):
            config = TESTER_CLASSES[test]
            category_key = TEST_TO_CATEGORY.get(test, "")
            category = TEST_CATEGORIES.get(category_key, {})
            icon = category.get('icon', '')
            table.add_row(
                f"{icon} {config['name']}",
                config['description'],
                str(config['estimated_time'])
            )

        console.print(table)

    def sanitize_input(self, input_str: str) -> str:
        """
        Санитизирует ввод пользователя для логирования.

        Удаляет или заменяет неподходящие символы.

        Args:
            input_str (str): Входная строка.

        Returns:
            str: Санитизированная строка.
        """
        try:
            return input_str.encode('utf-8', 'ignore').decode('utf-8')
        except UnicodeEncodeError:
            return ''

    def validate_test_definitions(self) -> bool:
        """
        Проверяет, что все тесты в TEST_CATEGORIES имеют определения в TESTER_CLASSES.

        Returns:
            bool: True, если все тесты определены, False иначе.
        """
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
        """
        Инициализирует выбранные тестеры, включая их зависимости.

        Возвращает:
            Dict[str, Any]: Словарь инициализированных тестеров.
        """
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
                tester_class = config['class_obj']
                if not tester_class:
                    self.logger.error(f"Не найден класс для тестера {name}")
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
        """
        Запускает тесты и возвращает результаты.

        Args:
            iterations (int): Количество повторений для каждого теста.

        Returns:
            Dict[str, List[TestResult]]: Результаты тестов для каждого тестера.
        """
        test_results: Dict[str, List[TestResult]] = {name: [] for name in self.tester_instances.keys()}

        # Расчёт общего ожидаемого времени выполнения всех тестов
        total_estimated_time = sum(TESTER_CLASSES[name]['estimated_time'] for name in self.tester_instances.keys()) * iterations

        with Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}"),
            BarColumn(),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
            console=console,
            transient=True
        ) as progress:
            task = progress.add_task("[bold blue]Выполнение тестов...", total=total_estimated_time)
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
                            # Предполагается, что тестеры заполняют поля 'duration' и 'timestamp'
                            if 'duration' not in result or 'timestamp' not in result:
                                result['duration'] = (end_time - start_time).total_seconds()
                                result['timestamp'] = start_time.strftime("%Y-%m-%d %H:%M:%S")
                            test_results[name].append(result)

                        self.logger.info(f"Тест {name} успешно завершен за {(end_time - start_time).total_seconds():.2f}с")

                        # Обновление прогресса на основе 'estimated_time'
                        estimated_duration = TESTER_CLASSES[name]['estimated_time']
                        progress.update(task, advance=estimated_duration)
                    except Exception as e:
                        self.logger.error(f"Ошибка при выполнении теста {name}: {e}")
                        self.logger.debug(traceback.format_exc())
                        # Продолжаем выполнение других тестов
                        continue

        self.logger.info("Выполнение тестов завершено")
        return test_results

    def generate_test_report(self, tester_results: Dict[str, List[TestResult]], start_time: datetime) -> None:
        """
        Генерирует отчет о тестировании.

        Создает лог-файл и Markdown-отчет с результатами тестирования.

        Args:
            tester_results (Dict[str, List[TestResult]]): Результаты тестов.
            start_time (datetime): Время начала тестирования.
        """
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
                        status = "✓" if result['success'] else "���"
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
            report_markdown.append("# Отчет о тестирвании\n")
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
        """
        Отображает отчет о тестировании в консоли с помощью rich.

        Args:
            tester_results (Dict[str, List[TestResult]]): Результаты тестов для каждого тестера.
        """
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

    def run_tests_directly(self) -> None:
        """
        Запускает тесты без ожидания ввода горячих клавиш.

        Выполняет инициализацию тестеров, отображает выбранные тесты,
        показывает сводку, подтверждает запуск тестов, запрашивает количество итераций,
        запускает тесты, генерирует отчеты и отображает результаты.
        """
        if not self.selected_testers:
            console.print("[yellow]Нет выбранных тестов для запуска.[/yellow]")
            self.logger.info("Попытка запуска тестов без выбранных тестеров")
            return

        # Инициализация тестеров
        tester_instances = self.initialize_testers()
        if not tester_instances:
            console.print("[red]Нет доступных тестеров для выполнения.[/red]")
            return

        # Показываем выбранные тесты
        self.display_testers_table({name: {} for name in tester_instances.keys()})

        # Показываем сводку перед запуском
        self.display_summary()

        if not Confirm.ask("Начать выполнение тестов?"):
            self.logger.info("Пользователь отказался от запуска тестов")
            return

        # Запрос на количество итераций
        while True:
            try:
                iterations_input = Prompt.ask(f"\n[bold blue]Введите количество повторений [{MIN_ITERATIONS}-{MAX_ITERATIONS}]:[/bold blue]")
                # Обработка горячих клавиш во время ввода
                if iterations_input.lower() == 'h':
                    self.show_help()
                    continue
                elif iterations_input.lower() == 'q':
                    self.quit_program()
                iterations = int(iterations_input)
                if MIN_ITERATIONS <= iterations <= MAX_ITERATIONS:
                    break
                console.print(f"[red]Значение должно быть между {MIN_ITERATIONS} и {MAX_ITERATIONS}.[/red]")
            except ValueError:
                # Проверка на специальные команды
                if iterations_input.lower() == 'h':
                    self.show_help()
                    continue
                elif iterations_input.lower() == 'q':
                    self.quit_program()
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
            self.quit_program()

    def run(self) -> None:
        """
        Запускает основную логику тестирования.

        Выводит заголовок, настраивает обработчики сигналов, валидирует тестеры,
        запускает основной цикл программы с выбором и выполнением тестов.
        """
        try:
            # Вывод заголовка
            header_panel = Panel(
                Align.center(
                    "[bold cyan]Система тестирования QA OpenYard[/bold cyan]",
                    vertical="middle"
                ),
                subtitle="[bold yellow]Версия 0.1.21[/bold yellow]",
                style="bold blue",
                box=box.ROUNDED
            )
            console.print(header_panel)

            # Настройка обработчиков сигналов
            self.setup_signal_handlers()

            # Валидация тестеров
            if not self.validate_test_definitions():
                self.logger.error(
                    "Некоторые тесты не имеют определений. Завершение программы."
                )
                sys.exit(1)

            # Оснвной цикл программы
            while self.running:
                # Показываем справку
                self.show_help()

                # Выбор тестов через интерактивное меню
                self.selected_testers = self.select_tests_interactive()
                if not self.selected_testers:
                    console.print("[yellow]Тестирование отменено пользователем.[/yellow]")
                    self.logger.info("Тестирование отменено пользователем")
                    break

                # Запуск тестов
                self.run_tests_directly()

        except KeyboardInterrupt:
            console.print("\n[yellow]Прервано пользователем.[/yellow]")
            self.logger.warning("Прервано пользователем через KeyboardInterrupt")
            self.quit_program()
        except Exception as e:
            if self.logger:
                self.logger.error(f"Критическая ошибка: {e}")
                self.logger.debug(traceback.format_exc())
            console.print(f"[red]Критическая ошибка: {e}[/red]")
            self.quit_program()
        finally:
            console.print("\nНажмите Enter для выхода...")
            input()

    def setup_signal_handlers(self) -> None:
        """
        Настраивает обработчики сигналов.

        Обработчики сигналов SIGINT и SIGTERM обеспечивают корректное завершение программы
        и восстановление настроек перед выходом.
        """

        def signal_handler(signum: int, frame: Any) -> None:
            """
            Обработчик сигналов завершения.

            Args:
                signum (int): Номер сигнала.
                frame (Any): Текущий стек вызовов.
            """
            self.logger.warning("Получен сигнал завершения")
            console.print("\n[yellow]Завершение работы...[/yellow]")
            sys.exit(0)

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

    def quit_program(self) -> None:
        """
        Корректно завершает программу.
        """
        self.logger.info("Завершение программы по запросу пользователя")
        console.print("\n[yellow]Работа программы завершена[/yellow]")
        sys.exit(0)

def main() -> None:
    """
    Основная функция программы.

    Создает экземпляр TestManager и запускает его.
    """
    manager = TestManager()
    manager.run()

if __name__ == '__main__':
    main()
