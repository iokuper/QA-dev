"""Модуль для управления конфигурацией."""

import os
import logging
from typing import Dict, Any, Optional, List, Union
import configparser
from pathlib import Path
from cryptography.fernet import Fernet


class ConfigError(Exception):
    """Исключение для ошибок конфигурации."""
    pass


class ConfigManager:
    """Централизованное управление конфигурацией."""

    def __init__(
        self,
        config_file: str,
        logger: Optional[logging.Logger] = None
    ) -> None:
        """
        Инициализирует менеджер конфигурации.

        Args:
            config_file: Путь к файлу конфигурации
            logger: Логгер для вывода сообщений

        Raises:
            ConfigError: При ошибке инициализации
        """
        self.config_file = config_file
        self.logger = logger or logging.getLogger(__name__)
        self.config = configparser.ConfigParser()
        self.credentials_cache: Dict[str, Dict[str, str]] = {}

        try:
            # Проверяем существование файла конфигурации
            if not os.path.exists(config_file):
                raise ConfigError(
                    f"Файл конфигурации не найден: {config_file}"
                )

            self.config.read(config_file)

            # Инициализируем шифрование
            key_file = Path("secret.key")
            if key_file.exists():
                self.key = key_file.read_bytes()
            else:
                self.key = Fernet.generate_key()
                key_file.write_bytes(self.key)

            self.cipher_suite = Fernet(self.key)

            # Проверяем обязательные секции
            required_sections = ['Network', 'IPMI', 'SSH', 'Redfish']
            missing_sections = [
                section for section in required_sections
                if not self.config.has_section(section)
            ]
            if missing_sections:
                raise ConfigError(
                    f"Отсутствуют обязательные секции: "
                    f"{', '.join(missing_sections)}"
                )

            # Валидируем конфигурацию
            self._validate_config()

        except configparser.Error as e:
            raise ConfigError(f"Ошибка чтения конфигурации: {e}")
        except Exception as e:
            raise ConfigError(f"Ошибка инициализации конфигурации: {e}")

    def _validate_config(self) -> None:
        """
        Проверяет корректность конфигурации.

        Raises:
            ConfigError: При обнаружении ошибок в конфигурации
        """
        try:
            # Проверяем сетевые настройки
            network_config = self.get_network_config('Network')
            if not network_config.get('ipmi_host'):
                raise ConfigError("Не указан IPMI хост")

            # Проверяем учетные данные
            for section in ['IPMI', 'SSH', 'Redfish']:
                credentials = self.get_credentials(section)
                if not credentials.get('username'):
                    raise ConfigError(
                        f"Не указано имя пользователя для {section}"
                    )
                if not credentials.get('password'):
                    raise ConfigError(f"Не указан пароль для {section}")

            # Проверяем таймауты и повторы
            for section in self.config.sections():
                if 'timeout' in self.config[section]:
                    timeout = self.config[section].getint('timeout')
                    if timeout <= 0:
                        raise ConfigError(
                            f"Некорректный таймаут в секции {section}: "
                            f"{timeout}"
                        )

                if 'retry_count' in self.config[section]:
                    retry_count = self.config[section].getint('retry_count')
                    if retry_count < 0:
                        raise ConfigError(
                            f"Некорректное количество повторов в секции "
                            f"{section}: {retry_count}"
                        )

        except (ValueError, KeyError) as e:
            raise ConfigError(f"Ошибка валидации конфигурации: {e}")

    def get_network_config(self, section: str) -> Dict[str, str]:
        """
        Получает сетевые настройки из указанной секции.

        Args:
            section: Название секции

        Returns:
            Dict[str, str]: Словарь с настройками

        Raises:
            ConfigError: При ошибке получения настроек
        """
        try:
            if not self.config.has_section(section):
                raise ConfigError(f"Секция не найдена: {section}")

            config = dict(self.config[section])

            # Проверяем обязательные параметры
            required_params = {
                'Network': ['ipmi_host'],
                'IPMI': ['interface'],
                'SSH': ['ssh_port'],
                'Redfish': ['redfish_port']
            }

            if section in required_params:
                missing_params = [
                    param for param in required_params[section]
                    if param not in config
                ]
                if missing_params:
                    raise ConfigError(
                        f"Отсутствуют обязательные параметры в секции "
                        f"{section}: {', '.join(missing_params)}"
                    )

            return config

        except configparser.Error as e:
            raise ConfigError(
                f"Ошибка получения настроек из секции {section}: {e}"
            )

    def get_credentials(self, section: str) -> Dict[str, str]:
        """
        Получает учетные данные из указанной секции.

        Args:
            section: Название секции

        Returns:
            Dict[str, str]: Словарь с учетными данными

        Raises:
            ConfigError: При ошибке получения учетных данных
        """
        try:
            # Проверяем кэш
            if section in self.credentials_cache:
                return self.credentials_cache[section]

            if not self.config.has_section(section):
                raise ConfigError(f"Секция не найдена: {section}")

            username = self.config[section].get('username')
            password = self.config[section].get('password')

            if not username or not password:
                raise ConfigError(
                    f"Отсутствуют учетные данные в секции {section}"
                )

            # Расшифровываем пароль если он зашифрован
            if password.startswith('ENC['):
                password = password[4:-1]  # Убираем ENC[]
                try:
                    password = self.cipher_suite.decrypt(
                        password.encode()
                    ).decode()
                except Exception as e:
                    raise ConfigError(
                        f"Ошибка расшифровки пароля в секции {section}: {e}"
                    )

            credentials = {
                'username': username,
                'password': password
            }

            # Сохраняем в кэш
            self.credentials_cache[section] = credentials
            return credentials

        except configparser.Error as e:
            raise ConfigError(
                f"Ошибка получения учетных данных из секции {section}: {e}"
            )

    def get_test_params(
        self,
        section: str
    ) -> Dict[str, Union[str, List[str]]]:
        """
        Получает параметры тестирования для указанной секции.

        Args:
            section: Название секции

        Returns:
            Dict[str, Union[str, List[str]]]: Словарь с параметрами

        Raises:
            ConfigError: При ошибке получения параметров
        """
        try:
            if not self.config.has_section(section):
                raise ConfigError(f"Секция не найдена: {section}")

            params = dict(self.config[section])

            # Преобразуем списки
            for key in params:
                if ',' in params[key]:
                    params[key] = [x.strip() for x in params[key].split(',')]

            return params

        except Exception as e:
            raise ConfigError(
                f"Ошибка получения параметров тестирования для {section}: {e}"
            )

    def update_bmc_ip(self, new_ip: str) -> None:
        """
        Обновляет IP-адрес BMC в конфигурации.

        Args:
            new_ip: Новый IP-адрес

        Raises:
            ConfigError: При ошибке обновления IP
        """
        try:
            self.config['Network']['ipmi_host'] = new_ip
            with open(self.config_file, 'w') as f:
                self.config.write(f)

            self.logger.info(f"IP-адрес BMC обновлен: {new_ip}")

        except Exception as e:
            raise ConfigError(f"Ошибка обновления IP-адреса BMC: {e}")

    def encrypt_password(self, password: str) -> str:
        """
        Шифрует пароль.

        Args:
            password: Пароль для шифрования

        Returns:
            str: Зашифрованный пароль

        Raises:
            ConfigError: При ошибке шифрования
        """
        try:
            encrypted = self.cipher_suite.encrypt(password.encode())
            return f"ENC[{encrypted.decode()}]"
        except Exception as e:
            raise ConfigError(f"Ошибка шифрования пароля: {e}")

    def decrypt_password(self, encrypted: str) -> str:
        """
        Расшифровывает пароль.

        Args:
            encrypted: Зашифрованный пароль

        Returns:
            str: Расшифрованный пароль

        Raises:
            ConfigError: При ошибке расшифровки
        """
        try:
            if not encrypted.startswith('ENC[') or not encrypted.endswith(']'):
                raise ConfigError("Некорректный формат зашифрованного пароля")

            encrypted = encrypted[4:-1]  # Убираем ENC[]
            decrypted = self.cipher_suite.decrypt(encrypted.encode())
            return decrypted.decode()

        except Exception as e:
            raise ConfigError(f"Ошибка расшифровки пароля: {e}")

    def get_network_params(self, section: str, network: str) -> Dict[str, Any]:
        """
        Получает параметры сети из конфигурации.

        Args:
            section: Название секции
            network: Номер сети

        Returns:
            Dict[str, Any]: Параметры сети
        """
        try:
            config = self.get_network_config(section)
            network_params = {
                'ips': [f'10.227.{network}.175'],  # Пример формирования IP
                'gateway': f'10.227.{network}.254',  # Пример формирования шлюза
                'subnet_mask': '255.255.255.0'
            }
            return network_params
        except Exception as e:
            raise ConfigError(f"Ошибка получения параметров сети: {e}")
