# QA OpenYard - Система тестирования BMC

## Описание
QA OpenYard - это комплексная система для автоматизированного тестирования Baseboard Management Controller (BMC). Система позволяет проводить различные виды тестов сетевых настроек, протоколов управления и сервисов BMC.

## Основные возможности
- Тестирование сетевых настроек (IPv4/IPv6, VLAN, MAC, интерфейсы)
- Проверка протоколов управления (IPMI, Redfish, SSH, SNMP)
- Тестирование сетевых сервисов (DNS, NTP, Hostname)
- Диагностика и мониторинг
- Управление питанием
- Генерация подробных отчетов
- Интерактивный CLI интерфейс

## Требования
- Python 3.8+
- Ubuntu/Debian
- Доступ к BMC по сети
- Права sudo для некоторых операций

## Установка
```bash
# Клонирование репозитория
git clone https://github.com/your-repo/qa-openyard.git
cd qa-openyard

# Создание виртуального окружения
python -m venv venv
source venv/bin/activate

# Установка зависимостей
pip install -r requirements.txt
```

## Конфигурация
1. Скопируйте пример конфигурации:
```bash
cp config.ini.example config.ini
```

2. Отредактируйте config.ini:
```ini
[Network]
ipmi_host = <BMC_IP>
interface = 1
...

[IPMI]
username = <IPMI_USER>
password = <IPMI_PASSWORD>
...
```

## Использование
```bash
# Запуск всех тестов
python main.py

# Запуск конкретного теста
python main.py --test network
```

## Структура тестов
- Network Tests - базовые сетевые настройки
- Management Tests - интерфейсы управления
- Service Tests - сетевые сервисы
- Diagnostic Tests - диагностика
- Power Tests - управление питанием

## Отчеты
Отчеты генерируются в двух форматах:
- Текстовый лог: reports/test_report_YYYYMMDD_HHMMSS.log
- Markdown: reports/test_report_YYYYMMDD_HHMMSS.md

## Разработка
### Добавление нового теста
1. Создайте новый класс тестера, наследующий BaseTester
2. Реализуйте методы perform_tests() и restore_settings()
3. Добавьте тестер в TEST_CATEGORIES и TESTER_CLASSES в main.py

### Запуск тестов разработчика
```bash
python -m pytest tests/
```

## Лицензия
MIT License

## Авторы
- OpenYard Team

## Поддержка
При возникновении проблем создавайте issue в репозитории проекта.
