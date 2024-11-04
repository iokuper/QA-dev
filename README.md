# QA OpenYard - Система тестирования BMC

## Описание
QA OpenYard - это комплексная система автоматизированного тестирования для Baseboard Management Controller (BMC). Система предоставляет широкий набор тестов для проверки сетевых настроек, протоколов управления и сервисов BMC с возможностью генерации подробных отчетов.

## Основные возможности

### Сетевое тестирование
- IPv4/IPv6 конфигурация и проверка
- Настройка и верификация VLAN
- Управление MAC-адресами
- Тестирование сетевых интерфейсов
- Фильтрация IP-адресов
- Проверка маршрутизации

### Протоколы управления
- IPMI (Intelligent Platform Management Interface)
- Redfish API
- SSH доступ и управление
- SNMP мониторинг и управление

### Сетевые сервисы
- DNS конфигурация и разрешение имен
- NTP синхронизация (автоматическая и ручная)
- Управление именем хоста
- Проверка сетевых портов

### Диагностика и мониторинг
- Сбор системных логов
- Мониторинг производительности
- Проверка состояния сервисов
- Анализ системных ресурсов

### Управление питанием
- Включение/выключение
- Перезагрузка
- Мониторинг состояния
- Проверка стабильности

## Требования

### Системные требования
- Python 3.8 или выше
- Ubuntu/Debian Linux
- Сетевой доступ к BMC
- Права sudo для некоторых операций

### Python зависимости
```
rich>=10.0.0
requests>=2.25.0
paramiko>=2.7.2
cryptography>=3.3.0
typing-extensions>=3.7.4
ipaddress>=1.0.23
pytest>=6.2.0
flake8>=3.9.0
mypy>=0.910
black>=21.5b2
```

## Установка

### Из репозитория
```bash
# Клонирование репозитория
git clone https://github.com/your-repo/qa-openyard.git
cd qa-openyard

# Создание виртуального окружения
python -m venv venv
source venv/bin/activate  # Linux
.\venv\Scripts\activate  # Windows

# Установка зависимостей
pip install -r requirements.txt

# Установка pre-commit хуков
pre-commit install
```

### Из архива
```bash
# Распаковка архива
tar -xzf qa-openyard-1.0.tar.gz
cd qa-openyard-1.0

# Установка
pip install .
```

## Конфигурация

### Базовая настройка
1. Создайте копию примера конфигурации:
```bash
cp config.ini.example config.ini
```

2. Настройте основные параметры в config.ini:
```ini
[Network]
ipmi_host = 192.168.1.100
interface = 1
default_subnet_mask = 255.255.255.0
verify_access = true

[IPMI]
username = admin
password = password
verify_timeout = 60
check_privileges = true
```

### Расширенная конфигурация
Система поддерживает множество параметров для тонкой настройки тестирования:

```ini
[Load]
test_duration = 300
bandwidth = 100M
parallel_streams = 4
monitor_resources = true

[Diagnostic]
collect_logs = true
test_ports = 22,623,443
verify_access = true
```

## Использование

### Запуск тестов
```bash
# Запуск всех тестов
python main.py

# Запуск конкретной категории тестов
python main.py --category network

# Запуск отдельного теста
python main.py --test ipmi
```

### Интерактивный режим
Система предоставляет интерактивный CLI интерфейс с следующими возможностями:
- Выбор тестов для выполнения
- Настройка количества итераций
- Просмотр прогресса выполнения
- Вывод результатов в реальном времени

### Горячие клавиши
- `q` - Выход
- `h` - Помощь
- `r` - Запуск тестов
- `a` - Выбрать все
- `n` - Снять выбор
- `s` - Поиск
- `f` - Фильтр
- `v` - Просмотр выбранных
- `c` - Очистить консоль

## Структура проекта

### Основные модули
- `base_tester.py` - Базовый класс для всех тестеров
- `network_utils.py` - Сетевые утилиты
- `config_manager.py` - Управление конфигурацией
- `logger.py` - Система логирования

### Тестовые модули
- Сетевые тесты (network_tester.py, vlan_tester.py и др.)
- Тесты протоколов (ipmi_tester.py, ssh_tester.py и др.)
- Тесты сервисов (dns_tester.py, ntp_tester.py и др.)
- Специальные тесты (diagnostic_tester.py, load_tester.py и др.)

## Разработка

### Стиль кода
- Следуем PEP 8
- Максимальная длина строки: 79 символов
- Используем типизацию Python
- Документируем все публичные методы и классы
- Обрабатываем все исключения

### Линтеры и форматтеры
```bash
# Проверка типов
mypy .

# Проверка стиля
flake8 .

# Форматирование кода
black .

# Запуск всех проверок
make lint
```

### Добавление нового теста
1. Создайте новый класс, наследующий BaseTester:
```python
class NewTester(BaseTester):
    def __init__(self, config_file: str, logger: Optional[logging.Logger] = None):
        super().__init__(config_file, logger)

    def perform_tests(self) -> None:
        # Реализация тестов

    def restore_settings(self) -> bool:
        # Восстановление настроек
```

2. Добавьте тест в конфигурацию:
```python
TEST_CATEGORIES['category']['tests'].append('NewTest')
TESTER_CLASSES['NewTest'] = {
    'name': 'New Tester',
    'class_obj': NewTester,
    'description': 'Description',
    'dependencies': [],
    'estimated_time': 60
}
```

## Тестирование

### Unit тесты
```bash
# Запуск всех тестов
python -m pytest tests/

# Запуск конкретного модуля
python -m pytest tests/test_network.py

# С покрытием кода
python -m pytest --cov=. tests/
```

### Интеграционные тесты
```bash
python -m pytest tests/integration/
```

### Тесты производительности
```bash
python -m pytest tests/performance/
```

## CI/CD

### GitHub Actions
- Линтинг кода
- Проверка типов
- Unit тесты
- Интеграционные тесты
- Сборка документации
- Публикация пакета

### Pre-commit хуки
- black
- flake8
- mypy
- isort
- pytest

## Решение проблем

### Частые проблемы
1. Недоступность BMC
   - Проверьте сетевое подключение
   - Убедитесь в корректности IP-адреса
   - Проверьте учетные данные

2. Ошибки выполнения тестов
   - Проверьте права доступа
   - Убедитесь в корректности конфигурации
   - Проверьте системные требования

### Логирование
- Логи приложения: logs/tester.log
- Отчеты о тестах: reports/
- Системные логи: /var/log/

## Безопасность

### Хранение учетных данных
- Используйте переменные окружения
- Шифруйте чувствительные данные
- Не храните пароли в открытом виде

### Сетевая безопасность
- Проверяйте SSL сертификаты
- Используйте безопасные протоколы
- Ограничивайте сетевой доступ

## Лицензия
MIT License. См. файл LICENSE для деталей.

## Авторы
- OpenYard Team

## Поддержка
- GitHub Issues: https://github.com/your-repo/qa-openyard/issues
- Email: support@openyard.com
- Documentation: https://docs.openyard.com

## Участие в разработке
Мы приветствуем вклад в развитие проекта! См. CONTRIBUTING.md для деталей.
