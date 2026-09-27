"""Configuração de logging local do FinBot para console e arquivo."""

import logging
from logging.handlers import RotatingFileHandler
import sys
from pathlib import Path


def setup_logging(log_level: str = "INFO", log_file: str = "logs/finbot.log") -> logging.Logger:
    """Configura e inicializa o logger local da aplicação com rotação de arquivos."""
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    numeric_level = getattr(logging, log_level.upper(), logging.INFO)
    logger = logging.getLogger("finbot")
    logger.setLevel(numeric_level)

    # Evita adicionar múltiplos handlers caso setup_logging seja invocado novamente
    if not logger.handlers:
        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(numeric_level)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

        file_handler = RotatingFileHandler(
            log_path,
            maxBytes=5 * 1024 * 1024,  # 5 MB
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setLevel(numeric_level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger
