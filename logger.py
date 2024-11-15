"""Модуль для централизованного логирования."""

import logging
import logging.handlers
from typing import Dict, Optional, Union, TextIO
from pathlib import Path
from datetime import datetime, timedelta
import gzip
import shutil
import os
import tarfile


class CustomFormatter(logging.Formatter):
    """Кастомный форматтер для логов с цветным выводом."""

    COLORS = {
        'DEBUG': '\033[37m',      # Белый
        'INFO': '\033[32m',       # Зеленый
        'WARNING': '\033[33m',    # Желтый
        'ERROR': '\033[31m',      # Красный
        'CRITICAL': '\033[35m',   # Пурпурный
    }
    RESET = '\033[0m'

    def __init__(self, use_colors: bool = True) -> None:
        """
        Инициализирует форматтер.

        Args:
            use_colors: Использовать ли цветной вывод
        """
        super().__init__(
            '%(asctime)s - %(name)s - %(levelname)s - '
            '%(filename)s:%(lineno)d - %(funcName)s - %(message)s'
        )
        self.use_colors = use_colors

    def format(self, record: logging.LogRecord) -> str:
        """
        Форматирует запись лога.

        Args:
            record: Запись для форматирования

        Returns:
            str: Отформатированная запись
        """
        if self.use_colors and record.levelname in self.COLORS:
            record.levelname = (
                f"{self.COLORS[record.levelname]}"
                f"{record.levelname}"
                f"{self.RESET}"
            )
        return super().format(record)


class CompressedRotatingFileHandler(logging.handlers.RotatingFileHandler):
    """Обработчик с ротацией и сжатием старых логов."""

    def __init__(
        self,
        filename: Union[str, Path],
        mode: str = 'a',
        maxBytes: int = 0,
        backupCount: int = 0,
        encoding: Optional[str] = None,
        delay: bool = False,
        errors: Optional[str] = None
    ) -> None:
        """
        Инициализирует обработчик.

        Args:
            filename: Путь к файлу лога
            mode: Режим открытия файла
            maxBytes: Максимальный размер файла
            backupCount: Количество резервных копий
            encoding: Кодировка файла
            delay: Отложенное открытие файла
            errors: Обработка ошибок кодировки
        """
        super().__init__(
            filename,
            mode,
            maxBytes,
            backupCount,
            encoding,
            delay,
            errors
        )
        self.rotator = self._rotator
        self.namer = self._namer

    def _rotator(
        self,
        source: str,
        dest: str
    ) -> None:
        """
        Выполняет ротацию файла с сжатием.

        Args:
            source: Исходный файл
            dest: Файл назначения
        """
        with open(source, 'rb') as f_in:
            with gzip.open(f"{dest}.gz", 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)
        os.remove(source)

    def _namer(self, name: str) -> str:
        """
        Генерирует имя для ротированного файла.

        Args:
            name: Базовое имя файла

        Returns:
            str: Имя ротированного файла
        """
        return name + ".gz"

    def rotate(
        self,
        source: str,
        dest: str
    ) -> None:
        """
        Выполняет ротацию файла.

        Args:
            source: Исходный файл
            dest: Файл назначения
        """
        if os.path.exists(source):
            try:
                os.remove(dest)
            except FileNotFoundError:
                pass
            self.rotator(source, dest)


def setup_logger(name: str, log_file: str) -> logging.Logger:
    """Настраивает и возвращает логгер."""
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    # Форматтер для файла (с полной информацией)
    file_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(module)s:%(lineno)d - '
        '%(funcName)s - %(message)s'
    )

    # Форматтер для консоли (только сообщение)
    console_formatter = logging.Formatter('%(message)s')

    # Обработчик для файла
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(file_formatter)

    # Обработчик для консоли
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(console_formatter)

    # Очищаем существующие обработчики
    logger.handlers.clear()

    # Добавляем обработчики
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger


def clear_logger(logger: Union[str, logging.Logger]) -> None:
    """
    Очищает обработчики логгера.

    Args:
        logger: Логгер или его имя
    """
    if isinstance(logger, str):
        logger = logging.getLogger(logger)
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)


def archive_old_logs(
    log_dir: Union[str, Path],
    max_age_days: int = 30
) -> None:
    """
    Архивирует старые лог-файлы.

    Args:
        log_dir: Директория с логами
        max_age_days: Максимальный возраст файлов в днях
    """
    log_dir = Path(log_dir)
    if not log_dir.exists():
        return

    now = datetime.now()
    archive_name = f"logs_{now:%Y%m%d_%H%M%S}.tar.gz"

    with tarfile.open(log_dir / archive_name, "w:gz") as tar:
        for log_file in log_dir.glob("*.log*"):
            # Пропускаем текущие файлы логов
            if not log_file.name.endswith((".1", ".2", ".3", ".4", ".5")):
                continue

            # Проверяем возраст файла
            mtime = datetime.fromtimestamp(log_file.stat().st_mtime)
            if now - mtime > timedelta(days=max_age_days):
                tar.add(
                    log_file,
                    arcname=log_file.name,
                    recursive=False
                )
                log_file.unlink()


def setup_test_logger(
    name: str,
    log_file: str = 'logs/tester.log',
    level: int = logging.DEBUG
) -> logging.Logger:
    """
    Настраивает логгер для конкретного теста.

    Args:
        name: Имя логгера
        log_file: Путь к файлу логов
        level: Уровень логирования

    Returns:
        logging.Logger: Настроенный логгер
    """
    return setup_logger(
        name=name,
        log_file=log_file,
        level=level,
        console_output=True,
        use_colors=True
    )
